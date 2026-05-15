# Tests for lib/updater.py
#
# Two layers:
# - TestUpdaterUnit: drives Updater methods directly with a tmp_path 'SD root'.
# - TestRunPendingUpdate: exercises the boot-time entry point end-to-end
#   with a fake HardwareFactory and machine.reset patched out.
#
# All tests use tmp_path as the SD root — no host_shims SD simulator needed.
# Scaffold ships with `xfail(strict=True)` so RED tests stay visible until the
# implementation lands. Drop the markers per-method as you implement.

import hashlib
import json

import pytest


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(p, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


@pytest.fixture
def sd_root(tmp_path):
    """Fake SD root with update/ and applied/ subdirs ready."""
    (tmp_path / "update").mkdir()
    (tmp_path / "applied").mkdir()
    return tmp_path


@pytest.fixture
def good_payload(sd_root):
    """
    Build a small valid payload under sd_root/update with a manifest.

    Returns (manifest_dict, [(rel_path, content_bytes), ...]).
    """
    files = [
        ("main.py", b"# new main\nprint('hi')\n"),
        ("config.py", b"# new config\nDEVICE_CONFIG = {}\n"),
        ("lib/relay.py", b"# new relay impl\n"),
    ]
    for rel, content in files:
        _write(sd_root / "update" / rel, content)
    manifest = {
        "version": "2026-05-15.1",
        "created_at": "2026-05-15T14:32:00Z",
        "files": [
            {"path": rel, "sha256": _sha256_bytes(content), "bytes": len(content)}
            for rel, content in files
        ],
    }
    (sd_root / "update" / "manifest.json").write_text(json.dumps(manifest))
    return manifest, files


@pytest.fixture
def updater_factory(sd_root):
    """Build an Updater pointing at sd_root with sane defaults."""

    def _make(**overrides):
        from lib.updater import Updater

        defaults = dict(
            update_dir=str(sd_root / "update"),
            applied_dir=str(sd_root / "applied"),
            log_path=str(sd_root / "updates.log"),
            allowed_paths=["main.py", "config.py", "lib/"],
            max_retries=3,
            retry_delay_ms=0,
        )
        defaults.update(overrides)
        return Updater(**defaults)

    return _make


class TestUpdaterUnit:
    """Direct method-level tests for the Updater class."""

    def test_has_pending_update_true_when_manifest_present(self, updater_factory, good_payload):
        u = updater_factory()
        assert u.has_pending_update() is True

    def test_has_pending_update_false_when_no_manifest(self, updater_factory, sd_root):
        u = updater_factory()
        assert u.has_pending_update() is False

    def test_load_manifest_parses_json(self, updater_factory, good_payload):
        manifest, _ = good_payload
        u = updater_factory()
        loaded = u.load_manifest()
        assert loaded["version"] == manifest["version"]
        assert len(loaded["files"]) == len(manifest["files"])

    def test_load_manifest_raises_on_bad_json(self, updater_factory, sd_root):
        from lib.updater import UpdateError

        (sd_root / "update" / "manifest.json").write_text("{not json")
        u = updater_factory()
        with pytest.raises(UpdateError):
            u.load_manifest()

    def test_verify_payload_clean(self, updater_factory, good_payload):
        manifest, _ = good_payload
        u = updater_factory()
        assert u.verify_payload(manifest) == []

    def test_verify_payload_detects_corrupt_file(self, updater_factory, good_payload, sd_root):
        manifest, _ = good_payload
        # Corrupt one file's bytes without updating manifest.
        (sd_root / "update" / "main.py").write_bytes(b"# tampered\n")
        u = updater_factory()
        errors = u.verify_payload(manifest)
        assert any("main.py" in e for e in errors)

    def test_verify_payload_rejects_path_outside_whitelist(self, updater_factory, sd_root):
        # Manifest claims a file outside the whitelist.
        manifest = {
            "version": "x",
            "files": [{"path": "docs/secrets.md", "sha256": "0" * 64, "bytes": 0}],
        }
        u = updater_factory()
        errors = u.verify_payload(manifest)
        assert any("docs/secrets.md" in e or "allowed" in e.lower() for e in errors)

    def test_verify_payload_rejects_traversal(self, updater_factory, sd_root):
        manifest = {
            "version": "x",
            "files": [{"path": "../etc/passwd", "sha256": "0" * 64, "bytes": 0}],
        }
        u = updater_factory()
        errors = u.verify_payload(manifest)
        assert errors  # any non-empty list is acceptable

    def test_apply_copies_files_to_flash_root(self, updater_factory, good_payload, sd_root, monkeypatch):
        # Point 'flash root' at a tmp dir by monkeypatching the updater's
        # write target. Exact mechanism TBD by implementation — this test
        # encodes the expectation, not the mechanism.
        manifest, files = good_payload
        flash_root = sd_root / "flash"
        flash_root.mkdir()
        monkeypatch.setattr("lib.updater._FLASH_ROOT", str(flash_root), raising=False)
        u = updater_factory()
        u.apply(manifest)
        for rel, content in files:
            assert (flash_root / rel).read_bytes() == content

    def test_finalize_moves_payload_to_applied(self, updater_factory, good_payload, sd_root):
        manifest, _ = good_payload
        u = updater_factory()
        u.finalize(manifest)
        applied = sd_root / "applied" / manifest["version"]
        assert applied.exists()
        assert (applied / "manifest.json").exists()
        assert not (sd_root / "update" / "manifest.json").exists()

    def test_log_appends_line(self, updater_factory, sd_root):
        u = updater_factory()
        u.log("apply_ok", "2026-05-15.1", detail="files=3")
        contents = (sd_root / "updates.log").read_text()
        assert "apply_ok" in contents
        assert "2026-05-15.1" in contents

    def test_is_path_allowed_matches_exact_and_prefix(self, updater_factory):
        u = updater_factory()
        assert u._is_path_allowed("main.py") is True
        assert u._is_path_allowed("lib/relay.py") is True
        assert u._is_path_allowed("docs/x.md") is False
        assert u._is_path_allowed("../etc/passwd") is False
        assert u._is_path_allowed("/etc/passwd") is False


class TestRunPendingUpdate:
    """End-to-end boot-time hook behaviour."""

    def test_no_payload_returns_silently(self, sd_root, monkeypatch):
        from lib import updater as upd_mod

        cfg = {
            "updater": {
                "enabled": True,
                "update_dir": str(sd_root / "update"),
                "applied_dir": str(sd_root / "applied"),
                "log_path": str(sd_root / "updates.log"),
                "max_retries": 3,
                "retry_delay_ms": 0,
                "allowed_paths": ["main.py", "config.py", "lib/"],
            }
        }

        class _HW:
            def is_sd_mounted(self):
                return True

        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update(cfg, _HW())
        assert reset_called == []

    def test_disabled_in_config_short_circuits(self, sd_root, good_payload, monkeypatch):
        from lib import updater as upd_mod

        cfg = {
            "updater": {
                "enabled": False,
                "update_dir": str(sd_root / "update"),
                "applied_dir": str(sd_root / "applied"),
                "log_path": str(sd_root / "updates.log"),
                "max_retries": 3,
                "retry_delay_ms": 0,
                "allowed_paths": ["main.py", "config.py", "lib/"],
            }
        }

        class _HW:
            def is_sd_mounted(self):
                return True

        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update(cfg, _HW())
        # Payload should be untouched; no reset.
        assert reset_called == []
        assert (sd_root / "update" / "manifest.json").exists()

    def test_good_payload_applies_and_resets(self, sd_root, good_payload, monkeypatch):
        from lib import updater as upd_mod

        manifest, files = good_payload
        flash_root = sd_root / "flash"
        flash_root.mkdir()
        monkeypatch.setattr("lib.updater._FLASH_ROOT", str(flash_root), raising=False)

        cfg = {
            "updater": {
                "enabled": True,
                "update_dir": str(sd_root / "update"),
                "applied_dir": str(sd_root / "applied"),
                "log_path": str(sd_root / "updates.log"),
                "max_retries": 3,
                "retry_delay_ms": 0,
                "allowed_paths": ["main.py", "config.py", "lib/"],
            }
        }

        class _HW:
            def is_sd_mounted(self):
                return True

        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update(cfg, _HW())

        for rel, content in files:
            assert (flash_root / rel).read_bytes() == content
        assert (sd_root / "applied" / manifest["version"]).exists()
        assert reset_called == [True]


class TestUpdaterErrorPaths:
    """Cover the failure / fallback branches that boot-time relies on."""

    def test_load_manifest_missing_required_keys(self, updater_factory, sd_root):
        from lib.updater import UpdateError

        (sd_root / "update" / "manifest.json").write_text('{"version": "x"}')
        u = updater_factory()
        with pytest.raises(UpdateError):
            u.load_manifest()

    def test_load_manifest_non_object_root(self, updater_factory, sd_root):
        from lib.updater import UpdateError

        (sd_root / "update" / "manifest.json").write_text("[]")
        u = updater_factory()
        with pytest.raises(UpdateError):
            u.load_manifest()

    def test_load_manifest_files_not_a_list(self, updater_factory, sd_root):
        from lib.updater import UpdateError

        (sd_root / "update" / "manifest.json").write_text('{"version": "x", "files": "no"}')
        u = updater_factory()
        with pytest.raises(UpdateError):
            u.load_manifest()

    def test_load_manifest_missing_file_raises(self, updater_factory):
        from lib.updater import UpdateError

        u = updater_factory()
        with pytest.raises(UpdateError):
            u.load_manifest()

    def test_verify_payload_empty_files(self, updater_factory):
        u = updater_factory()
        errors = u.verify_payload({"version": "x", "files": []})
        assert errors and any("empty" in e.lower() for e in errors)

    def test_verify_payload_malformed_entry(self, updater_factory):
        u = updater_factory()
        errors = u.verify_payload({"version": "x", "files": [{"path": "main.py"}]})
        assert errors and any("malformed" in e.lower() for e in errors)

    def test_verify_payload_missing_file_on_disk(self, updater_factory):
        u = updater_factory()
        errors = u.verify_payload(
            {"version": "x", "files": [{"path": "main.py", "sha256": "0" * 64, "bytes": 0}]}
        )
        assert errors and any("missing" in e.lower() for e in errors)

    def test_verify_payload_size_mismatch(self, updater_factory, sd_root):
        _write(sd_root / "update" / "main.py", b"hello")
        u = updater_factory()
        errors = u.verify_payload(
            {"version": "x", "files": [{"path": "main.py", "sha256": "0" * 64, "bytes": 999}]}
        )
        assert errors and any("size" in e.lower() for e in errors)

    def test_is_path_allowed_non_string(self, updater_factory):
        u = updater_factory()
        assert u._is_path_allowed(None) is False
        assert u._is_path_allowed("") is False
        assert u._is_path_allowed(123) is False  # type: ignore[arg-type]

    def test_is_path_allowed_dot_segment(self, updater_factory):
        u = updater_factory()
        assert u._is_path_allowed("./main.py") is False
        assert u._is_path_allowed("lib//x.py") is False

    def test_log_format_columns(self, updater_factory, sd_root):
        u = updater_factory()
        u.log("verify_fail", "v1", detail="sha256 mismatch for main.py")
        text = (sd_root / "updates.log").read_text()
        cols = text.strip().split("\t")
        assert len(cols) == 4
        assert cols[1] == "verify_fail"
        assert cols[2] == "v1"

    def test_log_swallows_io_error(self, updater_factory, sd_root):
        # Point log_path at a directory that doesn't exist; should not raise.
        u = updater_factory(log_path=str(sd_root / "missing_dir" / "updates.log"))
        u.log("start", "v1")  # would raise without best-effort guard

    def test_apply_retries_then_succeeds(self, updater_factory, good_payload, sd_root, monkeypatch):
        import lib.updater as upd_mod

        manifest, files = good_payload
        flash_root = sd_root / "flash"
        flash_root.mkdir()
        monkeypatch.setattr(upd_mod, "_FLASH_ROOT", str(flash_root), raising=False)

        # Make _copy_file fail twice then succeed.
        calls = {"n": 0}
        real_copy = upd_mod.Updater._copy_file

        def flaky_copy(self, src, dst):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("simulated transient")
            return real_copy(self, src, dst)

        monkeypatch.setattr(upd_mod.Updater, "_copy_file", flaky_copy)
        u = updater_factory(max_retries=5, retry_delay_ms=0)
        u.apply(manifest)
        # First file took 3 attempts; remaining files succeed first try each.
        assert calls["n"] >= 3
        for rel, content in files:
            assert (flash_root / rel).read_bytes() == content

    def test_apply_exhausts_retries(self, updater_factory, good_payload, sd_root, monkeypatch):
        import lib.updater as upd_mod
        from lib.updater import UpdateError

        manifest, _ = good_payload
        flash_root = sd_root / "flash"
        flash_root.mkdir()
        monkeypatch.setattr(upd_mod, "_FLASH_ROOT", str(flash_root), raising=False)

        def always_fail(self, src, dst):
            raise OSError("permanent")

        monkeypatch.setattr(upd_mod.Updater, "_copy_file", always_fail)
        u = updater_factory(max_retries=2, retry_delay_ms=0)
        with pytest.raises(UpdateError):
            u.apply(manifest)

    def test_finalize_creates_applied_dir(self, updater_factory, good_payload, sd_root):
        manifest, _ = good_payload
        # Remove pre-existing applied/ to force creation.
        (sd_root / "applied").rmdir()
        u = updater_factory()
        u.finalize(manifest)
        assert (sd_root / "applied" / manifest["version"] / "manifest.json").exists()

    def test_finalize_clears_stale_prior_dest(self, updater_factory, good_payload, sd_root):
        manifest, _ = good_payload
        # Pre-seed a stale applied/<version>/ with junk.
        stale = sd_root / "applied" / manifest["version"]
        stale.mkdir(parents=True)
        (stale / "old.txt").write_text("from prior run")
        u = updater_factory()
        u.finalize(manifest)
        assert (stale / "manifest.json").exists()
        assert not (stale / "old.txt").exists()

    def test_verify_sha256_mismatch_same_size(self, updater_factory, sd_root):
        # Same size, different bytes → size check passes, sha256 check fails.
        good = b"X" * 16
        bad = b"Y" * 16
        _write(sd_root / "update" / "main.py", bad)
        manifest = {
            "version": "x",
            "files": [
                {"path": "main.py", "sha256": _sha256_bytes(good), "bytes": len(good)},
            ],
        }
        u = updater_factory()
        errors = u.verify_payload(manifest)
        assert errors and any("sha256" in e.lower() for e in errors)

    def test_feed_wdt_swallows_exception(self, updater_factory):
        u = updater_factory()

        class _WDT:
            def feed(self):
                raise RuntimeError("simulated wdt fault")

        u.wdt = _WDT()
        # Should not raise.
        u._feed_wdt()

    def test_helpers_handle_edge_inputs(self):
        from lib import updater as upd_mod

        assert upd_mod._norm("") == ""
        assert upd_mod._norm(None) is None
        assert upd_mod._exists("/no/such/path/zzz") is False
        # _is_dir on a file should return False.
        assert upd_mod._is_dir(upd_mod.__file__) is False
        # _dirname when no separator present.
        assert upd_mod._dirname("main.py") == ""
        # _makedirs is a no-op on empty path.
        upd_mod._makedirs("")
        # _sleep_ms returns immediately on non-positive input.
        upd_mod._sleep_ms(0)
        upd_mod._sleep_ms(-5)

    def test_rmtree_handles_missing_path(self):
        from lib import updater as upd_mod

        # Should not raise.
        upd_mod._rmtree("/no/such/path/zzz")

    def test_hash_file_feeds_wdt(self, updater_factory, sd_root):
        u = updater_factory()
        fed = {"n": 0}

        class _WDT:
            def feed(self):
                fed["n"] += 1

        u.wdt = _WDT()
        # Force >1 chunk so the loop body runs multiple times.
        big = sd_root / "update" / "big.bin"
        big.write_bytes(b"x" * 4096)
        digest = u._hash_file(str(big))
        assert len(digest) == 64
        assert fed["n"] >= 1


class TestRunPendingUpdateBranches:
    """Cover boot-time branches not exercised by the happy/disabled paths."""

    def _base_cfg(self, sd_root):
        return {
            "updater": {
                "enabled": True,
                "update_dir": str(sd_root / "update"),
                "applied_dir": str(sd_root / "applied"),
                "log_path": str(sd_root / "updates.log"),
                "max_retries": 3,
                "retry_delay_ms": 0,
                "allowed_paths": ["main.py", "config.py", "lib/"],
            }
        }

    class _HW:
        def __init__(self, sd_ok=True, raise_on_check=False):
            self._sd_ok = sd_ok
            self._raise = raise_on_check

        def is_sd_mounted(self):
            if self._raise:
                raise RuntimeError("hw fault")
            return self._sd_ok

    def test_sd_not_mounted_returns(self, sd_root, good_payload, monkeypatch):
        from lib import updater as upd_mod

        cfg = self._base_cfg(sd_root)
        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update(cfg, self._HW(sd_ok=False))
        assert reset_called == []
        # Payload untouched.
        assert (sd_root / "update" / "manifest.json").exists()

    def test_sd_check_raises_returns(self, sd_root, good_payload, monkeypatch):
        from lib import updater as upd_mod

        cfg = self._base_cfg(sd_root)
        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update(cfg, self._HW(raise_on_check=True))
        assert reset_called == []

    def test_load_manifest_failure_logs_and_returns(self, sd_root, monkeypatch):
        from lib import updater as upd_mod

        (sd_root / "update" / "manifest.json").write_text("{not json")
        cfg = self._base_cfg(sd_root)
        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update(cfg, self._HW())
        assert reset_called == []
        log_text = (sd_root / "updates.log").read_text()
        assert "verify_fail" in log_text

    def test_verify_errors_log_and_return(self, sd_root, monkeypatch):
        from lib import updater as upd_mod

        # Manifest references a file that doesn't exist on disk.
        manifest = {
            "version": "v1",
            "files": [{"path": "main.py", "sha256": "0" * 64, "bytes": 5}],
        }
        (sd_root / "update" / "manifest.json").write_text(json.dumps(manifest))
        cfg = self._base_cfg(sd_root)
        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update(cfg, self._HW())
        assert reset_called == []
        assert "verify_fail" in (sd_root / "updates.log").read_text()

    def test_verify_error_detail_truncated(self, sd_root, monkeypatch):
        from lib import updater as upd_mod

        # Build a manifest with many missing files so the joined detail string > 240 chars.
        files = [{"path": f"lib/x{i}.py", "sha256": "0" * 64, "bytes": 0} for i in range(40)]
        manifest = {"version": "v1", "files": files}
        (sd_root / "update" / "manifest.json").write_text(json.dumps(manifest))
        cfg = self._base_cfg(sd_root)
        monkeypatch.setattr("machine.reset", lambda: None, raising=False)
        upd_mod.run_pending_update(cfg, self._HW())
        log_text = (sd_root / "updates.log").read_text()
        assert "..." in log_text  # truncation marker

    def test_apply_failure_logs_apply_fail(self, sd_root, good_payload, monkeypatch):
        from lib import updater as upd_mod

        flash_root = sd_root / "flash"
        flash_root.mkdir()
        monkeypatch.setattr(upd_mod, "_FLASH_ROOT", str(flash_root), raising=False)

        def always_fail(self, src, dst):
            raise OSError("simulated apply failure")

        monkeypatch.setattr(upd_mod.Updater, "_copy_file", always_fail)
        cfg = self._base_cfg(sd_root)
        cfg["updater"]["max_retries"] = 1
        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update(cfg, self._HW())
        assert reset_called == []
        assert "apply_fail" in (sd_root / "updates.log").read_text()

    def test_finalize_warn_still_resets(self, sd_root, good_payload, monkeypatch):
        from lib import updater as upd_mod

        flash_root = sd_root / "flash"
        flash_root.mkdir()
        monkeypatch.setattr(upd_mod, "_FLASH_ROOT", str(flash_root), raising=False)

        def boom(self, manifest):
            raise RuntimeError("simulated finalize fault")

        monkeypatch.setattr(upd_mod.Updater, "finalize", boom)
        cfg = self._base_cfg(sd_root)
        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update(cfg, self._HW())
        assert reset_called == [True]
        log_text = (sd_root / "updates.log").read_text()
        assert "apply_ok" in log_text and "finalize warn" in log_text

    def test_missing_config_returns_silently(self, sd_root, monkeypatch):
        from lib import updater as upd_mod

        reset_called = []
        monkeypatch.setattr("machine.reset", lambda: reset_called.append(True), raising=False)
        upd_mod.run_pending_update({}, self._HW())
        upd_mod.run_pending_update("not a dict", self._HW())  # type: ignore[arg-type]
        assert reset_called == []
