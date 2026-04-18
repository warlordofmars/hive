# Copyright (c) 2026 John Carter. All rights reserved.
"""
Unit tests for per-user usage quotas.

Tests the quota module, enforcement in server.py (MCP ToolError),
enforcement in memories.py (HTTP 429), and enforcement in clients.py (HTTP 429).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("HIVE_JWT_SECRET", "unit-test-secret")


class TestQuotaExceeded:
    def test_has_detail_attribute(self):
        from hive.quota import QuotaExceeded

        exc = QuotaExceeded("too many memories")
        assert exc.detail == "too many memories"
        assert str(exc) == "too many memories"


class TestCheckMemoryQuota:
    def test_allows_when_under_limit(self):
        from hive.quota import check_memory_quota

        storage = MagicMock()
        storage.count_memories.return_value = 10
        with patch.dict(os.environ, {"HIVE_QUOTA_MAX_MEMORIES": "500"}):
            check_memory_quota("user-1", storage)  # should not raise

    def test_raises_when_at_limit(self):
        from hive.quota import QuotaExceeded, check_memory_quota

        storage = MagicMock()
        storage.count_memories.return_value = 500
        with patch.dict(os.environ, {"HIVE_QUOTA_MAX_MEMORIES": "500"}):
            with pytest.raises(QuotaExceeded) as exc_info:
                check_memory_quota("user-1", storage)
            assert "500/500" in exc_info.value.detail

    def test_raises_when_over_limit(self):
        from hive.quota import QuotaExceeded, check_memory_quota

        storage = MagicMock()
        storage.count_memories.return_value = 600
        with (
            patch.dict(os.environ, {"HIVE_QUOTA_MAX_MEMORIES": "500"}),
            pytest.raises(QuotaExceeded),
        ):
            check_memory_quota("user-1", storage)

    def test_skips_none_user_id(self):
        from hive.quota import check_memory_quota

        storage = MagicMock()
        with patch.dict(os.environ, {"HIVE_QUOTA_MAX_MEMORIES": "0"}):
            check_memory_quota(None, storage)  # should not raise
        storage.count_memories.assert_not_called()

    def test_skips_exempt_user(self):
        from hive.quota import check_memory_quota

        storage = MagicMock()
        storage.count_memories.return_value = 9999
        with patch.dict(
            os.environ,
            {"HIVE_QUOTA_MAX_MEMORIES": "1", "HIVE_QUOTA_EXEMPT_USERS": "exempt-user"},
        ):
            check_memory_quota("exempt-user", storage)  # should not raise
        storage.count_memories.assert_not_called()

    def test_exempt_users_list_multiple(self):
        from hive.quota import check_memory_quota

        storage = MagicMock()
        storage.count_memories.return_value = 9999
        with patch.dict(
            os.environ,
            {"HIVE_QUOTA_MAX_MEMORIES": "1", "HIVE_QUOTA_EXEMPT_USERS": "a, b, c"},
        ):
            check_memory_quota("a", storage)
            check_memory_quota("b", storage)
            check_memory_quota("c", storage)
        storage.count_memories.assert_not_called()


class TestCheckClientQuota:
    def test_allows_when_under_limit(self):
        from hive.quota import check_client_quota

        storage = MagicMock()
        storage.count_clients.return_value = 5
        with patch.dict(os.environ, {"HIVE_QUOTA_MAX_CLIENTS": "10"}):
            check_client_quota("user-1", storage)  # should not raise

    def test_raises_when_at_limit(self):
        from hive.quota import QuotaExceeded, check_client_quota

        storage = MagicMock()
        storage.count_clients.return_value = 10
        with patch.dict(os.environ, {"HIVE_QUOTA_MAX_CLIENTS": "10"}):
            with pytest.raises(QuotaExceeded) as exc_info:
                check_client_quota("user-1", storage)
            assert "10/10" in exc_info.value.detail

    def test_skips_exempt_user(self):
        from hive.quota import check_client_quota

        storage = MagicMock()
        storage.count_clients.return_value = 9999
        with patch.dict(
            os.environ,
            {"HIVE_QUOTA_MAX_CLIENTS": "1", "HIVE_QUOTA_EXEMPT_USERS": "exempt-user"},
        ):
            check_client_quota("exempt-user", storage)  # should not raise
        storage.count_clients.assert_not_called()


class TestGetLimits:
    def test_get_memory_limit_returns_configured_value(self):
        from hive.quota import get_memory_limit

        with patch.dict(os.environ, {"HIVE_QUOTA_MAX_MEMORIES": "250"}):
            assert get_memory_limit() == 250

    def test_get_client_limit_returns_configured_value(self):
        from hive.quota import get_client_limit

        with patch.dict(os.environ, {"HIVE_QUOTA_MAX_CLIENTS": "5"}):
            assert get_client_limit() == 5


class TestMcpQuotaIntegration:
    """Verify remember() in server.py raises ToolError when quota exceeded."""

    def test_remember_raises_tool_error_on_quota_exceeded(self):
        import asyncio

        from fastmcp.exceptions import ToolError

        from hive.quota import QuotaExceeded

        with (
            patch("hive.server.validate_bearer_token") as mock_validate,
            patch("hive.server.check_rate_limit"),
            patch("hive.server.HiveStorage") as MockStorage,
            patch("hive.server.get_http_request", side_effect=RuntimeError("no request")),
            patch("hive.server.check_memory_quota") as mock_quota,
        ):
            mock_token = MagicMock()
            mock_token.client_id = "test-client"
            mock_token.scope = "memories:write"
            mock_validate.return_value = mock_token
            MockStorage.return_value.get_memory_by_key.return_value = None  # new memory path
            mock_quota.side_effect = QuotaExceeded("Memory quota reached (500/500).")

            from hive.server import remember

            with pytest.raises(ToolError) as exc_info:
                asyncio.get_event_loop().run_until_complete(remember("k", "v"))
            assert "quota" in str(exc_info.value).lower()

    def test_remember_does_not_check_quota_on_update(self):
        """Updating an existing memory must not trigger quota check."""
        import asyncio

        with (
            patch("hive.server.validate_bearer_token") as mock_validate,
            patch("hive.server.check_rate_limit"),
            patch("hive.server.HiveStorage") as MockStorage,
            patch("hive.server.get_http_request", side_effect=RuntimeError("no request")),
            patch("hive.server.check_memory_quota") as mock_quota,
            patch("hive.server.VectorStore"),
            patch("hive.server.emit_metric"),
        ):
            mock_token = MagicMock()
            mock_token.client_id = "test-client"
            mock_token.scope = "memories:write"
            mock_validate.return_value = mock_token

            existing_memory = MagicMock()
            existing_memory.value = "old-value"
            existing_memory.tags = []
            instance = MockStorage.return_value
            instance.get_memory_by_key.return_value = existing_memory
            # Response-meta builder reads count_memories; return a real int.
            instance.count_memories.return_value = 0
            instance.get_client.return_value = None

            from hive.server import remember

            asyncio.get_event_loop().run_until_complete(remember("k", "new-value"))
            mock_quota.assert_not_called()


class TestApiMemoryQuotaIntegration:
    """Verify create_memory raises 429 when memory quota exceeded."""

    def test_create_memory_returns_429_on_quota_exceeded(self):
        import asyncio

        from fastapi import HTTPException

        from hive.quota import QuotaExceeded

        with (
            patch("hive.api.memories.require_mgmt_user"),
            patch("hive.api.memories.check_memory_quota") as mock_quota,
        ):
            mock_quota.side_effect = QuotaExceeded("Memory quota reached (500/500).")

            from hive.api.memories import create_memory
            from hive.models import MemoryCreate

            body = MemoryCreate(key="k", value="v", tags=[])
            storage = MagicMock()
            storage.get_memory_by_key.return_value = None
            claims = {"sub": "user-1", "role": "user"}
            response = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    create_memory(body, response, claims, storage)
                )
            assert exc_info.value.status_code == 429
            assert "quota" in exc_info.value.detail.lower()


class TestApiClientQuotaIntegration:
    """Verify create_client raises 429 when client quota exceeded."""

    def test_create_client_returns_429_on_quota_exceeded(self):
        import asyncio

        from fastapi import HTTPException

        from hive.quota import QuotaExceeded

        with (
            patch("hive.api.clients.require_mgmt_user"),
            patch("hive.api.clients.check_client_quota") as mock_quota,
        ):
            mock_quota.side_effect = QuotaExceeded("Client quota reached (10/10).")

            from hive.api.clients import create_client
            from hive.models import ClientRegistrationRequest

            body = ClientRegistrationRequest(
                client_name="test",
                redirect_uris=["https://example.com/callback"],
            )
            storage = MagicMock()
            claims = {"sub": "user-1"}

            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(create_client(body, claims, storage))
            assert exc_info.value.status_code == 429
            assert "quota" in exc_info.value.detail.lower()
