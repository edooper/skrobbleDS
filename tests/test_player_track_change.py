"""Regression tests for track-change metadata races.

Duration and Metadata are independent, unsynchronized UPnP events on the
Info service. On a fast track change, Duration can arrive (and the
metadata debounce timer can fire) before the new track's Metadata XML
does - these tests guard against the previous track's stale title/artist
leaking into the new track's record.
"""
import threading
import time
from types import SimpleNamespace

import pytest

import Constants
import EventBus
import Player


DELAY = 0.05

NEW_TRACK_DIDL = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
    '<item>'
    '<dc:title>New Song</dc:title>'
    '<upnp:artist role="Performer">New Artist</upnp:artist>'
    '<upnp:album>New Album</upnp:album>'
    '<upnp:originalTrackNumber>2</upnp:originalTrackNumber>'
    '</item>'
    '</DIDL-Lite>'
)


@pytest.fixture
def now_playing_events():
    collected = []

    def collector(info):
        collected.append(info)

    bus = EventBus.EventBus()
    bus.subscribe('now_playing', collector)
    yield collected
    bus.unsubscribe('now_playing', collector)


@pytest.fixture
def scrobbles():
    collected = []

    def collector(info):
        collected.append(info)

    bus = EventBus.EventBus()
    bus.subscribe('scrobble', collector)
    yield collected
    bus.unsubscribe('scrobble', collector)


@pytest.fixture
def player(monkeypatch):
    monkeypatch.setattr(Constants, 'PLAYER_METADATA_UPDATE_DELAY', DELAY, raising=False)
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
    p.current_uri = 'tidal://track?trackId=old'
    # Simulate a previous track that already finished syncing.
    p.meta = {'title': 'Old Song', 'artist': 'Old Artist', 'album': 'Old Album', 'tracknum': '1'}
    p.current = {
        'playing': [time.time() - 10],
        'stopped': [],
        'duration': 200,
        'player': 'TestPlayer',
        'artist': 'Old Artist',
        'title': 'Old Song',
        'album': 'Old Album',
        'tracknum': '1',
    }
    yield p
    for timer in (p.update_meta_timer, p.play_status_timer, p.stop_scrobble_timer):
        if timer:
            timer.cancel()


def _wait_for_timer():
    time.sleep(DELAY * 4)


NEW_URI = 'tidal://track?trackId=new'


def test_new_uri_resets_meta_as_well_as_current(player):
    player._on_info_event('Uri', NEW_URI, 1)
    assert player.meta == {'title': '', 'artist': '', 'album': '', 'tracknum': '', 'duration': 0}
    assert player.current['title'] == ''
    assert player.current['artist'] == ''


def test_duration_before_late_metadata_does_not_produce_stale_title(player, now_playing_events):
    player._on_info_event('Uri', NEW_URI, 1)
    player._on_info_event('Duration', '111', 2)
    _wait_for_timer()

    # Debounce timer fired before Metadata arrived - must not carry over
    # the previous track's title/artist, only the new duration.
    assert player.current['duration'] == 111
    assert player.current['title'] == ''
    assert player.current['artist'] == ''

    player._on_info_event('Metadata', NEW_TRACK_DIDL, 3)

    assert player.current['title'] == 'New Song'
    assert player.current['artist'] == 'New Artist'
    assert player.current['duration'] == 111, 'duration must not revert once correctly set'
    assert now_playing_events[-1]['title'] == 'New Song'
    assert now_playing_events[-1]['duration'] == 111


DIDL_WITH_RES_50S = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
    '<item>'
    '<dc:title>Naked Truth, Part 6</dc:title>'
    '<upnp:artist role="Performer">Avishai Cohen</upnp:artist>'
    '<res duration="0:00:50.000">tidal://track</res>'
    '</item>'
    '</DIDL-Lite>'
)


def test_didl_duration_overrides_stale_duration_event(player, now_playing_events):
    # Regression for the "Naked Truth, Part 6" no-scrobble bug: on a fast
    # gapless track change the separate Info 'Duration' event lags a track, so
    # the new track's duration must come from its own DIDL <res>, not the
    # stale self.duration left over from the previous track.
    player.duration = 126   # stale value from the previous (127s) track
    player._on_info_event('Uri', NEW_URI, 1)
    player._on_info_event('Metadata', DIDL_WITH_RES_50S, 2)

    assert player.current['title'] == 'Naked Truth, Part 6'
    assert player.current['duration'] == 50, 'must use the DIDL res duration, not the stale 126s'
    assert now_playing_events[-1]['duration'] == 50


def test_new_uri_with_blank_metadata_emits_no_scrobble(player, scrobbles):
    # The outgoing track may have no metadata yet (blank title/artist), which
    # must never be submitted to Last.fm.
    player.current['title'] = ''
    player.current['artist'] = ''
    player._on_info_event('Uri', NEW_URI, 1)
    assert scrobbles == [], 'must not scrobble a track with blank title/artist'


def test_new_uri_with_real_metadata_emits_scrobble(player, scrobbles):
    # Sanity check a legitimate track change scrobbles the outgoing track.
    player._on_info_event('Uri', NEW_URI, 1)
    assert len(scrobbles) == 1
    assert scrobbles[0]['title'] == 'Old Song'


def test_repeated_uri_does_not_reset_metadata(player, scrobbles):
    # Regression for the missing-first-album-track bug: at an album boundary the
    # device fires TrackCount twice for the same track, re-sending the SAME Uri.
    # A repeated Uri must NOT be treated as a track change - otherwise the
    # first track's freshly-delivered metadata is wiped and it plays out blank.
    same_uri = player.current_uri
    player._on_info_event('Uri', same_uri, 1)
    assert scrobbles == [], 'a repeated Uri must not scrobble/reset'
    assert player.current['title'] == 'Old Song', 'metadata must be preserved'


def test_trackcount_alone_does_not_reset_or_scrobble(player, scrobbles):
    # TrackCount is no longer the change trigger (it is the unreliable signal).
    # A bare TrackCount must not reset state or scrobble.
    player._on_info_event('TrackCount', '99', 1)
    assert scrobbles == []
    assert player.current['title'] == 'Old Song'


def test_empty_uri_ignored(player, scrobbles):
    player._on_info_event('Uri', '', 1)
    assert scrobbles == []
    assert player.current['title'] == 'Old Song'


def test_prompt_metadata_resyncs_immediately_and_skips_duplicate_timer_emit(player, now_playing_events):
    player._on_info_event('Uri', NEW_URI, 1)
    player._on_info_event('Metadata', NEW_TRACK_DIDL, 2)

    assert player.current['title'] == 'New Song'
    assert len(now_playing_events) == 1

    _wait_for_timer()

    # The original debounce timer must have been cancelled once the
    # manual resync ran, so it doesn't redundantly re-emit later.
    assert len(now_playing_events) == 1
