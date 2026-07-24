# SkrobbleDS v0.95.3

Last.fm scrobbler for Linn DS and OpenHome-compliant UPnP media players.

📖 **Technical Overview** — a styled architecture, module-map, scrobble-rules and configuration reference lives in [`docs/index.html`](docs/index.html). Publish it via **Settings → Pages → deploy from `main` / `docs`** (requires a public repo or a plan with Pages) to serve it at `https://edooper.github.io/skrobbleDS/`.

## Overview

SkrobbleDS automatically scrobbles tracks played on your Linn DS or other OpenHome-compliant UPnP network music players to your Last.fm account. It discovers players on your network, monitors what's playing, and updates your Last.fm profile in real-time.

Original credits go to Rockfather, I merely updated the codebase to work with Python3 and Flask.
Tested with Linn Selekt DSM (2022) edition, but should work with all DS players.

### Features

- **Automatic Discovery**: Finds Linn DS and OpenHome players on your network via UPnP
- **Multi-Player Support**: Monitor multiple players simultaneously
- **Multi-Account Support**: Link different players to different Last.fm accounts
- **Now Playing Updates**: Real-time "Now Playing" status on Last.fm
- **Smart Scrobbling**: Follows Last.fm scrobbling rules (tracks > 30s, played for 50% or 4 minutes)
- **Web UI**: Easy configuration through a browser interface on port 9099
- **Offline Caching**: Failed scrobbles are cached and retried later

## Requirements

- Python 3.8 or higher
- Linn DS or OpenHome-compliant UPnP media player
- Last.fm account
- Network connection

## Installation

### Option 1: Using pip (recommended)

```bash
# Clone or download the repository
git clone <repository-url>
cd SkrobbleDS

# Install in a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python3 SkrobbleDs.py
```

### Option 2: Development installation

```bash
# Install in editable mode
pip install -e .

# Run using the installed command
skrobbleds
```

### Option 3: Docker (recommended for production)

```bash
# Clone the repository
git clone <repository-url>
cd SkrobbleDS

# Create config directory for persistent data
mkdir -p config

# Option A: Using environment variables for API keys
docker-compose up -d \
  -e LASTFM_API_KEY=your_api_key \
  -e LASTFM_API_SECRET=your_api_secret

# Option B: Using config file
cp config/config.json.example config/config.json
# Edit config/config.json with your Last.fm API credentials
docker-compose up -d
```

**Important**: Docker requires `network_mode: host` for UPnP multicast discovery to work. This is already configured in the provided `docker-compose.yml`.

## Configuration

1. **Start SkrobbleDS**:
   ```bash
   python3 SkrobbleDs.py
   ```

2. **Open Web UI**: Navigate to `http://localhost:9099` in your browser

3. **Add Last.fm Account**:
   - Click "Add account" to authorize SkrobbleDS with Last.fm
   - Log in to Last.fm and grant access
   - You'll be redirected back to SkrobbleDS

4. **Add Players**:
   - Discovered players appear in the dropdown
   - Select a player and link it to a Last.fm account
   - Click "Add Scrobbling" to start monitoring

5. **Network Interface** (optional):
   - Leave blank for default interface
   - Set to `0.0.0.0` to monitor all interfaces
   - Or specify a specific IP address

### Configuration Files

SkrobbleDS uses a single configuration file in the `config/` directory:

**config/config.json** - All configuration (required)
   - Copy from `config/config.json.example`
   - Contains Last.fm API credentials (api_key, api_secret)
   - Runtime settings (accounts, players, network interface) managed via web UI
   - API credentials can be replaced by environment variables: `LASTFM_API_KEY` and `LASTFM_API_SECRET`
   - Get API keys from: https://www.last.fm/api/account/create

## Usage

Once configured, SkrobbleDS runs continuously in the foreground:

- Monitors configured players for track changes
- Updates "Now Playing" when tracks start
- Scrobbles tracks that meet Last.fm's criteria
- Logs all activity to console with timestamps

### Scrobbling Rules

A track is scrobbled to Last.fm if:
- Track duration is longer than 30 seconds, **AND**
- Track has been played for at least:
  - Half its duration, **OR**
  - 4 minutes (whichever comes first)

## Supported Devices

SkrobbleDS supports UPnP devices implementing:
- `urn:linn-co-uk:device:Source:1` (Linn Cara family)
- `urn:av-openhome.org:device:Source:1` (OpenHome devices)

### Tested Players
- Linn DS players (Cara and Davaar families)
- Other OpenHome-compliant network players

## Troubleshooting

### Players not appearing
- Ensure players are on the same network
- Check firewall settings (UDP multicast required)
- Try setting network interface to `0.0.0.0`

### Scrobbles not appearing
- Verify track meets scrobbling criteria (>30s, played >50%)
- Check Last.fm account authorization
- Review console logs for error messages

### Web UI not accessible
- Default port is 9099
- Check for port conflicts
- Try accessing via `http://127.0.0.1:9099`

## Development

### Project Structure

```
SkrobbleDS/
├── SkrobbleDs.py      # Main entry point
├── LastFm.py          # Last.fm API integration
├── Scrobbler.py       # Scrobbling logic and queue management
├── Player.py          # UPnP player interface
├── Settings.py        # Configuration management
├── WebUi.py           # Web interface
├── Logger.py          # Logging system
├── Database.py        # SQLite persistence layer
├── EventBus.py        # Internal pub/sub event bus
├── Constants.py       # Application constants
├── Upnp/              # UPnP discovery and event handling
│   ├── Discovery.py
│   ├── Device.py
│   ├── EventServer.py
│   ├── EventSub.py
│   └── ...
├── requirements.txt   # Python dependencies
├── setup.py          # Package setup
└── README.md         # This file
```

### Running from source

```bash
python3 SkrobbleDs.py
```

### Building

```bash
python setup.py sdist bdist_wheel
```

### Docker Development

```bash
# Build the image
docker build -t skrobbleds .

# Run with host networking (required for UPnP)
docker run -d \
  --name skrobbleds \
  --network host \
  -v $(pwd)/config:/app/config \
  -e LASTFM_API_KEY=your_key \
  -e LASTFM_API_SECRET=your_secret \
  skrobbleds

# View logs
docker logs -f skrobbleds

# Check health
curl http://localhost:9099/health
```

### Environment Variables

The application supports the following environment variables:

- **LASTFM_API_KEY**: Last.fm API key (alternative to config.json)
- **LASTFM_API_SECRET**: Last.fm API secret (alternative to config.json)
- **WEBUI_PORT**: Web UI port (default: 9099)
- **WEBUI_USER** / **WEBUI_PASS**: Enable basic authentication for the web UI
- **CONFIG_DIR**: Configuration directory path (default: config)
- **DEBUG**: Enable debug-level logging (default: false)
- **LOG_FILE**: Enable file logging to config/skrobbleds.log (default: false)
- **USE_WAITRESS**: Use Waitress production WSGI server (default: true, falls back to Flask dev server if not installed)

## Changelog

### v0.95.3 (Current)

- **Fix (wrong scrobble decision on gapless albums)**: track duration is now read from the DIDL-Lite `<res duration=…>` attribute, atomic with the title/artist, instead of the separate Info `Duration` event. On fast (gapless) track changes the `Duration` event lagged by a track, so a track could be scored against the previous track's duration and wrongly skipped (e.g. a 50s track judged against 126s → "NO scrobble"). The fallback `Duration` event is still used when the DIDL omits a duration.

### v0.95.2

- **Fix (missing track titles)**: the UPnP event HTTP parser now frames packets by **byte** length. `Content-Length` is a byte count, but the body was measured in characters after UTF-8 decoding — so any `Info` `Metadata` event whose DIDL-Lite payload contained a multi-byte character (e.g. the `℗`/`©` marks common in Tidal metadata) was treated as perpetually incomplete, silently dropped, and eventually caused the device to drop the Info subscription (recurring "Bad response renewing" every ~22 min). Track titles/artists now come through reliably for streaming sources such as Tidal.
- **Fix**: a multi-byte character split across two TCP segments is no longer corrupted — inbound event data is accumulated as bytes and decoded once the full packet has been assembled.

### v0.95.1

- **Fix**: UPnP event HTTP parser now handles `Transfer-Encoding: chunked` NOTIFY bodies.
- **Fix**: metadata is no longer left stale across a fast track change — `Metadata`/`Duration` events arriving out of order can no longer attach the previous track's title/artist to a new track.
- **Diagnostics**: unparsable/malformed UPnP event packets are now logged instead of being swallowed silently.

### v0.95.0

- **Security**:
  - All mutating web routes now require **POST requests with CSRF tokens**
  - Timing-safe password comparison using `hmac.compare_digest()`
  - IP address validation checks octets are within 0-255
  - Non-root user in Docker container
  - HTTPS enforced in standalone token script
- **Thread Safety**:
  - Added `RLock` protection to Settings, Player shared state
  - Atomic config file writes (temp file + rename)
  - Shutdown guard prevents double-shutdown race condition
  - Player list copied under mutex during shutdown
  - EventBus unsubscribe on Scrobbler shutdown
- **Correctness**:
  - Fixed play-time calculation (stop events now consumed properly)
  - Guard against empty playing list preventing IndexError
  - Guard shutdown scrobble when no track is loaded
  - Safe metadata parsing (build dict locally before assigning)
  - Lazy Last.fm config loading (deferred from import time)
  - Periodic retry of cached scrobbles (every 5 minutes)
- **Operations**:
  - Waitress graceful fallback to Flask dev server if not installed
  - Docker: added templates copy, non-root user, optional .env file
  - Version ceilings on dependencies (Flask/waitress < 4.0.0)
  - Full traceback in EventBus error logging

### v0.90

- **Architecture Refinements**:
  - Implemented **Database Dependency Injection** for cleaner architecture and connection pooling readiness.
  - Enabled **SQLite WAL (Write-Ahead Logging)** mode for improved concurrency between Scrobbler and Web UI.
  - Decoupled data layer from presentation by moving date formatting to the Web UI template.
  - Integrated proper logging into the internal **Event Bus** for better observability.
  - Extracted core configuration values (timers, thresholds) into `Constants.py`.

### v0.80 (Legacy)
- **Architectural Overhaul**:
  - Implemented internal **Event Bus** to decouple Player and Scrobbler components.
  - Refactored Web UI using **Flask Application Factory** pattern.
  - Removed global state variables.
- **Persistence & Reliability**:
  - Added **SQLite database** for persistent scrobble caching (prevents data loss on restart).
  - Implemented structured **Scrobble History** stored in database.
- **Modernization**:
  - Full codebase refactor to **PEP 8** standards.
  - Updated to use Python 3 f-strings throughout.
- **Operations & Security**:
  - Integrated **Waitress** as the production WSGI server.
  - Added optional **Basic Authentication** for Web UI (via `WEBUI_USER`/`WEBUI_PASS`).

### v0.51 (Legacy)
- **Modernized to Python 3** (3.8+ required)
- **Migrated to Flask** (3.0+) from CherryPy for modern web framework
- Updated all dependencies
- Fixed deprecated syntax (`has_key`, `Queue`, `urllib2`, etc.)
- Improved file I/O with context managers
- Updated exception handling syntax
- Better error handling in XML parsing
- Added modern setuptools configuration
- Created comprehensive documentation
- **Container Support**:
  - Added Docker support with Dockerfile and docker-compose.yml
  - Proper signal handling for graceful shutdown (SIGTERM/SIGINT)
  - Environment variable support for configuration
  - Health check endpoint at `/health`
  - Externalized configuration to `config/` directory
- **Configuration Improvements**:
  - Support for environment variables (LASTFM_API_KEY, LASTFM_API_SECRET, WEBUI_PORT)
  - Config files moved to `config/` directory
  - Flexible config directory location via CONFIG_DIR environment variable

### v0.15 (Legacy)
- Original Python 2 version
- Bundled CherryPy 3.1.2

## Migration from v0.15

If upgrading from v0.15:

1. **Install Python 3.8+** if not already installed
2. **Install dependencies**: `pip install -r requirements.txt`
3. **Run with Python 3**: `python3 SkrobbleDs.py`
4. Your existing configuration file will work without changes

## Known Issues

- "No track playing" status cannot be explicitly cleared on Last.fm (API limitation)

## License

Copyright (c) Rockfather 2012-2016, edooper 2026, All Rights Reserved

See [Licence.txt](Licence.txt) for full terms and conditions of use.

## Credits

- Original author: Rockfather
- Python 3 modernization: v0.51 update

## Support

For issues, questions, or contributions, please refer to the project repository.

---

**Note**: This software scrobbles to Last.fm using your network players. Ensure you have proper authorization for any Last.fm accounts you configure.
