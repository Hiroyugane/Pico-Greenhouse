# Tests for sd_test.py
# Covers the check_sd_card state machine (backoff, recovery, state transitions)

import asyncio
from unittest.mock import Mock, patch

import pytest


@pytest.mark.asyncio
class TestCheckSdCard:
    """Tests for the SD health-check state machine."""

    async def test_healthy_card_polls_at_ok_interval(self):
        """When read_block succeeds, sleeps poll_ok_ms."""
        from sd_test import check_sd_card

        sleep_durations = []
        call_count = 0

        async def tracking_sleep(ms):
            nonlocal call_count
            sleep_durations.append(ms)
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch('time.sleep_ms'):
            with pytest.raises(asyncio.CancelledError):
                await check_sd_card(
                    read_block=Mock(),  # succeeds
                    remount=Mock(),
                    safe_umount=Mock(),
                    sleep_ms_fn=tracking_sleep,
                    poll_ok_ms=5000,
                )

        assert all(d == 5000 for d in sleep_durations)

    async def test_failed_read_triggers_remount(self):
        """When read_block fails, safe_umount + remount are called."""
        from sd_test import check_sd_card

        remount_mock = Mock()
        umount_mock = Mock()
        read_mock = Mock(side_effect=OSError('card removed'))

        call_count = 0
        async def limited_sleep(ms):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        with patch('time.sleep_ms'):
            with pytest.raises(asyncio.CancelledError):
                await check_sd_card(
                    read_block=read_mock,
                    remount=remount_mock,
                    safe_umount=umount_mock,
                    sleep_ms_fn=limited_sleep,
                )

        umount_mock.assert_called()
        remount_mock.assert_called()

    async def test_successful_recovery_resets_backoff(self):
        """After failed read + successful remount, backoff resets and polls ok."""
        from sd_test import check_sd_card

        # First read fails, remount succeeds, second read_block in recovery
        # succeeds
        read_calls = [0]
        def read_block():
            read_calls[0] += 1
            if read_calls[0] == 1:
                raise OSError('fail')
            # 2nd call (during recovery) succeeds

        sleep_durations = []
        call_count = 0
        async def tracking_sleep(ms):
            nonlocal call_count
            sleep_durations.append(ms)
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch('time.sleep_ms'):
            with pytest.raises(asyncio.CancelledError):
                await check_sd_card(
                    read_block=read_block,
                    remount=Mock(),
                    safe_umount=Mock(),
                    sleep_ms_fn=tracking_sleep,
                    poll_ok_ms=5000,
                )

        # After recovery, should poll at ok interval
        assert 5000 in sleep_durations

    async def test_exponential_backoff_on_repeated_failures(self):
        """Consecutive remount failures double the backoff up to max."""
        from sd_test import check_sd_card

        sleep_durations = []
        call_count = 0

        async def tracking_sleep(ms):
            nonlocal call_count
            sleep_durations.append(ms)
            call_count += 1
            if call_count >= 4:
                raise asyncio.CancelledError()

        with patch('time.sleep_ms'):
            with pytest.raises(asyncio.CancelledError):
                await check_sd_card(
                    read_block=Mock(side_effect=OSError('fail')),
                    remount=Mock(side_effect=OSError('no card')),
                    safe_umount=Mock(),
                    sleep_ms_fn=tracking_sleep,
                    initial_backoff_ms=1000,
                    max_backoff_ms=8000,
                    poll_missing_ms=500,
                )

        # Backoff progression: 1000→2000→4000→8000
        # sleep = max(poll_missing_ms, backoff)
        assert sleep_durations[0] == 2000  # after 1st fail: backoff doubled to 2000
        assert sleep_durations[1] == 4000  # 2nd fail: 4000
        assert sleep_durations[2] == 8000  # 3rd fail: 8000 (=max)
        assert sleep_durations[3] == 8000  # 4th fail: capped at max

    async def test_backoff_capped_at_maximum(self):
        """Backoff never exceeds max_backoff_ms."""
        from sd_test import check_sd_card

        sleep_durations = []
        call_count = 0

        async def tracking_sleep(ms):
            nonlocal call_count
            sleep_durations.append(ms)
            call_count += 1
            if call_count >= 6:
                raise asyncio.CancelledError()

        with patch('time.sleep_ms'):
            with pytest.raises(asyncio.CancelledError):
                await check_sd_card(
                    read_block=Mock(side_effect=OSError('fail')),
                    remount=Mock(side_effect=OSError('no card')),
                    safe_umount=Mock(),
                    sleep_ms_fn=tracking_sleep,
                    initial_backoff_ms=1000,
                    max_backoff_ms=4000,
                    poll_missing_ms=500,
                )

        # Should never exceed max_backoff
        assert all(d <= 4000 for d in sleep_durations)

    async def test_state_transition_ok_to_fail(self, capsys):
        """Prints state change message when transitioning ok → fail."""
        from sd_test import check_sd_card

        call_count = 0
        async def limited_sleep(ms):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        with patch('time.sleep_ms'):
            with pytest.raises(asyncio.CancelledError):
                await check_sd_card(
                    read_block=Mock(side_effect=OSError('gone')),
                    remount=Mock(side_effect=OSError('still gone')),
                    safe_umount=Mock(),
                    sleep_ms_fn=limited_sleep,
                )

        captured = capsys.readouterr()
        assert 'NOT ACCESSIBLE' in captured.out

    async def test_state_transition_fail_to_ok(self, capsys):
        """Prints state change message when transitioning fail → ok."""
        from sd_test import check_sd_card

        read_calls = [0]
        def flaky_read():
            read_calls[0] += 1
            if read_calls[0] <= 2:
                # First two reads fail (initial + recovery attempt)
                raise OSError('fail')
            # 3rd+ reads succeed

        remount_calls = [0]
        def flaky_remount():
            remount_calls[0] += 1
            if remount_calls[0] <= 1:
                raise OSError('no card')

        sleep_count = [0]
        async def tracking_sleep(ms):
            sleep_count[0] += 1
            if sleep_count[0] >= 3:
                raise asyncio.CancelledError()

        with patch('time.sleep_ms'):
            with pytest.raises(asyncio.CancelledError):
                await check_sd_card(
                    read_block=flaky_read,
                    remount=flaky_remount,
                    safe_umount=Mock(),
                    sleep_ms_fn=tracking_sleep,
                )

        captured = capsys.readouterr()
        # Should show transition from NOT ACCESSIBLE to OK
        assert 'NOT ACCESSIBLE' in captured.out
        assert 'MBR: OK' in captured.out

    async def test_recovery_error_logged_on_first_and_every_fifth(self, capsys):
        """Recovery error is printed on failures 1, 5, 10, etc."""
        from sd_test import check_sd_card

        call_count = 0
        async def tracking_sleep(ms):
            nonlocal call_count
            call_count += 1
            if call_count >= 6:
                raise asyncio.CancelledError()

        with patch('time.sleep_ms'):
            with pytest.raises(asyncio.CancelledError):
                await check_sd_card(
                    read_block=Mock(side_effect=OSError('fail')),
                    remount=Mock(side_effect=OSError('nope')),
                    safe_umount=Mock(),
                    sleep_ms_fn=tracking_sleep,
                )

        captured = capsys.readouterr()
        recovery_lines = [line for line in captured.out.splitlines()
                          if 'RECOVERY ERROR' in line]
        # Should print on failure 1 and failure 5
        assert len(recovery_lines) == 2

    async def test_outer_exception_caught(self, capsys):
        """Generic exception in the outer loop body is caught."""
        # The outer except guards code between inner try/excepts.
        # Trigger it by making the state-transition print explode via
        # a side-effect on safe_umount that corrupts last_state_ok.
        import builtins

        from sd_test import check_sd_card
        original_print = builtins.print
        print_calls = [0]

        def explosive_print(*args, **kwargs):
            print_calls[0] += 1
            # Let the first prints through (MBR Read Error, RECOVERY ERROR)
            # but blow up on the state-transition print
            text = ' '.join(str(a) for a in args)
            if 'MBR: NOT' in text:
                raise RuntimeError('print device error')
            return original_print(*args, **kwargs)

        sleep_count = [0]
        async def limited_sleep(ms):
            sleep_count[0] += 1
            if sleep_count[0] >= 2:
                raise asyncio.CancelledError()

        with patch('time.sleep_ms'):
            with patch('builtins.print', side_effect=explosive_print):
                with pytest.raises(asyncio.CancelledError):
                    await check_sd_card(
                        read_block=Mock(side_effect=OSError('fail')),
                        remount=Mock(side_effect=OSError('fail')),
                        safe_umount=Mock(),
                        sleep_ms_fn=limited_sleep,
                    )

        # The outer except caught the RuntimeError from the print explosion
        # and called print("SD Check Error: ...") — but that also explodes.
        # The loop continues because the outer except itself doesn't re-raise.
        # Verify at least 2 cycles ran.
        assert sleep_count[0] >= 2

    async def test_constants_exposed(self):
        """Module-level constants are importable."""
        from sd_test import MOUNT_POINT, SPI_BAUDRATE, SPI_ID
        assert SPI_ID == 1
        assert SPI_BAUDRATE == 40000000
        assert MOUNT_POINT == '/sd'
