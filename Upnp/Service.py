
class Service:
    """Info for a particular service - namely the stuff contained in the XML description files.

    Only the fields carried in the *device* description are held. The separate
    per-service SCPD file (actions, state variables) is never fetched: nothing
    in SkrobbleDs drives the devices, it only subscribes to their events, for
    which the event-subscription URL is enough."""

    def __init__( self, aParentDevice, aServElem, aServNs ):
        self.iParentDevice = aParentDevice

        self.iType       = aServElem.find( '{%s}serviceType' % (aServNs) ).text
        self.iId         = aServElem.find( '{%s}serviceId' % (aServNs) ).text
        self.iScpdUrl    = aServElem.find( '{%s}SCPDURL' % (aServNs) ).text
        self.iControlUrl = aServElem.find( '{%s}controlURL' % (aServNs) ).text
        eventSubElem = aServElem.find( '{%s}eventSubURL' % (aServNs) )
        self.iEventSubUrl = eventSubElem.text if eventSubElem is not None else None

        # Make sure the relative URLs have a '/' at the front
        if self.iScpdUrl[0:7] != "http://":
            if self.iScpdUrl[0] != '/':
                self.iScpdUrl = self.iParentDevice.UrlBase() + '/' + self.iScpdUrl
            else:
                self.iScpdUrl = self.iParentDevice.UrlBase() + self.iScpdUrl

        if self.iControlUrl[0:7] != "http://":
            if self.iControlUrl[0] != '/':
                self.iControlUrl = self.iParentDevice.UrlBase() + '/' + self.iControlUrl
            else:
                self.iControlUrl = self.iParentDevice.UrlBase() + self.iControlUrl

        if self.iEventSubUrl and self.iEventSubUrl[0:7] != "http://":
            if self.iEventSubUrl[0] != '/':
                self.iEventSubUrl = self.iParentDevice.UrlBase() + '/' + self.iEventSubUrl
            else:
                self.iEventSubUrl = self.iParentDevice.UrlBase() + self.iEventSubUrl

    def __str__(self):
        servStr  = '\t' + 'SERVICE:\r\n'
        servStr += '\t' + 'TYPE       : ' + self.iType + '\r\n'
        servStr += '\t' + 'ID         : ' + self.iId + '\r\n'
        servStr += '\t' + 'SCPD URL   : ' + self.ScpdUrl() + '\r\n'
        servStr += '\t' + 'CONTROL URL: ' + self.ControlUrl() + '\r\n'
        if self.iEventSubUrl:
            servStr += '\t' + 'EVENT URL  : ' + self.EventSubUrl() + '\r\n'
        return servStr

    def Type(self):
        return self.iType

    def Id(self):
        return self.iId

    def ScpdUrl(self):
        return self.iScpdUrl

    def ControlUrl(self):
        return self.iControlUrl

    def EventSubUrl(self):
        return self.iEventSubUrl
