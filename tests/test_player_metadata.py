"""Tests for DIDL-Lite metadata parsing in Player."""
from types import SimpleNamespace

import Player


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
    p.log = lambda msg: None
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
    }


def test_parse_falls_back_to_first_artist():
    p = _player()
    p._parse_metadata(DIDL.replace(' role="Performer"', ''))
    assert p.meta['artist'] == 'Composer Name'


def test_empty_metadata_resets():
    p = _player()
    p.meta = {'title': 'stale'}
    p._parse_metadata('')
    assert p.meta == {'title': '', 'artist': '', 'album': '', 'tracknum': ''}


def test_invalid_xml_does_not_raise():
    p = _player()
    p._parse_metadata('<not-closed')
    assert p.meta == {'title': '', 'artist': '', 'album': '', 'tracknum': ''}
