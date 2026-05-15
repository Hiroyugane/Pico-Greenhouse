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
        update_dir (str): Path operator drops payload into (e.g. /sd/update)
        applied_dir (str): Path successful payloads are renamed under
        log_path (str): Append-only history file path
        allowed_paths (list[str]): Whitelist; entries are either exact file
            paths (e.g. "main.py") or directory prefixes ending in "/"
            (e.g. "lib/"). Manifest entries not matching any prefix are
            rejected before any write.
        max_retries (int): Per-file write retry count
        retry_delay_ms (int): Sleep between retries
        wdt: Optional WDT instance; fed between file copies
        time_provider: Optional time provider (currently unused; reserved
            for future structured log timestamps)
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
        time_provider=None,
        feedback=None,
    ):
        self.update_dir = update_dir.rstrip("/").rstrip("\\")
        self.applied_dir = applied_dir.rstrip("/").rstrip("\\")
        self.log_path = log_path
        self.allowed_paths = list(allowed_paths)
        self.max_retries = int(max_retries)
        self.retry_delay_ms = int(retry_delay_ms)
        self.wdt = wdt
        self.time_provider = time_provider
        self.feedback = feedback

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
            return errors
        for entry in files:
            self._step_feedback(audio=True)
            try:
                rel = entry["path"]
                expected_hash = entry["sha256"]
                expected_size = int(entry["bytes"])
            except (KeyError, TypeError, ValueError):
                errors.append("manifest entry malformed: %r" % entry)
                continue

            if not self._is_path_allowed(rel):
                errors.append("path not allowed: %s" % rel)
                continue

            abs_path = self.update_dir + "/" + rel
            if not _exists(abs_path):
                errors.append("missing file: %s" % rel)
                continue
            try:
                actual_size = os.stat(abs_path)[6]
            except OSError as e:
                errors.append("stat failed for %s: %s" % (rel, e))
                continue
            if actual_size != expected_size:
                errors.append("size mismatch for %s: %d != %d" % (rel, actual_size, expected_size))
                continue
            try:
                actual_hash = self._hash_file(abs_path)
            except OSError as e:
                errors.append("hash failed for %s: %s" % (rel, e))
                continue
            if actual_hash.lower() != expected_hash.lower():
                errors.append("sha256 mismatch for %s" % rel)
        return errors

    def apply(self, manifest):
        flash_root = _FLASH_ROOT
        flash_root_clean = flash_root.rstrip("/").rstrip("\\")
        for entry in manifest["files"]:
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
                raise UpdateError("apply: %s failed after %d retries: %s" % (rel, self.max_retries, last_err))
            self._feed_wdt()

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
        try:
            ts = _timestamp_iso()
            line = "%s\t%s\t%s\t%s\n" % (ts, status, version, detail)
            with open(self.log_path, "a") as f:
                f.write(line)
        except Exception:
            # Logging is best-effort; never block boot continuation.
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

    updater = Updater(
        update_dir=upd_cfg["update_dir"],
        applied_dir=upd_cfg["applied_dir"],
        log_path=upd_cfg["log_path"],
        allowed_paths=upd_cfg.get("allowed_paths", []),
        max_retries=upd_cfg.get("max_retries", 3),
        retry_delay_ms=upd_cfg.get("retry_delay_ms", 200),
        wdt=wdt,
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
        # /sd/update manually.
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
