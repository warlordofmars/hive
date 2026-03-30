"""
E2E tests for the deployed Hive MCP server.
Requires environment variables:
  HIVE_MCP_URL    — Function URL of the deployed MCP Lambda
  HIVE_API_URL    — Function URL of the deployed management API Lambda
  E2E_CLIENT_ID   — pre-registered OAuth client ID
  E2E_CLIENT_SECRET — client secret (if confidential) or empty
"""

from __future__ import annotations

import os
import pytest

MCP_URL = os.environ.get("HIVE_MCP_URL")
API_URL = os.environ.get("HIVE_API_URL")
E2E_TOKEN = os.environ.get("E2E_ACCESS_TOKEN")

pytestmark = pytest.mark.skipif(
    not MCP_URL or not E2E_TOKEN,
    reason="E2E env vars not set — skipping e2e tests",
)


@pytest.fixture(scope="module")
def token():
    return E2E_TOKEN


@pytest.mark.asyncio
class TestMCPE2E:
    async def test_remember_and_recall_e2e(self, token):
        """Full round-trip against the deployed Lambda."""
        import httpx

        async with httpx.AsyncClient(base_url=MCP_URL) as http:
            # POST remember
            resp = await http.post(
                "/mcp",
                json={
                    "method": "tools/call",
                    "params": {
                        "name": "remember",
                        "arguments": {"key": "e2e-test", "value": "e2e-value", "tags": ["e2e"]},
                    },
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200

            # POST recall
            resp2 = await http.post(
                "/mcp",
                json={
                    "method": "tools/call",
                    "params": {"name": "recall", "arguments": {"key": "e2e-test"}},
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp2.status_code == 200
            content = resp2.json()
            assert "e2e-value" in str(content)
