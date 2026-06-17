"""Sec #22 — DSN/redis_url credential handling.

- Redis auth is opt-in: empty password => no userinfo (unchanged dev behavior).
- Credentials are URL-encoded so passwords with special chars don't corrupt the URL.
_env_file=None keeps the test hermetic (ignores any local .env).
"""
from config.settings import Settings


def _s(**kw):
    return Settings(_env_file=None, **kw)


def test_redis_url_no_password_is_unchanged():
    s = _s(redis_host="redis", redis_port=6379, redis_db=0, redis_password="")
    assert s.redis_url == "redis://redis:6379/0"


def test_redis_url_includes_password_when_set():
    s = _s(redis_host="redis", redis_port=6379, redis_db=2, redis_password="s3cret")
    assert s.redis_url == "redis://:s3cret@redis:6379/2"


def test_redis_password_is_url_encoded():
    s = _s(redis_host="redis", redis_password="p@ss:w/rd")
    # @ : / must be percent-encoded so the authority doesn't break.
    assert s.redis_url == "redis://:p%40ss%3Aw%2Frd@redis:6379/0"


def test_database_dsn_encodes_credentials():
    s = _s(postgres_user="ats", postgres_password="p@ss/word",
           postgres_host="timescaledb", postgres_port=5432, postgres_db="ats")
    assert s.database_dsn == "postgresql://ats:p%40ss%2Fword@timescaledb:5432/ats"


def test_database_dsn_default_creds_unchanged():
    s = _s(postgres_user="ats", postgres_password="ats",
           postgres_host="timescaledb", postgres_port=5432, postgres_db="ats")
    assert s.database_dsn == "postgresql://ats:ats@timescaledb:5432/ats"
