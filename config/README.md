# Configuration Directory

This directory contains the configuration file for SkrobbleDS.

## Files

### config.json
Contains all SkrobbleDS configuration including:
- Last.fm API credentials (api_key, api_secret)
- Last.fm accounts with session keys
- Network interface setting
- Player-to-account mappings

**Setup:**
1. Copy `config.json.example` to `config.json`
2. Add your Last.fm API key and secret
   - Get API credentials from: https://www.last.fm/api/account/create

Example minimal configuration:
```json
{
  "lastfm": {
    "api_key": "your_api_key_here",
    "api_secret": "your_api_secret_here",
    "accounts": []
  },
  "network": {
    "interface": null
  },
  "players": []
}
```

Example with configured account and player:
```json
{
  "lastfm": {
    "api_key": "your_api_key_here",
    "api_secret": "your_api_secret_here",
    "accounts": [
      {
        "user": "lastfm_username",
        "session_key": "session_key_from_authorization"
      }
    ]
  },
  "network": {
    "interface": null
  },
  "players": [
    {
      "name": "Living Room Player",
      "user": "lastfm_username"
    }
  ]
}
```

**Configuration Options:**

1. **Via Web UI (recommended for desktop use)**
   - Start the application with minimal config (just API credentials)
   - Open http://localhost:9099
   - Add Last.fm account(s) via OAuth flow
   - Map discovered players to accounts
   - Settings are saved automatically to config.json

2. **Via get-lastfm-token.py script (recommended for Docker/headless)**
   ```bash
   # Run the token generator script
   python3 get-lastfm-token.py

   # Follow the prompts to:
   # 1. Authorize with Last.fm
   # 2. Get your session key
   # 3. Optionally create/update config.json automatically
   ```

3. **Manual configuration**
   - Copy `config.json.example` to `config.json`
   - Use `get-lastfm-token.py` to get your session key
   - Edit config.json manually to add accounts and players

**Note:** For Docker deployments or servers without public internet access, use option 2 or 3, as the web UI OAuth callback requires the server to be reachable from Last.fm's servers.

### Environment Variables

You can use environment variables instead of config.json for API credentials:
- **LASTFM_API_KEY**: Last.fm API key (overrides config.json)
- **LASTFM_API_SECRET**: Last.fm API secret (overrides config.json)

Runtime settings (accounts, players, network interface) are always stored in config.json.

## Security Note

The `config.json` file contains sensitive information (API credentials and session keys) and is excluded from git via `.gitignore`.
