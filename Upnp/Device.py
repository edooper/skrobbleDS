import re
import http.client as httplib
import socket
import xml.etree.ElementTree as etree
from . import Service
from threading import Thread
import traceback
import sys
import io
from . import HttpConnection


class DescriptionRetriever(Thread):
    """A thread object that is dispatched to retrieve the device and service description
        XML files from a device."""

    def __init__(self, aUuid, aLocation, aDiscovery):
        Thread.__init__(self, daemon=True)
        self.iUuid = aUuid
        self.iLocation = aLocation
        self.iDiscovery = aDiscovery
        self.iDevice = None
        self.iConn = None

    def Uuid(self):
        return self.iUuid

    def Device(self):
        return self.iDevice

    def Start(self):
        self.start()

    def Stop(self):
        if self.iConn != None:
            self.iConn.close()

    def GetXmlDescription(self, aLocation):
        # Parse the URL for the host address:port and the resource name
        m = re.match('http://([^/]*)(.*$)', aLocation)
        host = m.group(1)
        relUrl = m.group(2)
    
        # Open a connection and request the resource
        headers = {'HOST': host}
        self.iConn = HttpConnection.HttpConnection(host, timeout=15)
        self.iConn.request('GET', relUrl, '', headers)    # blocks until socket times out
        resp = self.iConn.getresponse()
        descXml = resp.read()
        self.iConn.close()
        self.iConn = None
        return descXml

    def RetrieveServiceDescs(self, aDevice):
        for serv in aDevice.ServiceList():
            xmlDesc = self.GetXmlDescription(serv.ScpdUrl())
            serv.ParseXmlDesc(xmlDesc)
        for dev in aDevice.DeviceList():
            self.RetrieveServiceDescs(dev)

    def run(self):
        try:
            # Retrieve the device and service descriptions and notify the discovery object
            # when done
            devDescXml = self.GetXmlDescription(self.iLocation)
            rootDev = RootDevice(devDescXml, self.iLocation)
            self.RetrieveServiceDescs(rootDev.Device())
            self.iDevice = rootDev.Device().FindDevice(self.iUuid)
            self.iDiscovery.DeviceDescriptionDone( self.iUuid, self.iDevice )

        except Exception as e:
            strObj = io.StringIO()
            strObj.write( 'Device description failed...' )
            strObj.write( str(e) )
            traceback.print_tb(sys.exc_info()[2], None, strObj)
            print(strObj.getvalue())  # Print the error for debugging
            strObj.close()
            self.iDiscovery.DeviceDescriptionFailed( self.iUuid )


class RootDevice:
    def __init__(self, aDevDescXml, aLocation):
        self.iLocation = aLocation
        self.iUrlBase = None
        self.iDevice = None
        
        root = etree.fromstring( aDevDescXml )
        ns   = root.tag[1:].split('}')[0]

        # URLBase
        urlBase = root.find( '{%s}URLBase' % (ns) )
        if urlBase is not None and urlBase.text:
            self.iUrlBase = urlBase.text
        else:
            m = re.match('http://([^/]*)(.*$)', aLocation)
            self.iUrlBase = 'http://' + m.group(1)
        # Strip off any trailing '/'
        m = re.match( '(.*?)(/*$)', self.iUrlBase )
        if m:
            self.iUrlBase = m.group(1)

        # create the root device
        device = root.find( '{%s}device' % (ns) )
        self.iDevice = Device( device, ns, self )

    def Location(self):
        return self.iLocation

    def SetLocation(self, aLocation):
        self.iLocation = aLocation

    def UrlBase(self):
        return self.iUrlBase

    def Device(self):
        return self.iDevice


class Device:
    """A class representing a UPnP device."""

    def __init__(self, aDevElem, aDevNs, aRootDevice):
        self.iRootDevice = aRootDevice
        self.iServiceList = []
        self.iDeviceList = []

        # deviceType
        try:
            self.iType = aDevElem.find( '{%s}deviceType' % (aDevNs) ).text or ''
        except (AttributeError, TypeError):
            self.iType = ''

        # UDN
        try:
            self.iUuid = aDevElem.find( '{%s}UDN' % (aDevNs) ).text or ''
            if self.iUuid[0:5] == "uuid:":
                self.iUuid = self.iUuid[5:]
        except (AttributeError, TypeError):
            self.iUuid = ''

        # friendlyName
        try:
            self.iFriendlyName = aDevElem.find( '{%s}friendlyName' % (aDevNs) ).text or ''
        except (AttributeError, TypeError):
            self.iFriendlyName = ''

        # serviceList
        serviceList = aDevElem.find( '{%s}serviceList' % (aDevNs) )
        if serviceList is not None:
            for service in serviceList:
                newServ = Service.Service( self, service, aDevNs )
                self.iServiceList.append( newServ )
        
        # deviceList
        deviceList = aDevElem.find( '{%s}deviceList' % (aDevNs) )
        if deviceList:
            for device in deviceList:
                newDev = Device( device, aDevNs, aRootDevice )
                self.iDeviceList.append( newDev )
        
        # presentationUrl
        try:
            self.iPresentationUrl = aDevElem.find( '{%s}presentationURL' % (aDevNs) ).text or ''
        except (AttributeError, TypeError):
            self.iPresentationUrl = ''
        
    def __str__(self):
        devStr  = 'DEVICE:\r\n'
        devStr += 'UUID        : ' + self.Uuid() + '\r\n'
        devStr += 'DEV DESC URL: ' + self.Location() + '\r\n'
        devStr += 'URL BASE    : ' + self.UrlBase() + '\r\n'
        for serv in self.iServiceList:
            devStr += str(serv)
        devStr += '\r\n'
        return devStr

    def Uuid(self):
        return self.iUuid

    def Location(self):
        return self.iRootDevice.Location()

    def UrlBase(self):
        return self.iRootDevice.UrlBase()

    def Type(self):
        return self.iType

    def FriendlyName(self):
        return self.iFriendlyName

    def PresentationUrl(self):
        return self.iPresentationUrl

    def SetLocation(self, aLocation):
        self.iRootDevice.SetLocation(aLocation)

    def Service(self, aServId):
        for serv in self.iServiceList:
            if aServId == serv.Id():
                return serv
        return None

    def ServiceList(self):
        return self.iServiceList

    def DeviceList(self):
        return self.iDeviceList

    def FindDevice(self, aUuid):
        if aUuid == self.iUuid:
            return self
        for dev in self.iDeviceList:
            found = dev.FindDevice(aUuid)
            if found != None:
                return found
        return None
