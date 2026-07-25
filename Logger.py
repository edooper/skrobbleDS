"""Logger.py - Logging for SkrobbleDs

Copyright (c) Rockfather 2012, edooper 2026
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use

A thin facade over the standard library's logging, plus an in-memory ring
buffer that the web UI reads. Severity is carried by the record's level, so
the UI picks out submission failures by level rather than by substring
matching the message text against a hand-maintained list of prefixes.
"""
import collections
import logging
import os
import sys
import threading

import Constants

FORMAT = '[%(asctime)s] %(message)s'
DATE_FORMAT = '%d/%m/%y %H:%M:%S'


def _env_flag(name):
    return os.environ.get(name, '').lower() in ('true', '1', 'yes', 'on')


class RingBufferHandler(logging.Handler):
    """Keeps the most recent formatted records in memory for the web UI"""

    def __init__(self, capacity):
        super().__init__()
        self._records = collections.deque(maxlen=capacity)
        self._buf_lock = threading.Lock()

    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:  # never let logging break the caller
            return
        with self._buf_lock:
            self._records.append((record.levelno, line))

    def lines(self, count):
        with self._buf_lock:
            snapshot = [line for _, line in self._records]
        return snapshot[-count:] if count else snapshot

    def errors(self, count):
        with self._buf_lock:
            snapshot = [line for level, line in self._records
                        if level >= logging.ERROR]
        return snapshot[-count:] if count else snapshot

    def __len__(self):
        with self._buf_lock:
            return len(self._records)


class Logger:
    """Application logger: level-based, with an in-memory tail for the web UI"""

    def __init__(self, name='skrobbleds'):
        self.debug_enabled = _env_flag('DEBUG')

        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG if self.debug_enabled else logging.INFO)
        # Ours alone - don't hand records to the root logger as well
        self._logger.propagate = False
        # A process may construct more than one Logger (notably in tests);
        # start from a clean handler set rather than accumulating duplicates
        for handler in list(self._logger.handlers):
            self._logger.removeHandler(handler)
            handler.close()

        formatter = logging.Formatter(FORMAT, datefmt=DATE_FORMAT)

        # stdout, not the StreamHandler default of stderr - the previous
        # implementation used print(), and container log collection depends on
        # the stream not changing
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        self._logger.addHandler(stream_handler)

        self._ring = RingBufferHandler(Constants.LOG_RING_SIZE)
        self._ring.setFormatter(formatter)
        self._logger.addHandler(self._ring)

        if _env_flag('LOG_FILE'):
            config_dir = os.environ.get('CONFIG_DIR', 'config')
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_path = os.path.join(script_dir, config_dir, 'skrobbleds.log')
            try:
                file_handler = logging.FileHandler(log_path, encoding='utf-8')
                file_handler.setFormatter(formatter)
                self._logger.addHandler(file_handler)
                self.info(f'Logging to file: {log_path}')
            except OSError as e:
                self.error(f'Failed to open log file {log_path}: {e}')

        if self.debug_enabled:
            self.debug('Debug logging enabled')

    def info(self, msg):
        """Log a normal operational message"""
        self._logger.info(msg)

    # The bulk of the codebase calls .log(); it is plain informational output
    log = info

    def debug(self, msg):
        """Log a diagnostic message - suppressed unless DEBUG is set"""
        self._logger.debug(msg)

    def error(self, msg):
        """Log a failure. These surface in the web UI's failure banner."""
        self._logger.error(msg)

    def get_recent_lines(self, count=Constants.LOG_DISPLAY_LINES):
        """Return a snapshot of the last `count` formatted log lines"""
        return self._ring.lines(count)

    def get_recent_errors(self, count=Constants.LOG_ERROR_DISPLAY):
        """Return the most recent lines logged at ERROR or above"""
        return self._ring.errors(count)

    def shutdown(self):
        """Flush and release the log handlers"""
        self.info('ByeBye')
        for handler in list(self._logger.handlers):
            try:
                handler.flush()
            except (OSError, ValueError):
                pass
            self._logger.removeHandler(handler)
            handler.close()
