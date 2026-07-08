
from threading import Thread
from threading import Lock
from threading import Event
import socket
import select
import re
import os
import struct
from . import HttpPacket
from . import NetUtil

gSsdpAddr = ('239.255.255.250', 1900)


class SsdpObserver:
    """An SSDP observer interface. Classes implement this interface in order to listen to incoming
        SSDP messages from the server."""

    def SsdpReceived(self, aSsdpPkt):
        """Method to be implemented in subclass. The argument 'aSsdpPkt' is of type
            HttpPacket.HttpRequest"""


class SsdpServer(Thread):
    """An SSDP server - the subject in the observer pattern. This listens for incoming SSDP messages and
        notifies its list of observers when it receives a message."""

    def __init__(self, aIfAddr=None):
        """If no interface address argument (aIfAddr) is specified, the server will use any
            available address"""
        Thread.__init__(self, daemon=True)
        self.iObservers = []
        self.iIfAddr    = aIfAddr
        self.iStopPort  = None
        self.iLock      = Lock()
        self.iStarted   = Event()
        self.iStopped   = Event()
        self.iStopped.set()
        self.iDumpPackets = False
        if not self.iIfAddr:
            self.iIfAddr = NetUtil.get_local_ip()

    def AddObserver(self, aObs):
        """Add an observer to the list."""
        self.iLock.acquire()
        self.iObservers.append(aObs)
        self.iLock.release()

    def RemoveObserver(self, aObs):
        """Remove an observer from the list."""
        self.iLock.acquire()
        self.iObservers.remove(aObs)
        self.iLock.release()

    def Start(self):
        """Add a consistent Start/Stop interface (rather than start/Stop). Wait for the
            main loop of the thread to start before proceeding."""
        self.start()
        self.iStarted.wait()

    def Stop(self):
        """Stop the server. This sends a message on the loopback interface in order to break out
            of the select function in the main server thread. Wait for the thread to
            terminate before proceeding."""
        if self.iStopPort == None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        sock.sendto(b'close', ('127.0.0.1', self.iStopPort))
        sock.close()
        self.iStopped.wait()

    def run(self):
        """Main thread function for the SSDP server"""
        # create a socket to listen on the mutlicast channel
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        sock.setsockopt( socket.SOL_SOCKET, socket.SO_REUSEADDR, 1 )

        # For receiving multicast packets, the binding of the socket is OS dependent
        if os.name == 'posix':
            # Bind to INADDR_ANY on POSIX (Linux/macOS/BSD)
            # The IP_ADD_MEMBERSHIP below will specify which interface to use
            sock.bind( ('', gSsdpAddr[1]) )
        elif os.name == 'nt':
            # Bind to the local IP address on windows
            sock.bind( (self.iIfAddr, gSsdpAddr[1]) )
        else:
            raise RuntimeError('OS not supported')

        # inet_aton returns the 32-bit version of the string address
        # argument ***in a packed struct format (i.e. a string not an int)***
        mcastreq = None
        mcastreq = socket.inet_aton(gSsdpAddr[0]) + socket.inet_aton(self.iIfAddr)

        sock.setsockopt( socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mcastreq )

        # create the stop socket - this listens on the loopback interface for a message to quit the server
        stopSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)

        # Try to bind to the port - if it fails, increment the port and try again
        port = 6789
        portAssigned = 0
        while not portAssigned:
            try:
                stopSock.bind( ('127.0.0.1', port) )
                portAssigned = 1
            except socket.error as e:
                port += 1
        self.iStopPort = port

        self.iStopped.clear()
        self.iStarted.set()
        while(1):
            # listen for incoming messages
            iret, oret, eret = select.select( [sock, stopSock], [], [] )

            self.iLock.acquire()
            if sock in iret:
                # read and parse the packet and notify all observers - an SSDP packet will
                # not be bigger than 1024
                (data, (ipAddr, port)) = sock.recvfrom( 1024 )
                recvpkt = HttpPacket.HttpRequest()

                try:
                    recvpkt.Set( data )
                    for obs in self.iObservers:
                        obs.SsdpReceived(recvpkt)

                    if self.iDumpPackets:
                        print(recvpkt)
                        print()

                except Exception as e:
                    # ignore invalid requests
                    pass

            self.iLock.release()

            if stopSock in iret:
                break

        sock.close()
        stopSock.close()
        self.iStopped.set()

    def DumpPackets(self, aDump):
        self.iDumpPackets = aDump
