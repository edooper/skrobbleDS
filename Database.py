"""Database.py - SQLite database handler for SkrobbleDs

Copyright (c) 2026 edooper
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""
import contextlib
import sqlite3
import json
import os

MAX_HISTORY_ROWS = 10000

# Pruning scans the whole history table, so amortise it rather than paying it
# on every insert. The table is allowed to drift this far above the cap.
HISTORY_PRUNE_INTERVAL = 100

class Database(object):
    """Class to handle SQLite database operations for SkrobbleDs"""

    def __init__(self, config_dir='config'):
        """Initialise database connection and create tables if they don't exist"""
        # Support CONFIG_DIR environment variable for container deployments
        cfg_dir = os.environ.get('CONFIG_DIR', config_dir)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_dir = os.path.join(script_dir, cfg_dir)
        
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        self.db_path = os.path.join(db_dir, 'skrobbleds.db')
        self._inserts_since_prune = 0
        self._init_db()

    @contextlib.contextmanager
    def _connect(self):
        """Open a connection, commit on success, and always close it.

        `with sqlite3.connect(...)` commits but does NOT close, so using it
        directly leaks the connection until the GC gets to it.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Create the necessary tables if they don't already exist"""
        with self._connect() as conn:
            # Enable Write-Ahead Logging for better concurrency
            conn.execute('PRAGMA journal_mode=WAL;')
            
            # Table for caching failed scrobbles
            conn.execute('''
                CREATE TABLE IF NOT EXISTS scrobble_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player TEXT,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    tracknum TEXT,
                    duration INTEGER,
                    playing TEXT,
                    stopped TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Table for successful scrobble history
            conn.execute('''
                CREATE TABLE IF NOT EXISTS scrobble_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player TEXT,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    duration INTEGER,
                    timestamp INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    def add_to_cache(self, info):
        """Add a failed scrobble to the cache"""
        with self._connect() as conn:
            conn.execute('''
                INSERT INTO scrobble_cache 
                (player, title, artist, album, tracknum, duration, playing, stopped)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                info.get('player', ''),
                info.get('title', ''),
                info.get('artist', ''),
                info.get('album', ''),
                info.get('tracknum', ''),
                info.get('duration', 0),
                json.dumps(info.get('playing', [])),
                json.dumps(info.get('stopped', []))
            ))

    def pop_from_cache(self):
        """Retrieve and remove the oldest cached scrobble (FIFO)"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            # BEGIN IMMEDIATE acquires a reserved lock before SELECT,
            # preventing another thread from reading the same row
            conn.execute('BEGIN IMMEDIATE')
            cursor = conn.execute('SELECT * FROM scrobble_cache ORDER BY id ASC LIMIT 1')
            row = cursor.fetchone()
            if row:
                conn.execute('DELETE FROM scrobble_cache WHERE id = ?', (row['id'],))
                conn.commit()
                return {
                    'player': row['player'],
                    'title': row['title'],
                    'artist': row['artist'],
                    'album': row['album'],
                    'tracknum': row['tracknum'],
                    'duration': row['duration'],
                    'playing': json.loads(row['playing']),
                    'stopped': json.loads(row['stopped'])
                }
            conn.commit()
        return None

    def get_cache_size(self):
        """Return the number of items currently in the cache"""
        with self._connect() as conn:
            cursor = conn.execute('SELECT COUNT(*) FROM scrobble_cache')
            return cursor.fetchone()[0]

    def add_to_history(self, info):
        """Add a successful scrobble to the history"""
        with self._connect() as conn:
            conn.execute('''
                INSERT INTO scrobble_history 
                (player, title, artist, album, duration, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                info.get('player', ''),
                info.get('title', ''),
                info.get('artist', ''),
                info.get('album', ''),
                info.get('duration', 0),
                int(info['playing'][0]) if info.get('playing') else 0
            ))
            # Prune old entries to prevent unbounded growth. This scans the
            # whole table, so it runs periodically rather than on every insert
            self._inserts_since_prune += 1
            if self._inserts_since_prune >= HISTORY_PRUNE_INTERVAL:
                self._inserts_since_prune = 0
                conn.execute('''
                    DELETE FROM scrobble_history
                    WHERE id NOT IN (
                        SELECT id FROM scrobble_history ORDER BY id DESC LIMIT ?
                    )
                ''', (MAX_HISTORY_ROWS,))

    def get_recent_history(self, limit=10):
        """Retrieve the most recent successful scrobbles"""
        with self._connect() as conn:
            cursor = conn.execute('''
                SELECT player, title, artist, album, duration, timestamp, created_at 
                FROM scrobble_history 
                ORDER BY id DESC LIMIT ?
            ''', (limit,))
            history = []
            for row in cursor.fetchall():
                history.append({
                    'player': row[0],
                    'track': row[1],
                    'artist': row[2],
                    'album': row[3],
                    'duration': str(row[4]),
                    'timestamp': row[5]  # Return raw timestamp
                })
            return history
