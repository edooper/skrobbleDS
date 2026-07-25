"""Tests for Scrobbler play-time calculation and shutdown queue drain."""
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
    def log(self, msg):
        pass


class FakeDb:
    def __init__(self):
        self.cached = []
        self.history = []

    def get_cache_size(self):
        return 0

    def pop_from_cache(self):
        return None

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
