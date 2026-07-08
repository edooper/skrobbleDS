#!/usr/bin/env python3
"""
Standalone script to get Last.fm session key for SkrobbleDS
This allows you to configure the session key manually before starting the container.

Usage:
    1. python3 get-lastfm-token.py
    2. Follow the URL to authorize
    3. Copy the session key into your config/config.json
"""

import sys
import json
import os
import hashlib
import urllib.request
import urllib.parse
import webbrowser

def load_api_credentials():
    """Load Last.fm API credentials from config.json or environment variables"""
    # Try environment variables first
    api_key = os.environ.get('LASTFM_API_KEY')
    api_secret = os.environ.get('LASTFM_API_SECRET')

    if api_key and api_secret:
        return api_key, api_secret

    # Try config.json
    config_paths = [
        'config/config.json',
        os.path.join(os.path.dirname(__file__), 'config', 'config.json')
    ]

    for config_path in config_paths:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                if 'lastfm' in config:
                    return config['lastfm']['api_key'], config['lastfm']['api_secret']

    return None, None

def get_auth_token(api_key, api_secret):
    """Get authentication token from Last.fm"""
    # Build signature for auth.getToken
    sig_string = f'api_key{api_key}methodauth.getToken{api_secret}'
    sig = hashlib.md5(sig_string.encode('utf-8')).hexdigest()

    # Request token
    url = f'https://ws.audioscrobbler.com/2.0/?method=auth.getToken&api_key={api_key}&api_sig={sig}&format=json'

    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode('utf-8'))
            if 'token' in data:
                return data['token']
            elif 'error' in data:
                print(f"Error getting token: {data['message']}")
                return None
    except Exception as e:
        print(f"Error contacting Last.fm: {e}")
        return None

def get_session_key(api_key, api_secret, token):
    """Exchange token for session key"""
    # Build signature for auth.getSession
    sig_string = f'api_key{api_key}methodauth.getSessiontoken{token}{api_secret}'
    sig = hashlib.md5(sig_string.encode('utf-8')).hexdigest()

    # Request session
    url = f'https://ws.audioscrobbler.com/2.0/?method=auth.getSession&api_key={api_key}&token={token}&api_sig={sig}&format=json'

    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode('utf-8'))
            if 'session' in data:
                return data['session']['name'], data['session']['key']
            elif 'error' in data:
                print(f"Error getting session: {data['message']}")
                return None, None
    except Exception as e:
        print(f"Error contacting Last.fm: {e}")
        return None, None

def update_config_json(username, session_key, player_names=None):
    """Update or create config.json with session key"""
    config_dir = os.path.join(os.path.dirname(__file__), 'config')
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, 'config.json')

    # Load existing config or create new one
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
    else:
        config = {
            'lastfm': {},
            'network': {'interface': None},
            'players': []
        }

    # Ensure lastfm section exists
    if 'lastfm' not in config:
        config['lastfm'] = {}

    # Add or update account
    if 'accounts' not in config['lastfm']:
        config['lastfm']['accounts'] = []

    # Check if account already exists
    account_exists = False
    for account in config['lastfm']['accounts']:
        if account.get('user') == username:
            account['session_key'] = session_key
            account_exists = True
            break

    # Add new account if it doesn't exist
    if not account_exists:
        config['lastfm']['accounts'].append({
            'user': username,
            'session_key': session_key
        })

    # Add players if specified
    if player_names:
        if 'players' not in config:
            config['players'] = []

        for player_name in player_names:
            # Check if player already exists
            player_exists = False
            for player in config['players']:
                if player.get('name') == player_name:
                    player['user'] = username
                    player_exists = True
                    break

            # Add new player if it doesn't exist
            if not player_exists:
                config['players'].append({
                    'name': player_name,
                    'user': username
                })

    # Write updated config
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')

    return config_path

def main():
    print("SkrobbleDS - Last.fm Session Key Generator")
    print("=" * 50)
    print()

    # Load API credentials
    api_key, api_secret = load_api_credentials()

    if not api_key or not api_secret:
        print("ERROR: Last.fm API credentials not found!")
        print()
        print("Please either:")
        print("  1. Set environment variables:")
        print("     export LASTFM_API_KEY='your_api_key'")
        print("     export LASTFM_API_SECRET='your_api_secret'")
        print()
        print("  2. Create config/config.json:")
        print('     {"lastfm": {"api_key": "...", "api_secret": "..."}}')
        print()
        print("Get API keys from: https://www.last.fm/api/account/create")
        sys.exit(1)

    print("✓ API credentials loaded")
    print()

    # Get token
    print("Step 1: Getting authentication token...")
    token = get_auth_token(api_key, api_secret)

    if not token:
        print("Failed to get authentication token")
        sys.exit(1)

    print(f"✓ Token received: {token}")
    print()

    # Build authorization URL
    auth_url = f"https://www.last.fm/api/auth/?api_key={api_key}&token={token}"

    print("Step 2: Authorize SkrobbleDS with Last.fm")
    print("-" * 50)
    print(f"Please visit this URL to authorize:")
    print()
    print(f"  {auth_url}")
    print()

    # Try to open browser
    try:
        webbrowser.open(auth_url)
        print("✓ Opening browser...")
    except Exception:
        print("(Could not open browser automatically)")

    print()
    input("Press ENTER after you have authorized the application...")
    print()

    # Get session key
    print("Step 3: Getting session key...")
    username, session_key = get_session_key(api_key, api_secret, token)

    if not username or not session_key:
        print("Failed to get session key. Did you authorize the application?")
        sys.exit(1)

    print(f"✓ Session key received for user: {username}")
    print()

    # Display results
    print("=" * 50)
    print("SUCCESS!")
    print("=" * 50)
    print()
    print(f"Last.fm Username: {username}")
    print(f"Session Key:      {session_key}")
    print()

    # Ask if user wants to create config
    print("Configuration Options:")
    print("-" * 50)
    print()
    response = input("Update config/config.json file? (y/n): ").lower()

    if response == 'y':
        # Ask for player names
        print()
        print("Enter player names to configure (one per line, empty line to finish):")
        print("Examples: 'Linn Woonkamer ', 'Linn Woonkamer :UPnP AV (OpenHome)'")
        print()

        player_names = []
        while True:
            player = input(f"Player #{len(player_names)+1} (or press ENTER to finish): ").strip()
            if not player:
                break
            player_names.append(player)

        # Update config.json
        config_path = update_config_json(username, session_key, player_names if player_names else None)

        print()
        print(f"✓ Configuration written to: {config_path}")
        if player_names:
            print(f"✓ Configured {len(player_names)} player(s)")
    else:
        print()
        print("Manual Configuration:")
        print("-" * 50)
        print()
        print("Add this to your config/config.json under 'lastfm.accounts':")
        print()
        print(json.dumps({
            'user': username,
            'session_key': session_key
        }, indent=2))
        print()

    print()
    print("You can now start SkrobbleDS!")
    print()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(1)
