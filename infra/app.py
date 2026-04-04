#!/usr/bin/env python3
# Copyright (c) 2026 John Carter. All rights reserved.
"""CDK app entry point for Hive infrastructure."""

import aws_cdk as cdk
from stacks.hive_stack import HiveStack

app = cdk.App()

# env_name is passed at deploy time: cdk deploy -c env=dev
# Defaults to "prod" if not provided.
env_name = app.node.try_get_context("env") or "prod"
stack_id = "HiveStack" if env_name == "prod" else f"HiveStack-{env_name}"

env = cdk.Environment(
    # account is passed at deploy time: cdk deploy -c account=123456789012
    # Falls back to the CloudFormation pseudo-parameter for synth without credentials.
    account=app.node.try_get_context("account") or cdk.Aws.ACCOUNT_ID,
    region=app.node.try_get_context("region") or "us-east-1",
)

HiveStack(app, stack_id, env_name=env_name, env=env)

app.synth()
