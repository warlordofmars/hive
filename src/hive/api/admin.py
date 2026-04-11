# Copyright (c) 2026 John Carter. All rights reserved.
"""
Admin-only endpoints for CloudWatch metrics and AWS Cost Explorer data.
"""

from __future__ import annotations

import os
import time
from typing import Annotated, Any

import boto3
from fastapi import APIRouter, Depends, HTTPException, Query

from hive.api._auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])

NAMESPACE = "Hive"
ENVIRONMENT = os.environ.get("HIVE_ENV", os.environ.get("ENV", "local"))

# Seconds of CloudWatch data to fetch per period label
_PERIOD_SECONDS = {
    "1h": 3600,
    "24h": 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}
# CloudWatch resolution per period (stat window size in seconds)
_STAT_PERIOD = {
    "1h": 300,  # 5-min buckets
    "24h": 3600,  # 1-hour buckets
    "7d": 86400,  # 1-day buckets
    "30d": 86400,  # 1-day buckets
}

# Cost cache: store results in a module-level dict keyed by env to avoid
# hammering the Cost Explorer API ($0.01/request). TTL = 24 h.
_cost_cache: dict[str, tuple[float, Any]] = {}
_COST_CACHE_TTL = 86400  # 24 hours


def _cloudwatch_client():  # pragma: no cover
    return boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _ce_client():  # pragma: no cover
    return boto3.client("ce", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


def _build_metric_queries(period_label: str) -> list[dict[str, Any]]:
    """Return GetMetricData queries for all tracked metrics."""
    stat_period = _STAT_PERIOD[period_label]
    tools = ["remember", "recall", "forget", "list_memories", "summarize_context"]
    queries: list[dict[str, Any]] = []

    for tool in tools:
        safe_id = tool.replace("_", "")
        queries.append(
            {
                "Id": f"inv_{safe_id}",
                "MetricStat": {
                    "Metric": {
                        "Namespace": NAMESPACE,
                        "MetricName": "ToolInvocations",
                        "Dimensions": [
                            {"Name": "Environment", "Value": ENVIRONMENT},
                            {"Name": "operation", "Value": tool},
                        ],
                    },
                    "Period": stat_period,
                    "Stat": "Sum",
                },
            }
        )
        queries.append(
            {
                "Id": f"err_{safe_id}",
                "MetricStat": {
                    "Metric": {
                        "Namespace": NAMESPACE,
                        "MetricName": "ToolErrors",
                        "Dimensions": [
                            {"Name": "Environment", "Value": ENVIRONMENT},
                            {"Name": "operation", "Value": tool},
                        ],
                    },
                    "Period": stat_period,
                    "Stat": "Sum",
                },
            }
        )
        queries.append(
            {
                "Id": f"p99_{safe_id}",
                "MetricStat": {
                    "Metric": {
                        "Namespace": NAMESPACE,
                        "MetricName": "StorageLatencyMs",
                        "Dimensions": [
                            {"Name": "Environment", "Value": ENVIRONMENT},
                            {"Name": "operation", "Value": tool},
                        ],
                    },
                    "Period": stat_period,
                    "Stat": "p99",
                },
            }
        )

    queries.append(
        {
            "Id": "tokens_issued",
            "MetricStat": {
                "Metric": {
                    "Namespace": NAMESPACE,
                    "MetricName": "TokensIssued",
                    "Dimensions": [{"Name": "Environment", "Value": ENVIRONMENT}],
                },
                "Period": stat_period,
                "Stat": "Sum",
            },
        }
    )
    queries.append(
        {
            "Id": "token_failures",
            "MetricStat": {
                "Metric": {
                    "Namespace": NAMESPACE,
                    "MetricName": "TokenValidationFailures",
                    "Dimensions": [{"Name": "Environment", "Value": ENVIRONMENT}],
                },
                "Period": stat_period,
                "Stat": "Sum",
            },
        }
    )

    return queries


def _get_cloudwatch_metrics(period_label: str) -> dict[str, Any]:
    """Fetch metric data from CloudWatch and return structured results."""
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(seconds=_PERIOD_SECONDS[period_label])
    queries = _build_metric_queries(period_label)
    cw = _cloudwatch_client()

    try:
        resp = cw.get_metric_data(
            MetricDataQueries=queries,
            StartTime=start,
            EndTime=now,
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=502, detail=f"CloudWatch error: {exc}") from exc

    results: dict[str, Any] = {}
    for r in resp.get("MetricDataResults", []):
        results[r["Id"]] = {
            "timestamps": [t.isoformat() for t in r.get("Timestamps", [])],
            "values": r.get("Values", []),
        }
    return results


def _get_cost_data() -> dict[str, Any]:
    """Fetch cost data from Cost Explorer, cached for 24 h."""
    import datetime

    cached = _cost_cache.get(ENVIRONMENT)
    if cached and time.time() - cached[0] < _COST_CACHE_TTL:
        return cached[1]

    ce = _ce_client()
    today = datetime.date.today()
    # Last 6 full months + current month
    start_date = (today.replace(day=1) - datetime.timedelta(days=6 * 30)).replace(day=1)

    _tag_filter = {"Tags": {"Key": "project", "Values": ["hive"], "MatchOptions": ["EQUALS"]}}

    try:
        monthly_resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start_date.isoformat(), "End": today.isoformat()},
            Granularity="MONTHLY",
            Filter=_tag_filter,
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            Metrics=["UnblendedCost"],
        )
        daily_start = (today - datetime.timedelta(days=30)).isoformat()
        daily_resp = ce.get_cost_and_usage(
            TimePeriod={"Start": daily_start, "End": today.isoformat()},
            Granularity="DAILY",
            Filter=_tag_filter,
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            Metrics=["UnblendedCost"],
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=502, detail=f"Cost Explorer error: {exc}") from exc

    monthly: list[dict[str, Any]] = []
    for result in monthly_resp.get("ResultsByTime", []):
        period = result["TimePeriod"]["Start"]
        by_service = {
            g["Keys"][0]: float(g["Metrics"]["UnblendedCost"]["Amount"])
            for g in result.get("Groups", [])
        }
        total = sum(by_service.values())
        monthly.append({"period": period, "total": round(total, 4), "by_service": by_service})

    daily: list[dict[str, Any]] = []
    for result in daily_resp.get("ResultsByTime", []):
        day = result["TimePeriod"]["Start"]
        total = sum(
            float(g["Metrics"]["UnblendedCost"]["Amount"]) for g in result.get("Groups", [])
        )
        if total > 0:
            daily.append({"date": day, "total": round(total, 6)})

    data: dict[str, Any] = {
        "environment": ENVIRONMENT,
        "monthly": monthly,
        "daily": daily,
        "currency": "USD",
        "note": "Cost data lags ~24 h. Cached for 24 h.",
    }
    _cost_cache[ENVIRONMENT] = (time.time(), data)
    return data


@router.get(
    "/metrics",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Admin role required"},
        502: {"description": "CloudWatch error"},
    },
)
async def get_metrics(
    _claims: Annotated[dict[str, Any], Depends(require_admin)],
    period: Annotated[str, Query(pattern="^(1h|24h|7d|30d)$")] = "24h",
) -> dict[str, Any]:
    """Return CloudWatch metric time-series for the current environment.

    Admin-only. Period: 1h | 24h | 7d | 30d.
    """
    return {
        "period": period,
        "environment": ENVIRONMENT,
        "metrics": _get_cloudwatch_metrics(period),
    }


@router.get(
    "/costs",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Admin role required"},
        502: {"description": "Cost Explorer error"},
    },
)
async def get_costs(
    _claims: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    """Return AWS Cost Explorer monthly spend breakdown.

    Admin-only. Results cached for 24 h.
    """
    return _get_cost_data()
