# Write Queue Manager - Async SD Write Batching
# Dennis Hiro, 2026-04-05
#
# Decouples synchronous SD I/O from the uasyncio event loop by batching
# writes into a background task. Eliminates blocking writes that can starve
# event loop and trigger watchdog resets.
#
# Design principles:
# - enqueue_write() is O(1) non-blocking; returns immediately
# - Background drain task batches writes and handles cascading fallback
# - CSV ordering maintained via buffer_manager pre-migration logic
# - Queue overflow routes to fallback (preserving data)

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


class WriteQueueManager:
    """
    Non-blocking async write queue for deferred SD I/O.

    Provides a non-blocking interface to enqueue writes, which are batched
    and flushed to SD by a background task. Eliminates event loop blocking
    from synchronous file I/O while maintaining data ordering and reliability.

    Attributes:
        buffer_manager: BufferManager instance (performs actual I/O)
        logger: EventLogger instance for debug/diagnostic messages
        _queue: List of (relpath, data) tuples awaiting write
        _max_queue_size: Max queue entries before overflow to fallback
        _drain_interval_ms: Batch drain interval (milliseconds)
        _batch_size: Number of writes per drain cycle
        _running: Flag indicating drain task is active
        _drain_task: Reference to background drain task
        _stats: Metrics (enqueued, drained, failed to drain)
    """

    def __init__(
        self,
        buffer_manager,
        logger,
        max_queue_size=500,
        drain_interval_ms=100,
        batch_size=5,
    ):
        """
        Initialize WriteQueueManager.

        Args:
            buffer_manager: BufferManager instance for actual writes
            logger: EventLogger instance for debug messages
            max_queue_size (int): Max queue entries before overflow to fallback (default: 500)
            drain_interval_ms (int): Milliseconds between drain cycles (default: 100)
            batch_size (int): Max writes per drain cycle (default: 5)
        """
        self.buffer_manager = buffer_manager
        self.logger = logger
        self._max_queue_size = max_queue_size
        self._drain_interval_ms = drain_interval_ms
        self._batch_size = batch_size
        self._queue = []
        self._running = False
        self._drain_task = None

        # Metrics
        self._enqueued = 0
        self._drained = 0
        self._failed_drains = 0
        self._overflow_writes = 0

        self._log_debug("initialized", max_queue_size=max_queue_size, drain_interval_ms=drain_interval_ms)

    def enqueue_write(self, relpath: str, data: str) -> bool:
        """
        Enqueue a write for deferred processing.

        Non-blocking O(1) operation. Returns True always (queue accepts all writes).
        On queue overflow, writes directly to fallback to preserve data.

        Args:
            relpath (str): Relative path for write (e.g., 'dht_log.csv')
            data (str): Data to write

        Returns:
            bool: True always (queue accepted write or routed to fallback)
        """
        if len(self._queue) < self._max_queue_size:
            self._queue.append((relpath, data))
            self._enqueued += 1
            return True
        else:
            # Queue full; write directly to fallback to preserve data
            self._overflow_writes += 1
            self._log_debug(
                "queue overflow; writing to fallback",
                queue_size=len(self._queue),
                max=self._max_queue_size,
            )
            try:
                # Bypass queue; write directly to fallback
                self.buffer_manager.write(relpath, data)
                return True
            except Exception as e:
                self._log_debug("fallback write failed on overflow", error=str(e))
                return False

    async def start_drain_task(self) -> None:
        """
        Start background drain task.

        Tasks run continuously, batching and flushing queued writes to SD.
        Should be spawned as asyncio.create_task() in main.py Step 9.

        Catches asyncio.CancelledError separately for graceful shutdown.
        ALL OTHER EXCEPTIONS are caught and logged; the task NEVER dies.
        Individual write failures are logged but do not crash the drain loop.

        Example:
            >>> wq = WriteQueueManager(buffer_manager, logger)
            >>> asyncio.create_task(wq.start_drain_task())
        """
        self._running = True
        self._log_debug("drain task started")
        try:
            while True:
                try:
                    await self._drain_batch()
                except Exception as e:
                    # Catch unexpected errors from _drain_batch() but keep loop running
                    # _drain_batch already catches write errors, so this catches setup/await errors
                    self._log_debug("drain batch error (will retry)", error=str(e))

                try:
                    await asyncio.sleep(self._drain_interval_ms / 1000.0)
                except Exception as e:
                    # Catch sleep errors (unlikely but fail-safe)
                    self._log_debug("drain sleep error (will retry)", error=str(e))
                    await asyncio.sleep(0.1)  # Backoff before retry
        except asyncio.CancelledError:
            self._log_debug("drain task cancelled; flushing remaining queue")
            try:
                await self._flush_all()
            except Exception as e:
                self._log_debug("drain flush-all error on cancel", error=str(e))
            self._running = False
            raise

    async def _drain_batch(self) -> None:
        """
        Drain up to batch_size writes from queue.

        Batches writes for efficiency, handling cascading fallback on failure.
        """
        if not self._queue:
            return

        batch = self._queue[: self._batch_size]
        for relpath, data in batch:
            try:
                self.buffer_manager.write(relpath, data)
                self._drained += 1
            except Exception as e:
                self._failed_drains += 1
                self._log_debug(
                    "drain write failed",
                    relpath=relpath,
                    error=str(e),
                    failed_drains=self._failed_drains,
                )

        # Remove processed entries from queue
        self._queue = self._queue[self._batch_size :]

    async def _flush_all(self) -> None:
        """
        Flush all remaining queued writes (used on shutdown).

        Ensures no data loss during graceful shutdown.
        """
        while self._queue:
            await self._drain_batch()

    def flush(self) -> bool:
        """
        Synchronous flush override.

        Used for graceful shutdown or manual flush when async not available.
        Drains entire queue synchronously.

        Returns:
            bool: True if all entries flushed, False if errors occurred
        """
        errors = 0
        for relpath, data in self._queue:
            try:
                self.buffer_manager.write(relpath, data)
            except Exception as e:
                errors += 1
                self._log_debug("flush write failed", relpath=relpath, error=str(e))

        self._queue = []
        self._drained += len(self._queue)
        return errors == 0

    def get_queue_size(self) -> int:
        """Return current queue size."""
        return len(self._queue)

    def get_stats(self) -> dict:
        """Return queue statistics."""
        return {
            "queue_size": len(self._queue),
            "enqueued": self._enqueued,
            "drained": self._drained,
            "failed_drains": self._failed_drains,
            "overflow_writes": self._overflow_writes,
            "max_queue_size": self._max_queue_size,
            "drain_interval_ms": self._drain_interval_ms,
            "batch_size": self._batch_size,
        }

    def _log_debug(self, message: str, **fields) -> None:
        """Log debug message via injected logger."""
        if self.logger:
            self.logger.debug("WriteQueue", message, **fields)
        else:
            if fields:
                field_str = " ".join(f"{k}={v}" for k, v in fields.items())
                print(f"[WriteQueue][DEBUG] {message} | {field_str}")
            else:
                print(f"[WriteQueue][DEBUG] {message}")
