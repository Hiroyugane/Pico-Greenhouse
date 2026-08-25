# Tests for lib/phase_notice.py
# Dennis Hiro, 2026-08-25

from unittest.mock import Mock

import pytest


@pytest.fixture
def store_path(tmp_path):
    return str(tmp_path / "phase_ack.txt")


@pytest.fixture
def store(store_path):
    from lib.phase_notice import PhaseNoticeStore

    return PhaseNoticeStore(storage_path=store_path)


class TestPhaseNoticeStorage:
    def test_no_file_reads_as_nothing_acknowledged(self, store):
        assert store.last_acknowledged() is None

    def test_acknowledge_persists_the_phase(self, store, store_path):
        store.acknowledge("stretch")
        with open(store_path) as f:
            assert f.read().strip() == "stretch"

    def test_acknowledge_survives_a_new_instance(self, store, store_path):
        """The whole point: the confirmation outlives the process that took it."""
        from lib.phase_notice import PhaseNoticeStore

        store.acknowledge("bloom")
        assert PhaseNoticeStore(storage_path=store_path).last_acknowledged() == "bloom"

    def test_acknowledge_overwrites_the_previous_phase(self, store):
        store.acknowledge("seedling")
        store.acknowledge("stretch")
        assert store.last_acknowledged() == "stretch"

    def test_empty_file_reads_as_nothing_acknowledged(self, store, store_path):
        with open(store_path, "w") as f:
            f.write("   \n")
        assert store.last_acknowledged() is None

    def test_trailing_whitespace_is_stripped(self, store, store_path):
        with open(store_path, "w") as f:
            f.write("bloom\n")
        assert store.last_acknowledged() == "bloom"

    def test_falsy_storage_path_degrades_to_no_persistence(self):
        """No path = a notice every boot, which is the safe direction to fail in."""
        from lib.phase_notice import PhaseNoticeStore

        store = PhaseNoticeStore(storage_path="")
        store.acknowledge("bloom")
        assert store.last_acknowledged() is None

    def test_acknowledge_ignores_an_empty_phase(self, store):
        store.acknowledge(None)
        assert store.last_acknowledged() is None

    def test_unwritable_path_is_logged_not_raised(self, tmp_path):
        """A failed write costs one repeated notice; it must not break the button."""
        from lib.phase_notice import PhaseNoticeStore

        logger = Mock()
        store = PhaseNoticeStore(storage_path=str(tmp_path / "missing_dir" / "ack.txt"), logger=logger)
        store.acknowledge("bloom")  # must not raise
        assert logger.error.call_count == 1

    def test_unwritable_path_without_logger_does_not_raise(self, tmp_path):
        from lib.phase_notice import PhaseNoticeStore

        PhaseNoticeStore(storage_path=str(tmp_path / "missing_dir" / "ack.txt")).acknowledge("bloom")


class TestPhaseNoticeBootDecision:
    def test_first_boot_seeds_and_stays_silent(self, store, store_path):
        """The first phase of a grow is what the operator just configured."""
        assert store.needs_notice("seedling") is False
        assert store.last_acknowledged() == "seedling"

    def test_seeding_logs_once_when_a_logger_is_wired(self, store_path):
        from lib.phase_notice import PhaseNoticeStore

        logger = Mock()
        assert PhaseNoticeStore(storage_path=store_path, logger=logger).needs_notice("seedling") is False
        assert logger.info.call_count == 1

    def test_matching_phase_raises_no_notice(self, store):
        store.acknowledge("stretch")
        assert store.needs_notice("stretch") is False

    def test_mismatched_phase_raises_a_notice(self, store):
        """Reboot after an unseen change, or a controller off across a boundary."""
        store.acknowledge("stretch")
        assert store.needs_notice("bloom") is True

    def test_a_pending_notice_is_not_cleared_by_asking(self, store):
        """needs_notice() must not acknowledge on the operator's behalf."""
        store.acknowledge("stretch")
        assert store.needs_notice("bloom") is True
        assert store.last_acknowledged() == "stretch"
        assert store.needs_notice("bloom") is True

    def test_no_active_phase_raises_no_notice(self, store):
        """A schedule-less (mushroom) build has no phase to announce."""
        assert store.needs_notice(None) is False
        assert store.last_acknowledged() is None
