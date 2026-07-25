"""Tests for the SQLite cache and history (C8).

The cache is the durability guarantee for scrobbles that failed to submit, so
its FIFO ordering and round-tripping matter more than anything else here.
"""
import pytest

import Database


@pytest.fixture
def db(tmp_path):
    # An absolute config_dir wins the join against the script dir
    return Database.Database(config_dir=str(tmp_path))


def _track(title, playing=None):
    return {
        'player': 'Living Room',
        'title': title,
        'artist': 'Artist',
        'album': 'Album',
        'tracknum': '3',
        'duration': 200,
        'playing': playing if playing is not None else [1700000000.5],
        'stopped': [1700000200.5],
    }


def test_cache_round_trips_every_field(db):
    db.add_to_cache(_track('Song'))
    got = db.pop_from_cache()
    assert got['player'] == 'Living Room'
    assert got['title'] == 'Song'
    assert got['artist'] == 'Artist'
    assert got['album'] == 'Album'
    assert got['tracknum'] == '3'
    assert got['duration'] == 200
    # Timestamp lists survive the JSON round trip as floats, since the
    # scrobble timestamp is derived from playing[0]
    assert got['playing'] == [1700000000.5]
    assert got['stopped'] == [1700000200.5]


def test_cache_is_fifo(db):
    for i in range(3):
        db.add_to_cache(_track(f'Song {i}'))
    assert db.get_cache_size() == 3
    assert [db.pop_from_cache()['title'] for _ in range(3)] == ['Song 0', 'Song 1', 'Song 2']
    assert db.get_cache_size() == 0


def test_pop_from_empty_cache_returns_none(db):
    assert db.pop_from_cache() is None


def test_popped_entry_is_removed_not_just_read(db):
    """Two consumers must never receive the same cached scrobble."""
    db.add_to_cache(_track('Only'))
    assert db.pop_from_cache()['title'] == 'Only'
    assert db.pop_from_cache() is None


def test_history_returns_most_recent_first(db):
    for i in range(3):
        db.add_to_history(_track(f'Song {i}'))
    history = db.get_recent_history(limit=2)
    assert [h['track'] for h in history] == ['Song 2', 'Song 1']
    assert history[0]['player'] == 'Living Room'
    assert history[0]['timestamp'] == 1700000000  # int(playing[0])


def test_history_without_playing_timestamps_is_stored(db):
    db.add_to_history(_track('No timestamps', playing=[]))
    assert db.get_recent_history(1)[0]['timestamp'] == 0


def test_history_is_pruned_to_the_cap(db, monkeypatch):
    """Growth is bounded. Pruning is amortised, so the table may sit up to one
    interval above the cap between sweeps - but must not grow without limit."""
    monkeypatch.setattr(Database, 'MAX_HISTORY_ROWS', 10)
    monkeypatch.setattr(Database, 'HISTORY_PRUNE_INTERVAL', 5)
    for i in range(60):
        db.add_to_history(_track(f'Song {i}'))
    rows = db.get_recent_history(limit=1000)
    assert len(rows) <= Database.MAX_HISTORY_ROWS + Database.HISTORY_PRUNE_INTERVAL
    # The newest entry always survives pruning
    assert rows[0]['track'] == 'Song 59'


class TestWasScrobbledRecently:
    """Duplicate suppression across restarts.

    A track cannot legitimately be completed twice within its own runtime, so
    a second scrobble whose start time falls inside the first one's duration
    is a duplicate - typically the app being restarted mid-track, which
    scrobbles the in-progress track and then re-scrobbles it when it ends.
    """

    def _add(self, db, title, start, duration=7083):
        db.add_to_history({
            'player': 'Living Room', 'title': title, 'artist': 'UNKLE',
            'album': 'Essential Mix', 'tracknum': '1',
            'duration': duration, 'playing': [start], 'stopped': [],
        })

    def test_detects_the_essential_mix_case(self, db):
        """The real failure: 7083s track, second start 537s after the first."""
        self._add(db, 'Essential Mix 060102', 1784979508)
        assert db.was_scrobbled_recently(
            'Living Room', 'Essential Mix 060102', 'UNKLE', 7083, 1784980045)

    def test_allows_a_genuine_replay_after_the_track_ends(self, db):
        """Starting the track again once it has finished is a real second listen."""
        self._add(db, 'Essential Mix 060102', 1784979508)
        assert not db.was_scrobbled_recently(
            'Living Room', 'Essential Mix 060102', 'UNKLE', 7083,
            1784979508 + 7083)

    def test_back_to_back_short_track_is_not_suppressed(self, db):
        """A 200s track played twice in a row starts exactly one duration
        apart - that is two real listens, not a duplicate."""
        self._add(db, 'Short Song', 1000, duration=200)
        assert not db.was_scrobbled_recently(
            'Living Room', 'Short Song', 'UNKLE', 200, 1200)

    def test_a_different_track_is_never_suppressed(self, db):
        self._add(db, 'Essential Mix 060102', 1784979508)
        assert not db.was_scrobbled_recently(
            'Living Room', 'Some Other Track', 'UNKLE', 7083, 1784980045)

    def test_same_title_different_duration_is_a_different_track(self, db):
        """Suites often repeat a title across movements of different lengths."""
        self._add(db, 'Ashes to Gold', 1784902026, duration=215)
        assert not db.was_scrobbled_recently(
            'Living Room', 'Ashes to Gold', 'UNKLE', 132, 1784902583)

    def test_scoped_to_the_player(self, db):
        self._add(db, 'Essential Mix 060102', 1784979508)
        assert not db.was_scrobbled_recently(
            'Kitchen', 'Essential Mix 060102', 'UNKLE', 7083, 1784980045)

    def test_earlier_timestamp_also_detected(self, db):
        """Cache retries can submit out of order, so the check is symmetric."""
        self._add(db, 'Essential Mix 060102', 1784980045)
        assert db.was_scrobbled_recently(
            'Living Room', 'Essential Mix 060102', 'UNKLE', 7083, 1784979508)

    def test_empty_history_suppresses_nothing(self, db):
        assert not db.was_scrobbled_recently(
            'Living Room', 'Anything', 'UNKLE', 300, 1784979508)


def test_many_operations_do_not_exhaust_connections(db):
    """Each call opens and closes its own connection; a leak would surface as
    an OperationalError long before this completes."""
    for i in range(300):
        db.add_to_cache(_track(f'Song {i}'))
        db.get_cache_size()
        db.pop_from_cache()
    assert db.get_cache_size() == 0
