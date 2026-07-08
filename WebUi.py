"""WebUi.py - Web based user interface for SkrobbleDs

Copyright (c) Rockfather 2016, edooper 2026
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""
import hmac
import os
import re
import secrets
import threading
import time
from functools import wraps
from flask import Flask, render_template, request, redirect, jsonify, send_file, url_for, current_app, Response, session, abort
import LastFm

def auth_required(f):
    """Decorator to implement optional basic authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_user = os.environ.get('WEBUI_USER')
        auth_pass = os.environ.get('WEBUI_PASS')
        
        # If no auth is configured, just proceed
        if not auth_user or not auth_pass:
            return f(*args, **kwargs)
            
        auth = request.authorization
        if (not auth or not auth.username or not auth.password
                or not hmac.compare_digest(auth.username, auth_user)
                or not hmac.compare_digest(auth.password, auth_pass)):
            return Response(
                'Could not verify your access level for that URL.\n'
                'You have to login with proper credentials', 401,
                {'WWW-Authenticate': 'Basic realm="Login Required"'}
            )
        return f(*args, **kwargs)
    return decorated

def create_app(settings, players, shutdown_callback, version, db):
    """Flask application factory"""
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)

    # Store dependencies in app config
    app.config['SK_SETTINGS'] = settings
    app.config['SK_PLAYERS'] = players
    app.config['SK_SHUTDOWN'] = shutdown_callback
    app.config['SK_VERSION'] = version
    app.config['SK_DB'] = db

    def generate_csrf_token():
        if '_csrf_token' not in session:
            session['_csrf_token'] = secrets.token_hex(32)
        return session['_csrf_token']

    app.jinja_env.globals['csrf_token'] = generate_csrf_token

    @app.before_request
    def csrf_protect():
        if request.method == 'POST':
            token = session.get('_csrf_token')
            if not token or token != request.form.get('_csrf_token'):
                abort(403)

    @app.template_filter('datetimeformat')
    def datetimeformat_filter(value, format='%d/%m/%y %H:%M:%S'):
        if value is None: return ""
        import datetime
        dt = datetime.datetime.fromtimestamp(value)
        return dt.strftime(format)

    @app.route('/')
    @auth_required
    def index():
        """Main settings page"""
        settings = current_app.config['SK_SETTINGS']
        players = current_app.config['SK_PLAYERS']
        db = current_app.config['SK_DB']
        version = current_app.config['SK_VERSION']

        accounts = settings.get_accounts()
        
        configured_players = []
        for p_name in settings.get_players():
            configured_players.append({
                'name': p_name,
                'user': settings.get_user(p_name) or ''
            })

        available_players = []
        for p in players:
            if p.name not in settings.get_players():
                available_players.append(p.name)

        recent_scrobbles = db.get_recent_history(10)
        host = settings.get_host()

        return render_template(
            'index.html',
            accounts=accounts,
            configured_players=configured_players,
            available_players=available_players,
            host=host,
            recent_scrobbles=recent_scrobbles,
            version=version
        )

    @app.route('/addAccount')
    @auth_required
    def add_account():
        """Redirect to Last.fm for authentication"""
        callback = request.url_root.rstrip('/') + url_for('verify_account')
        auth_url = f"https://www.last.fm/api/auth/?api_key={LastFm.get_api_key()}&cb={callback}"
        return redirect(auth_url)

    @app.route('/verifyAccount')
    @auth_required
    def verify_account():
        """Handle callback from Last.fm authentication"""
        settings = current_app.config['SK_SETTINGS']
        token = request.args.get('token')
        if token:
            lastfm = LastFm.LastFm()
            session = lastfm.auth_get_session(token)
            if session and session['name'] not in settings.get_accounts():
                settings.add_account(session['name'], session['key'], True)
        return redirect(url_for('index'))

    @app.route('/removeAccount', methods=['POST'])
    @auth_required
    def remove_account():
        """Remove a Last.fm account"""
        settings = current_app.config['SK_SETTINGS']
        account = request.form.get('account')
        if account and account in settings.get_accounts():
            settings.remove_account(account)
        return redirect(url_for('index'))

    @app.route('/addPlayer', methods=['POST'])
    @auth_required
    def add_player():
        """Link a player to a Last.fm account"""
        settings = current_app.config['SK_SETTINGS']
        player = request.form.get('player')
        account = request.form.get('account')
        if player and account and player not in settings.get_players():
            try:
                settings.add_player(account, player, True)
            except ValueError as e:
                print(f"Error adding player: {e}")
        return redirect(url_for('index'))

    @app.route('/removePlayer', methods=['POST'])
    @auth_required
    def remove_player():
        """Unlink a player"""
        settings = current_app.config['SK_SETTINGS']
        player = request.form.get('player')
        if player and player in settings.get_players():
            settings.remove_player(player)
        return redirect(url_for('index'))

    @app.route('/updateHost', methods=['POST'])
    @auth_required
    def update_host():
        """Update network interface configuration"""
        settings = current_app.config['SK_SETTINGS']
        host = request.form.get('host', '').strip()
        
        if not host or host == 'blank':
            settings.update_host('', True)
        else:
            m = re.match(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$', host)
            if m and all(0 <= int(octet) <= 255 for octet in m.groups()):
                settings.update_host(host, True)
            
        return redirect(url_for('index'))

    @app.route('/exit', methods=['POST'])
    @auth_required
    def exit_app():
        """Shut down the application"""
        shutdown_cb = current_app.config['SK_SHUTDOWN']

        def delayed_shutdown():
            time.sleep(0.5)
            if shutdown_cb:
                shutdown_cb()
            os._exit(0)

        threading.Thread(target=delayed_shutdown, daemon=True).start()
        return "Shutting down..."

    @app.route('/favicon.png')
    def favicon():
        """Serve favicon"""
        return send_file('favicon.png', mimetype='image/png')

    @app.route('/health')
    def health():
        """Health check endpoint"""
        settings = current_app.config['SK_SETTINGS']
        version = current_app.config['SK_VERSION']
        return jsonify({
            'status': 'healthy',
            'version': version,
            'accounts': len(settings.get_accounts()),
            'players': len(settings.get_players())
        })

    return app

class WebUi:
    """Web interface wrapper for SkrobbleDs"""

    def __init__(self, settings, players, shutdown_callback, version, db):
        """Create the Flask app - call start() to serve (blocking)"""
        self.app = create_app(settings, players, shutdown_callback, version, db)

    def start(self):
        """Serve the web UI - blocks until the process exits"""
        # Support environment variable for port configuration
        webui_port = int(os.environ.get('WEBUI_PORT', '9099'))

        # Use Waitress for production by default, allow override via env
        use_waitress = os.environ.get('USE_WAITRESS', 'true').lower() in ('true', '1', 'yes', 'on')

        if use_waitress:
            try:
                from waitress import serve
                print(f"Starting Waitress server on port {webui_port}...")
                serve(self.app, host='0.0.0.0', port=webui_port, threads=4)
                return
            except ImportError:
                print("Waitress not installed, falling back to Flask development server")
        else:
            print(f"Starting Flask development server on port {webui_port}...")
        self.app.run(host='0.0.0.0', port=webui_port, debug=False, threaded=True)