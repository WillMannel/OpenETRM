"""Fail-fast secret handling (task #28, P0-6): a real, provable vulnerability --
Settings.jwt_secret_key defaults to a fixed, public string ("dev-only-insecure-secret
-change-me", right there in app/core/config.py for anyone who clones this open source
repo to read), and nothing previously stopped a deployment from booting with it. Anyone
who's read the source can forge a valid JWT against any such deployment.

These tests exercise _validate_secrets directly against constructed Settings instances
(not via get_settings()'s process-wide @lru_cache, which would make "test one bad
config, then test one good config" impossible within a single test process) -- see
_validate_secrets's docstring for why it's a standalone function for exactly this
reason.
"""

import pytest

from app.core.config import INSECURE_DEFAULT_JWT_SECRET, Settings, _validate_secrets

_GOOD_SECRET = "a" * 40  # long enough, not the known default


def _settings(**overrides) -> Settings:
    defaults = {"jwt_secret_key": _GOOD_SECRET, "environment": "production"}
    defaults.update(overrides)
    return Settings(**defaults)


def test_production_refuses_to_boot_with_the_well_known_default_secret():
    settings = _settings(jwt_secret_key=INSECURE_DEFAULT_JWT_SECRET, environment="production")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        _validate_secrets(settings)


def test_production_refuses_to_boot_with_a_too_short_secret():
    settings = _settings(jwt_secret_key="short", environment="production")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        _validate_secrets(settings)


def test_production_boots_fine_with_a_real_secret():
    settings = _settings(jwt_secret_key=_GOOD_SECRET, environment="production")
    _validate_secrets(settings)  # must not raise


@pytest.mark.parametrize("environment", ["development", "test", "staging"])
def test_non_production_only_warns_on_the_default_secret_not_raises(environment, caplog):
    settings = _settings(jwt_secret_key=INSECURE_DEFAULT_JWT_SECRET, environment=environment)
    _validate_secrets(settings)  # must not raise
    assert any("JWT_SECRET_KEY" in record.message for record in caplog.records)


def test_a_secret_exactly_at_the_minimum_length_is_accepted():
    from app.core.config import MIN_JWT_SECRET_LENGTH

    settings = _settings(jwt_secret_key="b" * MIN_JWT_SECRET_LENGTH, environment="production")
    _validate_secrets(settings)  # must not raise


def test_a_secret_one_character_under_the_minimum_length_is_rejected():
    from app.core.config import MIN_JWT_SECRET_LENGTH

    settings = _settings(jwt_secret_key="b" * (MIN_JWT_SECRET_LENGTH - 1), environment="production")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        _validate_secrets(settings)
