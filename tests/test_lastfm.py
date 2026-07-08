"""Tests for Last.fm API signature generation and response checking."""
import LastFm


def _instance():
    return LastFm.LastFm.__new__(LastFm.LastFm)


def test_api_signature_known_answer(monkeypatch):
    # md5('api_keykeymethodauth.getTokensecret')
    monkeypatch.setattr(LastFm, 'API_SECRET', 'secret')
    sig = _instance()._generate_api_sig({'method': 'auth.getToken', 'api_key': 'key'})
    assert sig == 'b4705499705a550b07ca058a15bde9b0'


def test_api_signature_excludes_existing_sig_and_sorts(monkeypatch):
    monkeypatch.setattr(LastFm, 'API_SECRET', 'secret')
    base = {'method': 'auth.getToken', 'api_key': 'key'}
    with_sig = dict(base, api_sig='junk-should-be-ignored')
    inst = _instance()
    assert inst._generate_api_sig(with_sig) == inst._generate_api_sig(base)


def test_check_response_ok():
    root = _instance()._check_response(b'<lfm status="ok"><token>t</token></lfm>')
    assert root is not None
    assert root.findtext('token') == 't'


def test_check_response_failed_status():
    assert _instance()._check_response(b'<lfm status="failed"/>') is None


def test_check_response_invalid_xml():
    assert _instance()._check_response(b'not xml at all') is None
