# Copyright (c) 2026 John Carter. All rights reserved.
"""
Invoke task definitions for Hive.

Usage:
    uv run inv --list                       # list all tasks
    uv run inv lint                         # lint + typecheck everything
    uv run inv fmt                          # auto-format Python source
    uv run inv test                         # run unit + integration + frontend tests
    uv run inv test-unit                    # unit tests only (no external deps)
    uv run inv test-integration             # integration tests (requires DynamoDB Local)
    uv run inv dev                          # start DynamoDB Local + API + UI dev servers
    uv run inv e2e                          # run e2e tests against deployed stack
    uv run inv deploy                       # deploy to AWS via CDK
    uv run inv synth                        # synthesize CDK template (no Docker bundling)
    uv run inv outputs                      # print CloudFormation stack outputs
"""

import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from invoke import task

ROOT = Path(__file__).parent
UI = ROOT / "ui"
INFRA = ROOT / "infra"
REGION = "us-east-1"
DYNAMO_CONTAINER = "hive-dynamo-local"
DYNAMO_PORT = 8000
API_PORT = 8001
UI_PORT = 5173


# ── Helpers ───────────────────────────────────────────────────────────────────


def _stack_name(env="prod"):
    return "HiveStack" if env == "prod" else f"HiveStack-{env}"


def _infer_next_version(ctx):
    """Infer the next semver from commits since the last tag using conventional commit rules."""
    try:
        last_tag = ctx.run("git describe --tags --abbrev=0", hide=True).stdout.strip()
    except Exception:
        last_tag = "v0.0.0"

    version = last_tag.lstrip("v")
    major, minor, patch = (int(x) for x in version.split("."))

    try:
        log = ctx.run(
            f"git log {last_tag}..HEAD --pretty=format:%s", hide=True
        ).stdout.strip()
    except Exception:
        log = ""

    bump = "patch"
    for msg in log.splitlines():
        if re.search(r"^[a-z]+(\(.+\))?!:|BREAKING CHANGE", msg):
            bump = "major"
            break
        elif re.search(r"^feat(\(.+\))?:", msg) and bump != "major":
            bump = "minor"

    if bump == "major":
        return f"{major + 1}.0.0"
    elif bump == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"



def _aws_account(ctx) -> str:
    """Get the current AWS account ID via STS."""
    return ctx.run(
        "aws sts get-caller-identity --query Account --output text",
        hide=True,
    ).stdout.strip()


def _cfn_output(ctx, key, env="prod"):
    stack = _stack_name(env)
    return ctx.run(
        f"aws cloudformation describe-stacks --stack-name {stack} --region {REGION}"
        f" --query \"Stacks[0].Outputs[?OutputKey=='{key}'].OutputValue\""
        " --output text",
        hide=True,
    ).stdout.strip()


def _wait_for_http(url: str, label: str, timeout: int = 30) -> bool:
    """Poll url until it responds or timeout (seconds) elapses. Returns True on success."""
    for _ in range(timeout):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(1)
    print(f"  {label} did not start in time")
    return False


# ── Lint ──────────────────────────────────────────────────────────────────────


@task
def lint_backend(ctx):
    """Lint backend Python with ruff (check + format)"""
    ctx.run("uv run ruff check src tests", pty=True)
    ctx.run("uv run ruff format --check src tests", pty=True)


@task
def lint_frontend(ctx):
    """Lint frontend with ESLint"""
    with ctx.cd(UI):
        ctx.run("npm run lint", pty=True)


@task
def lint_infra(ctx):
    """Lint CDK infra with ruff"""
    ctx.run("uv run ruff check infra", pty=True)


@task
def typecheck(ctx):
    """Type-check backend with mypy"""
    ctx.run("uv run mypy src/hive", pty=True)


@task(lint_backend, lint_frontend, lint_infra, typecheck)
def lint(ctx):
    """Lint + typecheck everything (backend + frontend + infra)"""


@task
def fmt(ctx):
    """Auto-format Python source with ruff"""
    ctx.run("uv run ruff format src tests", pty=True)
    ctx.run("uv run ruff check --fix src tests", pty=True)


# ── Audit ─────────────────────────────────────────────────────────────────────


@task
def audit_backend(ctx):
    """Security audit backend dependencies (pip-audit)"""
    ctx.run("uv run pip-audit", pty=True)


@task
def audit_frontend(ctx):
    """Security audit frontend dependencies (npm audit)"""
    with ctx.cd(UI):
        ctx.run("npm audit --audit-level=high", pty=True)


@task(audit_backend, audit_frontend)
def audit(ctx):
    """Audit all dependencies (backend + frontend)"""


# ── Test ──────────────────────────────────────────────────────────────────────


@task
def test_unit(ctx):
    """Run unit tests (no external deps)"""
    ctx.run("uv run pytest tests/unit -v", pty=True)


@task
def test_integration(ctx):
    """Run integration tests (requires DynamoDB Local on port 8000)"""
    env = {
        "DYNAMODB_ENDPOINT": f"http://localhost:{DYNAMO_PORT}",
        "AWS_ACCESS_KEY_ID": "local",
        "AWS_SECRET_ACCESS_KEY": "local",
        "AWS_DEFAULT_REGION": "us-east-1",
        "HIVE_JWT_SECRET": "test-secret",
    }
    ctx.run("uv run pytest tests/integration -v", env=env, pty=True)


@task
def test_frontend(ctx):
    """Run frontend vitest tests"""
    ci = bool(os.environ.get("CI"))
    extra = " -- --reporter=verbose" if ci else ""
    with ctx.cd(UI):
        ctx.run(f"npm test{extra}", pty=not ci)


@task(test_unit, test_integration, test_frontend)
def test(ctx):
    """Run all tests (unit + integration + frontend)"""


@task
def e2e(ctx, env="prod"):
    """Run e2e tests against the deployed stack. Fetches URLs from CloudFormation."""
    api_url = _cfn_output(ctx, "ApiFunctionUrl", env=env)
    mcp_url = _cfn_output(ctx, "McpFunctionUrl", env=env)
    ui_url = _cfn_output(ctx, "UiUrl", env=env)
    extra_env = {
        "HIVE_API_URL": api_url,
        "HIVE_MCP_URL": mcp_url,
        "HIVE_UI_URL": ui_url,
    }
    ctx.run(
        "uv run pytest tests/e2e -v",
        env=extra_env,
        pty=True,
    )


# ── Local dev ─────────────────────────────────────────────────────────────────


@task
def dynamo_start(ctx):
    """Start DynamoDB Local in Docker (detached)"""
    ctx.run(
        f"docker run -d --name {DYNAMO_CONTAINER} -p {DYNAMO_PORT}:{DYNAMO_PORT}"
        " amazon/dynamodb-local:latest",
        warn=True,
        hide=True,
    )
    print(f"DynamoDB Local running on port {DYNAMO_PORT}")


@task
def dynamo_stop(ctx):
    """Stop and remove the DynamoDB Local container"""
    ctx.run(f"docker rm -f {DYNAMO_CONTAINER}", warn=True, hide=True)
    print("DynamoDB Local stopped")


@task
def dev(ctx):
    """Start DynamoDB Local + management API + UI dev server (Ctrl-C to stop all)"""
    dev_env = {
        **os.environ,
        "HIVE_JWT_SECRET": os.environ.get("HIVE_JWT_SECRET", "dev-secret"),
        "HIVE_TABLE_NAME": "hive",
        "DYNAMODB_ENDPOINT": f"http://localhost:{DYNAMO_PORT}",
        "AWS_ACCESS_KEY_ID": "local",
        "AWS_SECRET_ACCESS_KEY": "local",
        "AWS_DEFAULT_REGION": "us-east-1",
    }
    ui_env = {
        **os.environ,
        "VITE_API_BASE": f"http://localhost:{API_PORT}",
    }

    # Start DynamoDB Local
    subprocess.run(
        ["docker", "rm", "-f", DYNAMO_CONTAINER],
        capture_output=True,
    )
    dynamo_proc = subprocess.Popen(
        [
            "docker",
            "run",
            "--name",
            DYNAMO_CONTAINER,
            "-p",
            f"{DYNAMO_PORT}:{DYNAMO_PORT}",
            "amazon/dynamodb-local:latest",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Start management API
    api_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "hive.api.main:app", f"--port={API_PORT}", "--reload"],
        cwd=ROOT,
        env=dev_env,
    )

    # Start UI dev server
    ui_proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=UI,
        env=ui_env,
    )

    procs = [dynamo_proc, api_proc, ui_proc]

    def _shutdown(sig, frame):
        print("\nShutting down...")
        for p in procs:
            p.terminate()
        subprocess.run(["docker", "rm", "-f", DYNAMO_CONTAINER], capture_output=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("\nServices starting:")
    print(f"  DynamoDB Local → http://localhost:{DYNAMO_PORT}")
    print(f"  Management API  → http://localhost:{API_PORT}")
    print(f"  UI dev server   → http://localhost:{UI_PORT}")
    print("\nPress Ctrl-C to stop all services.\n")

    for p in procs:
        p.wait()


# ── CDK ───────────────────────────────────────────────────────────────────────


@task
def synth(ctx, env="prod"):
    """Synthesize CDK template locally (skips Docker bundling). Use --env dev for dev stack."""
    account = _aws_account(ctx)
    stack = _stack_name(env)
    with ctx.cd(INFRA):
        ctx.run(
            f"uv run cdk synth {stack} --no-staging -c account={account} -c env={env}",
            pty=True,
        )


@task
def diff(ctx, env="prod"):
    """Show CDK diff against the deployed stack. Use --env dev for dev stack."""
    account = _aws_account(ctx)
    stack = _stack_name(env)
    with ctx.cd(INFRA):
        ctx.run(f"uv run cdk diff {stack} -c account={account} -c env={env}", pty=True)


@task
def deploy(ctx, env="prod"):
    """Deploy CDK stack to AWS. Use --env dev for dev stack."""
    account = _aws_account(ctx)
    stack = _stack_name(env)
    if env == "prod":
        # In CI, APP_VERSION is set by the release job. Locally, infer from commits.
        app_version = os.environ.get("APP_VERSION", _infer_next_version(ctx))
    else:
        short_sha = ctx.run("git rev-parse --short HEAD", hide=True).stdout.strip()
        app_version = f"{_infer_next_version(ctx)}-{env}.{short_sha}"

    # Build the React UI so assets are included in the S3 deployment.
    # CI does this explicitly before cdk deploy; local deploys must do the same.
    with ctx.cd(UI):
        ctx.run("npm install --silent", hide=True)
        ctx.run("npm run build", pty=True)

    with ctx.cd(INFRA):
        ctx.run(
            f"uv run cdk deploy {stack} --require-approval never"
            f" -c account={account} -c env={env}",
            env={"APP_VERSION": app_version},
            pty=True,
        )


@task
def outputs(ctx, env="prod"):
    """Print CloudFormation stack outputs. Use --env dev for dev stack."""
    stack = _stack_name(env)
    ctx.run(
        f"aws cloudformation describe-stacks --stack-name {stack}"
        f" --region {REGION}"
        " --query 'Stacks[0].Outputs' --output table --no-cli-pager",
        pty=True,
    )


# ── Lambda logs ───────────────────────────────────────────────────────────────


def _lambda_name(ctx, logical_id: str, env: str = "prod") -> str:
    """Look up the physical Lambda function name from the CloudFormation stack."""
    stack = _stack_name(env)
    return ctx.run(
        f"aws cloudformation describe-stack-resources --stack-name {stack}"
        f" --logical-resource-id {logical_id} --region {REGION}"
        " --query 'StackResources[0].PhysicalResourceId' --output text",
        hide=True,
    ).stdout.strip()


@task
def logs_mcp(ctx, env="prod"):
    """Tail MCP Lambda CloudWatch logs (Ctrl-C to stop)."""
    fn_name = _lambda_name(ctx, "McpFunction", env=env)
    ctx.run(f"aws logs tail /aws/lambda/{fn_name} --follow --region {REGION}", pty=True)


@task
def logs_api(ctx, env="prod"):
    """Tail management API Lambda CloudWatch logs (Ctrl-C to stop)."""
    fn_name = _lambda_name(ctx, "ApiFunction", env=env)
    ctx.run(f"aws logs tail /aws/lambda/{fn_name} --follow --region {REGION}", pty=True)


# ── Release ───────────────────────────────────────────────────────────────────


@task
def version(ctx):
    """Print the next semantic version inferred from conventional commits."""
    print(_infer_next_version(ctx))


@task
def back_merge(ctx):
    """Open a PR to merge main back into development after a prod release (auto-merges)."""
    # Check if main has commits not in development — nothing to do if branches are identical.
    ahead = ctx.run(
        "git fetch origin main development --quiet"
        " && git rev-list --count origin/development..origin/main",
        hide=True,
        warn=True,
    ).stdout.strip()
    if ahead == "0":
        print("main and development are already in sync — nothing to back-merge")
        return

    # Check if a PR already exists.
    existing = ctx.run(
        "gh pr list --base development --head main --state open --json number --jq '.[0].number'",
        hide=True,
        warn=True,
    ).stdout.strip()
    if existing:
        print(f"Back-merge PR #{existing} already open — enabling auto-merge")
        ctx.run(f"gh pr merge '{existing}' --auto --merge", warn=True)
        return

    result = ctx.run(
        "gh pr create"
        " --base development"
        " --head main"
        " --title 'chore: merge main back to development'"
        " --body 'Back-merge after prod release. Merge using **merge commit** (not squash).'",
        warn=True,
    )
    if result.ok:
        pr_url = result.stdout.strip().splitlines()[-1]
        print(f"PR created: {pr_url}")
        ctx.run(f"gh pr merge '{pr_url}' --auto --merge", warn=True)
    else:
        print(f"gh pr create failed: {result.stderr.strip()}")


# ── Clean ─────────────────────────────────────────────────────────────────────


@task
def clean(ctx):
    """Remove build artifacts (cdk.out, ui/dist, __pycache__, .pytest_cache, .mypy_cache)"""
    ctx.run(
        "find . -path ./.venv -prune -o -type d -name __pycache__ -print -exec rm -rf {} + 2>/dev/null; true"
    )
    ctx.run("rm -rf infra/cdk.out ui/dist .pytest_cache .mypy_cache .ruff_cache")
    print("Clean.")
