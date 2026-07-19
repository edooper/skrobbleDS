"""Logger.py - Logger for SkrobbleDs

Copyright (c) Rockfather 2012, edooper 2026
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""
import collections
import threading
import time
import queue
import os

import Constants

class Logger:
    """Thread-safe logging system for SkrobbleDs"""

    def __init__(self):
        self.shutdown_flag = False
        self.msg_queue = queue.Queue()
        self.log_file = None

        # In-memory ring buffer of recent formatted log lines, surfaced by the
        # web UI. Always available regardless of the optional LOG_FILE setting.
        self.recent = collections.deque(maxlen=Constants.LOG_RING_SIZE)
        self._recent_lock = threading.Lock()

        # Check debug logging level via environment variable
        # DEBUG=true enables debug messages, DEBUG=false (default) hides them
        self.debug_enabled = os.environ.get('DEBUG', '').lower() in ('true', '1', 'yes', 'on')

        # Check if file logging is enabled via environment variable
        log_file_enabled = os.environ.get('LOG_FILE', '').lower() in ('true', '1', 'yes', 'on')
        if log_file_enabled:
            config_dir = os.environ.get('CONFIG_DIR', 'config')
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_path = os.path.join(script_dir, config_dir, 'skrobbleds.log')
            ts = time.strftime('%d/%m/%y %H:%M:%S')
            try:
                self.log_file = open(log_path, 'a', encoding='utf-8')
                print(f'[{ts}] Logging to file: {log_path}')
            except Exception as e:
                print(f'[{ts}] Failed to open log file {log_path}: {e}')

        if self.debug_enabled:
            ts = time.strftime('%d/%m/%y %H:%M:%S')
            print(f'[{ts}] Debug logging enabled')

        self.output_thread = threading.Thread(target=self.output_loop, daemon=True)
        self.output_thread.start()

    def shutdown(self):
        """Cleanly shutdown the logger"""
        self.shutdown_flag = True
        self.log('ByeBye')
        self.output_thread.join()
        if self.log_file:
            try:
                self.log_file.close()
            except OSError:
                pass

    def log(self, msg):
        """Queue a message for logging"""
        if str(msg).startswith('[DEBUG]') and not self.debug_enabled:
            return
        self.msg_queue.put(msg)

    def get_recent_lines(self, count=Constants.LOG_DISPLAY_LINES):
        """Return a snapshot of the last `count` formatted log lines"""
        with self._recent_lock:
            lines = list(self.recent)
        return lines[-count:]

    def get_recent_errors(self, count=Constants.LOG_ERROR_DISPLAY):
        """Return recent buffered lines that mark a submission failure.

        Scans the whole buffer for Last.fm error markers and returns the most
        recent matches (oldest first), capped to `count`.
        """
        with self._recent_lock:
            lines = list(self.recent)
        errors = [
            line for line in lines
            if any(marker in line for marker in Constants.LOG_ERROR_MARKERS)
        ]
        return errors[-count:]

    def output_loop(self):
        """Background thread for processing the log message queue"""
        while not self.shutdown_flag:
            msg = str(self.msg_queue.get())

            # Filter debug messages if debug is not enabled
            if msg.startswith('[DEBUG]') and not self.debug_enabled:
                continue

            ts = time.strftime('%d/%m/%y %H:%M:%S')
            formatted_msg = f'[{ts}] {msg}'
            print(formatted_msg)
            with self._recent_lock:
                self.recent.append(formatted_msg)
            if self.log_file:
                try:
                    self.log_file.write(formatted_msg + '\n')
                    self.log_file.flush()  # Ensure immediate write
                except Exception as e:
                    print(f'[{ts}] Failed to write to log file: {e}')