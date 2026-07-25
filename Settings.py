"""Settings.py - User settings handler for SkrobbleDs

Copyright (c) Rockfather 2012, edooper 2026
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""
import copy
import json
import os
import tempfile
import threading

SETTINGS_FILE = 'config.json'
SETTINGS_DIR = 'config'

class Settings:
    """Class to handle user settings for SkrobbleDs"""

    def __init__(self):
        """Initialise class from JSON file (or create file if it doesn't exist)"""
        self._lock = threading.RLock()
        self.host = None
        # Two mappings, no derived copies: a player's session key is always
        # looked up through its account, so re-authorising an account takes
        # effect immediately for every player linked to it. Dicts preserve
        # insertion order, so the list accessors keep their config order.
        self.accounts = {}    # LastFm user -> session key
        self.players = {}     # player name -> LastFm user

        # Use local settings directory instead of user's home directory
        # Support CONFIG_DIR environment variable for container deployments
        config_dir = os.environ.get('CONFIG_DIR', SETTINGS_DIR)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        settings_path = os.path.join(script_dir, config_dir)

        # Create settings directory if it doesn't exist
        if not os.path.exists(settings_path):
            os.makedirs(settings_path)

        self.settings_file = os.path.join(settings_path, SETTINGS_FILE)

        # Track if we need to save settings
        need_save = False

        if os.path.exists(self.settings_file):
            with open(self.settings_file, 'rt') as f:
                config = json.load(f)

            # Check if runtime settings exist, if not we'll save them
            if 'network' not in config or 'players' not in config:
                need_save = True

            # Load network interface setting
            if 'network' in config and 'interface' in config['network']:
                self.host = config['network']['interface']

            # Load accounts
            if 'lastfm' in config and 'accounts' in config['lastfm']:
                for acc in config['lastfm']['accounts']:
                    if 'user' in acc and 'session_key' in acc:
                        self.add_account(acc['user'], acc['session_key'])

            # Load players
            if 'players' in config:
                for player in config['players']:
                    if 'name' in player and 'user' in player:
                        try:
                            self.add_player(player['user'], player['name'])
                        except ValueError:
                            # Player references an account that no longer exists -
                            # skip it rather than refusing to start
                            print(f"Ignoring player '{player['name']}': "
                                  f"account '{player['user']}' not found in config")
                            need_save = True
        else:
            # Config doesn't exist, need to create it
            need_save = True

        # Save settings if needed (to add runtime structure to existing configs)
        if need_save:
            self._save_settings()

    def get_host(self):
        """Return host IP address"""
        with self._lock:
            return self.host

    def get_accounts(self):
        """Return list of LastFm accounts"""
        with self._lock:
            return list(self.accounts)

    def get_players(self):
        """Return list of players"""
        with self._lock:
            return list(self.players)

    def get_session_key(self, player_name):
        """Return LastFm session key for use with supplied player"""
        with self._lock:
            return self.accounts.get(self.players.get(player_name))

    def get_user(self, player_name):
        """Return LastFm user for use with supplied player"""
        with self._lock:
            return self.players.get(player_name)

    def update_host(self, host, update_json=False):
        """Update host setting"""
        with self._lock:
            self.host = host
            if update_json:
                self._save_settings()

    def add_account(self, user, key, update_json=False):
        """Add a new LastFm account, or refresh the key of an existing one"""
        with self._lock:
            self.accounts[user] = key
            if update_json:
                self._save_settings()

    def add_player(self, user, player_name, update_json=False):
        """Add a new player to be scrobbled"""
        with self._lock:
            if user not in self.accounts:
                raise ValueError(f"User '{user}' not found. Please add the account first before adding a player.")
            self.players[player_name] = user
            if update_json:
                self._save_settings()

    def remove_account(self, user):
        """Remove a LastFm account from class and JSON"""
        with self._lock:
            self.accounts.pop(user, None)
            for player in [p for p, u in self.players.items() if u == user]:
                del self.players[player]
            self._save_settings()

    def remove_player(self, player_name):
        """Remove a player from class and JSON"""
        with self._lock:
            self.players.pop(player_name, None)
            self._save_settings()

    def _save_settings(self):
        """Save settings to JSON file"""
        # Read existing config to preserve lastfm api_key and api_secret
        config = {}
        if os.path.exists(self.settings_file):
            with open(self.settings_file, 'rt') as f:
                config = json.load(f)

        # Ensure lastfm section exists
        if 'lastfm' not in config:
            config['lastfm'] = {}

        # Preserve api_key and api_secret if they exist
        api_key = config['lastfm'].get('api_key')
        api_secret = config['lastfm'].get('api_secret')

        # Update accounts in lastfm section
        config['lastfm']['accounts'] = [
            {
                'user': user,
                'session_key': key
            }
            for user, key in self.accounts.items()
        ]

        # Restore api_key and api_secret if they were present
        if api_key is not None:
            config['lastfm']['api_key'] = api_key
        if api_secret is not None:
            config['lastfm']['api_secret'] = api_secret

        # Update network section
        config['network'] = {
            'interface': self.host
        }

        # Update players section
        config['players'] = [
            {
                'name': player,
                'user': user
            }
            for player, user in self.players.items()
        ]

        # Write atomically: write to temp file then rename
        dir_name = os.path.dirname(self.settings_file)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wt') as f:
                json.dump(config, f, indent=2)
                f.write('\n')
            os.replace(tmp_path, self.settings_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise