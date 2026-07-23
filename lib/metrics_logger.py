# Health-metrics Logger — one CSV row per health-check cycle.
# Dennis Hiro, 2026-07-14
#
# Unlike the sensor loggers, this one has no async loop of its own: the main
# health loop (which already gathers RAM / buffer / queue / task numbers every
# health_check_interval_s) calls write_row() once per cycle. The row records
# whether the regulation engine "runs smoothly" — heap stays flat, each tick
# stays far under tick_s, the write path isn't backing up, and the engine's
# commanded actuator vector tracks its severity/band state.
#
# Same on-disk layout as th/co2/soil (<root>/<type>/<YYYY>/<type>_<date>.csv via
# lib.sensor_paths) so it charts in the same PowerBI/Excel workbook. All storage
# resilience is delegated to BufferManager/WriteQueueManager; write_row is
# best-effort and never raises into the health loop.

try:
    from lib.sensor_paths import daily_csv_path
except ImportError:  # frozen into the firmware as a top-level module
    from sensor_paths import daily_csv_path


class MetricsLogger:
    """Append-only health-metrics CSV writer, driven by the health loop."""

    # Column order is the on-disk contract — the single source of truth for the
    # header and every row. Regulation columns are left blank when the engine is
    # disabled/absent so the file stays valid without the engine.
    COLUMNS = (
        "Timestamp",
        "mem_free_b",
        "mem_alloc_b",
        "mem_used_pct",
        "tasks",
        "queue_depth",
        "buffered",
        "sd_fallback_writes",
        "write_failures",
        "tick_us",
        "tick_max_us",
        "global_severity",
        "band",
        "latched",
        "emergency",
        "dev_t",
        "dev_h",
        "dev_c",
        "cmd_heater",
        "cmd_follower",
        "cmd_cooler",
        "cmd_humidifier",
        "cmd_exhaust",
        "cmd_circulation",
        "cmd_growlight",
    )

    def __init__(
        self,
        time_provider,
        buffer_manager,
        sensor_root="/sd/sensors",
        write_queue=None,
        logger=None,
        # fixed: "metrics" is part of the on-disk sensor layout, not an
        # operator knob — it names the CSV sub-tree, like "th"/"co2".
        sensor_type="metrics",
    ):
        """
        Args:
            time_provider: TimeProvider (now_date_tuple / now_timestamp).
            buffer_manager: BufferManager (has_data_for / write).
            sensor_root: absolute SD sensor root (e.g. "/sd/sensors").
            write_queue: optional WriteQueueManager for async batched writes.
            logger: optional EventLogger for error reporting.
            sensor_type: CSV sub-tree name (fixed "metrics").
        """
        self.time_provider = time_provider
        self.buffer_manager = buffer_manager
        self.write_queue = write_queue
        self.logger = logger
        self._sensor_root = sensor_root
        self._sensor_type = sensor_type

        self.current_date = None
        self.filename = None
        self._created_files = set()  # relpaths confirmed created this session

        self._update_filename_for_date()
        try:
            if not self._file_exists():
                self._create_file()
        except Exception as e:
            self._log_error("init error: {}".format(e))

    # -- file / date plumbing ---------------------------------------------

    def _update_filename_for_date(self):
        """Build <root>/<type>/YYYY/<type>_YYYY-MM-DD.csv from the RTC date."""
        try:
            year, month, day = self.time_provider.now_date_tuple()[:3]
            self.current_date = (year, month, day)
            self.filename = daily_csv_path(self._sensor_root, self._sensor_type, year, month, day)
        except Exception as e:
            self._log_error("filename update failed: {}".format(e))
            self.filename = "{}/{}/{}.csv".format(self._sensor_root.rstrip("/"), self._sensor_type, self._sensor_type)

    def _check_date_changed(self):
        """Switch to a new daily file when the RTC date rolls over."""
        try:
            year, month, day = self.time_provider.now_date_tuple()[:3]
            if (year, month, day) != self.current_date:
                self._update_filename_for_date()
        except Exception as e:
            self._log_error("date check failed: {}".format(e))

    def _file_exists(self):
        relpath = self._strip_sd_prefix(self.filename)
        if relpath in self._created_files:
            return True
        exists = self.buffer_manager.has_data_for(relpath)
        if exists:
            self._created_files.add(relpath)
        return exists

    def _create_file(self):
        """Write the CSV header once via BufferManager."""
        relpath = self._strip_sd_prefix(self.filename)
        header = ",".join(self.COLUMNS) + "\n"
        self.buffer_manager.write(relpath, header)
        self._created_files.add(relpath)

    # -- row emission ------------------------------------------------------

    def write_row(self, fields):
        """
        Append one metrics row. Best-effort: never raises into the caller.

        Args:
            fields: dict keyed by COLUMNS names (Timestamp is stamped here and
                may be omitted). Missing keys render as blank cells; bools become
                1/0; floats are fixed to 2 decimals.

        Returns:
            bool: True if the row reached the write queue / primary SD, else
            False (fallback/buffer or error).
        """
        try:
            self._check_date_changed()
            relpath = self._strip_sd_prefix(self.filename)
            if not self._file_exists():
                self._create_file()

            values = dict(fields)
            values["Timestamp"] = self.time_provider.now_timestamp()
            row = ",".join(self._fmt(values.get(c)) for c in self.COLUMNS) + "\n"

            if self.write_queue is not None:
                self.write_queue.enqueue_write(relpath, row)
                return True
            return self.buffer_manager.write(relpath, row)
        except Exception as e:
            self._log_error("write_row failed: {}".format(e))
            return False

    @staticmethod
    def _fmt(value):
        if value is None:
            return ""
        if isinstance(value, bool):  # check before int (bool is an int subclass)
            return "1" if value else "0"
        if isinstance(value, float):
            return "{:.2f}".format(value)
        return str(value)

    @staticmethod
    def _strip_sd_prefix(path):
        if path.startswith("/sd/"):
            return path[4:]
        return path

    def _log_error(self, message):
        if self.logger:
            try:
                self.logger.error("MetricsLogger", message)
            except Exception:
                pass
