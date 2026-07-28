# Software Updater - SD-payload self-update
# Dennis Hiro, 2026-05-15
#
# Operator drops a payload onto the SD card; on next boot the Pico replaces
# its own main.py / config.py / lib/*.py from that payload without needing
# Thonny or a USB connection.
#
# Boot-time wiring lives in main.py: run_pending_update() is called AFTER
# HardwareFactory.setup() (so /sd is mounted) but BEFORE EventLogger is
# created (so we don't depend on logging infrastructure that may itself
# be replaced by the update).
#
# Apply rules:
# - Path whitelist: only files matching updater.allowed_paths in DEVICE_CONFIG
#   are accepted. Anything outside is a verification failure.
# - Verify-then-write: every file's SHA-256 is checked BEFORE any file is
#   written. A bad payload never touches live code.
# - Per-file retry: failed writes retry up to updater.max_retries.
# - No backup of live code (per design decision 2026-05-15).
# - Prune: after a successful apply, files under the allowed_paths roots that
#   the payload did not ship are deleted, so flash stops being additive and a
#   stale lib/<mod>.mpy cannot go on shadowing its frozen twin. Bounded by four
#   rules — see Updater.prune().
# - Post-apply: payload is renamed to <applied_dir>/<version>/, then
#   machine.reset() is called so the new code runs cleanly.

import binascii
import hashlib
import json
import os

MANIFEST_FILENAME = "manifest.json"

# fixed: package structure, not a payload-managed module. The sweep leaves it
# alone rather than reasoning about whether this MicroPython needs it.
_PRUNE_NEVER = ("__init__.py",)

# Root that apply() writes into. Defaults to "/" on the Pico (flash root).
# Tests monkeypatch this to redirect writes into a tmp_path.
_FLASH_ROOT = "/"

_HASH_CHUNK = 1024


class UpdateError(Exception):
    """Raised when the updater cannot safely apply a payload."""


def _norm(path):
    """Normalize separators to forward-slash for whitelist matching."""
    return path.replace("\\", "/") if path else path


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _is_dir(path):
    try:
        return (os.stat(path)[0] & 0o40000) != 0
    except OSError:
        return False


def _dirname(path):
    norm = _norm(path)
    if "/" not in norm:
        return ""
    return norm.rsplit("/", 1)[0]


def _makedirs(path):
    """Recursively create directories; idempotent. Works on MicroPython."""
    if not path or _exists(path):
        return
    parent = _dirname(path)
    # On Windows the volume root (e.g. "L:") has no parent and exists.
    if parent and parent != path and not _exists(parent) and not (len(parent) == 2 and parent.endswith(":")):
        _makedirs(parent)
    try:
        os.mkdir(path)
    except OSError:
        if not _exists(path):
            raise


def _rmtree(path):
    """Recursive remove; best-effort, swallows OSError on per-entry failures."""
    try:
        entries = os.listdir(path)
    except OSError:
        return
    for entry in entries:
        sub = path + "/" + entry
        try:
            if _is_dir(sub):
                _rmtree(sub)
            else:
                os.remove(sub)
        except OSError:
            pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def _sleep_ms(ms):
    """Portable millisecond sleep."""
    if ms <= 0:
        return
    try:
        import time

        if hasattr(time, "sleep_ms"):
            time.sleep_ms(ms)
        else:
            time.sleep(ms / 1000.0)
    except Exception:
        pass


def _running_frozen_modules():
    """Module names the running firmware froze, or ``()`` when unknowable.

    Isolated like ``_running_mpy_abi`` so the prune guard can be exercised on
    the host, where there is no frozen ``fw_info`` to ask.
    """
    try:
        from lib import version

        return tuple(version.current_frozen_modules())
    except Exception:
        return ()


def _running_mpy_abi():
    """Bytecode ABI of the firmware we are running on, or None if unknowable.

    Isolated in a module-level function so the guard can be exercised on the
    host, where there is no MicroPython runtime to ask.
    """
    try:
        from lib import version

        return version.current_mpy_abi()
    except Exception:
        return None


def _timestamp_iso():
    """Best-effort ISO-like timestamp; falls back to '?' on failure."""
    try:
        import time

        t = time.localtime()
        return "%04d-%02d-%02dT%02d:%02d:%02d" % (t[0], t[1], t[2], t[3], t[4], t[5])
    except Exception:
        return "?"


class Updater:
    """
    SD-payload software updater.

    Constructed once per boot from DEVICE_CONFIG["updater"]. The owning
    caller (run_pending_update) drives the apply sequence:

        has_pending_update -> load_manifest -> verify_payload -> apply
        -> finalize -> machine.reset()

    Attributes:
        update_dir (str): Path operator drops payload into (e.g. /sd/ota/pending)
        applied_dir (str): Path successful payloads are renamed under
        log_path (str): Append-only history file path
        allowed_paths (list[str]): Whitelist; entries are either exact file
            paths (e.g. "main.py") or directory prefixes ending in "/"
            (e.g. "lib/"). Manifest entries not matching any prefix are
            rejected before any write.
        max_retries (int): Per-file write retry count
        retry_delay_ms (int): Sleep between retries
        prune_stale (bool): Delete files under the allowed_paths roots that
            this payload did not ship. See prune() for the safety rules.
        wdt: Optional WDT instance; fed between file copies
    """

    def __init__(
        self,
        update_dir,
        applied_dir,
        log_path,
        allowed_paths,
        max_retries=3,
        retry_delay_ms=200,
        wdt=None,
        feedback=None,
        log_max_size=50000,
        verify_max_retries=3,
        verify_retry_delay_ms=200,
        enforce_mpy_abi=True,
        prune_stale=False,
    ):
        self.update_dir = update_dir.rstrip("/").rstrip("\\")
        self.applied_dir = applied_dir.rstrip("/").rstrip("\\")
        self.log_path = log_path
        self.allowed_paths = list(allowed_paths)
        self.max_retries = int(max_retries)
        self.retry_delay_ms = int(retry_delay_ms)
        self.wdt = wdt
        self.feedback = feedback
        self.log_max_size = int(log_max_size)
        self.verify_max_retries = int(verify_max_retries)
        self.verify_retry_delay_ms = int(verify_retry_delay_ms)
        self.enforce_mpy_abi = bool(enforce_mpy_abi)
        self.prune_stale = bool(prune_stale)

    # --- Public API --------------------------------------------------

    def has_pending_update(self):
        return _exists(self.update_dir + "/" + MANIFEST_FILENAME)

    def load_manifest(self):
        path = self.update_dir + "/" + MANIFEST_FILENAME
        if not _exists(path):
            raise UpdateError("manifest missing: %s" % path)
        try:
            with open(path, "r") as f:
                # json.load(stream), not json.loads(f.read()): the read would
                # hold the whole manifest text AND the parsed tree at once,
                # which is what died first on the memory-tight Pico.
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise UpdateError("manifest unreadable: %s" % e)
        if not isinstance(data, dict):
            raise UpdateError("manifest must be a JSON object")
        if "version" not in data or "files" not in data:
            raise UpdateError("manifest missing required keys (version, files)")
        if not isinstance(data["files"], list):
            raise UpdateError("manifest.files must be a list")
        return data

    def check_mpy_abi(self, manifest):
        """Return None when the payload is importable here, else a refusal detail.

        A ``.mpy`` file only loads under the bytecode ABI its ``mpy-cross``
        targeted. SHA-256 verification cannot see that — it proves the bytes
        arrived intact, not that they mean anything to this firmware — so a
        mismatched compiled payload used to verify, apply, reset, and only
        then fail every import, on a board with no REPL. This check moves that
        failure to before the first write.

        Skipped (returns None) when:
        - the guard is disabled in config,
        - the manifest carries no ``mpy_abi`` (a raw-.py payload, which
          recompiles on-device against whatever firmware is present, and every
          payload built before this field existed),
        - the running firmware's ABI cannot be determined. Guessing would
          either brick a good payload or wave a bad one through; a breadcrumb
          records that the check did not run.

        A malformed stamp IS refused: it means the builder is broken, and a
        broken builder is exactly when you want the update to stop.
        """
        if not self.enforce_mpy_abi:
            return None
        declared = manifest.get("mpy_abi")
        if declared is None:
            return None
        try:
            declared = int(declared)
        except (TypeError, ValueError):
            return "mpy_abi malformed: %r" % (declared,)
        running = _running_mpy_abi()
        if running is None:
            self._breadcrumb("abi check skipped (firmware abi unknown)")
            return None
        if declared != running:
            return "mpy_abi mismatch: payload=%d firmware=%d" % (declared, running)
        self._breadcrumb("abi ok (%d)" % declared)
        return None

    def verify_payload(self, manifest):
        errors = []
        files = manifest.get("files", [])
        if not files:
            errors.append("manifest.files is empty")
            self._breadcrumb("verify done errors=1 (empty manifest)")
            return errors
        self._breadcrumb("verify start files=%d" % len(files))
        for entry in files:
            self._step_feedback(audio=True)
            try:
                rel = entry["path"]
                expected_hash = entry["sha256"]
                expected_size = int(entry["bytes"])
            except (KeyError, TypeError, ValueError):
                errors.append("manifest entry malformed: %r" % entry)
                self._breadcrumb("verify ? malformed_entry")
                continue

            if not self._is_path_allowed(rel):
                errors.append("path not allowed: %s" % rel)
                self._breadcrumb("verify %s not_allowed" % rel)
                continue

            abs_path = self.update_dir + "/" + rel
            outcome = self._verify_one_with_retry(abs_path, rel, expected_size, expected_hash)
            if outcome is None:
                self._breadcrumb("verify %s ok" % rel)
            else:
                kind, detail = outcome
                errors.append(detail)
                self._breadcrumb("verify %s %s" % (rel, kind))
        self._breadcrumb("verify done errors=%d" % len(errors))
        return errors

    def _verify_one_with_retry(self, abs_path, rel, expected_size, expected_hash):
        """Stat + hash one file; retry on OSError up to verify_max_retries.

        Returns None on success, or (breadcrumb_kind, detail_string) on terminal
        failure. Semantic mismatches (size_mismatch, hash_mismatch) return
        immediately without retrying — they're not bus glitches. OSError on
        stat or hash retries with verify_retry_delay_ms between attempts so a
        transient SD bus stall is given a chance to recover.
        """
        attempts = self.verify_max_retries + 1
        last_kind = "stat_fail"
        last_detail = "stat failed for %s: unknown" % rel
        for attempt in range(attempts):
            if attempt > 0:
                _sleep_ms(self.verify_retry_delay_ms)
                self._feed_wdt()
            try:
                actual_size = os.stat(abs_path)[6]
            except OSError as e:
                last_kind = "stat_fail %s" % e
                last_detail = "stat failed for %s: %s" % (rel, e)
                continue
            if actual_size != expected_size:
                return (
                    "size_mismatch %d/%d" % (actual_size, expected_size),
                    "size mismatch for %s: %d != %d" % (rel, actual_size, expected_size),
                )
            try:
                actual_hash = self._hash_file(abs_path)
            except OSError as e:
                last_kind = "hash_fail %s" % e
                last_detail = "hash failed for %s: %s" % (rel, e)
                continue
            if actual_hash.lower() != expected_hash.lower():
                return ("hash_mismatch", "sha256 mismatch for %s" % rel)
            return None
        return (last_kind, last_detail)

    def is_already_applied(self, manifest):
        """Return True if every manifest file already exists on flash with matching size + sha256.

        Used as a pre-apply short-circuit so the operator doesn't burn flash
        writes (or hit MicroPython-side write quirks) re-applying a payload
        that's byte-for-byte identical to the live code. The check uses the
        same SHA-256 path as verify_payload, just against ``_FLASH_ROOT``
        instead of ``update_dir``.
        """
        files = manifest.get("files", [])
        if not files:
            return False
        flash_root = _FLASH_ROOT
        flash_root_clean = flash_root.rstrip("/").rstrip("\\")
        for entry in files:
            try:
                rel = entry["path"]
                expected_hash = entry["sha256"]
                expected_size = int(entry["bytes"])
            except (KeyError, TypeError, ValueError):
                return False
            if flash_root_clean:
                abs_path = flash_root_clean + "/" + rel
            else:
                abs_path = "/" + rel
            if not _exists(abs_path):
                return False
            try:
                actual_size = os.stat(abs_path)[6]
            except OSError:
                return False
            if actual_size != expected_size:
                return False
            try:
                actual_hash = self._hash_file(abs_path)
            except OSError:
                return False
            if actual_hash.lower() != expected_hash.lower():
                return False
        return True

    def apply(self, manifest):
        flash_root = _FLASH_ROOT
        flash_root_clean = flash_root.rstrip("/").rstrip("\\")
        files = manifest["files"]
        self._breadcrumb("apply start files=%d" % len(files))
        for entry in files:
            self._step_feedback(audio=True)
            rel = entry["path"]
            src = self.update_dir + "/" + rel
            if flash_root_clean:
                dst = flash_root_clean + "/" + rel
            else:
                dst = "/" + rel
            parent = _dirname(dst)
            last_err = None
            for _attempt in range(self.max_retries):
                try:
                    if parent:
                        _makedirs(parent)
                    self._copy_file(src, dst)
                    last_err = None
                    break
                except OSError as e:
                    last_err = e
                    _sleep_ms(self.retry_delay_ms)
            if last_err is not None:
                self._breadcrumb("apply %s fail %s" % (rel, last_err))
                raise UpdateError("apply: %s failed after %d retries: %s" % (rel, self.max_retries, last_err))
            self._breadcrumb("apply %s ok" % rel)
            self._feed_wdt()
        self._breadcrumb("apply done")

    def prune(self, manifest):
        """Delete files this payload did not ship. Returns the removed rel-paths.

        Applying a payload is otherwise strictly additive, and on a frozen
        firmware that is a correctness bug rather than untidiness: imports
        resolve ``lib.<mod>`` before the bare frozen name, so a ``lib/foo.mpy``
        left over from a pre-freeze deploy *wins* over the frozen ``foo``. The
        module still imports and still runs — just the old copy, with the heap
        saving silently absent. Nothing raises, nothing logs.

        Four rules bound what may be deleted, and every one of them is load
        bearing:

        1. **Only inside ``allowed_paths``.** The same whitelist that decides
           what apply() may write decides what prune may unwrite. ``/sd``,
           ``/local``, ``boot.log`` and every data path are outside it, so they
           are not merely skipped — they are unreachable.
        2. **Only ``.py`` / ``.mpy``.** Anything else under those roots was put
           there by something that is not this updater.
        3. **A twin of a shipped file is always removable.** ``config.py`` next
           to a shipped ``config.mpy`` is a second copy of a file the payload
           owns, so dropping it cannot remove functionality — and it settles a
           question we would otherwise have to answer, since which of the pair
           MicroPython prefers is not something this code should have to know.
        4. **Anything else needs ``fw_info.FROZEN_MODULES``.** Deleting a
           module whose only copy is in ``/lib`` bricks the import. The frozen
           record is the one authority that cannot be wrong about this image —
           a manifest can be built from a repo commit newer than the flashed
           firmware and claim a freeze that never happened. When the record is
           absent (stock firmware, pre-2026-07-28 image) the sweep keeps the
           file and says so; "cannot tell" must never read as permission.

        Never raises: the payload is already live by the time this runs, so a
        failed unlink is a logged shadow, not a failed update.
        """
        if not self.prune_stale:
            return []
        shipped = self._shipped_paths(manifest)
        if not shipped:
            # An empty ship list would read as "the payload owns nothing here"
            # and take the whole scope with it. verify_payload already refuses
            # empty manifests; this is the belt to that suspenders.
            self._breadcrumb("prune skipped (nothing shipped)")
            return []
        frozen = _running_frozen_modules()
        if not frozen:
            self._breadcrumb("prune: firmware frozen set unknown, twins only")
        flash_root = _FLASH_ROOT.rstrip("/").rstrip("\\")
        removed = []
        for entry in self.allowed_paths:
            entry_norm = _norm(entry)
            if entry_norm.endswith("/"):
                removed.extend(self._prune_dir(entry_norm, shipped, frozen, flash_root))
            else:
                removed.extend(self._prune_twin(entry_norm, shipped, flash_root))
        self._breadcrumb("prune done removed=%d" % len(removed))
        return removed

    def _shipped_paths(self, manifest):
        """Normalized rel-paths the manifest ships, skipping malformed entries."""
        out = []
        for entry in manifest.get("files", []):
            try:
                rel = entry["path"]
            except (KeyError, TypeError):
                continue
            if isinstance(rel, str) and rel:
                out.append(_norm(rel))
        return out

    def _prune_dir(self, root, shipped, frozen, flash_root):
        """Sweep one directory root (an allowed_paths entry ending in '/')."""
        rel_dir = root.rstrip("/")
        abs_dir = (flash_root + "/" + rel_dir) if flash_root else "/" + rel_dir
        try:
            names = os.listdir(abs_dir)
        except OSError:
            return []
        shipped_here = set()
        for rel in shipped:
            if rel.startswith(root):
                shipped_here.add(rel[len(root) :].rsplit(".", 1)[0])
        shipped_set = set(shipped)
        removed = []
        for name in names:
            self._feed_wdt()
            if name in _PRUNE_NEVER:
                continue
            if not (name.endswith(".py") or name.endswith(".mpy")):
                continue
            rel = root + name
            if rel in shipped_set:
                continue
            abs_path = abs_dir + "/" + name
            if _is_dir(abs_path):
                continue
            stem = name.rsplit(".", 1)[0]
            if stem in shipped_here:
                reason = "twin"
            elif stem in frozen:
                reason = "shadow"
            elif frozen:
                reason = "orphan"
            else:
                self._breadcrumb("prune keep %s (frozen set unknown)" % rel)
                continue
            if self._remove_one(abs_path, rel, reason):
                removed.append(rel)
        return removed

    def _prune_twin(self, rel, shipped, flash_root):
        """Remove an exact allowed_paths entry only when a same-stem sibling shipped.

        Deliberately narrower than the directory sweep: at the flash root a
        not-shipped file is as likely to be something the payload never managed
        as it is to be stale, and ``main.py`` is not a file to be clever about.
        Only the ``config.py`` / ``config.mpy`` shape qualifies.
        """
        if rel in shipped:
            return []
        stem = rel.rsplit(".", 1)[0]
        if not any(other != rel and other.rsplit(".", 1)[0] == stem for other in shipped):
            return []
        abs_path = (flash_root + "/" + rel) if flash_root else "/" + rel
        if not _exists(abs_path) or _is_dir(abs_path):
            return []
        return [rel] if self._remove_one(abs_path, rel, "twin") else []

    def _remove_one(self, abs_path, rel, reason):
        try:
            os.remove(abs_path)
        except OSError as e:
            self._breadcrumb("prune %s fail %s" % (rel, e))
            return False
        self._breadcrumb("prune %s removed (%s)" % (rel, reason))
        return True

    def finalize(self, manifest):
        version = manifest.get("version") or "unknown"
        # Sanitize version for filesystem use (replace slashes/backslashes).
        safe_version = str(version).replace("/", "_").replace("\\", "_")
        if not _exists(self.applied_dir):
            _makedirs(self.applied_dir)
        dst = self.applied_dir + "/" + safe_version
        # Stale leftover from a prior interrupted finalize → remove first.
        if _exists(dst):
            _rmtree(dst)
        os.rename(self.update_dir, dst)

    def log(self, status, version, detail=""):
        # Whole body is best-effort: this is the sink the boot hook relies on
        # to report its own failures, so it must never become the thing that
        # raises. Even the line formatting can fail (a MemoryError, or a
        # version object whose __str__ blows up).
        try:
            self._log(status, version, detail)
        except Exception:
            pass

    def _log(self, status, version, detail=""):
        ts = _timestamp_iso()
        line = "%s\t%s\t%s\t%s" % (ts, status, version, detail)
        # Mirror to stdout so a Pico on USB serial still sees verify_fail
        # / apply_fail entries when the SD-side append silently fails.
        try:
            print("[updater]", line)
        except Exception:
            pass
        # Mirror to Pico internal flash (/boot.log) so the same entries
        # survive an SD card that's read-OK / write-flaky mid-update.
        try:
            try:
                from lib import boot_log
            except ImportError:  # frozen into the firmware as top-level modules
                import boot_log

            boot_log.write("[updater] " + line)
        except Exception:
            pass
        try:
            parent = _dirname(self.log_path)
            if parent:
                _makedirs(parent)
            self._maybe_rotate_log()
            with open(self.log_path, "a") as f:
                f.write(line + "\n")
        except Exception:
            # Logging is best-effort; never block boot continuation.
            pass

    def _maybe_rotate_log(self):
        """Rotate the log to a day-granular archive once it crosses ``log_max_size``.

        Uses ``<base>_<YYYY-MM-DD>.log`` (numbered ``.1.log``, ``.2.log`` … when
        the base name is already taken) so several same-day rotations coalesce
        instead of minting one file per rotation. Matches the EventLogger scheme
        — see docs/notes/chat-log 2026-07-20 for why per-rotation timestamps were
        a problem.
        """
        if self.log_max_size <= 0:
            return
        try:
            size = os.stat(self.log_path)[6]
        except OSError:
            return
        if size < self.log_max_size:
            return
        date_str = _timestamp_iso().split("T")[0]  # 'YYYY-MM-DD'
        base = self.log_path[:-4] if self.log_path.endswith(".log") else self.log_path
        # fixed: cap same-day numbered archives; far above any real daily rotation count.
        rotated = None
        for index in range(0, 1000):
            candidate = "%s_%s.log" % (base, date_str) if index == 0 else "%s_%s.%d.log" % (base, date_str, index)
            try:
                os.stat(candidate)  # taken — try the next index
                continue
            except OSError:
                rotated = candidate
                break
        if rotated is None:
            return
        try:
            os.rename(self.log_path, rotated)
        except OSError:
            pass

    # --- Internal helpers -------------------------------------------

    def _is_path_allowed(self, rel_path):
        if not rel_path or not isinstance(rel_path, str):
            return False
        if rel_path.startswith("/") or rel_path.startswith("\\"):
            return False
        norm = _norm(rel_path)
        parts = norm.split("/")
        for part in parts:
            if part in ("", "..", "."):
                return False
        for entry in self.allowed_paths:
            entry_norm = _norm(entry)
            if entry_norm.endswith("/"):
                if norm.startswith(entry_norm):
                    return True
            else:
                if norm == entry_norm:
                    return True
        return False

    def _hash_file(self, abs_path):
        h = hashlib.sha256()
        with open(abs_path, "rb") as f:
            while True:
                chunk = f.read(_HASH_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                self._feed_wdt()
                self._step_feedback(audio=False)
        return binascii.hexlify(h.digest()).decode("ascii")

    def _copy_file(self, src, dst):
        """Byte-for-byte copy with bounded buffer (MicroPython-friendly)."""
        with open(src, "rb") as fin:
            with open(dst, "wb") as fout:
                while True:
                    chunk = fin.read(_HASH_CHUNK)
                    if not chunk:
                        break
                    fout.write(chunk)
                    self._feed_wdt()
                    self._step_feedback(audio=False)

    def _feed_wdt(self):
        if self.wdt is None:
            return
        try:
            self.wdt.feed()
        except Exception:
            pass

    def _step_feedback(self, audio=False):
        """Advance loading-screen feedback if attached; silent otherwise."""
        if self.feedback is None:
            return
        try:
            self.feedback.step(audio=audio)
        except Exception:
            pass

    def _breadcrumb(self, message):
        """Append a verify/apply progress crumb to /boot.log only.

        Independent of self.log() so a per-file trail survives even when
        the SD-side updates.log append silently fails mid-run.
        """
        try:
            try:
                from lib import boot_log
            except ImportError:  # frozen into the firmware as top-level modules
                import boot_log

            boot_log.write("[updater.crumb] " + message)
        except Exception:
            pass


# --- Boot-time entry point -----------------------------------------


def _report_unhandled(updater, version, exc):
    """Log an exception that escaped the update sequence.

    Collects garbage first: the most likely escapee is a MemoryError, and the
    log line itself has to allocate. Every write is best-effort — the point is
    that the operator never again sees a payload detected with no follow-up.
    """
    try:
        import gc

        gc.collect()
    except Exception:
        pass
    try:
        detail = "%s: %s" % (type(exc).__name__, exc)
    except Exception:
        detail = "unhandled exception (detail unrenderable)"
    updater.log("error", version, detail=detail[:240])


def _prune_quietly(updater, manifest):
    """Run the prune sweep, swallowing anything it throws. Returns removed paths.

    Called only after the new code is already on flash, so a sweep that dies
    (MemoryError on a long listdir, an SD stall) must not turn a successful
    update into a failed one. The cost of skipping is a shadow that survives to
    the next payload; the cost of raising here would be a card that re-runs the
    whole update every boot.
    """
    try:
        return updater.prune(manifest)
    except Exception as e:
        updater.log("prune_fail", str(manifest.get("version", "?")), detail=str(e)[:200])
        return []


def _drive_pending_update(updater, signal_failure, version_out):
    """Run load -> verify -> apply -> finalize for an already-detected payload.

    Returns True when the apply succeeded and the caller should reset the
    board, False for every handled outcome (verify failure, apply failure,
    already-applied short-circuit). Handled outcomes log themselves.

    ``version_out`` is a one-element list the caller reads when an *unhandled*
    exception escapes, so its catch-all log line still names the version.
    """
    try:
        manifest = updater.load_manifest()
    except UpdateError as e:
        updater.log("verify_fail", "?", detail="load_manifest: %s" % e)
        signal_failure()
        return False

    version = str(manifest.get("version", "?"))
    version_out[0] = version

    # Cheapest refusal first: an ABI-incompatible payload can never be applied,
    # so there is no point hashing megabytes of it off a slow SD card.
    abi_error = updater.check_mpy_abi(manifest)
    if abi_error:
        updater.log("verify_fail", version, detail=abi_error)
        signal_failure()
        return False

    errors = updater.verify_payload(manifest)
    if errors:
        # Keep log line bounded so a long error list can't blow the file.
        detail = "; ".join(errors)
        if len(detail) > 240:
            detail = detail[:237] + "..."
        updater.log("verify_fail", version, detail=detail)
        signal_failure()
        return False

    # Short-circuit: payload content already on flash. Skip the apply (no
    # flash writes), still finalize so the trigger is consumed, play the
    # noop jingle, and let the boot continue without a reset.
    #
    # The sweep still runs here, and that is the point: re-dropping the payload
    # a card already has is the operator's repair procedure for a card that
    # drifted (pre-freeze shadows, a leftover .py beside a .mpy). Removing a
    # shadow only takes effect on the next import, so a sweep that actually
    # deleted something asks for the reset the noop path otherwise skips.
    if updater.is_already_applied(manifest):
        pruned = _prune_quietly(updater, manifest)
        try:
            updater.finalize(manifest)
        except Exception as e:
            updater.log("noop", version, detail="finalize warn: %s" % str(e)[:200])
        else:
            updater.log(
                "noop",
                version,
                detail="already up to date; files=%d pruned=%d" % (len(manifest.get("files", [])), len(pruned)),
            )
        if updater.feedback is not None:
            try:
                updater.feedback.already_applied()
            except Exception:
                pass
        return bool(pruned)

    try:
        updater.apply(manifest)
    except UpdateError as e:
        updater.log("apply_fail", version, detail=str(e)[:240])
        signal_failure()
        return False

    # Between apply and finalize: the new code is on flash, so the shipped set
    # is now the truth about what belongs there, and the reset below makes the
    # removals take effect in one step.
    pruned = _prune_quietly(updater, manifest)

    try:
        updater.finalize(manifest)
    except Exception as e:
        # Apply already succeeded; finalize failure leaves the trigger in
        # place but the new code is live. Log it and proceed to reset so
        # the next boot sees applied code; the operator can clean up
        # /sd/ota/pending manually.
        updater.log("apply_ok", version, detail="finalize warn: %s" % str(e)[:200])
    else:
        updater.log(
            "apply_ok",
            version,
            detail="files=%d pruned=%d" % (len(manifest.get("files", [])), len(pruned)),
        )

    # Apply succeeded — play the success jingle before resetting so the
    # operator hears confirmation while the Pico reboots into the new code.
    if updater.feedback is not None:
        try:
            updater.feedback.success()
        except Exception:
            pass
    return True


def run_pending_update(config, hardware, wdt=None):
    """
    Boot-time hook called from main.py BEFORE EventLogger init.

    Returns silently when there is no pending update or the updater is
    disabled in config. On a successful apply, calls machine.reset() and
    does not return.

    When config["updater_feedback"]["enabled"] is True and a pending payload
    is present, a loading-screen LED chase + buzzer ticks run during verify
    and apply, then a distinct jingle plays for success or failure.

    Once a payload is detected, this function always writes a terminal log
    line — ``verify_fail`` / ``apply_fail`` / ``apply_ok`` / ``noop``, or
    ``error`` when an unexpected exception escapes the sequence. A lone
    ``start`` line with nothing after it is a bug, not a diagnosis.
    """
    upd_cfg = config.get("updater", {}) if isinstance(config, dict) else {}
    if not upd_cfg.get("enabled", False):
        return

    try:
        sd_ok = bool(hardware.is_sd_mounted())
    except Exception:
        sd_ok = False
    if not sd_ok:
        return

    # Canonical path wins. If it has no manifest, fall through to any
    # configured legacy paths so payloads dropped at /sd/update from the
    # pre-2026-05-15 layout still apply without re-copying.
    update_dir = upd_cfg["update_dir"]
    used_legacy = None
    if not _exists(update_dir + "/" + MANIFEST_FILENAME):
        for legacy in upd_cfg.get("legacy_update_dirs", []):
            if _exists(legacy + "/" + MANIFEST_FILENAME):
                update_dir = legacy
                used_legacy = legacy
                break

    updater = Updater(
        update_dir=update_dir,
        applied_dir=upd_cfg["applied_dir"],
        log_path=upd_cfg["log_path"],
        allowed_paths=upd_cfg.get("allowed_paths", []),
        max_retries=upd_cfg.get("max_retries", 3),
        retry_delay_ms=upd_cfg.get("retry_delay_ms", 200),
        wdt=wdt,
        log_max_size=upd_cfg.get("log_max_size", 50000),
        verify_max_retries=upd_cfg.get("verify_max_retries", 3),
        verify_retry_delay_ms=upd_cfg.get("verify_retry_delay_ms", 200),
        enforce_mpy_abi=upd_cfg.get("enforce_mpy_abi", True),
        prune_stale=upd_cfg.get("prune_stale", False),
    )

    if not updater.has_pending_update():
        return

    # A real update run is imminent: start it from a collected heap. The
    # 2026-07-22 OTA failures were MemoryErrors before the manifest even
    # parsed, so every recoverable byte counts here.
    try:
        import gc

        gc.collect()
    except Exception:
        pass

    # Build LED/buzzer feedback only once we know a real update is about to
    # run — otherwise we'd light the row on every boot. Failures here never
    # block the update.
    feedback = None
    try:
        from lib.updater_feedback import build_from_config

        feedback = build_from_config(config)
    except Exception:
        feedback = None
    updater.feedback = feedback

    def _signal_failure():
        if feedback is None:
            return
        try:
            feedback.failure()
        except Exception:
            pass

    if used_legacy is not None:
        updater.log("start", "?", detail="payload detected at legacy %s" % used_legacy)
    else:
        updater.log("start", "?", detail="payload detected")

    # Anything that escapes the sequence below used to propagate to main.py's
    # print()-only handler, which is invisible on a standalone Pico: the trail
    # stopped dead at "payload detected", no jingle, payload left in place.
    # Catch it here instead, where the updater's three log sinks still exist.
    version_out = ["?"]
    try:
        should_reset = _drive_pending_update(updater, _signal_failure, version_out)
    except Exception as e:
        _report_unhandled(updater, version_out[0], e)
        _signal_failure()
        return

    if not should_reset:
        return

    import machine

    machine.reset()
