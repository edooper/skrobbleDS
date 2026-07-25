"""Tests for the Logger in-memory ring buffer and error detection."""
import time

import Constants
import Logger


def _make_logger():
    """Create a Logger without file logging or debug output."""
    return Logger.Logger()


def _wait_for(predicate, timeout=2.0):
    """Poll until predicate() is true or timeout; return its final value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_get_recent_lines_returns_last_n_in_order():
    logger = _make_logger()
    for i in range(5):
        logger.recent.append(f'line {i}')
    assert logger.get_recent_lines(3) == ['line 2', 'line 3', 'line 4']


def test_ring_buffer_caps_at_max_size():
    logger = _make_logger()
    for i in range(Constants.LOG_RING_SIZE + 50):
        logger.recent.append(f'line {i}')
    assert len(logger.recent) == Constants.LOG_RING_SIZE
    # Oldest lines have been evicted; newest is retained.
    assert logger.get_recent_lines(1) == [f'line {Constants.LOG_RING_SIZE + 49}']


def test_get_recent_errors_matches_lastfm_markers():
    logger = _make_logger()
    logger.recent.append('[12/07/26 10:00:00] Player: Submitting now playing -> A - B (200s)')
    logger.recent.append('[12/07/26 10:00:01] [Last.fm HTTP Error] track.updateNowPlaying failed with HTTP 403: Forbidden')
    errors = logger.get_recent_errors()
    assert len(errors) == 1
    assert 'HTTP 403' in errors[0]


def test_get_recent_errors_empty_when_no_failures():
    logger = _make_logger()
    logger.recent.append('[12/07/26 10:00:00] Player: Submitting now playing -> A - B (200s)')
    assert logger.get_recent_errors() == []


def test_get_recent_errors_caps_display_count():
    logger = _make_logger()
    for i in range(Constants.LOG_ERROR_DISPLAY + 3):
        logger.recent.append(f'[Last.fm HTTP Error] failure {i}')
    errors = logger.get_recent_errors()
    assert len(errors) == Constants.LOG_ERROR_DISPLAY
    # Most recent failures are kept.
    assert errors[-1].endswith(f'failure {Constants.LOG_ERROR_DISPLAY + 2}')


def test_log_message_reaches_ring_buffer():
    logger = _make_logger()
    logger.log('hello from test')
    assert _wait_for(lambda: any('hello from test' in line for line in logger.get_recent_lines()))


def test_shutdown_drains_pending_lines():
    """Lines queued before shutdown must be written, not dropped (A2).

    SkrobbleDs shuts the logger down last, so these are exactly the final
    scrobble results you would want when diagnosing a shutdown.
    """
    logger = _make_logger()
    for i in range(20):
        logger.log(f'pending line {i}')
    logger.shutdown()
    lines = list(logger.recent)
    for i in range(20):
        assert any(f'pending line {i}' in line for line in lines), f'dropped line {i}'


def test_debug_message_excluded_when_debug_disabled():
    logger = _make_logger()
    assert logger.debug_enabled is False
    logger.log('[DEBUG] should be filtered')
    logger.log('visible line')
    # Wait for the visible line to be processed, then confirm no debug line.
    assert _wait_for(lambda: any('visible line' in line for line in logger.get_recent_lines()))
    assert not any('should be filtered' in line for line in logger.get_recent_lines())
