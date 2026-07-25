"""Player.py - interface to DS players for SkrobbleDs

Copyright (c) Rockfather 2012, edooper 2026
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""
import copy
import threading
import time
import re
import xml.etree.ElementTree as ET
import Upnp.EventServer as EventServer
import Upnp.EventSub as EventSub
import Upnp.NetUtil as NetUtil
import EventBus
import Constants


def _blank_track(stopped=None):
    """A track record with no metadata yet. One definition, so a new field
       cannot be added to some resets and missed in others."""
    return {
        'playing': [],
        'stopped': list(stopped) if stopped else [],
        'duration': 0,
        'player': '',
        'artist': '',
        'title': '',
        'album': '',
        'tracknum': ''
    }


def _blank_meta():
    """Empty parsed-metadata record"""
    return {'title': '', 'artist': '', 'album': '', 'tracknum': '', 'duration': 0}


class Player:
    """Interface to OpenHome compliant player to scrobble to Last.fm"""
    
    def __init__(self, device, settings, logger):
        """Initialise class data and subscribe to UPnP events"""
        self.dev = device
        self.settings = settings
        self.log = logger.log
        self.bus = EventBus.EventBus()
        self._lock = threading.RLock()
        self.update_meta_timer = None
        self.play_status_timer = None
        self.stop_scrobble_timer = None
        self.is_playing = False
        self.current = _blank_track()
        self.duration = 0
        self.meta = {}
        self.current_uri = ''
        self.subscriptions = []
        self.event_server = None

        for service in self.dev.ServiceList():
            # support both Cara and Davaar families
            s_type = service.Type()
            if s_type in ('urn:av-openhome-org:service:Info:1', 'urn:linn-co-uk:service:Info:1'):
                sub = self.subscribe(service, self._on_info_event)
            elif s_type in ('urn:av-openhome-org:service:Playlist:1', 'urn:linn-co-uk:service:Ds:1'):
                sub = self.subscribe(service, self._on_playlist_event)
            else:
                continue
            if sub is not None:
                self.subscriptions.append(sub)

    def shutdown(self):
        """Scrobble outstanding track and unsubscribe from UPnP events"""
        with self._lock:
            self.current['stopped'].append(time.time())
            if self.play_status_timer:
                self.play_status_timer.cancel()
            if self.update_meta_timer:
                self.update_meta_timer.cancel()
            if self.stop_scrobble_timer:
                self.stop_scrobble_timer.cancel()

            # Scrobble only - announcing 'now playing' while quitting is
            # meaningless, and the Scrobbler discarded it anyway because the
            # stop above post-dates the last play
            if self.current.get('title') and self.current.get('artist'):
                self.bus.emit('scrobble', info=copy.deepcopy(self.current))

        for sub in self.subscriptions:
            sub.Unsubscribe()
        self.subscriptions = []
        if self.event_server is not None:
            self.event_server.Stop()
            self.event_server = None

    def _get_event_server(self):
        """Return the event server shared by this player's subscriptions,
           starting it on first use"""
        if self.event_server is None:
            device_location = self.dev.Location()
            m = re.match(r'http://([^:/]+)', device_location)
            device_ip = m.group(1) if m else None
            if_addr = NetUtil.get_local_ip(self.settings.get_host(), device_ip)
            self.event_server = EventServer.EventServer(if_addr)
            self.event_server.Start()
        return self.event_server

    def subscribe(self, service, callback):
        """Subscribe to UPnP events on specified service.
           Returns the subscription, or None if subscribing failed."""
        subscription = EventSub.EventSub(self._get_event_server(), self.log)
        subscription.SetListener(EventListen(callback))
        if subscription.Subscribe(service):
            return subscription
        return None
        
    def _on_info_event(self, name, value, seq):
        """Callback on Info service event"""
        with self._lock:
            if name == 'Duration':
                self.duration = int(value)
            elif name == 'Metadata':
                self._parse_metadata(value)
                # Metadata can arrive after the update_meta_timer already
                # fired (e.g. Duration lands first on a fast track change);
                # resync so a late title/artist isn't lost or left stale.
                if self.is_playing and self.meta.get('title') != self.current.get('title'):
                    if self.update_meta_timer:
                        self.update_meta_timer.cancel()
                        self.update_meta_timer = None
                    self._update_meta()
            elif name == 'Uri':
                # The Uri is the reliable per-track identity. A genuine track
                # change is a new, different, non-empty Uri. TrackCount is NOT
                # used: at an album boundary the device fires it twice for the
                # same track (before the Uri/Metadata arrive), which would
                # otherwise wipe the first track's freshly-delivered metadata.
                if value and value != self.current_uri:
                    self.current_uri = value
                    self._on_track_change()

    def _on_track_change(self):
        """Handle a track boundary (a new Uri): scrobble the outgoing track and
           reset state for the incoming one. Caller must hold self._lock."""
        self.log(f'[DEBUG] {self.name}: Track change event detected')
        if self.update_meta_timer:
            self.update_meta_timer.cancel()
        if self.stop_scrobble_timer:
            self.stop_scrobble_timer.cancel()
            self.stop_scrobble_timer = None

        self.current['stopped'].append(time.time())
        # Only scrobble a real track: the outgoing track may have no metadata
        # yet (blank title/artist), which must never be submitted
        if self.current.get('title') and self.current.get('artist'):
            self.bus.emit('scrobble', info=copy.deepcopy(self.current))

        self.current = _blank_track()
        # Prevent the previous track's metadata from being copied into this
        # track if its Metadata event hasn't arrived yet
        self.meta = _blank_meta()
        # Reset the fallback duration too so a stale Duration event can't leak
        # into the next track if its DIDL omits one
        self.duration = 0
        if self.is_playing:
            self.current['playing'].append(time.time())
        else:
            self.current['stopped'].append(time.time())

        self.update_meta_timer = threading.Timer(Constants.PLAYER_METADATA_UPDATE_DELAY, self._update_meta)
        self.update_meta_timer.daemon = True
        self.update_meta_timer.start()

    def _parse_metadata(self, xml_val):
        """Parse DIDL-Lite metadata XML"""
        new_meta = _blank_meta()
        if not xml_val:
            self.meta = new_meta
            return

        try:
            tree = ET.fromstring(xml_val)
            ns = {
                'didl': 'urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/',
                'dc': 'http://purl.org/dc/elements/1.1/',
                'upnp': 'urn:schemas-upnp-org:metadata-1-0/upnp/'
            }
            item = tree.find('.//didl:item', ns)
            if item is not None:
                title_elem = item.find('dc:title', ns)
                if title_elem is not None:
                    new_meta['title'] = title_elem.text or ''

                artists = item.findall('upnp:artist', ns)
                for artist in artists:
                    if artist.attrib.get('role', '').lower() == 'performer':
                        new_meta['artist'] = artist.text or ''
                        break
                if not new_meta['artist'] and artists:
                    new_meta['artist'] = artists[0].text or ''

                album_elem = item.find('upnp:album', ns)
                if album_elem is not None:
                    new_meta['album'] = album_elem.text or ''

                track_elem = item.find('upnp:originalTrackNumber', ns)
                if track_elem is not None:
                    new_meta['tracknum'] = track_elem.text or ''

                # Prefer the duration carried in the DIDL <res> element: it is
                # atomic with the title/artist, unlike the separate Info
                # 'Duration' event which can lag by a track on fast (gapless)
                # track changes and cause the wrong scrobble decision.
                for res in item.findall('didl:res', ns):
                    dur = self._parse_didl_duration(res.attrib.get('duration'))
                    if dur:
                        new_meta['duration'] = dur
                        break
        except ET.ParseError as e:
            self.log(f'[DEBUG] {self.name}: Failed to parse metadata XML: {e}')

        self.meta = new_meta

    @staticmethod
    def _parse_didl_duration(value):
        """Convert a DIDL-Lite res duration ('H:MM:SS.mmm') to whole seconds.
           Returns 0 if absent or unparseable."""
        if not value:
            return 0
        try:
            parts = value.split(':')
            if len(parts) != 3:
                return 0
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + int(float(seconds))
        except (ValueError, AttributeError):
            return 0

    def _on_playlist_event(self, name, value, seq):
        """Callback on Playlist service event"""
        with self._lock:
            if name == 'TransportState':
                if value == 'Playing':
                    self.log(f'[DEBUG] {self.name}: Playback started')
                    self.is_playing = True
                    self.current['playing'].append(time.time())
                    if self.stop_scrobble_timer:
                        self.stop_scrobble_timer.cancel()
                        self.stop_scrobble_timer = None
                    if self.play_status_timer:
                        self.play_status_timer.cancel()
                    self.play_status_timer = threading.Timer(Constants.PLAYER_PLAYBACK_STATUS_DELAY, self._update_play_status)
                    self.play_status_timer.daemon = True
                    self.play_status_timer.start()
                else:
                    self.log(f'[DEBUG] {self.name}: Playback {value.lower()}')
                    self.is_playing = False
                    self.current['stopped'].append(time.time())
                    if value == 'Stopped':
                        # Scrobble the finished track promptly rather than
                        # waiting for the next track change or app shutdown.
                        # Paused is excluded: a paused track may resume and is
                        # scrobbled on its track-change event
                        if self.stop_scrobble_timer:
                            self.stop_scrobble_timer.cancel()
                        self.stop_scrobble_timer = threading.Timer(Constants.PLAYER_STOP_SCROBBLE_DELAY, self._on_stopped)
                        self.stop_scrobble_timer.daemon = True
                        self.stop_scrobble_timer.start()

    def _on_stopped(self):
        """Scrobble the current track after playback stopped - triggered by the stop timer"""
        with self._lock:
            if self.is_playing:
                return
            if self.current.get('title') and self.current.get('artist'):
                self.log(f'[DEBUG] {self.name}: Playback stopped - scrobbling last track')
                self.bus.emit('scrobble', info=copy.deepcopy(self.current))
            # Mark the track consumed so a later track change or shutdown
            # doesn't scrobble it again
            self.current = _blank_track(stopped=[time.time()])

    def _update_meta(self):
        """Copy freshly-parsed metadata onto the current track - triggered by
           the metadata timer after a track change, or directly when a late
           Metadata event arrives"""
        with self._lock:
            if 'title' in self.meta:
                # Prefer the DIDL duration (atomic with the title); fall back to
                # the separate Info 'Duration' event only if the DIDL omitted it
                duration = self.meta.get('duration') or self.duration
                self.current['player'] = self.name
                self.current['duration'] = duration
                self.current['title'] = self.meta['title']
                self.current['artist'] = self.meta['artist']
                self.current['album'] = self.meta['album']
                self.current['tracknum'] = self.meta['tracknum']
                self.log(f"[DEBUG] {self.name}: Track metadata received -> {self.meta['artist']} - {self.meta['title']} ({duration}s)")
                if self.is_playing:
                    if self.play_status_timer:
                        self.play_status_timer.cancel()
                    self._update_play_status()

    def _update_play_status(self):
        """Announce the current track as now playing - triggered by the play
           status timer, or directly once metadata arrives while playing"""
        with self._lock:
            self.bus.emit('now_playing', info=copy.deepcopy(self.current))
            
    @property
    def device(self):
        return self.dev
    
    @property
    def name(self):
        return self.device.FriendlyName()



class EventListen(EventSub.EventListener):
    """Event Listener class - handles incoming UPnP events"""
    
    def __init__(self, callback):
        self.callback = callback
    
    def Event(self, name, value, seq):
        if self.callback:
            self.callback(name, value, seq)
