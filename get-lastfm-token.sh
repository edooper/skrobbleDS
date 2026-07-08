#!/bin/bash
#
# Last.fm Session Key Generator (curl-based)
# This script obtains a Last.fm session key using only curl and standard Unix tools
#
# Usage: ./get-lastfm-token.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================================="
echo "SkrobbleDS - Last.fm Session Key Generator"
echo "=================================================="
echo

# Load API credentials
if [ -f "config/config.json" ]; then
    API_KEY=$(grep -oP '"api_key":\s*"\K[^"]+' config/config.json)
    API_SECRET=$(grep -oP '"api_secret":\s*"\K[^"]+' config/config.json)
elif [ -n "$LASTFM_API_KEY" ] && [ -n "$LASTFM_API_SECRET" ]; then
    API_KEY="$LASTFM_API_KEY"
    API_SECRET="$LASTFM_API_SECRET"
else
    echo -e "${RED}ERROR: Last.fm API credentials not found!${NC}"
    echo
    echo "Please either:"
    echo "  1. Set environment variables:"
    echo "     export LASTFM_API_KEY='your_api_key'"
    echo "     export LASTFM_API_SECRET='your_api_secret'"
    echo
    echo "  2. Create config/config.json with:"
    echo '     {"lastfm": {"api_key": "...", "api_secret": "..."}}'
    echo
    echo "Get API keys from: https://www.last.fm/api/account/create"
    exit 1
fi

echo -e "${GREEN}✓${NC} API credentials loaded"
echo

# Function to calculate MD5 signature
calculate_signature() {
    local sig="$1"
    echo -n "${sig}${API_SECRET}" | md5sum | awk '{print $1}'
}

# Step 1: Get authentication token
echo "Step 1: Getting authentication token..."
SIG_STRING="api_key${API_KEY}methodauth.getToken"
API_SIG=$(calculate_signature "$SIG_STRING")

TOKEN_RESPONSE=$(curl -s "http://ws.audioscrobbler.com/2.0/?method=auth.getToken&api_key=${API_KEY}&api_sig=${API_SIG}&format=json")

# Check for error
if echo "$TOKEN_RESPONSE" | grep -q '"error"'; then
    ERROR_MSG=$(echo "$TOKEN_RESPONSE" | grep -oP '"message":\s*"\K[^"]+')
    echo -e "${RED}ERROR: $ERROR_MSG${NC}"
    exit 1
fi

TOKEN=$(echo "$TOKEN_RESPONSE" | grep -oP '"token":\s*"\K[^"]+')

if [ -z "$TOKEN" ]; then
    echo -e "${RED}ERROR: Failed to get token${NC}"
    echo "Response: $TOKEN_RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓${NC} Token received: $TOKEN"
echo

# Step 2: User authorization
AUTH_URL="http://www.last.fm/api/auth/?api_key=${API_KEY}&token=${TOKEN}"

echo "Step 2: Authorize SkrobbleDS with Last.fm"
echo "--------------------------------------------------"
echo "Please visit this URL to authorize:"
echo
echo -e "${YELLOW}  $AUTH_URL${NC}"
echo
echo "After authorizing, press ENTER to continue..."
read -r

# Step 3: Get session key
echo
echo "Step 3: Getting session key..."

SIG_STRING="api_key${API_KEY}methodauth.getSessiontoken${TOKEN}"
API_SIG=$(calculate_signature "$SIG_STRING")

SESSION_RESPONSE=$(curl -s "http://ws.audioscrobbler.com/2.0/?method=auth.getSession&api_key=${API_KEY}&token=${TOKEN}&api_sig=${API_SIG}&format=json")

# Check for error
if echo "$SESSION_RESPONSE" | grep -q '"error"'; then
    ERROR_CODE=$(echo "$SESSION_RESPONSE" | grep -oP '"error":\s*\K[0-9]+')
    ERROR_MSG=$(echo "$SESSION_RESPONSE" | grep -oP '"message":\s*"\K[^"]+')
    echo -e "${RED}ERROR $ERROR_CODE: $ERROR_MSG${NC}"
    echo
    echo "Did you authorize the application?"
    exit 1
fi

USERNAME=$(echo "$SESSION_RESPONSE" | grep -oP '"name":\s*"\K[^"]+')
SESSION_KEY=$(echo "$SESSION_RESPONSE" | grep -oP '"key":\s*"\K[^"]+')

if [ -z "$USERNAME" ] || [ -z "$SESSION_KEY" ]; then
    echo -e "${RED}ERROR: Failed to get session key${NC}"
    echo "Response: $SESSION_RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓${NC} Session key received for user: $USERNAME"
echo

# Display results
echo "=================================================="
echo "SUCCESS!"
echo "=================================================="
echo
echo "Last.fm Username: $USERNAME"
echo "Session Key:      $SESSION_KEY"
echo

# Offer to update config
echo "Configuration Options:"
echo "--------------------------------------------------"
echo
read -p "Update config/config.json file? (y/n): " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo

    # Ask for player names
    echo "Enter player names to configure (one per line, empty line to finish):"
    echo "Examples: 'Linn Woonkamer ', 'Linn Woonkamer :UPnP AV (OpenHome)'"
    echo

    PLAYERS=()
    PLAYER_NUM=1
    while true; do
        read -p "Player #${PLAYER_NUM} (or press ENTER to finish): " PLAYER_NAME
        if [ -z "$PLAYER_NAME" ]; then
            break
        fi
        PLAYERS+=("$PLAYER_NAME")
        PLAYER_NUM=$((PLAYER_NUM + 1))
    done

    # Read existing config or create new
    mkdir -p config
    if [ -f "config/config.json" ]; then
        EXISTING_CONFIG=$(cat config/config.json)
    else
        EXISTING_CONFIG='{
  "lastfm": {
    "api_key": "'${API_KEY}'",
    "api_secret": "'${API_SECRET}'"
  },
  "network": {
    "interface": null
  },
  "players": []
}'
    fi

    # Use Python to update JSON (more reliable than bash JSON manipulation)
    python3 - <<PYTHON_SCRIPT
import json
import sys

# Read existing config
config = json.loads('''$EXISTING_CONFIG''')

# Ensure structure exists
if 'lastfm' not in config:
    config['lastfm'] = {}
if 'accounts' not in config['lastfm']:
    config['lastfm']['accounts'] = []
if 'network' not in config:
    config['network'] = {'interface': None}
if 'players' not in config:
    config['players'] = []

# Add or update account
account_exists = False
for account in config['lastfm']['accounts']:
    if account.get('user') == '$USERNAME':
        account['session_key'] = '$SESSION_KEY'
        account_exists = True
        break

if not account_exists:
    config['lastfm']['accounts'].append({
        'user': '$USERNAME',
        'session_key': '$SESSION_KEY'
    })

# Add players
players = $(printf '%s\n' "${PLAYERS[@]}" | python3 -c "import sys, json; print(json.dumps([line.strip() for line in sys.stdin if line.strip()]))")
for player_name in players:
    player_exists = False
    for player in config['players']:
        if player.get('name') == player_name:
            player['user'] = '$USERNAME'
            player_exists = True
            break

    if not player_exists:
        config['players'].append({
            'name': player_name,
            'user': '$USERNAME'
        })

# Write updated config
with open('config/config.json', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')

print("✓ Configuration updated successfully")
PYTHON_SCRIPT

    echo
    echo -e "${GREEN}✓${NC} Configuration written to: config/config.json"
    if [ ${#PLAYERS[@]} -gt 0 ]; then
        echo -e "${GREEN}✓${NC} Configured ${#PLAYERS[@]} player(s)"
    fi
else
    echo
    echo "Manual Configuration:"
    echo "--------------------------------------------------"
    echo
    echo "Add this to your config/config.json under 'lastfm.accounts':"
    echo
    cat <<EOF
{
  "user": "${USERNAME}",
  "session_key": "${SESSION_KEY}"
}
EOF
    echo
fi

echo
echo "You can now start SkrobbleDS!"
echo
