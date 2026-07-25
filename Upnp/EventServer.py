
from . import HttpPacket
from threading import Thread
from threading import Lock
from threading import BoundedSemaphore
from threading import Event
import socket
import select
import traceback

#
# The core event classes used a modified version of the observer patter.
#
#    1) class EventServer - this is the subject that observers subscribe to. The main difference is that
#                            rather than notifying all observers when the event happens, it only notifies
#                            the one observer that the event is intended for.
#
#    2) class EventObserver - the observer. This interface has an additional operation to get the SID so that
#                            the subject can determine who gets notified of the event.
#

class EventSession:
    """A class to handle incoming data arriving in chunks"""
    def __init__(self, aSocket, aAddr):
        self.iSocket = aSocket
        self.iAddr = aAddr
        # Accumulate raw BYTES, not a decoded string: a multi-byte UTF-8
        # character split across two recv() boundaries would be corrupted if
        # each segment were decoded on its own, and HTTP framing (Content-
        # Length, chunk sizes) is defined in bytes.
        self.iData = b''

    def Socket(self):
        return self.iSocket

    def Address(self):
        return self.iAddr

    def Data(self):
        return self.iData

    def SetData(self, aData):
        if aData:
            self.iData = aData
        else:
            self.iData = b''

    def Append(self, aData):
        self.iData += aData


class EventObserver:
    """An interface for classes to implement event listening behaviour."""
    def __init__(self):
        pass

    def SubId(self):
        """Return the subscription ID (SID) of the observer. The subject in the observer pattern will use
            this to determine which observer gets notified."""
        pass

    def Notify(self, aSeq, aXmlBody):
        """Called when an event happens."""
        pass


class EventServer(Thread):
    """HTTP server for listening to events."""

    def __init__(self, aEventAddr=None):
        """Initialise."""
        Thread.__init__(self, daemon=True)
        self.iObservers = []
        self.iAddr      = aEventAddr
        self.iEventPort = None
        self.iStopPort  = None
        # Bounded so an unbalanced Unpause raises instead of silently
        # disabling the pause mechanism
        self.iPauseSem  = BoundedSemaphore(1)
        self.iLock      = Lock()
        self.iStarted   = Event()
        self.iStopped   = Event()
        self.iStopped.set()

    @staticmethod
    def _extract_packets(session):
        """Parse and remove every complete HTTP request currently buffered in
           the session, returning them as a list. Any trailing incomplete bytes
           are left in the session to be completed by the next read. An
           unparsable packet is logged and the buffer discarded so one bad
           message can't poison the ones behind it."""
        packets = []
        while session.Data():
            recvpkt = HttpPacket.HttpRequest()
            try:
                xs = recvpkt.Set( session.Data() )
            except HttpPacket.IncompletePacket:
                # more data still to arrive - keep what we have and wait
                break
            except Exception as e:
                print('[EventServer] Discarding unparsable HTTP packet: %r' % (e,))
                traceback.print_exc()
                session.SetData(b'')
                break
            # A full packet was parsed - keep any trailing bytes for the next one
            session.SetData(xs)
            packets.append(recvpkt)
        return packets

    def AddObserver(self, aObs):
        """Add an observer to listen to events."""
        self.iLock.acquire()
        self.iObservers.append(aObs)
        self.iLock.release()

    def RemoveObserver(self, aObs):
        """Remove an observer from the list."""
        self.iLock.acquire()
        if aObs in self.iObservers:
            self.iObservers.remove(aObs)
        self.iLock.release()

    def EventUrl(self):
        """Get the URL that devices need to send events to."""
        if self.iEventPort == None:
            return ''
        return 'http://' + self.iAddr + ':' + repr(self.iEventPort) + '/eventURL'

    def Start(self):
        """Add a consistent Start/Stop interface (rather than start/Stop)."""
        self.start()
        self.iStarted.wait()

    def Stop(self):
        """Stop the server. This sends a message on the loopback interface in order to break out
            of the select function in the main server thread."""
        if self.iStopPort == None:
            return
        self.iLock.acquire()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        sock.sendto(b'close', ('127.0.0.1', self.iStopPort))
        sock.close()
        self.iLock.release()
        self.iStopped.wait()
        self.iStopPort = None

    def Pause(self):
        self.iPauseSem.acquire()

    def Unpause(self):
        self.iPauseSem.release()

    def run(self):
        # create a socket to listen on the mutlicast channel
        listenSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)

        # Try to bind to the port - if it fails, increment the port and try again
        port = 5600
        max_port = port + 1000
        portAssigned = 0
        while not portAssigned:
            try:
                listenSock.bind( (self.iAddr, port) )
                portAssigned = 1
            except socket.error as e:
                port += 1
                if port > max_port:
                    raise RuntimeError("Unable to bind event server to any port in range 5600-%d" % max_port)
        self.iEventPort = port
        listenSock.listen(5)

        # stop socket - for exiting the main server loop below
        stopSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        port = 5678
        max_port = port + 1000
        portAssigned = 0
        while not portAssigned:
            try:
                stopSock.bind( ('127.0.0.1', port) )
                portAssigned = 1
            except socket.error as e:
                port += 1
                if port > max_port:
                    raise RuntimeError("Unable to bind stop socket to any port in range 5678-%d" % max_port)
        self.iStopPort = port
        
        # A list of connected sockets
        connSocks = []
        connSessions = {}

        # Main server loop
        self.iStopped.clear()
        self.iStarted.set()
        while(1):
            # listen for incoming messages
            socks = connSocks + [listenSock, stopSock]
            iret, oret, eret = select.select( socks, [], [] )

            # Handle pausing of the server
            self.iPauseSem.acquire()
            self.iPauseSem.release()

            # Stop the server?
            if stopSock in iret:
                break

            # New connection?
            if listenSock in iret:
                # A device is requesting a connection
                (sock, addr) = listenSock.accept()
                connSocks.append(sock)
                connSessions[sock] = EventSession(sock, addr)

            # Message from a current connection?
            self.iLock.acquire()
            toRemove = []
            try:
                for sock in connSocks:
                    if sock in iret:
                        # read the data from this socket
                        try:
                            data = sock.recv( 10000 )
                        except OSError:
                            # socket closed by peer - treat as end of stream
                            data = b''

                        if len(data) == 0:
                            # The socket has been closed
                            toRemove.append(sock)

                        else:
                            connSessions[sock].Append(data)
                            # Process EVERY complete NOTIFY currently buffered,
                            # not just the first: a device may coalesce several
                            # NOTIFYs into one TCP segment, and the trailing ones
                            # would otherwise be lost when the connection closes.
                            for recvpkt in self._extract_packets(connSessions[sock]):
                                sid = recvpkt.Header('SID')
                                seq = recvpkt.Header('SEQ')
                                if sid is not None and seq is not None:
                                    for obs in self.iObservers:
                                        if sid == obs.SubId():
                                            # A misbehaving observer must not kill
                                            # the server thread
                                            try:
                                                obs.Notify( seq, recvpkt.Body() )
                                            except Exception:
                                                traceback.print_exc()

                                # Acknowledge every NOTIFY
                                ack = HttpPacket.HttpResponse()
                                ack.SetResponseLine('1.1', '200 OK')
                                try:
                                    sock.send( str(ack).encode('utf-8') )
                                except OSError:
                                    if sock not in toRemove:
                                        toRemove.append(sock)
            finally:
                self.iLock.release()

            # Remove any closed sockets
            for sock in toRemove:
                connSocks.remove(sock)
                sock.close()
                del connSessions[sock]

        stopSock.close()
        listenSock.close()
        for sock in connSocks:
            sock.close()

        self.iStopped.set()
