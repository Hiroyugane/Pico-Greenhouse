# Tests for lib/sd_integration.py
# Covers mount_sd() and is_mounted() for host and device paths

import lib as _lib_pkg
import pytest
from unittest.mock import Mock, patch, MagicMock


def _patch_lib_sdcard(mock_sdcard):
    """Context manager to patch lib.sdcard in both sys.modules and package attr."""
    return patch.object(_lib_pkg, 'sdcard', mock_sdcard)


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

        with patch.object(sd_mod, '_IS_DEVICE', True):
            with _patch_lib_sdcard(mock_sdcard):
                with patch('os.mount', create=True) as mock_mount:
                    ok, sd = sd_mod.mount_sd(mock_spi, mock_cs, '/sd')

        assert ok is True
        assert sd is mock_sd
        mock_sdcard.SDCard.assert_called_once_with(mock_spi, mock_cs)
        mock_mount.assert_called_once() # type: ignore

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

        with patch.object(sd_mod, '_IS_DEVICE', True):
            with _patch_lib_sdcard(mock_sdcard):
                with patch.dict('sys.modules', {
                    'machine': MagicMock(Pin=mock_pin_class),
                }):
                    with patch('os.mount', create=True):
                        ok, sd = sd_mod.mount_sd(mock_spi, 13, '/sd')

        assert ok is True
        mock_pin_class.assert_called_with(13)
        mock_sdcard.SDCard.assert_called_once_with(mock_spi, mock_pin_instance)

    def test_mount_device_failure(self):
        """On device path, SDCard creation failure returns (False, None)."""
        import lib.sd_integration as sd_mod
        mock_sdcard = MagicMock()
        mock_sdcard.SDCard.side_effect = OSError('no card')

        with patch.object(sd_mod, '_IS_DEVICE', True):
            with _patch_lib_sdcard(mock_sdcard):
                ok, sd = sd_mod.mount_sd(Mock(), Mock(), '/sd')

        assert ok is False
        assert sd is None


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
            'spi': {'id': 1, 'baudrate': 40000000, 'sck': 10, 'mosi': 11,
                    'miso': 12, 'cs': 13, 'mount_point': '/sd'}
        }

        with patch.object(sd_mod, '_IS_DEVICE', True):
            with _patch_lib_sdcard(MagicMock()):
                with patch.dict('sys.modules', {
                    'config': MagicMock(DEVICE_CONFIG=mock_device_config),
                }):
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
            'spi': {'id': 1, 'baudrate': 40000000, 'sck': 10, 'mosi': 11,
                    'miso': 12, 'cs': 13, 'mount_point': '/sd'}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, '_IS_DEVICE', True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict('sys.modules', {
                    'config': MagicMock(DEVICE_CONFIG=mock_device_config),
                    'machine': mock_machine,
                }):
                    with patch('os.mount', create=True):
                        result = sd_mod.is_mounted(None, None, return_instances=False)

        assert result is True

    def test_is_mounted_device_mbr_fail_reinit(self):
        """Device path: first readblocks fails, reinit succeeds."""
        import lib.sd_integration as sd_mod

        first_sd = Mock()
        first_sd.readblocks = Mock(side_effect=OSError('read error'))

        second_sd = Mock()
        second_sd.readblocks = Mock()  # succeeds

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = second_sd
        mock_spi_instance = Mock()
        mock_spi_class = MagicMock(return_value=mock_spi_instance)

        mock_device_config = {
            'spi': {'id': 1, 'baudrate': 40000000, 'sck': 10, 'mosi': 11,
                    'miso': 12, 'cs': 13, 'mount_point': '/sd'}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, '_IS_DEVICE', True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict('sys.modules', {
                    'config': MagicMock(DEVICE_CONFIG=mock_device_config),
                    'machine': mock_machine,
                }):
                    with patch('os.mount', create=True):
                        with patch('os.umount', create=True):
                            with patch('time.sleep_ms'):
                                result = sd_mod.is_mounted(first_sd, Mock(), return_instances=True)

        assert isinstance(result, tuple)
        assert result[0] is True

    def test_is_mounted_device_total_failure(self):
        """Device path: both MBR reads fail → graceful False with None sd/spi."""
        import lib.sd_integration as sd_mod

        bad_sd = Mock()
        bad_sd.readblocks = Mock(side_effect=OSError('card dead'))

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = bad_sd
        mock_spi_instance = Mock()
        mock_spi_class = MagicMock(return_value=mock_spi_instance)

        mock_device_config = {
            'spi': {'id': 1, 'baudrate': 40000000, 'sck': 10, 'mosi': 11,
                    'miso': 12, 'cs': 13, 'mount_point': '/sd'}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, '_IS_DEVICE', True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict('sys.modules', {
                    'config': MagicMock(DEVICE_CONFIG=mock_device_config),
                    'machine': mock_machine,
                }):
                    with patch('os.mount', create=True):
                        with patch('os.umount', create=True):
                            with patch('time.sleep_ms'):
                                result = sd_mod.is_mounted(bad_sd, Mock())

        # Total failure returns False (from the except block)
        assert result is False

    def test_is_mounted_device_total_failure_returns_none_instances(self):
        """Device path: total failure returns (False, None, None) for return_instances."""
        import lib.sd_integration as sd_mod

        bad_sd = Mock()
        bad_sd.readblocks = Mock(side_effect=OSError('card dead'))

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.return_value = bad_sd
        mock_spi_instance = Mock()
        mock_spi_class = MagicMock(return_value=mock_spi_instance)

        mock_device_config = {
            'spi': {'id': 1, 'baudrate': 40000000, 'sck': 10, 'mosi': 11,
                    'miso': 12, 'cs': 13, 'mount_point': '/sd'}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, '_IS_DEVICE', True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict('sys.modules', {
                    'config': MagicMock(DEVICE_CONFIG=mock_device_config),
                    'machine': mock_machine,
                }):
                    with patch('os.mount', create=True):
                        with patch('os.umount', create=True):
                            with patch('time.sleep_ms'):
                                result = sd_mod.is_mounted(bad_sd, Mock(), return_instances=True)

        assert isinstance(result, tuple)
        assert result[0] is False
        assert result[1] is None
        assert result[2] is None

    def test_init_sd_local_deinits_spi_on_mount_failure(self):
        """When mount fails in reinit, the newly created SPI is deinited."""
        import lib.sd_integration as sd_mod

        first_sd = Mock()
        first_sd.readblocks = Mock(side_effect=OSError('read error'))

        new_spi_instance = Mock()
        mock_spi_class = MagicMock(return_value=new_spi_instance)

        mock_sdcard_mod = MagicMock()
        mock_sdcard_mod.SDCard.side_effect = OSError('no card')

        mock_device_config = {
            'spi': {'id': 1, 'baudrate': 40000000, 'sck': 10, 'mosi': 11,
                    'miso': 12, 'cs': 13, 'mount_point': '/sd'}
        }
        mock_machine = MagicMock()
        mock_machine.Pin = MagicMock(return_value=Mock())
        mock_machine.SPI = mock_spi_class

        with patch.object(sd_mod, '_IS_DEVICE', True):
            with _patch_lib_sdcard(mock_sdcard_mod):
                with patch.dict('sys.modules', {
                    'config': MagicMock(DEVICE_CONFIG=mock_device_config),
                    'machine': mock_machine,
                }):
                    with patch('os.mount', create=True, side_effect=OSError('mount fail')):
                        with patch('os.umount', create=True):
                            with patch('time.sleep_ms'):
                                result = sd_mod.is_mounted(first_sd, Mock(), return_instances=True)

        assert result[0] is False
        # The SPI created during _init_sd_local should have been deinited
        new_spi_instance.deinit.assert_called()
