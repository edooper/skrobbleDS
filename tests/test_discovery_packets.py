"""Tests for SSDP discovery packet parsing."""
import pytest

from Upnp import Discovery, HttpPacket


DEVICE_TYPE = 'urn:linn-co-uk:device:Source:1'
UUID = '4c494e4e-0026-0f21-cc9a-01320147013f'


def _search_response(**overrides):
    pkt = HttpPacket.HttpResponse()
    pkt.SetResponseLine('1.1', '200 OK')
    headers = {
        'CACHE-CONTROL': 'max-age=1800',
        'EXT': '',
        'LOCATION': 'http://192.168.1.20:80/desc.xml',
        'SERVER': 'Linn/1.0 UPnP/1.0',
        'ST': DEVICE_TYPE,
        'USN': f'uuid:{UUID}::{DEVICE_TYPE}',
    }
    headers.update(overrides)
    for name, value in headers.items():
        if value is not None:
            pkt.SetHeader(name, value)
    return pkt


def _notify(nts='ssdp:alive', **overrides):
    pkt = HttpPacket.HttpRequest()
    pkt.SetRequest('NOTIFY', '*')
    headers = {
        'HOST': '239.255.255.250:1900',
        'CACHE-CONTROL': 'max-age=1800',
        'LOCATION': 'http://192.168.1.20:80/desc.xml',
        'SERVER': 'Linn/1.0 UPnP/1.0',
        'NT': DEVICE_TYPE,
        'NTS': nts,
        'USN': f'uuid:{UUID}::{DEVICE_TYPE}',
    }
    headers.update(overrides)
    for name, value in headers.items():
        if value is not None:
            pkt.SetHeader(name, value)
    return pkt


class TestPacketSearchResponse:
    def test_parses_device_type_packet(self):
        parsed = Discovery.PacketSearchResponse(_search_response())
        assert parsed.Uuid() == UUID
        assert parsed.ExpireTime() == 1800
        assert parsed.Location() == 'http://192.168.1.20:80/desc.xml'
        assert parsed.DeviceType() == 'urn:linn-co-uk:device:Source'
        assert parsed.DeviceTypeVersion() == '1'

    def test_missing_cache_control_rejected(self):
        with pytest.raises(Discovery.InvalidPacket):
            Discovery.PacketSearchResponse(_search_response(**{'CACHE-CONTROL': None}))

    def test_missing_location_rejected(self):
        with pytest.raises(Discovery.InvalidPacket):
            Discovery.PacketSearchResponse(_search_response(LOCATION=None))


class TestPacketNotify:
    def test_alive(self):
        parsed = Discovery.PacketNotify(_notify())
        assert parsed.IsAlive() is True
        assert parsed.Uuid() == UUID
        assert parsed.ExpireTime() == 1800

    def test_byebye(self):
        parsed = Discovery.PacketNotify(_notify(nts='ssdp:byebye'))
        assert parsed.IsAlive() is False
        assert parsed.Uuid() == UUID

    def test_wrong_host_rejected(self):
        with pytest.raises(Discovery.InvalidPacket):
            Discovery.PacketNotify(_notify(HOST='192.168.1.1:1900'))

    def test_missing_nts_rejected(self):
        with pytest.raises(Discovery.InvalidPacket):
            Discovery.PacketNotify(_notify(NTS=None))

    def test_rootdevice_packet(self):
        pkt = _notify(NT='upnp:rootdevice',
                      USN=f'uuid:{UUID}::upnp:rootdevice')
        parsed = Discovery.PacketNotify(pkt)
        assert parsed.Uuid() == UUID
        assert parsed.Type() == Discovery.Packet.kTypeRootDevice
