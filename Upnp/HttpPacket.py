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
        """Parse a data chunk to retrieve the headers and body of an HTTP packet."""
        # Decode bytes to string if needed (Python 3 compatibility)
        if isinstance(aData, bytes):
            aData = aData.decode('utf-8', errors='replace')

        self.iHeaders = {}
        self.iBody    = ''

        try:
            # split the data packet into a headers and body section
            t = re.split( '\r\n\r\n', aData )
            headers = t[0]
            self.iBody = t[1]
            # split the headers section into a list of individual headers (the '\r\n' gets removed from each)
            headerList = re.split( '\r\n', headers )

            for header in headerList:
                m = re.match( r"""(?P<name>[^:]*)    # match any characters upto the first ':'
                                :\s*                 # match the ':' plus any number of following spaces
                                (?P<value>.*$)""",   # match all characters up to the end of the string
                                header,
                                re.VERBOSE )
                if m:
                    self.iHeaders[ m.group('name').lower() ] = m.group('value')

        except Exception as e:
            raise InvalidPacket(aData)

        # Do this last
        contentLen = self.Header('Content-Length')
        if contentLen:
            if int(contentLen) > len(self.iBody):
                # Packet is incomplete
                raise IncompletePacket(aData)

            elif int(contentLen) < len(self.iBody):
                # The data supplied contains excess data - return this
                xs = self.iBody[int(contentLen):]
                self.iBody = self.iBody[0:int(contentLen)]
                return xs


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
        # Decode bytes to string if needed (Python 3 compatibility)
        if isinstance(aData, bytes):
            aData = aData.decode('utf-8', errors='replace')
        m = re.match( r'^(\S*) (\S*) HTTP/(\d.\d)', aData )
        try:
            self.iRequestMethod = m.group(1)
            self.iRequestUri    = m.group(2)
            self.iVersion       = m.group(3)
        except IndexError as e:
            raise InvalidRequest(aData)
        except AttributeError as e:
            raise InvalidRequest(aData)
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
        # Decode bytes to string if needed (Python 3 compatibility)
        if isinstance(aData, bytes):
            aData = aData.decode('utf-8', errors='replace')
        m = re.match( r'HTTP/(\d.\d)\s*([^\r\n]*)', aData )
        try:
            self.iVersion    = m.group(1);
            self.iStatuscode = m.group(2)
        except IndexError as e:
            raise InvalidResponse(aData)
        except AttributeError as e:
            raise InvalidResponse(aData)
        return HttpPacket.Set(self, aData)
