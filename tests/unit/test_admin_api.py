# Copyright (c) 2026 John Carter. All rights reserved.
"""
Unit tests for /admin/metrics and /admin/costs endpoints.

CloudWatch and Cost Explorer boto3 calls are mocked via unittest.mock so
tests run without any AWS credentials.
"""

from __future__ import annotations

import datetime
import os
from unittest.mock import MagicMock, patch

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

os.environ.setdefault("HIVE_TABLE_NAME", "hive-unit-admin")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("HIVE_JWT_SECRET", "unit-test-secret")
os.environ.pop("DYNAMODB_ENDPOINT", None)

_ADMIN_CLAIMS = {"sub": "admin-001", "role": "admin", "email": "admin@example.com"}
_USER_CLAIMS = {"sub": "user-001", "role": "user", "email": "user@example.com"}


def _create_table() -> None:
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="hive-unit-admin",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
            {"AttributeName": "GSI4PK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "KeyIndex",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "TagIndex",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "UserEmailIndex",
                "KeySchema": [
                    {"AttributeName": "GSI4PK", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _make_cw_response(metric_ids: list[str]) -> dict:
    """Build a minimal CloudWatch GetMetricData response."""
    ts = datetime.datetime(2026, 4, 1, 12, 0, tzinfo=datetime.timezone.utc)
    return {
        "MetricDataResults": [
            {"Id": mid, "Timestamps": [ts], "Values": [1.0]} for mid in metric_ids
        ]
    }


def _make_ce_response() -> dict:
    """Build a minimal Cost Explorer GetCostAndUsage response."""
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-03-01", "End": "2026-04-01"},
                "Groups": [
                    {
                        "Keys": ["AWS Lambda"],
                        "Metrics": {"UnblendedCost": {"Amount": "0.5000", "Unit": "USD"}},
                    },
                    {
                        "Keys": ["Amazon DynamoDB"],
                        "Metrics": {"UnblendedCost": {"Amount": "0.1200", "Unit": "USD"}},
                    },
                ],
            }
        ]
    }


@pytest.fixture()
def admin_tc():
    """TestClient authenticated as admin, with CW/CE boto3 calls mocked."""
    with mock_aws():
        _create_table()
        from hive.api import _auth as auth_mod
        from hive.api.main import app

        app.dependency_overrides[auth_mod.require_mgmt_user] = lambda: _ADMIN_CLAIMS
        yield TestClient(app)
        app.dependency_overrides.clear()


@pytest.fixture()
def user_tc():
    """TestClient authenticated as a non-admin user."""
    with mock_aws():
        _create_table()
        from hive.api import _auth as auth_mod
        from hive.api.main import app

        app.dependency_overrides[auth_mod.require_mgmt_user] = lambda: _USER_CLAIMS
        yield TestClient(app)
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /admin/metrics
# ---------------------------------------------------------------------------


class TestAdminMetrics:
    def test_returns_metrics_for_24h(self, admin_tc):
        metric_ids = [
            "inv_remember",
            "err_remember",
            "p99_remember",
            "inv_recall",
            "err_recall",
            "p99_recall",
            "inv_forget",
            "err_forget",
            "p99_forget",
            "inv_listmemories",
            "err_listmemories",
            "p99_listmemories",
            "inv_summarizecontext",
            "err_summarizecontext",
            "p99_summarizecontext",
            "tokens_issued",
            "token_failures",
        ]
        cw_resp = _make_cw_response(metric_ids)
        with patch("hive.api.admin._cloudwatch_client") as mock_cw_factory:
            mock_cw = MagicMock()
            mock_cw.get_metric_data.return_value = cw_resp
            mock_cw_factory.return_value = mock_cw

            resp = admin_tc.get("/api/admin/metrics?period=24h")

        assert resp.status_code == 200
        body = resp.json()
        assert body["period"] == "24h"
        assert "metrics" in body
        assert "inv_remember" in body["metrics"]
        assert body["metrics"]["inv_remember"]["values"] == [1.0]

    def test_returns_metrics_for_1h(self, admin_tc):
        with patch("hive.api.admin._cloudwatch_client") as mock_cw_factory:
            mock_cw = MagicMock()
            mock_cw.get_metric_data.return_value = {"MetricDataResults": []}
            mock_cw_factory.return_value = mock_cw

            resp = admin_tc.get("/api/admin/metrics?period=1h")

        assert resp.status_code == 200
        assert resp.json()["period"] == "1h"

    def test_returns_metrics_for_7d(self, admin_tc):
        with patch("hive.api.admin._cloudwatch_client") as mock_cw_factory:
            mock_cw = MagicMock()
            mock_cw.get_metric_data.return_value = {"MetricDataResults": []}
            mock_cw_factory.return_value = mock_cw

            resp = admin_tc.get("/api/admin/metrics?period=7d")

        assert resp.status_code == 200
        assert resp.json()["period"] == "7d"

    def test_invalid_period_returns_422(self, admin_tc):
        resp = admin_tc.get("/api/admin/metrics?period=99d")
        assert resp.status_code == 422

    def test_non_admin_gets_403(self, user_tc):
        resp = user_tc.get("/api/admin/metrics?period=24h")
        assert resp.status_code == 403

    def test_environment_in_response(self, admin_tc):
        with patch("hive.api.admin._cloudwatch_client") as mock_cw_factory:
            mock_cw = MagicMock()
            mock_cw.get_metric_data.return_value = {"MetricDataResults": []}
            mock_cw_factory.return_value = mock_cw

            resp = admin_tc.get("/api/admin/metrics?period=24h")

        assert "environment" in resp.json()


# ---------------------------------------------------------------------------
# /admin/costs
# ---------------------------------------------------------------------------


class TestAdminCosts:
    def setup_method(self):
        # Clear the module-level cache before each test
        import hive.api.admin as admin_mod

        admin_mod._cost_cache.clear()

    def test_returns_cost_data(self, admin_tc):
        with patch("hive.api.admin._ce_client") as mock_ce_factory:
            mock_ce = MagicMock()
            mock_ce.get_cost_and_usage.return_value = _make_ce_response()
            mock_ce_factory.return_value = mock_ce

            resp = admin_tc.get("/api/admin/costs")

        assert resp.status_code == 200
        body = resp.json()
        assert body["currency"] == "USD"
        assert len(body["monthly"]) == 1
        assert body["monthly"][0]["period"] == "2026-03-01"
        assert body["monthly"][0]["total"] == pytest.approx(0.62, abs=0.01)
        assert "AWS Lambda" in body["monthly"][0]["by_service"]

    def test_non_admin_gets_403(self, user_tc):
        resp = user_tc.get("/api/admin/costs")
        assert resp.status_code == 403

    def test_cache_is_used_on_second_call(self, admin_tc):
        with patch("hive.api.admin._ce_client") as mock_ce_factory:
            mock_ce = MagicMock()
            mock_ce.get_cost_and_usage.return_value = _make_ce_response()
            mock_ce_factory.return_value = mock_ce

            admin_tc.get("/api/admin/costs")
            admin_tc.get("/api/admin/costs")

            # CE should only be called once — second hit uses cache
            assert mock_ce.get_cost_and_usage.call_count == 1

    def test_cache_expires_after_ttl(self, admin_tc):
        with patch("hive.api.admin._ce_client") as mock_ce_factory:
            mock_ce = MagicMock()
            mock_ce.get_cost_and_usage.return_value = _make_ce_response()
            mock_ce_factory.return_value = mock_ce

            admin_tc.get("/api/admin/costs")

            # Backdate the cache entry so it appears expired
            import hive.api.admin as admin_mod

            env = admin_mod.ENVIRONMENT
            ts, data = admin_mod._cost_cache[env]
            admin_mod._cost_cache[env] = (ts - admin_mod._COST_CACHE_TTL - 1, data)

            admin_tc.get("/api/admin/costs")
            assert mock_ce.get_cost_and_usage.call_count == 2

    def test_note_and_environment_in_response(self, admin_tc):
        with patch("hive.api.admin._ce_client") as mock_ce_factory:
            mock_ce = MagicMock()
            mock_ce.get_cost_and_usage.return_value = _make_ce_response()
            mock_ce_factory.return_value = mock_ce

            resp = admin_tc.get("/api/admin/costs")

        body = resp.json()
        assert "note" in body
        assert "environment" in body
