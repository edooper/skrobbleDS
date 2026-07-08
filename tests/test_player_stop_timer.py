"""Tests for scrobbling promptly when playback stops (stop timer)."""
import threading
import time
from types import SimpleNamespace

import pytest

import Constants
import EventBus
import Player


STOP_DELAY = 0.05


@pytest.fixture
def scrobbles():
    """Collect scrobble events emitted on the bus during the test."""
    collected = []

    def collector(info):
        collected.append(info)

    bus = EventBus.EventBus()
    bus.subscribe('scrobble', collector)
    yield collected
    bus.unsubscribe('scrobble', collector)


@pytest.fixture
def player(monkeypatch):
    monkeypatch.setattr(Constants, 'PLAYER_STOP_SCROBBLE_DELAY', STOP_DELAY, raising=False)
    p = Player.Player.__new__(Player.Player)
    p._lock = threading.RLock()
    p.bus = EventBus.EventBus()
    p.log = lambda msg: None
    p.dev = SimpleNamespace(FriendlyName=lambda: 'TestPlayer')
    p.update_meta_timer = None
    p.play_status_timer = None
    p.stop_scrobble_timer = None
    p.is_playing = True
    p.duration = 200
    p.meta = {}
    p.current = {
        'playing': [time.time() - 150],
        'stopped': [],
        'duration': 200,
        'player': 'TestPlayer',
        'artist': 'Artist',
        'title': 'Song',
        'album': 'Album',
        'tracknum': '1',
    }
    yield p
    for timer in (p.update_meta_timer, p.play_status_timer, p.stop_scrobble_timer):
        if timer:
            timer.cancel()


def _wait_for_timer():
    time.sleep(STOP_DELAY * 4)


def test_stop_scrobbles_current_track(player, scrobbles):
    player._on_playlist_event('TransportState', 'Stopped', 1)
    _wait_for_timer()
    assert len(scrobbles) == 1
    assert scrobbles[0]['title'] == 'Song'
    assert scrobbles[0]['stopped'], 'stop time must be recorded before scrobbling'
    # consumed - a later track change or shutdown must not scrobble it again
    assert player.current['title'] == ''


def test_resume_before_timer_cancels_scrobble(player, scrobbles):
    player._on_playlist_event('TransportState', 'Stopped', 1)
    player._on_playlist_event('TransportState', 'Playing', 2)
    _wait_for_timer()
    assert scrobbles == []
    assert player.current['title'] == 'Song'


def test_pause_does_not_trigger_stop_scrobble(player, scrobbles):
    player._on_playlist_event('TransportState', 'Paused', 1)
    _wait_for_timer()
    assert scrobbles == []
    assert player.current['title'] == 'Song'
