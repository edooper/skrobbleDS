"""Scrobbler.py - Scrobble handler for SkrobbleDs

Copyright (c) Rockfather 2012, edooper 2026
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""
import threading
import queue
import LastFm
import EventBus
import Constants

class Scrobbler:
    """Handles scrobbling logic and now-playing updates for Last.fm"""
    
    def __init__(self, settings, logger, db, lastfm=None):
        """Initialise class data, start scrobbling and now-playing monitors.
           `lastfm` is injectable so tests need no on-disk credentials."""
        self.settings = settings
        self.log = logger.log
        self.shutdown_flag = False
        self.lastfm = lastfm if lastfm is not None else LastFm.LastFm(logger)
        self.scrobble_q = queue.Queue()
        self.now_playing_q = queue.Queue()
        self.db = db
        
        # Subscribe to EventBus
        self.bus = EventBus.EventBus()
        self.bus.subscribe('scrobble', self._on_scrobble_event)
        self.bus.subscribe('now_playing', self._on_now_playing_event)
        
        # Prime the retry chain with a single cached scrobble - the rest stay
        # in the database until needed. Draining the whole cache into memory
        # would defeat its purpose: it exists to survive a restart, and an
        # in-memory backlog dies with the process (A4). Each success pops the
        # next one, and the queue timeout below sweeps up any remainder.
        cache_size = self.db.get_cache_size()
        if cache_size > 0:
            self.log(f'Scrobbler: {cache_size} cached scrobbles pending retry')
            item = self.db.pop_from_cache()
            if item:
                self.scrobble_q.put(item)


        self.scrobble_thread = threading.Thread(target=self._scrobble_loop, daemon=True)
        self.now_playing_thread = threading.Thread(target=self._now_playing_loop, daemon=True)
        self.scrobble_thread.start()
        self.now_playing_thread.start()
        
    def shutdown(self):
        """Cleanly shutdown the scrobbler"""
        self.bus.unsubscribe('scrobble', self._on_scrobble_event)
        self.bus.unsubscribe('now_playing', self._on_now_playing_event)
        self.shutdown_flag = True
        self.scrobble_q.put({'player': 'bye'})
        self.now_playing_q.put({'player': 'bye'})
        self.scrobble_thread.join()
        self.now_playing_thread.join()

    def _on_scrobble_event(self, info):
        """Callback for scrobble events from the bus"""
        self.scrobble_q.put(info)

    def _on_now_playing_event(self, info):
        """Callback for now_playing events from the bus"""
        self.now_playing_q.put(info)
        
    def _scrobble_loop(self):
        """Background loop for submitting scrobbles to Last.fm"""
        # Terminates on the 'bye' sentinel, which shutdown() enqueues last so
        # that scrobbles already queued are still submitted, not dropped
        while True:
            try:
                info = self.scrobble_q.get(timeout=300)
            except queue.Empty:
                if self.shutdown_flag:
                    break
                # Periodically check for cached scrobbles to retry
                cached = self.db.pop_from_cache()
                if cached:
                    self.scrobble_q.put(cached)
                continue
            if not info or not info.get('player'):
                continue
            if info.get('player') == 'bye':
                break
            # These threads are daemons: an unhandled exception would end all
            # scrobbling silently while the process carried on looking healthy
            try:
                self._handle_scrobble(info)
            except Exception as e:
                self.log(f'Scrobbler: error handling scrobble: {type(e).__name__}: {e}')

    def _handle_scrobble(self, info):
        """Apply the Last.fm scrobble rules to one queued track and submit it"""
        if info['player'] not in self.settings.get_players():
            return

        # Never submit a scrobble without a track/artist - Last.fm would store
        # a blank entry. Guards against a track change that fired with no
        # metadata. Checked *before* the message below, which indexes the
        # very keys this guard exists because they may be missing.
        if not (info.get('title') and info.get('artist')):
            return
        if not info.get('playing'):
            return

        duration = info.get('duration', 0)
        album = info.get('album', '')
        info_msg = f"{info['title']} by {info['artist']} from {album} ({duration}s)"

        if duration <= Constants.SCROBBLE_MIN_DURATION:
            self.log(f"{info['player']}: NO scrobble (track duration too short) {info_msg}")
            return

        play_time = self._calculate_play_time(info)
        if not (play_time > duration * Constants.SCROBBLE_PERCENT_THRESHOLD
                or play_time > Constants.SCROBBLE_TIME_THRESHOLD):
            self.log(f"{info['player']}: NO scrobble (playtime {play_time}s) {info_msg}")
            return

        sk = self.settings.get_session_key(info['player'])
        self.log(f"{info['player']}: Submitting scrobble -> {info_msg}")
        resp = self.lastfm.track_scrobble(
            sk, info['title'], info['artist'], album,
            info.get('tracknum', ''), duration, int(info['playing'][0])
        )

        if resp is not None:
            self.log(f"{info['player']}: Scrobble accepted -> {info_msg}")
            self.db.add_to_history(info)
            if self.db.get_cache_size() > 0:
                self.scrobble_q.put(self.db.pop_from_cache())
        else:
            self.log(f"{info['player']}: FAILED scrobbling -> {info_msg}")
            self.db.add_to_cache(info)

    def _now_playing_loop(self):
        """Background loop for updating 'Now Playing' status on Last.fm"""
        while True:
            info = self.now_playing_q.get()
            if not info or not info.get('player'):
                continue
            if info.get('player') == 'bye':
                break
            try:
                self._handle_now_playing(info)
            except Exception as e:
                self.log(f'Scrobbler: error handling now playing: {type(e).__name__}: {e}')

    def _handle_now_playing(self, info):
        """Submit one 'Now Playing' update if the track is currently running"""
        if info['player'] not in self.settings.get_players():
            return

        artist = info.get('artist')
        title = info.get('title')
        duration = info.get('duration')
        if not (artist and title and duration):
            return

        # Only announce a track that is actually playing now: it must have
        # started, and not have been stopped since it last started
        if not info.get('playing'):
            return
        if info.get('stopped') and info['stopped'][-1] >= info['playing'][-1]:
            return

        info_msg = f"-> {artist} - {title} ({duration}s)"
        sk = self.settings.get_session_key(info['player'])
        self.log(f"{info['player']}: Submitting now playing {info_msg}")
        resp = self.lastfm.track_update_now_playing(sk, title, artist, duration)

        if resp is not None:
            self.log(f"{info['player']}: Now playing accepted {info_msg}")
        else:
            self.log(f"{info['player']}: FAILED now playing {info_msg}")

    def _calculate_play_time(self, info):
        """Calculate total playback time for a track in seconds"""
        play_time = 0
        playing_times = info.get('playing', [])
        stopped_times = info.get('stopped', [])
        stop_idx = 0

        for p in playing_times:
            # Advance past any stop events that occurred before this play event
            while stop_idx < len(stopped_times) and stopped_times[stop_idx] <= p:
                stop_idx += 1
            # If there's a matching stop event, consume it
            if stop_idx < len(stopped_times):
                play_time += stopped_times[stop_idx] - p
                stop_idx += 1
        return play_time