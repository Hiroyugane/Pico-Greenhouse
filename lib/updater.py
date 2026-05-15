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
#
# This is a SCAFFOLD. Method bodies raise NotImplementedError; tests are
# expected to drive the implementation (TDD).

MANIFEST_FILENAME = "manifest.json"


class UpdateError(Exception):
    """Raised when the updater cannot safely apply a payload."""


class Updater:
    """
    SD-payload software updater.

    Constructed once per boot from DEVICE_CONFIG["updater"]. The owning
    caller (run_pending_update) drives the apply sequence:

        has_pending_update -> load_manifest -> verify_payload -> apply
        -> finalize -> machine.reset()

    Each method is independently testable; tests under tests/test_updater.py
    inject a temp-dir 'SD root' to exercise the full flow on host.

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
    """

    def __init__(
        self,
        update_dir: str,
        applied_dir: str,
        log_path: str,
        allowed_paths: list,
        max_retries: int = 3,
        retry_delay_ms: int = 200,
        wdt=None,
        time_provider=None,
    ):
        self.update_dir = update_dir.rstrip("/")
        self.applied_dir = applied_dir.rstrip("/")
        self.log_path = log_path
        self.allowed_paths = list(allowed_paths)
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.wdt = wdt
        self.time_provider = time_provider

    # --- Public API --------------------------------------------------

    def has_pending_update(self) -> bool:
        """
        Return True iff <update_dir>/<MANIFEST_FILENAME> exists.

        Does NOT validate the manifest contents; that's load_manifest().
        """
        raise NotImplementedError("Updater.has_pending_update")

    def load_manifest(self) -> dict:
        """
        Read and JSON-parse <update_dir>/manifest.json.

        Returns the parsed dict. Raises UpdateError if the file is missing,
        unreadable, malformed JSON, or missing required top-level keys
        (version, files).
        """
        raise NotImplementedError("Updater.load_manifest")

    def verify_payload(self, manifest: dict) -> list:
        """
        Walk manifest["files"], hash each on disk, and verify against the
        manifest. Return a list of error strings; an empty list means the
        payload is safe to apply.

        Checks performed:
        - Every entry path passes _is_path_allowed()
        - Every entry path is normalized (no '..', no absolute paths)
        - The corresponding file exists under <update_dir>/
        - The file's byte length matches entry["bytes"]
        - The file's SHA-256 matches entry["sha256"]
        """
        raise NotImplementedError("Updater.verify_payload")

    def apply(self, manifest: dict) -> None:
        """
        Copy each verified file from <update_dir>/ to its target location
        on flash. Retry per-file up to self.max_retries on OSError.

        Raises UpdateError if any file exhausts its retries; live code is
        left in whatever partial state the loop reached, and the payload
        is left in place so the next boot can retry.
        """
        raise NotImplementedError("Updater.apply")

    def finalize(self, manifest: dict) -> None:
        """
        Rename <update_dir> to <applied_dir>/<manifest['version']>/ so the
        trigger is cleared and the next boot doesn't re-apply. Creates
        <applied_dir>/ if missing.
        """
        raise NotImplementedError("Updater.finalize")

    def log(self, status: str, version: str, detail: str = "") -> None:
        """
        Append a single line to self.log_path:

            <iso_timestamp>  <status>  <version>  <detail>

        status is one of: "start", "verify_fail", "apply_fail",
        "apply_ok". Best-effort; swallows IO errors so a logging
        failure can't prevent boot continuation.
        """
        raise NotImplementedError("Updater.log")

    # --- Internal helpers -------------------------------------------

    def _is_path_allowed(self, rel_path: str) -> bool:
        """
        True iff rel_path is whitelisted by self.allowed_paths.

        - Exact match against any non-slash-terminated entry, OR
        - rel_path starts with any slash-terminated entry (prefix match).
        - Rejects '..' segments and absolute paths.
        """
        raise NotImplementedError("Updater._is_path_allowed")

    def _hash_file(self, abs_path: str) -> str:
        """
        Return the SHA-256 hex digest of the file at abs_path.

        Reads in chunks so a large file doesn't blow MicroPython memory.
        Feeds self.wdt between chunks when present.
        """
        raise NotImplementedError("Updater._hash_file")


# --- Boot-time entry point -----------------------------------------


def run_pending_update(config: dict, hardware, wdt=None) -> None:
    """
    Boot-time hook called from main.py BEFORE EventLogger init.

    Returns silently when there is no pending update or the updater is
    disabled in config. On a successful apply, calls machine.reset() and
    does not return.

    Args:
        config: DEVICE_CONFIG dict (we read config["updater"]).
        hardware: HardwareFactory instance (used to confirm SD is mounted).
        wdt: Optional WDT instance to feed during the apply loop.

    Flow:
        1. Skip if config["updater"]["enabled"] is False.
        2. Skip if SD is not mounted (no payload possible).
        3. Construct Updater from config["updater"].
        4. updater.has_pending_update() -> if False, return.
        5. updater.log("start", ...)
        6. manifest = updater.load_manifest()
           on UpdateError: updater.log("verify_fail", ...) and return.
        7. errors = updater.verify_payload(manifest)
           on errors: updater.log("verify_fail", ...) and return.
        8. try updater.apply(manifest)
           on UpdateError: updater.log("apply_fail", ...) and return
           (live code may be partially overwritten; next boot will
           re-attempt because /sd/update/ still exists).
        9. updater.finalize(manifest)
        10. updater.log("apply_ok", ...)
        11. machine.reset()
    """
    raise NotImplementedError("run_pending_update")
