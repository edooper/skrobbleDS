from . import EventServer
import re
import threading
import xml.etree.ElementTree as etree
from . import HttpConnection


class EventListener:
    """An interface for listening to events."""

    def Event(self, aSvName, aSvVal, aSvSeq):
        pass


class EventSub(EventServer.EventObserver):
    """A class for a UPnP service subscription."""

    def __init__(self, aEventServer, aLog):
        self.iSubId       = None
        self.iEventServer = aEventServer
        self.iService     = None
        self.iListener    = None
        self.iRequestTimeout = 1800
        self.iActualTimeout = 0
        self.iTimer = None
        self.iTimedOut = False
        # Guards iSubId/iService/iTimer, which are touched from the caller's
        # thread (Subscribe/Unsubscribe) and from renewal Timer threads
        self.iLock = threading.RLock()
        self.log = aLog

    def SetListener(self, aListener):
        self.iListener = aListener

    def SubId(self):
        """Return the subscription ID (SID) of the observer. The subject in the observer pattern will use
            this to determine which observer gets notified."""
        return self.iSubId

    def SetRequestTimeout(self, aTimeout):
        self.iRequestTimeout = aTimeout

    def RequestTimeout(self):
        return self.iRequestTimeout

    def ActualTimeout(self):
        return self.iActualTimeout

    def Notify(self, aSeq, aXmlBody):
        """Called when an event happens."""
        # This XML should take the form
        #
        # <propertyset>
        #    <property>
        #        <svTag>svVal</svTag>
        #    </property>
        #    ...
        # </propertyset>
        #
        # i.e. each <property>...</property> node has 1 child (<svTag>...</svTag>)
        #        each <svTag>...</svTag> node has 1 child which is the value of the SV
        #
        try:
            body = etree.fromstring( aXmlBody )
        except Exception as e:
            self.log('[DEBUG] Failed to parse event body for SID %s: %s' % (self.iSubId, e))
            return

        properties = body.iter( '{urn:schemas-upnp-org:event-1-0}property' )
        for property in properties:
            elements = list(property.iter())
            if len(elements) < 2:
                # <property/> without a state-variable child - ignore
                continue
            svName   = elements[1].tag
            svVal    = elements[1].text
            if svVal == None:
                svVal = ''

            # Notify derived classes
            if self.iListener:
                self.iListener.Event(svName, svVal, aSeq)

    def _http_request(self, aMethod, aHeaders, aTimeout):
        """Send an eventing request to the service host. Returns the response
            (already read) or None on connection failure."""
        m = re.match( 'http://([^/]*)(.*$)', self.iService.EventSubUrl() )
        publisherHost   = m.group(1)
        publisherRelURL = m.group(2)
        aHeaders['HOST'] = publisherHost
        conn = HttpConnection.HttpConnection( publisherHost, timeout=aTimeout )
        try:
            conn.request( aMethod, publisherRelURL, '', aHeaders )
            resp = conn.getresponse()
            resp.read()
            return resp
        finally:
            conn.close()

    def _parse_timeout_header(self, aResp):
        """Extract the subscription timeout from a response, e.g. 'Second-1800'"""
        timeout = aResp.getheader('TIMEOUT')
        try:
            return int(timeout[7:])
        except (TypeError, ValueError):
            return self.iRequestTimeout

    def _start_renew_timer(self, aDelay):
        """(Re)start the renewal timer - caller must hold iLock"""
        if self.iTimer != None:
            self.iTimer.cancel()
        self.iTimer = threading.Timer(aDelay, self.Renew)
        self.iTimer.daemon = True
        self.iTimer.start()

    def Subscribe(self, aService):
        """UPnP EVENTING PHASE - Subscribe to this services events.
            Returns True on success."""
        self.log( '%s subscribing to %s' %
            (aService.iParentDevice.FriendlyName(), aService.iType) )
        self.log( '[DEBUG] Callback URL: %s' % self.iEventServer.EventUrl() )
        if aService.EventSubUrl() == None:
            self.log( 'FAILED: %s No event subscription URL for %s' %
                (aService.iParentDevice.FriendlyName(), aService.iType) )
            return False

        with self.iLock:
            self.iService = aService
            self.iEventServer.Pause()
            try:
                headers = { 'CALLBACK': '<' + self.iEventServer.EventUrl() + '>',
                            'NT': 'upnp:event',
                            'TIMEOUT': 'Second-' + str(self.iRequestTimeout) }
                try:
                    resp = self._http_request('SUBSCRIBE', headers, aTimeout=2)
                except Exception as e:
                    self.log( 'FAILED: %s subscription error: %s' %
                        (aService.iParentDevice.FriendlyName(), str(e)) )
                    self.iService = None
                    return False

                if resp.status != 200:
                    self.log( 'FAILED: %s subscription failed with status %d' %
                        (aService.iParentDevice.FriendlyName(), resp.status) )
                    self.iService = None
                    self.iSubId   = None
                    return False

                sid = resp.getheader('SID')
                if sid == None:
                    self.log( 'FAILED: %s subscription response carried no SID' %
                        aService.iParentDevice.FriendlyName() )
                    self.iService = None
                    return False

                self.iSubId = sid
                self.iActualTimeout = self._parse_timeout_header(resp)
                self.log( 'SUCCESS: %s subscribed to %s (SID: %s, timeout: %ds)' %
                    (aService.iParentDevice.FriendlyName(), aService.iType,
                     self.iSubId[:16] + '...', self.iActualTimeout) )

                self._start_renew_timer(self.iActualTimeout*0.75)
                self.iEventServer.AddObserver(self)
                return True
            finally:
                self.iEventServer.Unpause()

    def Renew(self):
        """UPnP EVENTING PHASE - Renew a subscription to this services events."""
        resubscribeService = None
        with self.iLock:
            if not self.iService:
                return
            retry = self.iActualTimeout*0.75
            self.iEventServer.Pause()
            try:
                headers = { 'SID': self.iSubId,
                            'TIMEOUT': 'Second-' + str(self.iRequestTimeout) }
                resp = None
                try:
                    resp = self._http_request('SUBSCRIBE', headers, aTimeout=5)
                except Exception as e:
                    # Device unreachable - keep the subscription and retry later
                    pass

                if resp != None:
                    if resp.status == 200:
                        sid = resp.getheader('SID')
                        if sid != None:
                            self.iSubId = sid
                        self.iActualTimeout = self._parse_timeout_header(resp)
                        retry = self.iActualTimeout*0.75
                    else:
                        # Renewal rejected (e.g. device rebooted and forgot the
                        # SID) - resubscribe from scratch below
                        self.log( 'FAILED: [2] %s Bad response renewing event subscription for %s' %
                            (self.iService.iParentDevice.FriendlyName(), self.iService.iType) )
                        resubscribeService = self.iService
            finally:
                self.iEventServer.Unpause()

            if resubscribeService == None:
                self._start_renew_timer(retry)

        if resubscribeService != None:
            # Outside the pause window - Unsubscribe/Subscribe pause themselves
            self.Unsubscribe()
            self.Subscribe( resubscribeService )

    def Unsubscribe(self):
        """UPNP EVENTING PHASE - Unsubscribe from this services events."""
        with self.iLock:
            if not self.iService:
                return
            self.log( '%s unsubscribing from %s' %
                (self.iService.iParentDevice.FriendlyName(), self.iService.iType) )

            headers = { 'SID': self.iSubId }
            service = self.iService

            # Kill the subscription locally - even if the actual connection and
            # message fail later
            self.iSubId   = None
            self.iService = None
            self.iEventServer.RemoveObserver(self)
            if self.iTimer != None:
                self.iTimer.cancel()
            self.iTimer = None

            self.iEventServer.Pause()
            try:
                try:
                    self._service_unsubscribe(service, headers)
                except Exception as e:
                    pass
            finally:
                self.iEventServer.Unpause()

    def _service_unsubscribe(self, aService, aHeaders):
        """Send the UNSUBSCRIBE message for a service we no longer track"""
        m = re.match( 'http://([^/]*)(.*$)', aService.EventSubUrl() )
        publisherHost   = m.group(1)
        publisherRelURL = m.group(2)
        aHeaders['HOST'] = publisherHost
        conn = HttpConnection.HttpConnection( publisherHost, timeout=5 )
        try:
            conn.request( 'UNSUBSCRIBE', publisherRelURL, '', aHeaders )
            conn.getresponse().read()
        finally:
            conn.close()

    def Timeout(self):
        self.iTimedOut = True

    def Clear(self):
        """If the UPnP device has gone offline while the control point is subscribed, calling
            this function will reset the EventSub object for reuse."""
        with self.iLock:
            self.iSubId   = None
            self.iService = None
            self.iEventServer.RemoveObserver(self)
            if self.iTimer != None:
                self.iTimer.cancel()
            self.iTimer = None
