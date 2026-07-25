"""Tests for the web UI /logs endpoint."""
import pytest

# WebUi imports Flask at module level; skip the file rather than fail
# collection where the optional web-UI dependency isn't installed
pytest.importorskip('flask')

import WebUi


class _FakeLogger:
    def __init__(self, lines=None, errors=None):
        self._lines = lines or []
        self._errors = errors or []

    def get_recent_lines(self):
        return self._lines

    def get_recent_errors(self):
        return self._errors


def _client(logger):
    app = WebUi.create_app(
        settings=None, players=[], shutdown_callback=None,
        version='test', db=None, logger=logger,
    )
    app.config['TESTING'] = True
    return app.test_client()


def test_logs_returns_lines_and_errors():
    logger = _FakeLogger(
        lines=['[12/07/26 10:00:00] a line'],
        errors=['[12/07/26 10:00:01] [Last.fm HTTP Error] track.updateNowPlaying failed with HTTP 403: Forbidden'],
    )
    resp = _client(logger).get('/logs')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['lines'] == logger.get_recent_lines()
    assert len(data['errors']) == 1
    assert 'HTTP 403' in data['errors'][0]


def test_logs_empty_when_no_logger():
    resp = _client(None).get('/logs')
    assert resp.status_code == 200
    assert resp.get_json() == {'lines': [], 'errors': []}


class _FakeSettings:
    def __init__(self):
        self.accounts = {'alice': 'key-a'}
        self.players = {'Living Room': 'alice'}
        self.host = '192.168.1.5'

    def get_accounts(self):
        return list(self.accounts)

    def get_players(self):
        return list(self.players)

    def get_user(self, name):
        return self.players.get(name)

    def get_host(self):
        return self.host


class _FakeDb:
    def get_recent_history(self, limit=10):
        return [{'player': 'Living Room', 'track': 'T', 'artist': 'A',
                 'album': 'Al', 'duration': '200', 'timestamp': 1700000000}]


class _FakePlayer:
    def __init__(self, name):
        self.name = name


def _full_app():
    """An app wired the way SkrobbleDs wires it, for exercising the routes."""
    return WebUi.create_app(
        settings=_FakeSettings(),
        players=[_FakePlayer('Living Room'), _FakePlayer('Kitchen')],
        shutdown_callback=None,
        version='9.9.9',
        db=_FakeDb(),
        logger=_FakeLogger(lines=['a line'], errors=[]),
    )


def test_health_reports_counts_from_settings():
    resp = _full_app().test_client().get('/health')
    assert resp.status_code == 200
    assert resp.get_json() == {
        'status': 'healthy', 'version': '9.9.9', 'accounts': 1, 'players': 1,
    }


def test_index_renders_with_all_dependencies():
    """Exercises every closure dependency the page reads: settings, players,
    db, logger and version."""
    resp = _full_app().test_client().get('/')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Living Room' in body      # configured player
    assert 'Kitchen' in body          # discovered but unconfigured
    assert '9.9.9' in body            # version
    assert '192.168.1.5' in body      # host


def test_post_without_csrf_token_is_rejected():
    resp = _full_app().test_client().post('/removePlayer', data={'player': 'Living Room'})
    assert resp.status_code == 403
