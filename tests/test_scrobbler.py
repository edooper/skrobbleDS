"""Tests for Scrobbler play-time calculation and shutdown queue drain."""
import threading
import time

import Scrobbler


def _calc(info):
    s = Scrobbler.Scrobbler.__new__(Scrobbler.Scrobbler)
    return s._calculate_play_time(info)


class TestCalculatePlayTime:
    def test_simple_play_stop(self):
        assert _calc({'playing': [100.0], 'stopped': [250.0]}) == 150.0

    def test_pause_and_resume(self):
        info = {'playing': [100.0, 200.0], 'stopped': [150.0, 260.0]}
        assert _calc(info) == 110.0

    def test_repeated_playing_events_not_double_counted(self):
        # e.g. Buffering -> Playing transitions mid-track
        info = {'playing': [100.0, 120.0], 'stopped': [250.0]}
        assert _calc(info) == 150.0

    def test_idle_gap_between_stop_and_track_change(self):
        # stop at 250, track change appends another stop much later
        info = {'playing': [100.0], 'stopped': [250.0, 900.0]}
        assert _calc(info) == 150.0

    def test_no_stop_events(self):
        assert _calc({'playing': [100.0]}) == 0

    def test_empty(self):
        assert _calc({}) == 0

    def test_stop_before_play_ignored(self):
        info = {'playing': [100.0], 'stopped': [50.0, 250.0]}
        assert _calc(info) == 150.0


class FakeSettings:
    def get_players(self):
        return ['P']

    def get_session_key(self, player):
        return 'sk'


class FakeLogger:
    """Records failures so tests can assert on them; discards the rest."""

    def __init__(self):
        self.errors = []

    def info(self, msg):
        pass

    log = info

    def debug(self, msg):
        pass

    def error(self, msg):
        self.errors.append(msg)


class FakeDb:
    def __init__(self, cached=None):
        self.cached = list(cached or [])
        self.history = []

    def get_cache_size(self):
        return len(self.cached)

    def pop_from_cache(self):
        return self.cached.pop(0) if self.cached else None

    def add_to_cache(self, info):
        self.cached.append(info)

    def add_to_history(self, info):
        self.history.append(info)


class FakeLastFm:
    def __init__(self):
        self.scrobbled = []

    def track_scrobble(self, sk, title, artist, album, tracknum, duration, timestamp):
        self.scrobbled.append(title)
        return object()

    def track_update_now_playing(self, sk, title, artist, duration):
        return object()


def _track(title):
    now = time.time()
    return {
        'player': 'P',
        'title': title,
        'artist': 'Artist',
        'album': 'Album',
        'tracknum': '1',
        'duration': 200,
        'playing': [now - 150],
        'stopped': [now],
    }


def test_shutdown_drains_pending_scrobbles():
    """All scrobbles queued before shutdown must be submitted, not dropped."""
    db = FakeDb()
    fake = FakeLastFm()
    scrobbler = Scrobbler.Scrobbler(FakeSettings(), FakeLogger(), db, lastfm=fake)
    try:
        for i in range(3):
            scrobbler.scrobble_q.put(_track(f'Track {i}'))
    finally:
        scrobbler.shutdown()
    assert sorted(fake.scrobbled) == ['Track 0', 'Track 1', 'Track 2']


class ExplodingLastFm(FakeLastFm):
    """Fails the first submission, then behaves normally."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def track_scrobble(self, sk, title, artist, album, tracknum, duration, timestamp):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('boom')
        return super().track_scrobble(sk, title, artist, album, tracknum, duration, timestamp)


def test_worker_survives_unexpected_error():
    """An exception must not kill the daemon thread and end all scrobbling (A3).

    The thread dying is silent: the process keeps running and /health keeps
    reporting healthy while nothing is ever scrobbled again.
    """
    fake = ExplodingLastFm()
    logger = FakeLogger()
    scrobbler = Scrobbler.Scrobbler(FakeSettings(), logger, FakeDb(), lastfm=fake)
    try:
        scrobbler.scrobble_q.put(_track('Explodes'))
        scrobbler.scrobble_q.put(_track('Survives'))
    finally:
        scrobbler.shutdown()
    assert scrobbler.scrobble_thread.is_alive() is False  # exited via sentinel, not a crash
    assert fake.scrobbled == ['Survives']
    # The failure is reported at error level, so it reaches the UI banner
    assert any('RuntimeError: boom' in e for e in logger.errors)


class BlockingLastFm(FakeLastFm):
    """Holds the first submission open so the cache can be inspected mid-flight."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def track_scrobble(self, *args):
        self.entered.set()
        self.release.wait(5)
        return super().track_scrobble(*args)


def test_startup_does_not_drain_cache_into_memory():
    """Only one cached scrobble is primed; the rest stay durable in the DB (A4).

    An in-memory backlog dies with the process, defeating the cache's whole
    purpose. Items leave the database one at a time as each is submitted.
    """
    db = FakeDb(cached=[_track(f'Cached {i}') for i in range(5)])
    fake = BlockingLastFm()
    scrobbler = Scrobbler.Scrobbler(FakeSettings(), FakeLogger(), db, lastfm=fake)
    try:
        # Block inside the first submission: exactly one item has been taken
        assert fake.entered.wait(5), 'worker never picked up the primed scrobble'
        assert db.get_cache_size() == 4
    finally:
        fake.release.set()
        scrobbler.shutdown()
