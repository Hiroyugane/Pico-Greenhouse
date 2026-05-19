# Tests for lib/sd_integration.py
# Covers mount_sd() and is_mounted() for host and device paths

from unittest.mock import MagicMock, Mock, patch

import lib as _lib_pkg


def _patch_lib_sdcard(mock_sdcard):
    """Context manager to patch lib.sdcard in both sys.modules and package attr."""
    return patch.object(_lib_pkg, "sdcard", mock_sdcard, create=True)


class TestMountSD:
    """Tests for mount_sd() function."""

    def test_mount_host_creates_directory(self, tmp_path):
        """On host (non-micropython), mount_sd creates directory."""
        from lib.sd_integration import mount_sd

        mount_point = str(tmp_path / "sd")
        ok, sd = mount_sd(None, None, mount_point)
        assert ok is True
        assert sd is None
        assert (tmp_path / "sd").exists()

    def test_mount_host_existing_dir(self, tmp_path):
        """On host, existing mount point works fine."""
        from lib.sd_integration import mount_sd

        mount_point = str(tmp_path / "sd")
        (tmp_path / "sd").mkdir()
        ok, sd = mount_sd(None, None, mount_point)
        assert ok is True

    def test_mount_device_success(self):
        """On device path, mount_sd creates SDCard and mounts."""
        import lib.sd_integration as sd_mod

        mock_spi = Mock()
        mock_cs = Mock()
        mock_sd = Mock()
        mock_sdcard = MagicMock()
        mock_sdcard.SDCard.return_value = mock_sd

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard):
                with patch("os.mount", create=True) as mock_mount:
                    ok, sd = sd_mod.mount_sd(mock_spi, mock_cs, "/sd")

        assert ok is True
        assert sd is mock_sd
        mock_sdcard.SDCard.assert_called_once_with(mock_spi, mock_cs)
        mock_mount.assert_called_once()  # type: ignore

    def test_mount_device_cs_int_wraps_pin(self):
        """On device path, integer cs_pin is wrapped in Pin()."""
        import lib.sd_integration as sd_mod

        mock_spi = Mock()
        mock_sd = Mock()
        mock_sdcard = MagicMock()
        mock_sdcard.SDCard.return_value = mock_sd
        mock_pin_class = MagicMock()
        mock_pin_instance = Mock()
        mock_pin_class.return_value = mock_pin_instance

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard):
                with patch.dict(
                    "sys.modules",
                    {
                        "machine": MagicMock(Pin=mock_pin_class),
                    },
                ):
                    with patch("os.mount", create=True):
                        ok, sd = sd_mod.mount_sd(mock_spi, 13, "/sd")

        assert ok is True
        mock_pin_class.assert_called_with(13)
        mock_sdcard.SDCard.assert_called_once_with(mock_spi, mock_pin_instance)

    def test_mount_device_failure(self):
        """On device path, SDCard creation failure returns (False, None)."""
        import lib.sd_integration as sd_mod

        mock_sdcard = MagicMock()
        mock_sdcard.SDCard.side_effect = OSError("no card")

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard):
                ok, sd = sd_mod.mount_sd(Mock(), Mock(), "/sd")

        assert ok is False
        assert sd is None

    def test_mount_device_busy_mount_reuses_existing(self):
        """On device path, busy/already-mounted mount point is treated as success when writable."""
        import lib.sd_integration as sd_mod

        mock_spi = Mock()
        mock_cs = Mock()
        mock_sd = Mock()
        mock_sdcard = MagicMock()
        mock_sdcard.SDCard.return_value = mock_sd

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard):
                with patch("os.mount", create=True, side_effect=OSError("mount busy")):
                    with patch.object(sd_mod, "_probe_mount_rw", return_value=True):
                        ok, sd = sd_mod.mount_sd(mock_spi, mock_cs, "/sd")

        assert ok is True
        assert sd is mock_sd


class TestIsMounted:
    """Tests for is_mounted() function."""

    def test_is_mounted_host_returns_true(self):
        """On host (non-micropython), is_mounted returns True."""
        from lib.sd_integration import is_mounted

        result = is_mounted(None)
        assert result is True

    def test_is_mounted_host_return_instances(self):
        """On host, return_instances=True returns 3-tuple."""
        from lib.sd_integration import is_mounted

        mock_sd = Mock()
        mock_spi = Mock()
        result = is_mounted(mock_sd, mock_spi, return_instances=True)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert result[0] is True

    def test_is_mounted_host_with_none_sd(self):
        """Host mode handles None sd/spi gracefully."""
        from lib.sd_integration import is_mounted

        result = is_mounted(None, None, return_instances=False)
        assert result is True

    def test_is_mounted_device_sd_provided_ok(self):
        """Device path with pre-existing sd object: readblocks succeeds."""
        import lib.sd_integration as sd_mod

        mock_sd = Mock()
        mock_sd.readblocks = Mock()  # No error → card is accessible
        mock_spi = Mock()

        mock_device_config = {
            "spi": {"id": 1, "baudrate": 40000000, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}
        }

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(MagicMock()):
                with patch.dict(
                    "sys.modules",
                    {
                        "config": MagicMock(DEVICE_CONFIG=mock_device_config),
                    },
                ):
                    result = sd_mod.is_mounted(mock_sd, mock_spi, return_instances=True)

        assert isinstance(result, tuple)
        assert result[0] is True
        assert result[1] is mock_sd

    def test_is_mounted_device_sd_none_initializes(self):
        """Device path with sd=None: initializes new SPI/SDCard and reads MBR."""
        import lib.sd_integration as sd_mod

        mock_sd_instance = Mock()
        mock_sd_instance.readblocks = Mock()
        mock_spi_instance = Mock()

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = mock_sd_instance
        mock_spi_class = MagicMock(return_value=mock_spi_instance)

        mock_device_config = {
            "spi": {"id": 1, "baudrate": 40000000, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {
                        "config": MagicMock(DEVICE_CONFIG=mock_device_config),
                        "machine": mock_machine,
                    },
                ):
                    with patch("os.mount", create=True):
                        result = sd_mod.is_mounted(None, None, return_instances=False)

        assert result is True

    def test_is_mounted_device_sd_none_busy_mount_reuses_existing(self):
        """Device path with sd=None handles busy/already-mounted mount point when writable."""
        import lib.sd_integration as sd_mod

        mock_sd_instance = Mock()
        mock_sd_instance.readblocks = Mock()
        mock_spi_instance = Mock()

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = mock_sd_instance
        mock_spi_class = MagicMock(return_value=mock_spi_instance)

        mock_device_config = {
            "spi": {"id": 1, "baudrate": 40000000, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {
                        "config": MagicMock(DEVICE_CONFIG=mock_device_config),
                        "machine": mock_machine,
                    },
                ):
                    with patch("os.mount", create=True, side_effect=OSError("already mounted")):
                        with patch.object(sd_mod, "_probe_mount_rw", return_value=True):
                            result = sd_mod.is_mounted(None, None, return_instances=True)

        assert isinstance(result, tuple)
        assert result[0] is True
        assert result[1] is mock_sd_instance
        assert result[2] is mock_spi_instance

    def test_is_mounted_device_mbr_fail_feeds_watchdog(self):
        """Device recovery path feeds wdt_feed at each blocking step.

        Why: the recovery path runs synchronously and stacks umount,
        SPI deinit, sleep_ms(200), SDCard reinit, and another MBR read.
        Without WDT feeds inside that block, a slow card pushes total
        latency past the watchdog window and triggers a silent reset.
        """
        import lib.sd_integration as sd_mod

        first_sd = Mock()
        first_sd.readblocks = Mock(side_effect=OSError("read error"))
        second_sd = Mock()
        second_sd.readblocks = Mock()

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = second_sd
        mock_spi_class = MagicMock(return_value=Mock())
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class
        mock_device_config = {
            "spi": {"id": 1, "baudrate": 40000000, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}
        }

        feeds = []

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {
                        "config": MagicMock(DEVICE_CONFIG=mock_device_config),
                        "machine": mock_machine,
                    },
                ):
                    with patch("os.mount", create=True):
                        with patch("os.umount", create=True):
                            with patch("time.sleep_ms"):
                                sd_mod.is_mounted(
                                    first_sd,
                                    Mock(),
                                    return_instances=True,
                                    wdt_feed=lambda: feeds.append(1),
                                )

        # At least three feeds: umount, spi deinit / sleep, sdcard reinit.
        assert len(feeds) >= 3

    def test_is_mounted_wdt_feed_exceptions_swallowed(self):
        """A throwing wdt_feed callable must not abort the recovery path."""
        import lib.sd_integration as sd_mod

        first_sd = Mock()
        first_sd.readblocks = Mock(side_effect=OSError("read error"))
        second_sd = Mock()
        second_sd.readblocks = Mock()

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = second_sd
        mock_spi_class = MagicMock(return_value=Mock())
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class
        mock_device_config = {
            "spi": {"id": 1, "baudrate": 40000000, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}
        }

        def boom():
            raise RuntimeError("watchdog driver crashed")

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {
                        "config": MagicMock(DEVICE_CONFIG=mock_device_config),
                        "machine": mock_machine,
                    },
                ):
                    with patch("os.mount", create=True):
                        with patch("os.umount", create=True):
                            with patch("time.sleep_ms"):
                                result = sd_mod.is_mounted(
                                    first_sd,
                                    Mock(),
                                    return_instances=True,
                                    wdt_feed=boom,
                                )

        assert isinstance(result, tuple)
        assert result[0] is True

    def test_is_mounted_device_mbr_fail_reinit(self):
        """Device path: first readblocks fails, reinit succeeds."""
        import lib.sd_integration as sd_mod

        first_sd = Mock()
        first_sd.readblocks = Mock(side_effect=OSError("read error"))

        second_sd = Mock()
        second_sd.readblocks = Mock()  # succeeds

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = second_sd
        mock_spi_instance = Mock()
        mock_spi_class = MagicMock(return_value=mock_spi_instance)

        mock_device_config = {
            "spi": {"id": 1, "baudrate": 40000000, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {
                        "config": MagicMock(DEVICE_CONFIG=mock_device_config),
                        "machine": mock_machine,
                    },
                ):
                    with patch("os.mount", create=True):
                        with patch("os.umount", create=True):
                            with patch("time.sleep_ms"):
                                result = sd_mod.is_mounted(first_sd, Mock(), return_instances=True)

        assert isinstance(result, tuple)
        assert result[0] is True

    def test_is_mounted_device_total_failure(self):
        """Device path: both MBR reads fail → graceful False with None sd/spi."""
        import lib.sd_integration as sd_mod

        bad_sd = Mock()
        bad_sd.readblocks = Mock(side_effect=OSError("card dead"))

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = bad_sd
        mock_spi_instance = Mock()
        mock_spi_class = MagicMock(return_value=mock_spi_instance)

        mock_device_config = {
            "spi": {"id": 1, "baudrate": 40000000, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {
                        "config": MagicMock(DEVICE_CONFIG=mock_device_config),
                        "machine": mock_machine,
                    },
                ):
                    with patch("os.mount", create=True):
                        with patch("os.umount", create=True):
                            with patch("time.sleep_ms"):
                                result = sd_mod.is_mounted(bad_sd, Mock())

        # Total failure returns False (from the except block)
        assert result is False

    def test_is_mounted_device_total_failure_returns_none_instances(self):
        """Device path: total failure returns (False, None, None) for return_instances."""
        import lib.sd_integration as sd_mod

        bad_sd = Mock()
        bad_sd.readblocks = Mock(side_effect=OSError("card dead"))

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = bad_sd
        mock_spi_instance = Mock()
        mock_spi_class = MagicMock(return_value=mock_spi_instance)

        mock_device_config = {
            "spi": {"id": 1, "baudrate": 40000000, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {
                        "config": MagicMock(DEVICE_CONFIG=mock_device_config),
                        "machine": mock_machine,
                    },
                ):
                    with patch("os.mount", create=True):
                        with patch("os.umount", create=True):
                            with patch("time.sleep_ms"):
                                result = sd_mod.is_mounted(bad_sd, Mock(), return_instances=True)

        assert isinstance(result, tuple)
        assert result[0] is False
        assert result[1] is None
        assert result[2] is None

    def test_init_sd_local_deinits_spi_on_mount_failure(self):
        """When mount fails in reinit, the newly created SPI is deinited."""
        import lib.sd_integration as sd_mod

        first_sd = Mock()
        first_sd.readblocks = Mock(side_effect=OSError("read error"))

        new_spi_instance = Mock()
        mock_spi_class = MagicMock(return_value=new_spi_instance)

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.side_effect = OSError("no card")

        mock_device_config = {
            "spi": {"id": 1, "baudrate": 40000000, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {
                        "config": MagicMock(DEVICE_CONFIG=mock_device_config),
                        "machine": mock_machine,
                    },
                ):
                    with patch("os.mount", create=True, side_effect=OSError("mount fail")):
                        with patch("os.umount", create=True):
                            with patch("time.sleep_ms"):
                                result = sd_mod.is_mounted(first_sd, Mock(), return_instances=True)

        assert result[0] is False
        # The SPI created during _init_sd_local should have been deinited
        new_spi_instance.deinit.assert_called()


class TestIsMountBusyError:
    """Tests for the busy/errno detection helper."""

    def test_message_says_busy(self):
        from lib.sd_integration import _is_mount_busy_error

        assert _is_mount_busy_error(OSError("device is BUSY")) is True

    def test_message_says_already_mounted(self):
        from lib.sd_integration import _is_mount_busy_error

        assert _is_mount_busy_error(RuntimeError("already mounted at /sd")) is True

    def test_errno_ebusy(self):
        from lib.sd_integration import _is_mount_busy_error

        e = OSError(16, "EBUSY")
        assert _is_mount_busy_error(e) is True

    def test_errno_eexist(self):
        from lib.sd_integration import _is_mount_busy_error

        e = OSError(17, "EEXIST")
        assert _is_mount_busy_error(e) is True

    def test_unrelated_error_is_false(self):
        from lib.sd_integration import _is_mount_busy_error

        assert _is_mount_busy_error(ValueError("totally different")) is False

    def test_empty_args_is_false(self):
        from lib.sd_integration import _is_mount_busy_error

        class NoArgs(Exception):
            args = ()

        assert _is_mount_busy_error(NoArgs()) is False


class TestProbeMountRW:
    """Tests for _probe_mount_rw write/read/remove probe."""

    def test_probe_writable_directory_returns_true(self, tmp_path):
        from lib.sd_integration import _probe_mount_rw

        assert _probe_mount_rw(str(tmp_path)) is True
        # Probe file is cleaned up
        assert not (tmp_path / ".probe").exists()


class TestDebugCallbackPaths:
    """debug_callback branches in mount_sd / is_mounted."""

    def test_mount_host_debug_callback_invoked(self, tmp_path):
        from lib.sd_integration import mount_sd

        calls = []
        ok, _ = mount_sd(None, None, str(tmp_path / "sd"), debug_callback=calls.append)
        assert ok is True
        assert any("Host mount simulated" in m for m in calls)

    def test_mount_device_debug_callback_on_success(self):
        import lib.sd_integration as sd_mod

        mock_sdcard = MagicMock()
        mock_sdcard.SDCard.return_value = Mock()
        calls = []
        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard):
                with patch("os.mount", create=True):
                    sd_mod.mount_sd(Mock(), Mock(), "/sd", debug_callback=calls.append)
        assert any("SD mounted at /sd" in m for m in calls)

    def test_mount_device_debug_callback_on_reuse(self):
        import lib.sd_integration as sd_mod

        mock_sdcard = MagicMock()
        mock_sdcard.SDCard.return_value = Mock()
        calls = []
        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard):
                with patch("os.mount", create=True, side_effect=OSError("busy")):
                    with patch.object(sd_mod, "_probe_mount_rw", return_value=True):
                        sd_mod.mount_sd(Mock(), Mock(), "/sd", debug_callback=calls.append)
        assert any("reusing existing mount" in m for m in calls)

    def test_mount_device_debug_callback_on_failure(self):
        import lib.sd_integration as sd_mod

        mock_sdcard = MagicMock()
        mock_sdcard.SDCard.side_effect = OSError("dead")
        calls = []
        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard):
                sd_mod.mount_sd(Mock(), Mock(), "/sd", debug_callback=calls.append)
        assert any("mount failed" in m.lower() for m in calls)

    def test_is_mounted_device_init_debug_callback(self):
        import lib.sd_integration as sd_mod

        mock_sd = Mock()
        mock_sd.readblocks = Mock()
        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = mock_sd
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = MagicMock(return_value=Mock())

        cfg = {"spi": {"id": 1, "baudrate": 1, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}}
        calls = []
        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {"config": MagicMock(DEVICE_CONFIG=cfg), "machine": mock_machine},
                ):
                    with patch("os.mount", create=True):
                        sd_mod.is_mounted(None, None, debug_callback=calls.append)
        assert any("created new SD/SPI" in m for m in calls)
        assert any("MBR read OK" in m for m in calls)

    def test_is_mounted_device_reinit_debug_callback(self):
        """MBR read fails first, then succeeds — both 'MBR failed' and 'MBR read OK' fire."""
        import lib.sd_integration as sd_mod

        bad = Mock()
        bad.readblocks = Mock(side_effect=OSError("dead"))
        good = Mock()
        good.readblocks = Mock()
        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = good
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = MagicMock(return_value=Mock())

        cfg = {"spi": {"id": 1, "baudrate": 1, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}}
        calls = []
        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {"config": MagicMock(DEVICE_CONFIG=cfg), "machine": mock_machine},
                ):
                    with patch("os.mount", create=True):
                        with patch("os.umount", create=True):
                            with patch("time.sleep_ms"):
                                sd_mod.is_mounted(bad, Mock(), debug_callback=calls.append)
        assert any("MBR failed" in m for m in calls)

    def test_is_mounted_device_busy_reuse_debug_callback(self):
        """sd=None busy/already-mounted path with debug_callback fires reuse message."""
        import lib.sd_integration as sd_mod

        mock_sd = Mock()
        mock_sd.readblocks = Mock()
        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = mock_sd
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = MagicMock(return_value=Mock())

        cfg = {"spi": {"id": 1, "baudrate": 1, "sck": 10, "mosi": 11, "miso": 12, "cs": 13, "mount_point": "/sd"}}
        calls = []
        with patch.object(sd_mod, "_IS_DEVICE", True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict(
                    "sys.modules",
                    {"config": MagicMock(DEVICE_CONFIG=cfg), "machine": mock_machine},
                ):
                    with patch("os.mount", create=True, side_effect=OSError("already mounted")):
                        with patch.object(sd_mod, "_probe_mount_rw", return_value=True):
                            sd_mod.is_mounted(None, None, debug_callback=calls.append)
        assert any("reusing active mount" in m for m in calls)
