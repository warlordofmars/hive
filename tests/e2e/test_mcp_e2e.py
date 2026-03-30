"""
E2E tests for the deployed Hive MCP server.
Requires environment variables:
  HIVE_MCP_URL    — Function URL of the deployed MCP Lambda
  HIVE_API_URL    — Function URL of the deployed management API Lambda
"""

from __future__ import annotations

import os

import pytest

MCP_URL = os.environ.get("HIVE_MCP_URL")

pytestmark = pytest.mark.skipif(
    not MCP_URL,
    reason="HIVE_MCP_URL not set — skipping e2e tests",
)


@pytest.mark.asyncio
class TestMCPE2E:
    async def test_remember_and_recall_e2e(self, live_token):
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
                headers={"Authorization": f"Bearer {live_token}"},
            )
            assert resp.status_code == 200

            # POST recall
            resp2 = await http.post(
                "/mcp",
                json={
                    "method": "tools/call",
                    "params": {"name": "recall", "arguments": {"key": "e2e-test"}},
                },
                headers={"Authorization": f"Bearer {live_token}"},
            )
            assert resp2.status_code == 200
            content = resp2.json()
            assert "e2e-value" in str(content)
