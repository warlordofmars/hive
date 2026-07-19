# Copyright (c) 2026 John Carter. All rights reserved.
"""Unit tests for the TTL secret cache (auth/secret_cache.py) — #585."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from hive.auth.secret_cache import (
    DEFAULT_TTL_SECONDS,
    TTL_ENV_VAR,
    SecretConfigError,
    _ttl_seconds,
    ttl_cached,
)


def _clear_secret_caches():
    from hive.auth import google as g
    from hive.auth import tokens as t

    t._jwt_secret.cache_clear()
    t._origin_verify_secret.cache_clear()
    g._google_client_id.cache_clear()
    g._google_client_secret.cache_clear()
    g._allowed_emails.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_caches():
    """Clear every secret cache before and after each test in this module."""
    _clear_secret_caches()
    yield
    _clear_secret_caches()


# ---------------------------------------------------------------------------
# _ttl_seconds
# ---------------------------------------------------------------------------


class TestTtlSeconds:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv(TTL_ENV_VAR, raising=False)
        assert _ttl_seconds() == DEFAULT_TTL_SECONDS

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(TTL_ENV_VAR, "42.5")
        assert _ttl_seconds() == 42.5

    @pytest.mark.parametrize("raw", ["not-a-number", "nan", "inf", "-inf", "-5"])
    def test_invalid_env_falls_back_to_default(self, monkeypatch, raw):
        from hive.auth import secret_cache

        monkeypatch.setattr(secret_cache, "_last_invalid_ttl", None)
        monkeypatch.setenv(TTL_ENV_VAR, raw)
        with patch("hive.auth.secret_cache.logger") as mock_logger:
            assert _ttl_seconds() == DEFAULT_TTL_SECONDS
        mock_logger.warning.assert_called_once()
        assert "Invalid" in mock_logger.warning.call_args[0][0]

    def test_invalid_env_warns_once_per_distinct_value(self, monkeypatch):
        """A misconfigured TTL must not spam the log on every secret access."""
        from hive.auth import secret_cache

        monkeypatch.setattr(secret_cache, "_last_invalid_ttl", None)
        monkeypatch.setenv(TTL_ENV_VAR, "bogus")
        with patch("hive.auth.secret_cache.logger") as mock_logger:
            assert _ttl_seconds() == DEFAULT_TTL_SECONDS
            assert _ttl_seconds() == DEFAULT_TTL_SECONDS
            assert mock_logger.warning.call_count == 1
            monkeypatch.setenv(TTL_ENV_VAR, "-1")  # a *new* invalid value warns again
            assert _ttl_seconds() == DEFAULT_TTL_SECONDS
            assert mock_logger.warning.call_count == 2

    def test_zero_is_a_valid_ttl(self, monkeypatch):
        monkeypatch.setenv(TTL_ENV_VAR, "0")
        assert _ttl_seconds() == 0.0


# ---------------------------------------------------------------------------
# ttl_cached decorator
# ---------------------------------------------------------------------------


class TestTtlCached:
    def test_serves_cached_value_within_ttl(self, monkeypatch):
        monkeypatch.delenv(TTL_ENV_VAR, raising=False)
        fetch = MagicMock(return_value="v1")
        cached = ttl_cached()(fetch)

        assert cached() == "v1"
        assert cached() == "v1"
        assert fetch.call_count == 1

    def test_refetches_after_ttl_expiry(self, monkeypatch):
        """Rotation takes effect once the TTL lapses."""
        monkeypatch.setenv(TTL_ENV_VAR, "0")
        fetch = MagicMock(side_effect=["v1", "v2"])
        cached = ttl_cached()(fetch)

        assert cached() == "v1"
        assert cached() == "v2"
        assert fetch.call_count == 2

    def test_refresh_failure_serves_stale_value(self, monkeypatch):
        """Fail-static: a failed refresh serves the previous value + warns."""
        monkeypatch.setenv(TTL_ENV_VAR, "0")
        fetch = MagicMock(side_effect=["v1", RuntimeError("ssm blip")])
        cached = ttl_cached()(fetch)

        assert cached() == "v1"
        with patch("hive.auth.secret_cache.logger") as mock_logger:
            assert cached() == "v1"
        mock_logger.warning.assert_called_once()
        assert "serving previously cached value" in mock_logger.warning.call_args[0][0]

    def test_refresh_failure_backs_off_one_ttl(self, monkeypatch):
        """After a failed refresh the cache waits a full TTL before retrying."""
        monkeypatch.delenv(TTL_ENV_VAR, raising=False)
        fetch = MagicMock(side_effect=["v1", RuntimeError("ssm blip"), "v2"])
        cached = ttl_cached()(fetch)

        assert cached() == "v1"
        cached._fetched_at -= DEFAULT_TTL_SECONDS + 1  # expire the entry
        assert cached() == "v1"  # refresh fails -> stale served, clock reset
        assert cached() == "v1"  # within the reset TTL -> no fetch attempt
        assert fetch.call_count == 2

    def test_first_fetch_failure_without_fallback_raises(self, monkeypatch):
        monkeypatch.delenv(TTL_ENV_VAR, raising=False)
        fetch = MagicMock(side_effect=RuntimeError("ssm down"))
        cached = ttl_cached()(fetch)

        with pytest.raises(RuntimeError, match="ssm down"):
            cached()

    def test_first_fetch_failure_uses_fallback_and_caches_it(self, monkeypatch):
        monkeypatch.delenv(TTL_ENV_VAR, raising=False)
        fetch = MagicMock(side_effect=RuntimeError("ssm down"))
        fallback = MagicMock(return_value="fallback-value")
        cached = ttl_cached(fallback=fallback)(fetch)

        with patch("hive.auth.secret_cache.logger") as mock_logger:
            assert cached() == "fallback-value"
        mock_logger.warning.assert_called_once()
        assert "using fallback value" in mock_logger.warning.call_args[0][0]
        assert cached() == "fallback-value"  # cached; no second fetch/fallback
        assert fetch.call_count == 1
        assert fallback.call_count == 1

    def test_cache_clear_forces_refetch(self, monkeypatch):
        monkeypatch.delenv(TTL_ENV_VAR, raising=False)
        fetch = MagicMock(side_effect=["v1", "v2"])
        cached = ttl_cached()(fetch)

        assert cached() == "v1"
        cached.cache_clear()
        assert cached() == "v2"
        assert fetch.call_count == 2

    def test_config_error_bypasses_fallback(self, monkeypatch):
        """SecretConfigError fails closed: never masked by the fallback."""
        monkeypatch.delenv(TTL_ENV_VAR, raising=False)
        fetch = MagicMock(side_effect=SecretConfigError("bad config"))
        fallback = MagicMock(return_value="open")
        cached = ttl_cached(fallback=fallback)(fetch)

        with pytest.raises(SecretConfigError, match="bad config"):
            cached()
        fallback.assert_not_called()

    def test_config_error_bypasses_stale_serve(self, monkeypatch):
        """SecretConfigError fails closed even when a stale value exists."""
        monkeypatch.setenv(TTL_ENV_VAR, "0")
        fetch = MagicMock(side_effect=["v1", SecretConfigError("bad config")])
        cached = ttl_cached()(fetch)

        assert cached() == "v1"
        with pytest.raises(SecretConfigError, match="bad config"):
            cached()

    def test_wrapper_preserves_function_metadata(self):
        def my_secret() -> str:
            """Docstring."""
            return "s"

        cached = ttl_cached()(my_secret)
        assert cached.__name__ == "my_secret"
        assert cached.__doc__ == "Docstring."


# ---------------------------------------------------------------------------
# Cached secret functions — rotation + fail-static per call site
# ---------------------------------------------------------------------------


def _ssm_mock(*values):
    """An SSM client mock whose get_parameter yields each value in turn."""
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.side_effect = [
        v if isinstance(v, Exception) else {"Parameter": {"Value": v}} for v in values
    ]
    return mock_ssm


class TestJwtSecretRotation:
    def test_rotation_applies_after_ttl(self):
        from hive.auth import tokens

        env = {k: v for k, v in os.environ.items() if k != "HIVE_JWT_SECRET"}
        env[TTL_ENV_VAR] = "0"
        with (
            patch.dict(os.environ, env, clear=True),
            patch("boto3.client", return_value=_ssm_mock("old-secret", "new-secret")),
        ):
            assert tokens._jwt_secret() == "old-secret"
            assert tokens._jwt_secret() == "new-secret"

    def test_refresh_failure_serves_stale_not_random(self):
        """An SSM blip must not mint a random secret (would invalidate tokens)."""
        from hive.auth import tokens

        env = {k: v for k, v in os.environ.items() if k != "HIVE_JWT_SECRET"}
        env[TTL_ENV_VAR] = "0"
        with (
            patch.dict(os.environ, env, clear=True),
            patch("boto3.client", return_value=_ssm_mock("old-secret", RuntimeError("blip"))),
        ):
            assert tokens._jwt_secret() == "old-secret"
            assert tokens._jwt_secret() == "old-secret"


class TestOriginVerifySecretRotation:
    def test_rotation_applies_after_ttl(self, monkeypatch):
        from hive.auth import tokens

        monkeypatch.delenv("HIVE_ORIGIN_VERIFY_SECRET", raising=False)
        monkeypatch.setenv("HIVE_ORIGIN_VERIFY_PARAM", "/hive/origin-verify-secret")
        monkeypatch.setenv(TTL_ENV_VAR, "0")
        with patch("boto3.client", return_value=_ssm_mock("old-ov", "new-ov")):
            assert tokens._origin_verify_secret() == "old-ov"
            assert tokens._origin_verify_secret() == "new-ov"

    def test_refresh_failure_serves_stale(self, monkeypatch):
        from hive.auth import tokens

        monkeypatch.delenv("HIVE_ORIGIN_VERIFY_SECRET", raising=False)
        monkeypatch.setenv("HIVE_ORIGIN_VERIFY_PARAM", "/hive/origin-verify-secret")
        monkeypatch.setenv(TTL_ENV_VAR, "0")
        with patch("boto3.client", return_value=_ssm_mock("old-ov", RuntimeError("blip"))):
            assert tokens._origin_verify_secret() == "old-ov"
            assert tokens._origin_verify_secret() == "old-ov"


class TestGoogleCredentialRotation:
    def test_client_id_rotation_applies_after_ttl(self):
        from hive.auth import google as g

        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_CLIENT_ID"}
        env[TTL_ENV_VAR] = "0"
        with (
            patch.dict(os.environ, env, clear=True),
            patch("boto3.client", return_value=_ssm_mock("old-id", "new-id")),
        ):
            assert g._google_client_id() == "old-id"
            assert g._google_client_id() == "new-id"

    def test_client_secret_refresh_failure_serves_stale(self):
        from hive.auth import google as g

        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_CLIENT_SECRET"}
        env[TTL_ENV_VAR] = "0"
        with (
            patch.dict(os.environ, env, clear=True),
            patch("boto3.client", return_value=_ssm_mock("old-cs", RuntimeError("blip"))),
        ):
            assert g._google_client_secret() == "old-cs"
            assert g._google_client_secret() == "old-cs"


class TestAllowedEmailsRotation:
    def test_rotation_applies_after_ttl(self):
        from hive.auth import google as g

        env = {k: v for k, v in os.environ.items() if k != "ALLOWED_EMAILS"}
        env[TTL_ENV_VAR] = "0"
        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "boto3.client",
                return_value=_ssm_mock('["old@example.com"]', '["new@example.com"]'),
            ),
        ):
            assert g._allowed_emails() == frozenset({"old@example.com"})
            assert g._allowed_emails() == frozenset({"new@example.com"})

    def test_refresh_failure_serves_stale_allowlist(self):
        """An SSM blip must not drop the allowlist to empty (= allow all)."""
        from hive.auth import google as g

        env = {k: v for k, v in os.environ.items() if k != "ALLOWED_EMAILS"}
        env[TTL_ENV_VAR] = "0"
        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "boto3.client",
                return_value=_ssm_mock('["kept@example.com"]', RuntimeError("blip")),
            ),
        ):
            assert g._allowed_emails() == frozenset({"kept@example.com"})
            assert g._allowed_emails() == frozenset({"kept@example.com"})

    def test_malformed_env_json_fails_closed(self, monkeypatch):
        """A typo in ALLOWED_EMAILS must raise, not silently allow all."""
        from hive.auth import google as g

        monkeypatch.setenv("ALLOWED_EMAILS", "not-json[")
        with pytest.raises(SecretConfigError, match="ALLOWED_EMAILS env var"):
            g._allowed_emails()

    def test_malformed_ssm_json_fails_closed(self):
        """Malformed allowlist JSON in SSM must raise, not silently allow all."""
        from hive.auth import google as g

        env = {k: v for k, v in os.environ.items() if k != "ALLOWED_EMAILS"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("boto3.client", return_value=_ssm_mock("{broken")),
            pytest.raises(SecretConfigError, match="SSM parameter"),
        ):
            g._allowed_emails()
