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
        for i, name in enumerate(reg_names):
            r = regulators[name]
            driven = r["driven"]
            if driven == "surface":
                idxs = [dim_order.index(d) for d in r["dims"]]
                if name == "exhaust" and co2_idx not in idxs:
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

        reg_index = {name: i for i, name in enumerate(reg_names)}
        conflicts = []
        for rule in reg_cfg["conflicts"]:
            when = tuple(
                (dim_order.index(dim), op == "above", float(thresh)) for dim, op, thresh in rule["when"]
            )
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
        esc_high = self._esc_high
        if esc_high is None:
            emax = gmax
        else:
            esc_low = self._esc_low
            emax = 0.0
            for i in range(len(sev)):
                d = dev[i]
                if d > 50.0:
                    allowed = esc_high[i]
                elif d < 50.0:
                    allowed = esc_low[i]
                else:
                    allowed = False
                if allowed and sev[i] > emax:
                    emax = sev[i]
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
        self.just_entered_emergency = False
        if emax >= self._e_emerg:
            hold = self._emergency_hold
            for i in range(n):
                if hold[i]:
                    out[i] = self._emergency[i]
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
                self.just_entered_latch = True
        if self.latched:
            hold = self._safe_hold
            for i in range(n):
                if hold[i]:
                    out[i] = self._safe_state[i]
            self._latch_ticks += 1
            if emax <= self._latch_release_max:
                self._release_counter += 1
            else:
                self._release_counter = 0
            elapsed_s = self._latch_ticks * self._tick_s
            if self._release_counter >= self._latch_release_ticks and elapsed_s >= self._latch_min_s:
                self.latched = False
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
