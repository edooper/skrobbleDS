"""Tests for the hand-rolled HTTP packet parser used by the UPnP layer."""
import pytest

from Upnp import HttpPacket


NOTIFY = (
    'NOTIFY /eventURL HTTP/1.1\r\n'
    'HOST: 192.168.1.10:5600\r\n'
    'CONTENT-TYPE: text/xml\r\n'
    'CONTENT-LENGTH: 5\r\n'
    'SID: uuid:abc\r\n'
    'SEQ: 0\r\n'
    '\r\n'
    'hello'
)

CHUNKED_NOTIFY = (
    'NOTIFY /eventURL HTTP/1.1\r\n'
    'HOST: 192.168.1.10:5600\r\n'
    'CONTENT-TYPE: text/xml\r\n'
    'TRANSFER-ENCODING: chunked\r\n'
    'SID: uuid:abc\r\n'
    'SEQ: 0\r\n'
    '\r\n'
    '5\r\n'
    'hello\r\n'
    '0\r\n'
    '\r\n'
)


class TestHttpRequest:
    def test_parse_request_line_and_headers(self):
        pkt = HttpPacket.HttpRequest()
        pkt.Set(NOTIFY)
        assert pkt.Request() == ('NOTIFY', '/eventURL')
        assert pkt.Header('SID') == 'uuid:abc'
        assert pkt.Body() == 'hello'

    def test_headers_case_insensitive(self):
        pkt = HttpPacket.HttpRequest()
        pkt.Set(NOTIFY)
        assert pkt.Header('sid') == 'uuid:abc'
        assert pkt.Header('Content-Length') == '5'

    def test_bytes_input_accepted(self):
        pkt = HttpPacket.HttpRequest()
        pkt.Set(NOTIFY.encode('utf-8'))
        assert pkt.Body() == 'hello'

    def test_incomplete_body_raises(self):
        short = NOTIFY.replace('CONTENT-LENGTH: 5', 'CONTENT-LENGTH: 50')
        pkt = HttpPacket.HttpRequest()
        with pytest.raises(HttpPacket.IncompletePacket):
            pkt.Set(short)

    def test_excess_data_returned(self):
        pkt = HttpPacket.HttpRequest()
        extra = pkt.Set(NOTIFY + 'NEXT')
        assert pkt.Body() == 'hello'
        assert extra == 'NEXT'

    def test_garbage_raises_invalid_request(self):
        pkt = HttpPacket.HttpRequest()
        with pytest.raises(HttpPacket.InvalidRequest):
            pkt.Set('complete garbage')

    def test_incomplete_headers_raises_incomplete(self):
        # Headers section itself hasn't fully arrived yet - must be treated
        # as needing more data, not as a malformed packet.
        pkt = HttpPacket.HttpRequest()
        with pytest.raises(HttpPacket.IncompletePacket):
            pkt.Set('NOTIFY /eventURL HTTP/1.1\r\nHOST: 192.168.1.10:5600\r\nSID: uuid:abc')

    def test_chunked_body_decoded(self):
        pkt = HttpPacket.HttpRequest()
        pkt.Set(CHUNKED_NOTIFY)
        assert pkt.Body() == 'hello'
        assert pkt.Header('SID') == 'uuid:abc'

    def test_chunked_multiple_chunks_concatenated(self):
        multi = (
            'NOTIFY /eventURL HTTP/1.1\r\n'
            'TRANSFER-ENCODING: chunked\r\n'
            '\r\n'
            '5\r\n'
            'hello\r\n'
            '6\r\n'
            ' world\r\n'
            '0\r\n'
            '\r\n'
        )
        pkt = HttpPacket.HttpRequest()
        pkt.Set(multi)
        assert pkt.Body() == 'hello world'

    def test_chunked_missing_terminator_raises_incomplete(self):
        partial = (
            'NOTIFY /eventURL HTTP/1.1\r\n'
            'TRANSFER-ENCODING: chunked\r\n'
            '\r\n'
            '5\r\n'
            'hel'
        )
        pkt = HttpPacket.HttpRequest()
        with pytest.raises(HttpPacket.IncompletePacket):
            pkt.Set(partial)

    def test_chunked_excess_data_returned(self):
        pkt = HttpPacket.HttpRequest()
        extra = pkt.Set(CHUNKED_NOTIFY + 'NEXT')
        assert pkt.Body() == 'hello'
        assert extra == 'NEXT'


class TestHttpResponse:
    def test_parse_status_line(self):
        pkt = HttpPacket.HttpResponse()
        pkt.Set('HTTP/1.1 200 OK\r\nEXT: \r\n\r\n')
        assert pkt.iStatuscode == '200 OK'
        assert pkt.Header('EXT') == ''

    def test_garbage_raises_invalid_response(self):
        pkt = HttpPacket.HttpResponse()
        with pytest.raises(HttpPacket.InvalidResponse):
            pkt.Set('nonsense')

    def test_serialise_round_trip(self):
        pkt = HttpPacket.HttpResponse()
        pkt.SetResponseLine('1.1', '200 OK')
        assert str(pkt).startswith('HTTP/1.1 200 OK\r\n')
