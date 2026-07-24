"""Tests for the event server's packet extraction.

A UPnP device may coalesce several NOTIFYs into a single TCP segment (one
recv). Every complete packet must be processed, not just the first, or the
trailing NOTIFYs (e.g. an Info 'Metadata' event) are lost when the device
closes the connection.
"""
from Upnp import EventServer


def _notify(sid, seq, body):
    body_bytes = body.encode('utf-8')
    return (
        b'NOTIFY /eventURL HTTP/1.1\r\n'
        b'SID: ' + sid.encode() + b'\r\n'
        b'SEQ: ' + str(seq).encode() + b'\r\n'
        b'CONTENT-LENGTH: ' + str(len(body_bytes)).encode() + b'\r\n'
        b'\r\n' + body_bytes
    )


def _session(raw):
    sess = EventServer.EventSession(None, ('192.168.1.20', 5000))
    sess.Append(raw)
    return sess


def test_single_packet_extracted():
    sess = _session(_notify('a', 0, 'hello'))
    pkts = EventServer.EventServer._extract_packets(sess)
    assert [p.Header('SID') for p in pkts] == ['a']
    assert [p.Body() for p in pkts] == ['hello']
    assert sess.Data() == b''


def test_multiple_coalesced_packets_all_extracted():
    # Two NOTIFYs delivered in one recv - both must come out.
    sess = _session(_notify('a', 0, 'hello') + _notify('b', 1, 'world'))
    pkts = EventServer.EventServer._extract_packets(sess)
    assert [p.Header('SID') for p in pkts] == ['a', 'b']
    assert [p.Body() for p in pkts] == ['hello', 'world']
    assert sess.Data() == b''


def test_trailing_incomplete_packet_retained():
    # A complete NOTIFY followed by the start of another: the first is
    # extracted, the partial second is kept for the next read.
    partial = b'NOTIFY /eventURL HTTP/1.1\r\nSID: b\r\nSEQ: 1\r\nCONTENT-LENGTH: 20\r\n\r\nonly-some'
    sess = _session(_notify('a', 0, 'hello') + partial)
    pkts = EventServer.EventServer._extract_packets(sess)
    assert [p.Header('SID') for p in pkts] == ['a']
    assert sess.Data() == partial


def test_multibyte_coalesced_packets():
    # Metadata bodies carry multi-byte UTF-8; Content-Length is a byte count,
    # so the split point between coalesced packets must be byte-accurate.
    sess = _session(_notify('a', 0, '℗ one') + _notify('b', 1, 'café two'))
    pkts = EventServer.EventServer._extract_packets(sess)
    assert [p.Body() for p in pkts] == ['℗ one', 'café two']
    assert sess.Data() == b''
