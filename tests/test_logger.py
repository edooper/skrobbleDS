"""Tests for the Logger ring buffer and level-based failure detection (C4)."""
import pytest

import Constants
import Logger


@pytest.fixture
def logger():
    """A fresh logger. Each construction resets the underlying handlers, so
    tests do not accumulate output from one another."""
    log = Logger.Logger(name='skrobbleds-test')
    yield log
    log.shutdown()


def test_info_reaches_the_ring_buffer(logger):
    logger.info('hello from test')
    assert any('hello from test' in line for line in logger.get_recent_lines())


def test_log_is_an_alias_for_info(logger):
    """Most of the codebase calls .log(); it must behave as info."""
    logger.log('via log alias')
    lines = logger.get_recent_lines()
    assert any('via log alias' in line for line in lines)
    assert logger.get_recent_errors() == []


def test_lines_are_timestamped(logger):
    logger.info('timestamped')
    line = [l for l in logger.get_recent_lines() if 'timestamped' in l][0]
    assert line.startswith('[') and '] timestamped' in line


def test_get_recent_lines_returns_last_n_in_order(logger):
    for i in range(5):
        logger.info(f'line {i}')
    lines = logger.get_recent_lines(3)
    assert len(lines) == 3
    assert 'line 2' in lines[0] and 'line 4' in lines[2]


def test_ring_buffer_caps_at_max_size(logger):
    for i in range(Constants.LOG_RING_SIZE + 50):
        logger.info(f'line {i}')
    assert len(logger._ring) == Constants.LOG_RING_SIZE
    assert f'line {Constants.LOG_RING_SIZE + 49}' in logger.get_recent_lines(1)[0]


def test_errors_are_identified_by_level_not_message_text(logger):
    """The whole point of C4: a failure is a failure because of its level.

    The old scheme substring-matched against a hand-maintained marker list, so
    rewording a message silently emptied the banner.
    """
    logger.info('Living Room: Submitting now playing -> A - B (200s)')
    logger.error('Last.fm: track.updateNowPlaying failed with HTTP 403: Forbidden')
    errors = logger.get_recent_errors()
    assert len(errors) == 1
    assert 'HTTP 403' in errors[0]


def test_info_containing_the_word_error_is_not_a_failure(logger):
    """Text that merely mentions an error must not reach the failure banner."""
    logger.info('Recovered from a previous Last.fm Error, resuming')
    assert logger.get_recent_errors() == []


def test_get_recent_errors_caps_display_count(logger):
    for i in range(Constants.LOG_ERROR_DISPLAY + 3):
        logger.error(f'failure {i}')
    errors = logger.get_recent_errors()
    assert len(errors) == Constants.LOG_ERROR_DISPLAY
    assert errors[-1].endswith(f'failure {Constants.LOG_ERROR_DISPLAY + 2}')


def test_errors_also_appear_in_the_general_line_feed(logger):
    logger.error('something failed')
    assert any('something failed' in line for line in logger.get_recent_lines())


def test_debug_suppressed_when_debug_disabled(logger):
    assert logger.debug_enabled is False
    logger.debug('should be filtered')
    logger.info('visible line')
    lines = logger.get_recent_lines()
    assert any('visible line' in line for line in lines)
    assert not any('should be filtered' in line for line in lines)


def test_debug_emitted_when_debug_enabled(monkeypatch):
    monkeypatch.setenv('DEBUG', 'true')
    log = Logger.Logger(name='skrobbleds-test-debug')
    try:
        assert log.debug_enabled is True
        log.debug('diagnostic detail')
        assert any('diagnostic detail' in line for line in log.get_recent_lines())
        # A debug line is not a failure
        assert log.get_recent_errors() == []
    finally:
        log.shutdown()


def test_shutdown_writes_pending_lines(logger):
    """Lines logged right before shutdown must still be present (A2)."""
    for i in range(20):
        logger.info(f'pending line {i}')
    logger.shutdown()
    lines = logger.get_recent_lines(100)
    for i in range(20):
        assert any(f'pending line {i}' in line for line in lines), f'dropped line {i}'
