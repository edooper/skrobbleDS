"""Constants.py - Application constants for SkrobbleDs

Copyright (c) 2026 edooper
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""

# Scrobbling Rules
SCROBBLE_MIN_DURATION = 30        # Minimum track duration (seconds)
SCROBBLE_PERCENT_THRESHOLD = 0.5  # Percentage of track to play
SCROBBLE_TIME_THRESHOLD = 240     # Or fix time to play (seconds)

# Hysteresis / Debounce Timers
PLAYER_METADATA_UPDATE_DELAY = 10 # Delay to wait for metadata update (seconds)
PLAYER_PLAYBACK_STATUS_DELAY = 10 # Delay to wait for playback status (seconds)
PLAYER_STOP_SCROBBLE_DELAY = 10   # Delay after Stopped before scrobbling the last track (seconds)

# UPnP Device Types
DEV_TYPE_SOURCE = 'urn:linn-co-uk:device:Source:1'

# Activity Log (in-memory ring buffer surfaced in the web UI)
LOG_RING_SIZE = 200               # Max log lines kept in memory
LOG_DISPLAY_LINES = 10            # Lines shown in the web UI log section
LOG_ERROR_DISPLAY = 5            # Max error lines shown in the callout banner
LOG_ERROR_MARKERS = (             # Substrings marking a submission failure
    '[Last.fm HTTP Error]',
    '[Last.fm API Error]',
    '[Last.fm Connection Error]',
    '[Last.fm Error]',
    '[Last.fm Unexpected Error]',
)
