import re


class InvalidPacket(Exception):
    def __init__(self, aPkt):
        self.iPkt = aPkt
    def __str__(self):
        return 'Invalid HTTP packet: ' + self.iPkt

class IncompletePacket(Exception):
    def __init__(self, aPkt):
        self.iPkt = aPkt
    def __str__(self):
        return 'Incomplete HTTP packet: ' + self.iPkt

class InvalidRequest(Exception):
    """An exception thrown when parsing an incoming HTTP packet as a request."""
    def __init__(self, aPacket):
        self.iPacket = aPacket
    def __str__(self):
        return 'Invalid HTTP Request packet:\n' + str(self.iPacket) + '\n'

class InvalidResponse(Exception):
    """An exception thrown when parsing an incoming HTTP packet as a response."""
    def __init__(self, aPacket):
        self.iPacket = aPacket
    def __str__(self):
        return 'Invalid HTTP Response packet:\n' + str(self.iPacket) + '\n'


class HttpPacket:
    """Base class for an HTTP packet (request or response). This class only holds the data and has functions
        for adding headers, parsing etc... It does not have any functionality to do with the actual network
        connection."""

    def __init__(self):
        self.iHeaders = {}
        self.iBody    = ''

    def SetHeader(self, aHeaderName, aHeaderValue):
        """Add a header to the packet. Convert all header names to lower case."""
        self.iHeaders[aHeaderName.lower()] = aHeaderValue

    def Header(self, aHeaderName):
        """Get the value of a header in the packet."""
        try:
            return self.iHeaders[aHeaderName.lower()]
        except KeyError as e:
            return None

    def Body(self):
        """Get the body of the packet."""
        return self.iBody

    def SetBody(self, aBody):
        """Set the body of the packet."""
        self.iBody = aBody

    def __str__(self):
        """Convert the packet to a string."""
        pktStr = ''
        for headerName in self.iHeaders.keys():
            pktStr += headerName + ': ' + self.iHeaders[headerName] + '\r\n'

        pktStr += '\r\n'
        pktStr += self.iBody
        return pktStr

    def Set(self, aData):
        """Parse a data chunk to retrieve the headers and body of an HTTP packet.

           Framing (header/body split, Content-Length, chunk sizes) is done on
           the raw BYTES. Content-Length and chunk sizes are byte counts, so
           decoding to a string first and measuring len() would undercount any
           multi-byte UTF-8 character in the body - making a fully-received body
           look perpetually incomplete. The body is decoded to str only once the
           whole packet has been framed. The caller's type is preserved for the
           returned leftover (str in -> str out, bytes in -> bytes out)."""
        was_str = isinstance(aData, str)
        raw = aData.encode('utf-8') if was_str else aData

        self.iHeaders = {}
        self.iBody    = ''

        def _leftover(excess_bytes):
            if not excess_bytes:
                return None
            return excess_bytes.decode('utf-8', errors='replace') if was_str else excess_bytes

        try:
            # split the data packet into a headers section and everything
            # after it - only on the FIRST blank line, since a chunked body
            # can legitimately contain further '\r\n\r\n' sequences (e.g. its
            # terminating chunk) that must stay part of the body
            idx = raw.find(b'\r\n\r\n')
            if idx == -1:
                raise IncompletePacket(aData)
            headers = raw[:idx]
            rest = raw[idx + 4:]
            # header names/values are ASCII; latin-1 is a safe 1:1 byte decode
            for header in headers.split(b'\r\n'):
                m = re.match( rb'(?P<name>[^:]*):\s*(?P<value>.*)$', header )
                if m:
                    name  = m.group('name').decode('latin-1').lower()
                    value = m.group('value').decode('latin-1')
                    self.iHeaders[ name ] = value

        except IncompletePacket:
            raise
        except Exception as e:
            raise InvalidPacket(aData)

        # Do this last
        transferEncoding = self.Header('Transfer-Encoding')
        if transferEncoding and 'chunked' in transferEncoding.lower():
            decoded, excess = self._decode_chunked(rest)
            if decoded is None:
                # Not all chunks have arrived yet
                raise IncompletePacket(aData)
            self.iBody = decoded.decode('utf-8', errors='replace')
            return _leftover(excess)

        contentLen = self.Header('Content-Length')
        if contentLen:
            cl = int(contentLen)
            if cl > len(rest):
                # Packet is incomplete
                raise IncompletePacket(aData)
            elif cl < len(rest):
                # The data supplied contains excess data - return this
                self.iBody = rest[:cl].decode('utf-8', errors='replace')
                return _leftover(rest[cl:])
            else:
                self.iBody = rest.decode('utf-8', errors='replace')
        else:
            self.iBody = rest.decode('utf-8', errors='replace')

    @staticmethod
    def _decode_chunked(aRaw):
        """Decode a chunked-transfer-encoded body (bytes). Returns
            (body_bytes, excess_bytes) once all chunks (including the
            terminating zero-length chunk) have been received, or (None, None)
            if more data is still needed."""
        body = b''
        pos = 0
        while True:
            lineEnd = aRaw.find(b'\r\n', pos)
            if lineEnd == -1:
                return None, None

            sizeStr = aRaw[pos:lineEnd].split(b';', 1)[0].strip()
            try:
                size = int(sizeStr, 16)
            except ValueError:
                raise InvalidPacket(aRaw)

            chunkStart = lineEnd + 2
            if size == 0:
                # Terminating chunk - the rest is optional trailers, ended by
                # a blank line; we don't expect trailers from UPnP eventing
                trailerEnd = aRaw.find(b'\r\n', chunkStart)
                if trailerEnd == -1:
                    return None, None
                return body, aRaw[trailerEnd + 2:] or None

            chunkEnd = chunkStart + size
            if chunkEnd + 2 > len(aRaw):
                return None, None

            body += aRaw[chunkStart:chunkEnd]
            pos = chunkEnd + 2


class HttpRequest(HttpPacket):
    """An HTTP request. This has extra functionality to handle the first line of the packet."""

    def __init__(self):
        HttpPacket.__init__(self)
        self.iRequestMethod = ''
        self.iRequestUri    = ''
        self.iVersion       = '1.1'

    def SetRequest(self, aMethod, aUri):
        """Set the request method and URI."""
        self.iRequestMethod = aMethod
        self.iRequestUri    = aUri

    def Request(self):
        """Return a tuple of (method, uri)."""
        return (self.iRequestMethod, self.iRequestUri)

    def __str__(self):
        """Convert to a string."""
        pktStr = self.iRequestMethod + ' ' + self.iRequestUri + ' HTTP/' + self.iVersion + '\r\n'
        pktStr += HttpPacket.__str__(self)
        return pktStr

    def Set(self, aData):
        """Parse a data chunk to retrieve the headers and body of an HTTP packet."""
        # Read the request line without decoding the whole (possibly multi-byte)
        # body - latin-1 is a safe 1:1 byte->char mapping for the ASCII line.
        head = aData.decode('latin-1', errors='replace') if isinstance(aData, bytes) else aData
        m = re.match( r'^(\S*) (\S*) HTTP/(\d.\d)', head )
        try:
            self.iRequestMethod = m.group(1)
            self.iRequestUri    = m.group(2)
            self.iVersion       = m.group(3)
        except IndexError as e:
            raise InvalidRequest(aData)
        except AttributeError as e:
            raise InvalidRequest(aData)
        # Pass the original data (bytes preserved) through for byte-accurate framing
        return HttpPacket.Set(self, aData)


class HttpResponse(HttpPacket):
    """An HTTP response. This has extra functionality to handle the first line of the packet."""

    def __init__(self):
        HttpPacket.__init__(self)
        self.iVersion    = ''
        self.iStatuscode = ''

    def SetResponseLine(self, aVersion, aStatus):
        """Set the version (as a string e.g. '1.1') and the status (as a string e.g. '200 OK')"""
        self.iVersion = aVersion
        self.iStatuscode = aStatus

    def __str__(self):
        """Convert to a string."""
        pktStr = 'HTTP/' + self.iVersion + ' ' + self.iStatuscode + '\r\n'
        pktStr += HttpPacket.__str__(self)
        return pktStr

    def Set(self, aData):
        """Parse a data chunk to retrieve the headers and body of an HTTP packet."""
        # Read the status line without decoding the whole (possibly multi-byte)
        # body - latin-1 is a safe 1:1 byte->char mapping for the ASCII line.
        head = aData.decode('latin-1', errors='replace') if isinstance(aData, bytes) else aData
        m = re.match( r'HTTP/(\d.\d)\s*([^\r\n]*)', head )
        try:
            self.iVersion    = m.group(1);
            self.iStatuscode = m.group(2)
        except IndexError as e:
            raise InvalidResponse(aData)
        except AttributeError as e:
            raise InvalidResponse(aData)
        # Pass the original data (bytes preserved) through for byte-accurate framing
        return HttpPacket.Set(self, aData)
