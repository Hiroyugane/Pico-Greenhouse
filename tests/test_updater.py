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
