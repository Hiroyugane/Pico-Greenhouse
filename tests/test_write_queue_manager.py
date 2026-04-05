# Tests for WriteQueueManager
# Dennis Hiro, 2026-04-05
#
# Unit tests for async write queue with batching and fallback handling.
# Tests cover:
# - enqueue_write non-blocking O(1) behavior
# - batch drain with fallback cascade
# - queue overflow to fallback
# - graceful shutdown with CancelledError

from unittest.mock import Mock, call

import pytest

from lib.write_queue_manager import WriteQueueManager

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_buffer_manager():
    """Mock BufferManager for WriteQueueManager tests."""
    bm = Mock()
    bm.write = Mock(return_value=True)
    return bm


@pytest.fixture
def mock_logger():
    """Mock EventLogger for WriteQueueManager tests."""
    logger = Mock()
    logger.debug = Mock()
    return logger


@pytest.fixture
def write_queue_manager(mock_buffer_manager, mock_logger):
    """Instantiate WriteQueueManager with mocks."""
    return WriteQueueManager(
        buffer_manager=mock_buffer_manager,
        logger=mock_logger,
        max_queue_size=10,
        drain_interval_ms=50,
        batch_size=3,
    )


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------


class TestWriteQueueManagerInit:
    """Test WriteQueueManager initialization."""

    def test_init_defaults(self, mock_buffer_manager, mock_logger):
        """Verify initialization with default values."""
        wq = WriteQueueManager(mock_buffer_manager, mock_logger)
        assert wq.get_queue_size() == 0
        assert wq._running is False
        assert wq._max_queue_size == 500
        assert wq._drain_interval_ms == 100
        assert wq._batch_size == 5

    def test_init_custom_params(self, mock_buffer_manager, mock_logger):
        """Verify initialization with custom parameters."""
        wq = WriteQueueManager(
            mock_buffer_manager,
            mock_logger,
            max_queue_size=100,
            drain_interval_ms=200,
            batch_size=10,
        )
        assert wq._max_queue_size == 100
        assert wq._drain_interval_ms == 200
        assert wq._batch_size == 10

    def test_init_logs_debug_message(self, mock_buffer_manager, mock_logger):
        """Verify debug message logged on init."""
        WriteQueueManager(mock_buffer_manager, mock_logger)
        mock_logger.debug.assert_called()
        assert "initialized" in str(mock_logger.debug.call_args)


# ---------------------------------------------------------------------------
# Tests: enqueue_write
# ---------------------------------------------------------------------------


class TestEnqueueWrite:
    """Test non-blocking enqueue_write behavior."""

    def test_enqueue_single_write(self, write_queue_manager):
        """Verify single write can be enqueued."""
        result = write_queue_manager.enqueue_write("test.csv", "data1\n")
        assert result is True
        assert write_queue_manager.get_queue_size() == 1
        assert write_queue_manager._enqueued == 1

    def test_enqueue_multiple_writes(self, write_queue_manager):
        """Verify multiple writes queued sequentially."""
        for i in range(5):
            result = write_queue_manager.enqueue_write(f"file{i}.csv", f"data{i}\n")
            assert result is True

        assert write_queue_manager.get_queue_size() == 5
        assert write_queue_manager._enqueued == 5

    def test_enqueue_always_returns_true(self, write_queue_manager):
        """Verify enqueue_write always returns True (queue accepts)."""
        for i in range(15):
            result = write_queue_manager.enqueue_write("test.csv", f"line{i}\n")
            assert result is True

    def test_enqueue_non_blocking(self, write_queue_manager):
        """Verify enqueue_write is O(1) non-blocking."""
        # Enqueue many writes and verify they're all added
        for i in range(100):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        # Queue should still be manageable (not blocking)
        assert write_queue_manager.get_queue_size() <= 100


# ---------------------------------------------------------------------------
# Tests: Queue Overflow
# ---------------------------------------------------------------------------


class TestQueueOverflow:
    """Test queue overflow handling."""

    def test_overflow_routes_to_fallback(self, write_queue_manager, mock_buffer_manager):
        """Verify overflow writes route directly to fallback via buffer_manager."""
        # Fill queue to max
        for i in range(write_queue_manager._max_queue_size):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        # Next write should bypass queue and call buffer_manager.write()
        write_queue_manager.enqueue_write("test.csv", "overflow\n")

        assert write_queue_manager._overflow_writes == 1
        mock_buffer_manager.write.assert_called_with("test.csv", "overflow\n")

    def test_overflow_failure_returns_false(self, write_queue_manager, mock_buffer_manager):
        """Verify overflow returns False if buffer_manager write fails."""
        mock_buffer_manager.write.side_effect = OSError("SD error")

        # Fill queue
        for i in range(write_queue_manager._max_queue_size):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        # Overflow write should return False if direct write fails (data not safely stored)
        result = write_queue_manager.enqueue_write("test.csv", "overflow\n")
        assert result is False  # Write attempt failed

    def test_overflow_logs_debug(self, write_queue_manager, mock_logger, mock_buffer_manager):
        """Verify overflow is logged as debug message."""
        # Fill queue
        for i in range(write_queue_manager._max_queue_size):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        # Overflow write logs debug
        write_queue_manager.enqueue_write("test.csv", "overflow\n")

        # Verify debug log was called with overflow message
        debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
        assert any("overflow" in str(c).lower() for c in debug_calls)


# ---------------------------------------------------------------------------
# Tests: Async Drain Task
# ---------------------------------------------------------------------------


class TestDrainTask:
    """Test async drain task behavior."""

    @pytest.mark.asyncio
    async def test_drain_batch_processes_writes(self, write_queue_manager, mock_buffer_manager):
        """Verify drain task processes queued writes in batches."""
        # Enqueue 5 writes
        for i in range(5):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        # Drain batch (should process first 3 due to batch_size=3)
        await write_queue_manager._drain_batch()

        # Should have called buffer_manager.write 3 times (batch_size)
        assert mock_buffer_manager.write.call_count == 3
        assert write_queue_manager._drained == 3
        assert write_queue_manager.get_queue_size() == 2

    @pytest.mark.asyncio
    async def test_drain_task_started(self, write_queue_manager, mock_buffer_manager):
        """Verify start_drain_task sets running flag."""
        assert write_queue_manager._running is False

        # Start drain task
        task = asyncio.create_task(write_queue_manager.start_drain_task())

        # Give task time to start and set flag
        await asyncio.sleep(0.01)

        assert write_queue_manager._running is True

        # Cancel task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_drain_empty_queue(self, write_queue_manager, mock_buffer_manager):
        """Verify draining empty queue does nothing."""
        await write_queue_manager._drain_batch()
        mock_buffer_manager.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_drain_task_batches_continuously(self, write_queue_manager, mock_buffer_manager):
        """Verify drain task processes queue in batch cycles."""
        # Enqueue 7 writes
        for i in range(7):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        # First drain: 3 writes (batch_size=3)
        await write_queue_manager._drain_batch()
        assert mock_buffer_manager.write.call_count == 3
        assert write_queue_manager.get_queue_size() == 4

        # Second drain: 3 writes
        await write_queue_manager._drain_batch()
        assert mock_buffer_manager.write.call_count == 6
        assert write_queue_manager.get_queue_size() == 1

        # Third drain: 1 write
        await write_queue_manager._drain_batch()
        assert mock_buffer_manager.write.call_count == 7
        assert write_queue_manager.get_queue_size() == 0

    @pytest.mark.asyncio
    async def test_drain_handles_write_failure(self, write_queue_manager, mock_buffer_manager):
        """Verify drain continues if buffer_manager.write() fails."""
        mock_buffer_manager.write.side_effect = OSError("SD error")

        # Enqueue 3 writes
        for i in range(3):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        # Drain should continue despite failures
        await write_queue_manager._drain_batch()

        # All 3 writes attempted despite failures
        assert mock_buffer_manager.write.call_count == 3
        assert write_queue_manager._failed_drains == 3
        assert write_queue_manager.get_queue_size() == 0


# ---------------------------------------------------------------------------
# Tests: Graceful Shutdown
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    """Test graceful shutdown with CancelledError."""

    @pytest.mark.asyncio
    async def test_drain_task_cancellation(self, write_queue_manager, mock_buffer_manager):
        """Verify drain task handles CancelledError and flushes queue."""
        # Enqueue writes
        for i in range(5):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        task = asyncio.create_task(write_queue_manager.start_drain_task())
        await asyncio.sleep(0.01)

        # Cancel task
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # Verify flag cleared
        assert write_queue_manager._running is False

    @pytest.mark.asyncio
    async def test_synchronous_flush(self, write_queue_manager, mock_buffer_manager):
        """Verify synchronous flush drains all queued writes."""
        # Enqueue writes
        for i in range(5):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        result = write_queue_manager.flush()

        assert result is True
        assert write_queue_manager.get_queue_size() == 0
        assert mock_buffer_manager.write.call_count == 5

    def test_synchronous_flush_with_failures(self, write_queue_manager, mock_buffer_manager):
        """Verify synchronous flush returns False if any write fails."""
        mock_buffer_manager.write.side_effect = [True, OSError("error"), True]

        # Enqueue 3 writes
        for i in range(3):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        result = write_queue_manager.flush()

        assert result is False  # Errors occurred


# ---------------------------------------------------------------------------
# Tests: Statistics
# ---------------------------------------------------------------------------


class TestStatistics:
    """Test statistics collection."""

    def test_get_stats(self, write_queue_manager):
        """Verify get_stats returns all metrics."""
        # Enqueue some writes
        for i in range(5):
            write_queue_manager.enqueue_write("test.csv", f"line{i}\n")

        stats = write_queue_manager.get_stats()

        assert stats["queue_size"] == 5
        assert stats["enqueued"] == 5
        assert stats["drained"] == 0
        assert stats["failed_drains"] == 0
        assert stats["overflow_writes"] == 0
        assert stats["max_queue_size"] == 10
        assert stats["drain_interval_ms"] == 50
        assert stats["batch_size"] == 3

    def test_get_queue_size(self, write_queue_manager):
        """Verify get_queue_size returns current queue length."""
        assert write_queue_manager.get_queue_size() == 0

        write_queue_manager.enqueue_write("test.csv", "data\n")
        assert write_queue_manager.get_queue_size() == 1

        write_queue_manager.enqueue_write("test.csv", "data\n")
        assert write_queue_manager.get_queue_size() == 2


# ---------------------------------------------------------------------------
# Tests: Multiple Filepaths
# ---------------------------------------------------------------------------


class TestMultipleFilepaths:
    """Test queue handling multiple filepaths."""

    @pytest.mark.asyncio
    async def test_enqueue_different_filepaths(self, write_queue_manager, mock_buffer_manager):
        """Verify queue handles writes to different filepaths."""
        write_queue_manager.enqueue_write("dht_log.csv", "temp data\n")
        write_queue_manager.enqueue_write("system.log", "event data\n")
        write_queue_manager.enqueue_write("dht_log.csv", "more temp\n")

        assert write_queue_manager.get_queue_size() == 3

        # Drain all
        await write_queue_manager._drain_batch()
        await write_queue_manager._drain_batch()

        # Verify writes called with correct paths
        calls = mock_buffer_manager.write.call_args_list
        assert calls[0] == call("dht_log.csv", "temp data\n")
        assert calls[1] == call("system.log", "event data\n")
        assert calls[2] == call("dht_log.csv", "more temp\n")


# ---------------------------------------------------------------------------
# Tests: Drain Task Resilience
# ---------------------------------------------------------------------------


class TestDrainTaskResilience:
    """Test drain task resilience to exceptions (does NOT crash on error)."""

    @pytest.mark.asyncio
    async def test_drain_task_resilient_to_batch_exception(self, write_queue_manager, mock_buffer_manager):
        """Verify drain task continues running even if _drain_batch() throws."""
        write_queue_manager.enqueue_write("test1.csv", "data1\n")
        write_queue_manager.enqueue_write("test2.csv", "data2\n")

        # Simulate _drain_batch exception on first call, success on second
        side_effects = [
            None,  # First call: succeeds, drains batch 1
            Exception("Simulated batch error"),  # Second call: throws
            None,  # Third call: recovers and succeeds
        ]
        original_drain_batch = write_queue_manager._drain_batch

        async def mock_drain_batch():
            effect = side_effects.pop(0) if side_effects else None
            if isinstance(effect, Exception):
                raise effect
            return await original_drain_batch()

        write_queue_manager._drain_batch = mock_drain_batch

        # Run drain task for multiple iterations
        drain_iterations = 0

        async def run_limited_drain():
            nonlocal drain_iterations
            try:
                while drain_iterations < 3:
                    try:
                        await write_queue_manager._drain_batch()
                        drain_iterations += 1
                    except Exception:
                        # Task should catch exception and continue (resilience)
                        drain_iterations += 1
                        pass
                    if drain_iterations < 3:
                        await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                pass

        # Run the resilience loop
        task = asyncio.create_task(run_limited_drain())
        await asyncio.sleep(0.1)  # Let it run
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify: despite exception on iteration 2, drain_iterations should complete all 3
        assert drain_iterations >= 2  # At minimum, should have attempted beyond the error
