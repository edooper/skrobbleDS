#!/usr/bin/env python3

"""SkrobbleDs.py - Last.fm scrobbler from Linn DS players

Copyright (c) Rockfather 2016, edooper 2026
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""
import sys
import signal
import threading
import Upnp.Discovery as Discovery
import Logger
import Player
import Scrobbler
import Settings
import WebUi
import Database
import EventBus
import Constants

VERSION = '0.95.0'

class SkrobbleDs(Discovery.DiscoveryObserver):
    """Last.fm scrobbler for Linn DS players"""

    def __init__(self):
        """Initialise class data and startup scrobbler and UPnP discovery"""
        self.player_list = []
        self.list_mutex = threading.Lock()
        self._shutdown_once = threading.Event()
        self.logger = Logger.Logger()
        self.log = self.logger.log
        self.settings = Settings.Settings()
        self.db = Database.Database()
        
        # Initialize EventBus logger
        EventBus.EventBus().set_logger(self.logger)
        
        self.scrobbler = Scrobbler.Scrobbler(self.settings, self.logger, self.db)
        
        self.discovery = Discovery.Discovery(self.settings.get_host())
        self.discovery.AddObserver(self)
        self.discovery.Start(Constants.DEV_TYPE_SOURCE)  # Start() also runs the first M-SEARCH
        
        self.log(f'SkrobbleDs v{VERSION} started')
        self.webui = WebUi.WebUi(self.settings, self.player_list, self.shutdown, VERSION, self.db, self.logger)

    def run(self):
        """Serve the web UI - blocks until the process exits"""
        self.webui.start()

    def shutdown(self):
        """Shutdown SkrobbleDs and exit to OS"""
        if self._shutdown_once.is_set():
            return
        self._shutdown_once.set()

        self.log('Shutting down....')
        try:
            if self.discovery:
                self.discovery.RemoveObserver(self)
                self.discovery.Stop()
                self.discovery = None
        except Exception as e:
            self.log(f'Error during discovery shutdown: {e}')

        with self.list_mutex:
            players = list(self.player_list)
        for player in players:
            player.shutdown()

        self.scrobbler.shutdown()
        self.logger.shutdown()

    def DeviceDiscovered(self, device):
        """Callback on device discovery - add device to monitored players"""
        with self.list_mutex:
            player = self._find_player_in_list(device)
            if player is None:
                self.log(f'{device.FriendlyName()} joined network')
                player = Player.Player(device, self.settings, self.logger)
                self.player_list.append(player)

    def DeviceRemoved(self, device, reason):
        """Callback on device byebye/expiry - remove device from monitored players"""
        with self.list_mutex:
            player = self._find_player_in_list(device)
            if player is not None:
                self.log(f'{player.name} gone away ({reason})')
                self.player_list.remove(player)
                player.shutdown()

    def _find_player_in_list(self, device):
        """Return player for device passed in (caller must hold list_mutex)"""
        for player in self.player_list:
            if player.device == device:
                return player
        return None


def main():
    """Run the application"""
    app = None

    def signal_handler(signum, frame):
        print(f'\nReceived signal {signum}, shutting down gracefully...')
        if app is not None:
            app.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    app = SkrobbleDs()
    app.run()


if __name__ == '__main__':
    main()
