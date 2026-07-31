# Regulation Arbiter — bands, slew, floors, conflicts, emergency, latch
# Part of the regulation matrix (see docs/prompts/regulation-matrix.md).
#
# Stages 3 and 4 of the pipeline. Takes the organic target vector produced by
# the surfaces and resolves it into the commanded vector, in this exact order:
#
#   1. slew-limit the organic output vs the last command,
#   2. floors        (regulator severity >= minor edge)   — forced,
#   3. conflicts     (global severity >= conflict edge)    — forced,
#   4. emergency     (escalating severity >= emergency edge)  — forced,
#   5. latch         (escalating severity >= latch edge)      — forced + held.
#
# Steps 2-5 write forced values AFTER the slew limiter and are NEVER
# slew-limited, so a mold-risk cut or a shutdown lands in a single tick. The
# per-tick path allocates nothing: all vectors are caller-owned or preallocated
# arrays addressed by index.
#
# Steps 4-5 use the ESCALATING severity, not the global one: only deviation
# directions marked in reg_cfg["escalation"] (by default the hazardous high
# side — too hot, too wet) may force the emergency/safe-state vectors. Severity
# saturates at 50 as soon as a reading passes an outer anchor, which a tent
# being brought up from ambient does routinely; escalating on that shut the
# system down with the corrective actuators pinned off and no path back. Steps
# 2-3 keep using the full severity, so being far from ideal still drives floors
# and conflict rules — it just no longer counts as an emergency.
#
# A regulator whose emergency_value / safe_state is None is left "free" in that
# forced vector: it keeps its arbitrated organic command, so the actuator that
# resolves the condition can keep working while the latch is held.
#
# The forced vectors are also CAUSE-AWARE. Each escalating direction is a
# "cause" (dim_index * 2, +1 for the low side), and a regulator may carry a
# per-cause override of its emergency/safe value. This exists because the
# response to "too hot" and "too wet" are not the same: forcing the heater off
# is correct for the first and actively harmful for the second, since cooling
# the tent raises relative humidity at unchanged absolute moisture and the
# severity that fired the emergency can then never fall (field incident
# 2026-07-30/31, docs/notes/chat-log.md).
#
# When SEVERAL causes escalate at once the merge is deliberately conservative: a
# regulator keeps a per-cause value only if EVERY active cause agrees on it,
# otherwise the base vector applies. Adding a cause can therefore only remove
# freedom, never grant it — so "heater free because it is too wet" stops
# applying the moment the tent is also too hot. There is no scalar ordering of
# safety across this vector (0 is safe for the heater, 100 is safe for the
# exhaust), so min/max would be wrong for half the regulators; the base vector
# is the operator-blessed conservative state and a per-cause override is a
# relaxation justified by that cause alone.

from array import array


def _forced_vector(values):
    """Split a forced vector into (float array, hold mask). None entry = free."""
    vec = array("f", [0.0] * len(values))
    hold = []
    for i, v in enumerate(values):
        if v is None:
            hold.append(False)
        else:
            vec[i] = float(v)
            hold.append(True)
    return vec, tuple(hold)


def _cause_index(cause, dim_order):
    """Map a config cause name ("humidity_high") to its bit index."""
    dim, _, side = cause.rpartition("_")
    return (dim_order.index(dim) << 1) | (0 if side == "high" else 1)


def _cause_vectors(base_values, per_cause, n_causes):
    """Build one forced vector per cause, or None when no cause overrides.

    ``per_cause`` maps cause index → {regulator index: value-or-None}. A cause
    with no entry reuses the base vector, represented as None so the hot path
    can skip it without copying.
    """
    if not per_cause:
        return None
    out = []
    for c in range(n_causes):
        overrides = per_cause.get(c)
        if not overrides:
            out.append(None)
            continue
        values = list(base_values)
        for reg_idx, v in overrides.items():
            values[reg_idx] = v
        out.append(_forced_vector(values))
    return tuple(out)


class RegulationArbiter:
    """Resolve the organic target vector into the commanded vector each tick."""

    def __init__(
        self,
        reg_dims,
        band_edges,
        slew_normal,
        slew_fast,
        floor,
        emergency,
        safe_state,
        conflicts,
        latch_release_max,
        latch_release_ticks,
        latch_min_s,
        tick_s,
        escalation=None,
        latch_enter_ticks=1,
        emergency_by_cause=None,
        safe_state_by_cause=None,
    ):
        """All list/array inputs are indexed by regulator position.

        Args:
            reg_dims: tuple per regulator of the deviation-dim indices that set
                its band (empty tuple → band 0).
            band_edges: ascending severity edges; the minor/conflict/emergency/
                latch thresholds are the last four.
            slew_normal, slew_fast, floor: per-regulator float sequences.
            emergency, safe_state: per-regulator forced values; a None entry
                leaves that regulator free (organic command) in that vector.
            conflicts: parsed rules — see from_config for the compact shape.
            latch_release_max, latch_release_ticks, latch_min_s: release gate.
            tick_s: seconds per tick (for the latch minimum-time gate).
            escalation: per-dimension (high, low) bool pairs deciding which
                deviation directions may fire emergency/latch. None = every
                direction escalates (the pre-gating behaviour).
            latch_enter_ticks: consecutive ticks the latch condition must hold
                before the latch fires.
            emergency_by_cause, safe_state_by_cause: optional {cause index →
                {regulator index → value-or-None}} overrides. Absent → the
                scalar vectors apply to every cause (pre-2026-07-31 behaviour).
        """
        self._n = len(reg_dims)
        self._reg_dims = reg_dims
        self._slew_normal = slew_normal
        self._slew_fast = slew_fast
        self._floor = floor
        self._emergency, self._emergency_hold = _forced_vector(emergency)
        self._safe_state, self._safe_hold = _forced_vector(safe_state)
        self._conflicts = conflicts
        self._edges = tuple(band_edges)
        # Named thresholds derived from the last four edges (config guarantees
        # at least four): minor / conflict / emergency / latch.
        self._e_minor = float(band_edges[-4])
        self._e_conflict = float(band_edges[-3])
        self._e_emerg = float(band_edges[-2])
        self._e_latch = float(band_edges[-1])
        self._latch_release_max = latch_release_max
        self._latch_release_ticks = latch_release_ticks
        self._latch_min_s = latch_min_s
        self._tick_s = tick_s
        self._latch_enter_ticks = latch_enter_ticks

        # Per-dimension direction gates, split into two tuples so the hot path
        # indexes instead of unpacking. None → every direction escalates.
        if escalation is None:
            self._esc_high = None
            self._esc_low = None
        else:
            self._esc_high = tuple(bool(pair[0]) for pair in escalation)
            self._esc_low = tuple(bool(pair[1]) for pair in escalation)

        # Per-cause forced vectors + preallocated merge scratch. Emergency and
        # latch can both apply in the same tick, so they need separate scratch.
        # Two causes (high/low) per deviation dimension; without an escalation
        # block the dimension count is the config default of three.
        self._n_causes = 2 * (len(escalation) if escalation is not None else 3)
        self._emerg_cause = _cause_vectors(emergency, emergency_by_cause, self._n_causes)
        self._safe_cause = _cause_vectors(safe_state, safe_state_by_cause, self._n_causes)
        self._merge_e = (array("f", [0.0] * self._n), bytearray(self._n))
        self._merge_s = (array("f", [0.0] * self._n), bytearray(self._n))

        self._last = array("f", [0.0] * self._n)
        self._regsev = array("f", [0.0] * self._n)

        # State exposed for the engine (buzzer / event logging / OLED).
        self.emergency_active = False
        self.latched = False
        self.just_entered_emergency = False
        self.just_entered_latch = False
        self.just_released_latch = False
        self.escalation_severity = 0.0
        self._latch_ticks = 0
        self._enter_counter = 0
        self._release_counter = 0
        # Causes that fired the current latch episode, accumulated (see
        # arbitrate step 5 for why it is sticky rather than per-tick).
        self._latch_cause_mask = 0

    @classmethod
    def from_config(cls, reg_cfg, reg_names, dim_order, tick_s):
        """Build an arbiter from the DEVICE_CONFIG['regulation'] dict.

        Parsing lives here (near the arbiter) rather than in the engine, but the
        module still imports no config — the dict is passed in.
        """
        regulators = reg_cfg["regulators"]
        co2_idx = dim_order.index("co2")
        temp_idx = dim_order.index("temp")
        hum_idx = dim_order.index("humidity")

        reg_dims = []
        slew_normal = array("f", [0.0] * len(reg_names))
        slew_fast = array("f", [0.0] * len(reg_names))
        floor = array("f", [0.0] * len(reg_names))
        # Plain lists: a None entry ("free") cannot live in a float array; the
        # constructor splits them into a float array plus a hold mask.
        emergency = [0.0] * len(reg_names)
        safe_state = [0.0] * len(reg_names)
        # cause index → {regulator index: value-or-None}
        emergency_by_cause = {}
        safe_state_by_cause = {}
        for i, name in enumerate(reg_names):
            r = regulators[name]
            driven = r["driven"]
            if driven == "surface":
                idxs = [dim_order.index(d) for d in r["dims"]]
                # A regulator that takes the CO2 additive term is driven by CO2
                # even though no surface has it as an axis, so its band (and
                # therefore its floor and slew rate) must see that severity.
                if "co2_gain" in r and co2_idx not in idxs:
                    idxs.append(co2_idx)
                reg_dims.append(tuple(idxs))
            elif driven == "follower":
                reg_dims.append((temp_idx, hum_idx))
            else:  # tod
                reg_dims.append(())
            slew_normal[i] = float(r["slew_normal"])
            slew_fast[i] = float(r["slew_fast"])
            floor[i] = float(r["floor"])
            ev = r["emergency_value"]
            ss = r["safe_state"]
            emergency[i] = None if ev is None else float(ev)
            safe_state[i] = None if ss is None else float(ss)
            for key, sink in (
                ("emergency_by_cause", emergency_by_cause),
                ("safe_state_by_cause", safe_state_by_cause),
            ):
                for cause, v in (r.get(key) or {}).items():
                    sink.setdefault(_cause_index(cause, dim_order), {})[i] = None if v is None else float(v)

        reg_index = {name: i for i, name in enumerate(reg_names)}
        conflicts = []
        for rule in reg_cfg["conflicts"]:
            when = tuple((dim_order.index(dim), op == "above", float(thresh)) for dim, op, thresh in rule["when"])
            force = tuple((reg_index[n], float(v)) for n, v in rule.get("force", {}).items())
            prefer = tuple((reg_index[n], float(v)) for n, v in rule.get("prefer", {}).items())
            conflicts.append((when, force, prefer))

        esc_cfg = reg_cfg.get("escalation")
        escalation = None
        if esc_cfg is not None:
            escalation = tuple((esc_cfg[d]["high"], esc_cfg[d]["low"]) for d in dim_order)

        latch = reg_cfg["latch"]
        return cls(
            tuple(reg_dims),
            reg_cfg["band_edges"],
            slew_normal,
            slew_fast,
            floor,
            emergency,
            safe_state,
            tuple(conflicts),
            float(latch["release_max"]),
            int(latch["release_ticks"]),
            float(latch["min_s"]),
            float(tick_s),
            escalation=escalation,
            latch_enter_ticks=int(latch.get("enter_ticks", 1)),
            emergency_by_cause=emergency_by_cause,
            safe_state_by_cause=safe_state_by_cause,
        )

    def band_index(self, sev):
        """Band index of a severity: count of edges the severity has reached."""
        idx = 0
        for e in self._edges:
            if sev >= e:
                idx += 1
            else:
                break
        return idx

    def _reg_severity(self, dims, sev):
        m = 0.0
        for di in dims:
            if sev[di] > m:
                m = sev[di]
        return m

    def _forced_for(self, mask, base, cause_vecs, scratch):
        """Pick the forced (values, hold) pair for the active cause ``mask``.

        Returns ``base`` unchanged whenever nothing cause-specific applies,
        which is the whole cost for a config that sets no overrides. With
        exactly one active cause its vector is used directly. With several, the
        conservative merge runs into the preallocated ``scratch`` — a regulator
        keeps a per-cause value only if every active cause agrees on it.
        """
        if cause_vecs is None or mask == 0:
            return base

        n_causes = self._n_causes
        # Single active cause: no merge needed.
        lone = -1
        count = 0
        for c in range(n_causes):
            if mask & (1 << c):
                lone = c
                count += 1
                if count > 1:
                    break
        if count == 1:
            cv = cause_vecs[lone]
            return base if cv is None else cv

        base_vec, base_hold = base
        out_vec, out_hold = scratch
        for i in range(self._n):
            first = True
            agree = True
            h0 = False
            v0 = 0.0
            for c in range(n_causes):
                if not (mask & (1 << c)):
                    continue
                cv = cause_vecs[c]
                if cv is None:
                    h = base_hold[i]
                    v = base_vec[i]
                else:
                    h = cv[1][i]
                    v = cv[0][i]
                if first:
                    h0 = h
                    v0 = v
                    first = False
                elif h != h0 or (h and v != v0):
                    agree = False
                    break
            if agree:
                out_hold[i] = 1 if h0 else 0
                out_vec[i] = v0
            else:
                out_hold[i] = 1 if base_hold[i] else 0
                out_vec[i] = base_vec[i]
        return out_vec, out_hold

    def arbitrate(self, target, sev, dev, out):
        """Resolve ``target`` into ``out`` (both len num_regs). Returns global severity.

        Args:
            target: organic surface/follower/tod outputs (array f).
            sev: per-dimension severity (array f, len 3).
            dev: per-dimension deviation (array f, len 3) — for conflict sides.
            out: preallocated array f to receive the commanded vector.
        """
        n = self._n
        last = self._last
        regsev = self._regsev

        gmax = 0.0
        for s in sev:
            if s > gmax:
                gmax = s

        # Escalating severity: the worst severity among the deviation
        # directions allowed to escalate. Drives steps 4-5 (and the latch
        # release gate) so a correctable direction — a tent still being
        # brought up to spec — never forces a shutdown it cannot undo.
        # Alongside the magnitude, record WHICH directions are escalating, as a
        # bitmask over causes (dim * 2, +1 for the low side). Three thresholds
        # are tracked because the three consumers differ: the emergency vector
        # wants causes at the emergency edge, the latch wants causes at the
        # latch edge, and the sticky latch mask wants causes still above
        # release_max (the same terms the release gate itself is written in).
        esc_high = self._esc_high
        esc_low = self._esc_low
        ungated = esc_high is None
        emax = 0.0
        mask_emerg = 0
        mask_latch = 0
        mask_hold = 0
        for i in range(len(sev)):
            d = dev[i]
            if d > 50.0:
                cause = i << 1
                allowed = True if ungated else esc_high[i]
            elif d < 50.0:
                cause = (i << 1) | 1
                allowed = True if ungated else esc_low[i]
            else:
                # Exactly at ideal: no direction, so no cause to attribute.
                # Ungated still counts it toward emax, which is what keeps
                # "no escalation block" identical to plain global severity.
                cause = -1
                allowed = ungated
            if not allowed:
                continue
            s = sev[i]
            if s > emax:
                emax = s
            if cause < 0:
                continue
            if s >= self._e_emerg:
                mask_emerg |= 1 << cause
            if s >= self._e_latch:
                mask_latch |= 1 << cause
            if s > self._latch_release_max:
                mask_hold |= 1 << cause
        self.escalation_severity = emax

        # 1. Slew limit (organic output only) + cache regulator severities.
        for i in range(n):
            rs = self._reg_severity(self._reg_dims[i], sev)
            regsev[i] = rs
            rate = self._slew_normal[i] if rs < self._e_minor else self._slew_fast[i]
            prev = last[i]
            delta = target[i] - prev
            if delta > rate:
                out[i] = prev + rate
            elif delta < -rate:
                out[i] = prev - rate
            else:
                out[i] = target[i]

        # 2. Floors (forced): only push toward stronger actuation.
        for i in range(n):
            if regsev[i] >= self._e_minor and out[i] < self._floor[i]:
                out[i] = self._floor[i]

        # 3. Conflict overrides (forced, global severity >= conflict edge).
        if gmax >= self._e_conflict:
            for when, force, prefer in self._conflicts:
                if self._when_satisfied(when, dev):
                    for idx, val in force:
                        out[idx] = val
                    for idx, val in prefer:
                        if out[idx] < val:
                            out[idx] = val

        # 4. Emergency (forced): any escalating dim severity >= emergency edge.
        # Stateless — the cause mask is re-read every tick by design.
        self.just_entered_emergency = False
        if emax >= self._e_emerg:
            vec, hold = self._forced_for(
                mask_emerg,
                (self._emergency, self._emergency_hold),
                self._emerg_cause,
                self._merge_e,
            )
            for i in range(n):
                if hold[i]:
                    out[i] = vec[i]
            if not self.emergency_active:
                self.just_entered_emergency = True
            self.emergency_active = True
        else:
            self.emergency_active = False

        # 5. Latch (forced + held): any escalating dim severity >= latch edge,
        # sustained for enter_ticks consecutive ticks.
        self.just_entered_latch = False
        self.just_released_latch = False
        if not self.latched:
            if emax >= self._e_latch:
                self._enter_counter += 1
            else:
                self._enter_counter = 0
            if self._enter_counter >= self._latch_enter_ticks:
                self.latched = True
                self._latch_ticks = 0
                self._enter_counter = 0
                self._release_counter = 0
                self._latch_cause_mask = mask_latch
                self.just_entered_latch = True
        if self.latched:
            # The latch cause mask is STICKY across the episode, unioned with
            # whatever is still above release_max. Two failure modes bracket
            # this. Freezing it at entry is unsafe: a latch entered on humidity
            # frees the heater, the heater runs, the tent genuinely overheats,
            # and a frozen mask keeps the heater free — a new hazard could never
            # take that freedom back. Re-reading it fresh each tick is the
            # opposite trap: release needs release_ticks AND min_s, so a cause
            # dipping under the edge for one tick would re-pin the heater, cool
            # the tent, push RH back up and reset the release counter — exactly
            # the deadlock this whole change exists to remove. Union of both is
            # safe in the only direction that matters, because the merge rule is
            # monotone: more causes can only remove freedom.
            self._latch_cause_mask |= mask_hold
            vec, hold = self._forced_for(
                self._latch_cause_mask,
                (self._safe_state, self._safe_hold),
                self._safe_cause,
                self._merge_s,
            )
            for i in range(n):
                if hold[i]:
                    out[i] = vec[i]
            self._latch_ticks += 1
            if emax <= self._latch_release_max:
                self._release_counter += 1
            else:
                self._release_counter = 0
            elapsed_s = self._latch_ticks * self._tick_s
            if self._release_counter >= self._latch_release_ticks and elapsed_s >= self._latch_min_s:
                self.latched = False
                self._latch_cause_mask = 0
                self.just_released_latch = True

        # Persist the commanded vector for next tick's slew reference.
        for i in range(n):
            last[i] = out[i]
        return gmax

    @staticmethod
    def _when_satisfied(when, dev):
        for dim_idx, is_above, thresh in when:
            d = dev[dim_idx]
            if is_above:
                if d - 50.0 < thresh:
                    return False
            else:
                if 50.0 - d < thresh:
                    return False
        return True
