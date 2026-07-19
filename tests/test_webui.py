"""Tests for the web UI /logs endpoint."""
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
