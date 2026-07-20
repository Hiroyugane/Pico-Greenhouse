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
# - Post-apply: payload is renamed to <applied_dir>/<version>/, then
#   machine.reset() is called so the new code runs cleanly.

import binascii
import hashlib
import json
import os

MANIFEST_FILENAME = "manifest.json"

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

    # --- Public API --------------------------------------------------

    def has_pending_update(self):
        return _exists(self.update_dir + "/" + MANIFEST_FILENAME)

    def load_manifest(self):
        path = self.update_dir + "/" + MANIFEST_FILENAME
        if not _exists(path):
            raise UpdateError("manifest missing: %s" % path)
        try:
            with open(path, "r") as f:
                data = json.loads(f.read())
        except (OSError, ValueError) as e:
            raise UpdateError("manifest unreadable: %s" % e)
        if not isinstance(data, dict):
            raise UpdateError("manifest must be a JSON object")
        if "version" not in data or "files" not in data:
            raise UpdateError("manifest missing required keys (version, files)")
        if not isinstance(data["files"], list):
            raise UpdateError("manifest.files must be a list")
        return data

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
            from lib import boot_log

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
            from lib import boot_log

            boot_log.write("[updater.crumb] " + message)
        except Exception:
            pass


# --- Boot-time entry point -----------------------------------------


def run_pending_update(config, hardware, wdt=None):
    """
    Boot-time hook called from main.py BEFORE EventLogger init.

    Returns silently when there is no pending update or the updater is
    disabled in config. On a successful apply, calls machine.reset() and
    does not return.

    When config["updater_feedback"]["enabled"] is True and a pending payload
    is present, a loading-screen LED chase + buzzer ticks run during verify
    and apply, then a distinct jingle plays for success or failure.
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
    )

    if not updater.has_pending_update():
        return

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

    try:
        manifest = updater.load_manifest()
    except UpdateError as e:
        updater.log("verify_fail", "?", detail="load_manifest: %s" % e)
        _signal_failure()
        return

    version = str(manifest.get("version", "?"))
    errors = updater.verify_payload(manifest)
    if errors:
        # Keep log line bounded so a long error list can't blow the file.
        detail = "; ".join(errors)
        if len(detail) > 240:
            detail = detail[:237] + "..."
        updater.log("verify_fail", version, detail=detail)
        _signal_failure()
        return

    # Short-circuit: payload content already on flash. Skip the apply (no
    # flash writes), still finalize so the trigger is consumed, play the
    # noop jingle, and let the boot continue without a reset.
    if updater.is_already_applied(manifest):
        try:
            updater.finalize(manifest)
        except Exception as e:
            updater.log("noop", version, detail="finalize warn: %s" % str(e)[:200])
        else:
            updater.log("noop", version, detail="already up to date; files=%d" % len(manifest.get("files", [])))
        if feedback is not None:
            try:
                feedback.already_applied()
            except Exception:
                pass
        return

    try:
        updater.apply(manifest)
    except UpdateError as e:
        updater.log("apply_fail", version, detail=str(e)[:240])
        _signal_failure()
        return

    try:
        updater.finalize(manifest)
    except Exception as e:
        # Apply already succeeded; finalize failure leaves the trigger in
        # place but the new code is live. Log it and proceed to reset so
        # the next boot sees applied code; the operator can clean up
        # /sd/ota/pending manually.
        updater.log("apply_ok", version, detail="finalize warn: %s" % str(e)[:200])
    else:
        updater.log("apply_ok", version, detail="files=%d" % len(manifest.get("files", [])))

    # Apply succeeded — play the success jingle before resetting so the
    # operator hears confirmation while the Pico reboots into the new code.
    if feedback is not None:
        try:
            feedback.success()
        except Exception:
            pass

    import machine

    machine.reset()
