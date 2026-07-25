from . import Ssdp
from . import Device
from . import HttpPacket
from . import NetUtil
import re
import socket
import select
import time
from threading import Lock
from threading import Thread
from threading import Semaphore
from threading import Event
from threading import Timer


class DiscoveryObserver:
    """An interface for objects to be notified of device discovery and removal."""

    def DeviceDiscovered(self, aDev):
        """A device has been discovered."""

    def DeviceRemoved(self, aDev, aReason):
        """A device has been removed. Returning 'self' from this function will cause
            the observer to be removed from the list. This should be done rather than
            explicitly calling RemoveObserver on the Discovery instance."""


class Msearch(Thread):
    """A class to spawn a thread for the M_SEARCH discovery."""

    def __init__(self, aDiscovery):
        Thread.__init__(self, daemon=True)
        self.iDiscovery = aDiscovery

    def run(self):
        self.iDiscovery.DoMsearch()


class Discovery(Ssdp.SsdpObserver):
    """A control point class. This class handles the discovery phase of UPnP and manages a list of
        currently available devices. It only implements the UPnP DISCOVERY PHASE. Other UPnP phases
        are implemented in different classes."""

    def __init__(self, aIfAddr=None, aSsdpServer=None):
        self.iIfAddr      = aIfAddr        
        self.iSearchType  = None
        self.iDeviceList  = []
        self.iDescList    = []
        self.iDiscoverObs = []
        self.timerDict    = {}
        self.iLock        = Lock()
        self.iSearchDone  = Event()
        self.iSearchTime  = 2
        self.iSsdpServer = aSsdpServer
        if aSsdpServer == None:
            self.iOwnsSsdpServer = True
        else:
            self.iOwnsSsdpServer = False

    def LockDeviceList(self):
        self.iLock.acquire()
        return self.iDeviceList

    def UnlockDeviceList(self):
        self.iLock.release()

    def Start(self, aSearchType, aSearchTime=2):
        """Start the discovery"""
        self.iSearchType = aSearchType
        if self.iOwnsSsdpServer:
            self.iSsdpServer = Ssdp.SsdpServer( self.iIfAddr )
            self.iSsdpServer.AddObserver(self)
            self.iSsdpServer.Start()
        else:
            self.iSsdpServer.AddObserver(self)
        self.Discover(aSearchTime)

    def Stop(self):
        """Stop the discovery"""
        # Cancel outstanding device-expiry timers so they neither fire after
        # shutdown nor keep the process alive
        self.iLock.acquire()
        for timer in self.timerDict.values():
            timer.cancel()
        self.timerDict = {}
        self.iLock.release()

        if self.iOwnsSsdpServer:
            self.iSsdpServer.RemoveObserver(self)
            self.iSsdpServer.Stop()
            self.iSsdpServer.join()
            self.iSsdpServer = None
            self.iDiscoverObs = []
        else:
            self.iSsdpServer.RemoveObserver(self)
            self.iDiscoverObs = []

    def AddObserver(self, aObs):
        """Add a discovery observer to the list."""
        self.iLock.acquire()
        self.iDiscoverObs.append(aObs);
        self.iLock.release()

    def RemoveObserver(self, aObs):
        """Remove a discovery observer from the list."""
        self.iLock.acquire()
        self.iDiscoverObs.remove(aObs);
        self.iLock.release()

    def Discover(self, aSearchTime=2):
        """Start the UPnP M-SEARCH discovery. Spawn the thread to handle it and return.
            Need to create a new Msearch object since, for thread objects, the start()
            operation can only be called once - even if the thread has terminated."""
        self.iSearchTime = aSearchTime
        msearch = Msearch(self)
        msearch.start()

    def WaitForDiscover(self):
        """Wait for the end of the M_SEARCH discovery."""
        self.iSearchDone.wait()

    def DeviceDescriptionDone( self, aUuid, aDevice ):
        """Callback from DescriptionRetriever on success"""
        self.iLock.acquire()
        self.iDeviceList.append( aDevice )
        observers = list(self.iDiscoverObs)
        if aUuid in self.iDescList:
            self.iDescList.remove( aUuid )
        self.iLock.release()
        # Notify outside the lock - observers may block (e.g. subscribing to
        # the device) and must not stall SSDP processing or invite deadlock
        for obs in observers:
            obs.DeviceDiscovered( aDevice )

    def DeviceDescriptionFailed( self, aUuid ):
        """Callback from DescriptionRetriever on failure"""
        self.iLock.acquire()
        if aUuid in self.iDescList:
            self.iDescList.remove( aUuid )
        self.iLock.release()

    def DoMsearch(self):
        """Thread function for discovering devices on the network. This sends out a
            M_SEARCH request to discover what devices are present on the network. This
            implements part of the UPnP DISCOVERY PHASE."""
        # Send a m-search packet
        searchPkt = HttpPacket.HttpRequest()
        searchPkt.SetRequest('M-SEARCH', '*')
        searchPkt.SetHeader('HOST', '239.255.255.250:1900')
        searchPkt.SetHeader('MAN', '"ssdp:discover"')
        searchPkt.SetHeader('MX', str(self.iSearchTime))
        searchPkt.SetHeader('ST', self.iSearchType)

        # create a socket to send the request and listen to responses
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        sock.setsockopt( socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4 )

        # Try to bind to the port - if it fails, increment the port and try again
        port = 22671
        max_port = port + 1000
        portAssigned = 0
        ifAddr = self.iIfAddr if self.iIfAddr else NetUtil.get_local_ip()
        while not portAssigned:
            try:
                sock.bind( (ifAddr, port) )
                portAssigned = 1
            except socket.error as e:
                port += 1
                if port > max_port:
                    raise RuntimeError("Unable to bind to any port in range 22671-%d" % max_port)

        # send the request
        sock.sendto( str(searchPkt).encode('utf-8'), ('239.255.255.250', 1900))

        # listen for search responses
        recvPkt = HttpPacket.HttpResponse()
        done = 0
        timeRemaining = self.iSearchTime
        while( done == 0 ):
            preSelectTime = time.time()
            iret, oret, eret = select.select( [sock], [], [], timeRemaining )
            timeRemaining -= time.time() - preSelectTime
            if timeRemaining < 0:
                timeRemaining = 0

            if len(iret) == 0:
                done = 1
                continue

            # Devices send an SSDP response packet which should easily be no bigger
            # than 1024 bytes
            (data, (ipAddr, port)) = sock.recvfrom( 1024 )
            try:
                recvPkt.Set( data )
            except HttpPacket.InvalidResponse as e:
                # ignore invalid packets
                continue

            # Parse the response packet
            try:
                newPkt = PacketSearchResponse(recvPkt)
            except InvalidPacket as e:
                continue

            # Ignore responses that do not match the search target - some
            # devices (e.g. Hue bridges) answer M-SEARCH with unrelated types
            if newPkt.TypeString() != self.iSearchType:
                continue

            # Look for the device
            self.iLock.acquire()
            existingDev = [ dev for dev in self.iDeviceList if dev.Uuid() == newPkt.Uuid() ]
            if len(existingDev) != 0:
                # device already in list - update
                existingDev[0].SetLocation( newPkt.Location() )
                self.__RefreshExpiryTimer(newPkt.Uuid(), newPkt.ExpireTime())
            else:
                # device not in list - is it in the description retriever list?
                if newPkt.Uuid() in self.iDescList:
                    # Device is currently retrieving its description files - ignore it
                    pass
                else:
                    # Device has just appeared on the network for the first time
                    self.__RefreshExpiryTimer(newPkt.Uuid(), newPkt.ExpireTime())
                    newDescRetr = Device.DescriptionRetriever(newPkt.Uuid(), newPkt.Location(), self)
                    self.iDescList.append( newPkt.Uuid() )
                    newDescRetr.Start()
            self.iLock.release()
        sock.close()
        self.iSearchDone.set()

    def SsdpReceived(self, aSsdpPkt):
        """Implementation of the SSDPObserver interface. This function is called whenever the SSDP server
            receives an incoming SSDP message. This implements part of the UPnP DISCOVERY PHASE"""

        # Check this is the type of packet we are interested in
        (method, uri) = aSsdpPkt.Request()
        m = re.match('NOTIFY', method)
        if m == None:
            return

        # parse the packet
        try:
            newPkt = PacketNotify(aSsdpPkt)
        except InvalidPacket as e:
            # Ignore invalid packets
            return


        # Skip packets that do not match the search type. A plain comparison,
        # as in DoMsearch: the type comes from the NT header of any NOTIFY on
        # the LAN, and building a regex out of it lets a device with regex
        # metacharacters in its type raise re.error instead of just not matching
        if newPkt.TypeString() != self.iSearchType:
            return

        self.iLock.acquire()
        if newPkt.IsAlive():
            #
            # An ssdp:alive message
            #
            existingDev = [ dev for dev in self.iDeviceList if dev.Uuid() == newPkt.Uuid() ]
            if len(existingDev) != 0:
                # Device is already on the network
                self.__RefreshExpiryTimer(newPkt.Uuid(), newPkt.ExpireTime())
                existingDev[0].SetLocation( newPkt.Location() )
            else:
                # Need to check if the device is in the description list
                if newPkt.Uuid() in self.iDescList:
                    # Device is currently retrieving its description files - ignore it
                    pass
                else:
                    # Device has just (re)appeared on the network
                    self.__RefreshExpiryTimer(newPkt.Uuid(), newPkt.ExpireTime())
                    newDescRetr = Device.DescriptionRetriever(newPkt.Uuid(), newPkt.Location(), self)
                    self.iDescList.append( newPkt.Uuid() )
                    newDescRetr.Start()
        else:
            #
            # An ssdp:byebye message
            #
            devToGo = [ dev for dev in self.iDeviceList if dev.Uuid() == newPkt.Uuid() ]
            if len(devToGo) != 0:
                observers = self.__RemoveDevice(devToGo[0])
                self.iLock.release()
                self.__NotifyRemoved(observers, devToGo[0], 'BYEBYE')
                return
        self.iLock.release()
        
    def __RefreshExpiryTimer(self, aUuid, aExpireTime):
        "Update notification expiry timer"
        if aUuid in self.timerDict:
            timer = self.timerDict[aUuid]
            timer.cancel()
            del self.timerDict[aUuid]
        timer = Timer(aExpireTime, self.__DeviceExpired, [aUuid])
        timer.daemon = True
        timer.start()
        self.timerDict[aUuid] = timer
        
    def __DeviceExpired(self, aUuid):
        "Callback on notification-valid timeout (runs in a Timer thread)"
        self.iLock.acquire()
        devToGo = [ dev for dev in self.iDeviceList if dev.Uuid() == aUuid ]
        observers = self.__RemoveDevice(devToGo[0]) if devToGo else []
        self.iLock.release()
        if devToGo:
            self.__NotifyRemoved(observers, devToGo[0], 'NOTIFY EXPIRED')

    def __RemoveDevice(self, aDevice):
        """Remove device from list, cancel notification timer. Caller must hold
            iLock. Returns the observers to notify once the lock is released."""
        uuid = aDevice.Uuid()

        if uuid in self.timerDict:
            # Cancel notification timer
            timer = self.timerDict[uuid]
            timer.cancel()
            del self.timerDict[uuid]

        self.iDeviceList.remove(aDevice)

        if uuid in self.iDescList:
            # Device is currently retrieving its description files
            self.iDescList.remove( uuid )

        return list(self.iDiscoverObs)

    def __NotifyRemoved(self, aObservers, aDevice, aReason):
        "Inform observers of device removal - call without holding iLock"
        toRemove = [ obs for obs in aObservers if obs.DeviceRemoved(aDevice, aReason) ]
        if toRemove:
            self.iLock.acquire()
            for obs in toRemove:
                if obs in self.iDiscoverObs:
                    self.iDiscoverObs.remove(obs)
            self.iLock.release()

        
class InvalidPacket(Exception):
    def __init__(self, aPacket):
        self.iPacket = aPacket
    def __str__(self):
        return 'Invalid discovery packet:\n' + str(self.iPacket) + '\n'


class Packet:
    """A base class for packets received from a device as part of the
        discovery phase."""
    kTypeRootDevice = 0
    kTypeUuid = 1
    kTypeDeviceType = 2
    kTypeServiceType = 3

    def __init__(self, aPkt):
        self.iType = None
        self.iTypeString = None
        self.iUuid = None
        self.iDevType = None
        self.iDevTypeVer = None
        self.iServType = None
        self.iServTypeVer = None

    def Uuid(self):
        return self.iUuid

    def Type(self):
        return self.iType

    def TypeString(self):
        return self.iTypeString

    def DeviceType(self):
        return self.iDevType

    def DeviceTypeVersion(self):
        return self.iDevTypeVer

    def ServiceType(self):
        return self.iServType

    def ServiceTypeVersion(self):
        return self.iServTypeVer

    def ParseTypeHeaders(self, aPkt, aTypeHeader, aUsn):
        m1 = re.match('upnp:rootdevice', aTypeHeader)
        m2 = re.match('uuid:(.*)::upnp:rootdevice', aUsn)
        if m1 and m2:
            self.iType = Packet.kTypeRootDevice
            self.iTypeString = aTypeHeader
            self.iUuid = m2.group(1)
            return

        m1 = re.match('uuid:(.*)', aTypeHeader)
        m2 = re.match('uuid:(.*)', aUsn)
        if m1 and m2:
            self.iType = Packet.kTypeUuid
            self.iTypeString = aTypeHeader
            self.iUuid = m2.group(1)
            return

        m1 = re.match('urn:(.*):device:(.*):(.*)', aTypeHeader)
        m2 = re.match('uuid:(.*)::urn:(.*):device:(.*):(.*)', aUsn)
        if m1 and m2:
            self.iType = Packet.kTypeDeviceType
            self.iTypeString = aTypeHeader
            self.iUuid = m2.group(1)
            self.iDevType = 'urn:' + m1.group(1) + ':device:' + m1.group(2)
            self.iDevTypeVer = m1.group(3)
            return

        m1 = re.match('urn:(.*):service:(.*):(.*)', aTypeHeader)
        m2 = re.match('uuid:(.*)::urn:(.*):service:(.*):(.*)', aUsn)
        if m1 and m2:
            self.iType = Packet.kTypeServiceType
            self.iTypeString = aTypeHeader
            self.iUuid = m2.group(1)
            self.iServType = 'urn:' + m1.group(1) + ':service:' + m1.group(2)
            self.iServTypeVer = m1.group(3)
            return

        raise InvalidPacket(aPkt)


class PacketSearchResponse(Packet):
    """A class to parse a M-SEARCH response packet."""
    def __init__(self, aPkt):
        """Initialise and parse the packet headers to extract the required info."""
        Packet.__init__(self, aPkt)
        self.iExpire = None
        self.iLocation = None
        self.iServer = None

        # CACHE-CONTROL is a required header
        cache = aPkt.Header('CACHE-CONTROL')
        if cache == None:
            raise InvalidPacket(aPkt)
        m = re.match( r'.*max-age\s*=\s*([0-9]+)', cache )
        if m == None or m.group(1) == None:
            raise InvalidPacket(aPkt)
        self.iExpire = int(m.group(1))

        # EXT is a required header
        ext = aPkt.Header('EXT')
        if ext == None:
            raise InvalidPacket(aPkt)

        # LOCATION is a required header
        self.iLocation = aPkt.Header('LOCATION')
        if self.iLocation == None:
            raise InvalidPacket(aPkt)

        # SERVER is a required header
        self.iServer = aPkt.Header('SERVER')
        if self.iServer == None:
            raise InvalidPacket(aPkt)

        # Parse type headers
        st = aPkt.Header('ST')
        if st == None:
            raise InvalidPacket(aPkt)
        usn = aPkt.Header('USN')
        if usn == None:
            raise InvalidPacket(aPkt)
        self.ParseTypeHeaders(aPkt, st, usn)

    def ExpireTime(self):
        return self.iExpire

    def Location(self):
        return self.iLocation

    def Server(self):
        return self.iServer


class PacketNotify(Packet):
    """A class to parse an SSDP notify packet."""
    def __init__(self, aPkt):
        """Initialise and parse the packet headers to extract the required info."""
        Packet.__init__(self, aPkt)
        self.iIsAlive = None
        self.iExpire = None
        self.iLocation = None
        self.iServer = None
        
        # HOST is a required header for alive and byebye
        host = aPkt.Header('HOST')
        if host == None or host != '239.255.255.250:1900':
            raise InvalidPacket(aPkt)

        # Parse type headers
        nt = aPkt.Header('NT')
        if nt == None:
            raise InvalidPacket(aPkt)
        usn = aPkt.Header('USN')
        if usn == None:
            raise InvalidPacket(aPkt)
        self.ParseTypeHeaders(aPkt, nt, usn)

        # parse NTS header for alive and byebye
        nts = aPkt.Header('NTS')
        if nts == None:
            raise InvalidPacket(aPkt)

        if nts == 'ssdp:alive':
            self.iIsAlive = True

            # CACHE-CONTROL is a required header
            cache = aPkt.Header('CACHE-CONTROL')
            if cache == None:
                raise InvalidPacket(aPkt)
            m = re.match( r'.*max-age\s*=\s*([0-9]+)', cache )
            if m == None or m.group(1) == None:
                raise InvalidPacket(aPkt)
            self.iExpire = int(m.group(1))

            # LOCATION is a required header
            self.iLocation = aPkt.Header('LOCATION')
            if self.iLocation == None:
                raise InvalidPacket(aPkt)

            # SERVER is a required header
            self.iServer = aPkt.Header('SERVER')
            if self.iServer == None:
                raise InvalidPacket(aPkt)

        elif nts == 'ssdp:byebye':
            self.iIsAlive = False

        else:
            raise InvalidPacket(aPkt)

    def IsAlive(self):
        return self.iIsAlive

    def ExpireTime(self):
        return self.iExpire

    def Location(self):
        return self.iLocation

    def Server(self):
        return self.iServer
