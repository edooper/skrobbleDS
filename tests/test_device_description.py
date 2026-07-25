"""Tests for parsing a UPnP device description.

Covers the path B1 changed: the device description alone must yield everything
Player needs (service type + event-subscription URL), with no per-service SCPD
fetch. Any HTTP attempted here would be a regression.
"""
import Upnp.Device as Device

NS = 'urn:schemas-upnp-org:device-1-0'

DEV_DESC = f"""<?xml version="1.0"?>
<root xmlns="{NS}">
  <device>
    <deviceType>urn:linn-co-uk:device:Source:1</deviceType>
    <UDN>uuid:root-1234</UDN>
    <friendlyName>Kitchen</friendlyName>
    <serviceList>
      <service>
        <serviceType>urn:av-openhome-org:service:Info:1</serviceType>
        <serviceId>urn:av-openhome-org:serviceId:Info</serviceId>
        <SCPDURL>/Info/scpd.xml</SCPDURL>
        <controlURL>/Info/control</controlURL>
        <eventSubURL>/Info/event</eventSubURL>
      </service>
      <service>
        <serviceType>urn:av-openhome-org:service:Playlist:1</serviceType>
        <serviceId>urn:av-openhome-org:serviceId:Playlist</serviceId>
        <SCPDURL>Playlist/scpd.xml</SCPDURL>
        <controlURL>Playlist/control</controlURL>
        <eventSubURL>Playlist/event</eventSubURL>
      </service>
    </serviceList>
  </device>
</root>
"""


def _root():
    return Device.RootDevice(DEV_DESC, 'http://192.168.1.50:55178/desc.xml')


def test_device_identity_parsed():
    dev = _root().Device()
    assert dev.Uuid() == 'root-1234'          # 'uuid:' prefix stripped
    assert dev.FriendlyName() == 'Kitchen'
    assert dev.Type() == 'urn:linn-co-uk:device:Source:1'
    assert dev.FindDevice('root-1234') is dev


def test_services_expose_type_and_event_url():
    """Exactly what Player.__init__ reads when subscribing."""
    services = {s.Type(): s for s in _root().Device().ServiceList()}
    assert set(services) == {
        'urn:av-openhome-org:service:Info:1',
        'urn:av-openhome-org:service:Playlist:1',
    }
    # URL base derived from the description location; both leading-slash and
    # bare relative forms resolve to the same absolute shape
    base = 'http://192.168.1.50:55178'
    assert services['urn:av-openhome-org:service:Info:1'].EventSubUrl() == f'{base}/Info/event'
    assert services['urn:av-openhome-org:service:Playlist:1'].EventSubUrl() == f'{base}/Playlist/event'


def test_missing_event_sub_url_is_none_not_an_error():
    """A service without eventSubURL must parse; Player skips it on subscribe."""
    desc = DEV_DESC.replace('<eventSubURL>/Info/event</eventSubURL>', '')
    dev = Device.RootDevice(desc, 'http://192.168.1.50:55178/desc.xml').Device()
    info = [s for s in dev.ServiceList() if s.Type().endswith('Info:1')][0]
    assert info.EventSubUrl() is None


def test_empty_device_list_does_not_confuse_parsing():
    """An empty <deviceList/> is falsy as an Element - it must not be treated
    as absent, and must not raise on Python 3.12+ (A5)."""
    desc = DEV_DESC.replace('</serviceList>', '</serviceList><deviceList/>')
    dev = Device.RootDevice(desc, 'http://192.168.1.50:55178/desc.xml').Device()
    assert dev.DeviceList() == []
    assert len(dev.ServiceList()) == 2
