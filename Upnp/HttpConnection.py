import http.client as httplib
import socket

class HttpConnection( httplib.HTTPConnection ):
    "Over-ride for http.client.HTTPConnection to add socket timeout"

    def __init__(self, host, port=None, strict=None, timeout=None):
        "init base class, setup class timeout value"
        # Note: strict parameter was removed in Python 3, ignored for compatibility
        httplib.HTTPConnection.__init__( self, host, port )
        self.timeout=timeout

    def connect(self):
        """Connect to the host and port specified in __init__."""
        last_error = "getaddrinfo returns an empty list"
        for res in socket.getaddrinfo(self.host, self.port, 0,
                                      socket.SOCK_STREAM):
            af, socktype, proto, canonname, sa = res
            try:
                self.sock = socket.socket(af, socktype, proto)
                if self.timeout:
                    self.sock.settimeout( self.timeout )
                if self.debuglevel > 0:
                    print("connect: (%s, %s)" % (self.host, self.port))
                self.sock.connect(sa)
            except socket.error as e:
                last_error = str(e)
                if self.debuglevel > 0:
                    print('connect fail:', (self.host, self.port))
                if self.sock:
                    self.sock.close()
                self.sock = None
                continue
            break
        if not self.sock:
            raise socket.error(last_error)
