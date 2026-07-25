"""Tests for Settings persistence and config loading."""
import json
import os

import pytest

import Settings


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    # Settings joins CONFIG_DIR onto its script dir; an absolute path wins the join.
    monkeypatch.setenv('CONFIG_DIR', str(tmp_path))
    return tmp_path


def test_round_trip(config_dir):
    s = Settings.Settings()
    s.add_account('alice', 'key-a', update_json=True)
    s.add_player('alice', 'Living Room', update_json=True)
    s.update_host('192.168.1.5', update_json=True)

    reloaded = Settings.Settings()
    assert reloaded.get_accounts() == ['alice']
    assert reloaded.get_players() == ['Living Room']
    assert reloaded.get_user('Living Room') == 'alice'
    assert reloaded.get_session_key('Living Room') == 'key-a'
    assert reloaded.get_host() == '192.168.1.5'


def test_save_preserves_api_credentials(config_dir):
    config_file = config_dir / 'config.json'
    config_file.write_text(json.dumps({
        'lastfm': {'api_key': 'K', 'api_secret': 'S', 'accounts': []},
    }))
    s = Settings.Settings()
    s.add_account('bob', 'key-b', update_json=True)

    saved = json.loads(config_file.read_text())
    assert saved['lastfm']['api_key'] == 'K'
    assert saved['lastfm']['api_secret'] == 'S'
    assert saved['lastfm']['accounts'] == [{'user': 'bob', 'session_key': 'key-b'}]


def test_remove_account_removes_linked_players(config_dir):
    s = Settings.Settings()
    s.add_account('alice', 'key-a')
    s.add_player('alice', 'Living Room')
    s.remove_account('alice')
    assert s.get_players() == []
    assert s.get_session_key('Living Room') is None


def test_player_for_unknown_account_is_skipped_on_load(config_dir):
    """An inconsistent config.json must not crash startup (P0.5)."""
    config_file = config_dir / 'config.json'
    config_file.write_text(json.dumps({
        'lastfm': {'accounts': [{'user': 'alice', 'session_key': 'key-a'}]},
        'network': {'interface': None},
        'players': [
            {'name': 'Living Room', 'user': 'alice'},
            {'name': 'Kitchen', 'user': 'ghost-user'},
        ],
    }))
    s = Settings.Settings()
    assert s.get_players() == ['Living Room']


def test_add_player_unknown_account_raises(config_dir):
    s = Settings.Settings()
    with pytest.raises(ValueError):
        s.add_player('nobody', 'Kitchen')


def test_reauth_updates_key_for_linked_players(config_dir):
    """Re-authorising an account must refresh the key already-linked players use.

    Previously the per-player key was a denormalized copy taken at add_player
    time, so a rotated or revoked session key could never be repaired (A1).
    """
    s = Settings.Settings()
    s.add_account('alice', 'key-old')
    s.add_player('alice', 'Living Room')
    assert s.get_session_key('Living Room') == 'key-old'

    s.add_account('alice', 'key-new', update_json=True)
    assert s.get_session_key('Living Room') == 'key-new'
    assert s.get_accounts() == ['alice']  # not duplicated

    reloaded = Settings.Settings()
    assert reloaded.get_session_key('Living Room') == 'key-new'
