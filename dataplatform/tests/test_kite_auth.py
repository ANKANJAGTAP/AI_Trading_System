import datetime as dt
import json

from cryptography.fernet import Fernet

from dataplatform.kite_auth import save_token, load_token, _encrypt


def test_plaintext_roundtrip(tmp_path):
    p = tmp_path / "tok.json"
    save_token("ACCESS123", p)               # no key (dev)
    assert load_token(p) == "ACCESS123"


def test_encrypted_roundtrip_and_at_rest(tmp_path):
    key = Fernet.generate_key().decode()
    p = tmp_path / "tok.json"
    save_token("ACCESS123", p, key)
    assert b"ACCESS123" not in p.read_bytes()   # not stored in the clear
    assert load_token(p, key) == "ACCESS123"


def test_stale_token_rejected(tmp_path):
    p = tmp_path / "tok.json"
    yday = json.dumps({"access_token": "OLD",
                       "date": str(dt.date.today() - dt.timedelta(days=1))}).encode()
    p.write_bytes(_encrypt(yday, None))
    assert load_token(p) is None                       # default: must be today's
    assert load_token(p, require_today=False) == "OLD"  # opt out of the date check


def test_missing_file_returns_none(tmp_path):
    assert load_token(tmp_path / "nope.json") is None


def test_wrong_key_returns_none(tmp_path):
    p = tmp_path / "tok.json"
    save_token("ACCESS123", p, Fernet.generate_key().decode())
    assert load_token(p, Fernet.generate_key().decode()) is None   # bad key -> None, no crash
