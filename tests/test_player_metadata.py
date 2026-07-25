"""Tests for DIDL-Lite metadata parsing in Player."""
from types import SimpleNamespace

import Player
from conftest import NullLogger


DIDL = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
    '<item>'
    '<dc:title>Song Title</dc:title>'
    '<upnp:artist>Composer Name</upnp:artist>'
    '<upnp:artist role="Performer">Performer Name</upnp:artist>'
    '<upnp:album>Album Name</upnp:album>'
    '<upnp:originalTrackNumber>7</upnp:originalTrackNumber>'
    '</item>'
    '</DIDL-Lite>'
)


def _player():
    p = Player.Player.__new__(Player.Player)
    p.meta = {}
    p.log = NullLogger()
    p.dev = SimpleNamespace(FriendlyName=lambda: 'TestPlayer')
    return p


def test_parse_full_metadata_prefers_performer():
    p = _player()
    p._parse_metadata(DIDL)
    assert p.meta == {
        'title': 'Song Title',
        'artist': 'Performer Name',
        'album': 'Album Name',
        'tracknum': '7',
        'duration': 0,
    }


def test_parse_falls_back_to_first_artist():
    p = _player()
    p._parse_metadata(DIDL.replace(' role="Performer"', ''))
    assert p.meta['artist'] == 'Composer Name'


def test_empty_metadata_resets():
    p = _player()
    p.meta = {'title': 'stale'}
    p._parse_metadata('')
    assert p.meta == {'title': '', 'artist': '', 'album': '', 'tracknum': '', 'duration': 0}


def test_invalid_xml_does_not_raise():
    p = _player()
    p._parse_metadata('<not-closed')
    assert p.meta == {'title': '', 'artist': '', 'album': '', 'tracknum': '', 'duration': 0}


DIDL_WITH_RES = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
    '<item>'
    '<dc:title>Naked Truth, Part 6</dc:title>'
    '<upnp:artist>Avishai Cohen</upnp:artist>'
    '<res protocolInfo="http-get:*:audio/x-flac:*" duration="0:00:50.000">tidal://track</res>'
    '</item>'
    '</DIDL-Lite>'
)


def test_duration_parsed_from_didl_res():
    # Duration must come from the DIDL <res> (atomic with the title), not from
    # the separate, independently-timed Info 'Duration' event.
    p = _player()
    p._parse_metadata(DIDL_WITH_RES)
    assert p.meta['title'] == 'Naked Truth, Part 6'
    assert p.meta['duration'] == 50


def test_parse_didl_duration_formats():
    assert Player.Player._parse_didl_duration('0:02:07.000') == 127
    assert Player.Player._parse_didl_duration('1:00:00') == 3600
    assert Player.Player._parse_didl_duration('') == 0
    assert Player.Player._parse_didl_duration(None) == 0
    assert Player.Player._parse_didl_duration('garbage') == 0
