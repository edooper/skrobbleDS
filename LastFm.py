"""LastFm.py - Last FM interface for SkrobbleDs

Copyright (c) Rockfather 2012, edooper 2026
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API_URL = 'https://ws.audioscrobbler.com/2.0/'

def _load_config():
    """Load configuration from environment variables or config/config.json"""
    api_key = os.environ.get('LASTFM_API_KEY')
    api_secret = os.environ.get('LASTFM_API_SECRET')

    if api_key and api_secret:
        return {
            'lastfm': {
                'api_key': api_key,
                'api_secret': api_secret
            }
        }

    config_dir = os.environ.get('CONFIG_DIR', 'config')
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, config_dir, 'config.json')

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            "Please either:\n"
            "  1. Set environment variables: LASTFM_API_KEY and LASTFM_API_SECRET, or\n"
            "  2. Copy config/config.json.example to config/config.json and add your Last.fm API credentials."
        )

    with open(config_path, 'r') as f:
        config = json.load(f)

    return config

_config = None
API_KEY = None
API_SECRET = None

def _ensure_config():
    """Lazy-load configuration on first access"""
    global _config, API_KEY, API_SECRET
    if _config is None:
        _config = _load_config()
        API_KEY = _config['lastfm']['api_key']
        API_SECRET = _config['lastfm']['api_secret']

def get_api_key():
    """Get the API key, loading config if needed"""
    _ensure_config()
    return API_KEY


class LastFm:
    """Interface for Last.fm API"""

    def __init__(self, logger=None):
        _ensure_config()
        self.log = logger.log if logger else print

    def auth_get_session(self, token):
        """Get a session key using an authentication token"""
        params = {
            'method': 'auth.getSession',
            'token': token, 
            'api_key': API_KEY
        }
        data = self._get_data(params, sign=True)
        if data is not None:
            sess = data.find('session')
            if sess is not None:
                return {
                    'name': sess.findtext('name'),
                    'key': sess.findtext('key')
                }
        return None
        
    def track_scrobble(self, session_key, track, artist, album, track_num, duration, timestamp):
        """Scrobble a track to Last.fm"""
        params = {
            'method': 'track.scrobble',
            'track': track,
            'artist': artist,
            'album': album,
            'trackNumber': track_num,
            'duration': duration,
            'timestamp': timestamp,
            'sk': session_key,
            'api_key': API_KEY
        }
        return self._post_data(params, sign=True)
        
    def track_update_now_playing(self, session_key, track, artist, duration):
        """Update the 'now playing' status on Last.fm"""
        params = {
            'method': 'track.updateNowPlaying',
            'track': track,
            'artist': artist,
            'duration': duration,
            'sk': session_key,
            'api_key': API_KEY
        }
        return self._post_data(params, sign=True)
    
    def _get_data(self, params, sign=False):
        """HTTP GET request to Last.fm"""
        unicoded = {k: str(v) for k, v in params.items()}
        if sign:
            unicoded['api_sig'] = self._generate_api_sig(unicoded)

        url = f"{API_URL}?{urllib.parse.urlencode(unicoded)}"
        request = urllib.request.Request(url)
        method = params.get('method', 'unknown')
        try:
            with urllib.request.urlopen(request, timeout=10) as conn:
                return self._check_response(conn.read())
        except urllib.error.HTTPError as e:
            self.log(f"[Last.fm HTTP Error] GET {method} failed with HTTP {e.code}: {e.reason}")
            return None
        except urllib.error.URLError as e:
            self.log(f"[Last.fm Connection Error] GET {method} failed: {e.reason}")
            return None
    
    def _post_data(self, params, sign=False):
        """HTTP POST request to Last.fm"""
        unicoded = {k: str(v) for k, v in params.items()}
        if sign:
            unicoded['api_sig'] = self._generate_api_sig(unicoded)

        data = urllib.parse.urlencode(unicoded).encode('utf-8')
        request = urllib.request.Request(API_URL, data)
        method = params.get('method', 'unknown')

        try:
            with urllib.request.urlopen(request, timeout=10) as conn:
                resp_data = conn.read()
                resp = self._check_response(resp_data)
                if resp is None:
                    self._log_api_error(method, resp_data)
                return resp
        except urllib.error.HTTPError as e:
            self.log(f"[Last.fm HTTP Error] {method} failed with HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            self.log(f"[Last.fm Connection Error] {method} failed: {e.reason}")
        except Exception as e:
            self.log(f"[Last.fm Unexpected Error] {method} failed: {type(e).__name__}: {str(e)}")
        return None
    
    def _log_api_error(self, method, resp_data):
        """Parse and log specific API error messages from Last.fm response"""
        try:
            error_xml = ET.XML(resp_data)
            error_elem = error_xml.find('error')
            if error_elem is not None:
                code = error_elem.get('code') or 'unknown'
                msg = error_elem.text or 'no message'
                self.log(f"[Last.fm API Error] {method} failed with code {code}: {msg}")
            else:
                self.log(f"[Last.fm Error] {method} returned invalid response (status != ok)")
        except Exception:
            preview = resp_data[:200].decode('utf-8', errors='replace') if resp_data else 'empty'
            self.log(f"[Last.fm Error] {method} returned unparseable response: {preview}")

    def _check_response(self, xml_data):
        """Verify valid response from Last.fm, return XML root or None"""
        try:
            data = ET.XML(xml_data)
            if data is not None and data.get('status') == "ok":
                return data
        except (SyntaxError, ET.ParseError):
            pass
        return None
    
    def _generate_api_sig(self, params):
        """Generate Last.fm api_sig parameter"""
        api_sig = ''
        for key in sorted(params.keys()):
            if key != 'api_sig':
                api_sig += str(key) + str(params[key])
        api_sig += API_SECRET
        return hashlib.md5(api_sig.encode('utf-8')).hexdigest()