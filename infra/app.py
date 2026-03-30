#!/usr/bin/env python3
"""CDK app entry point for Hive infrastructure."""

import aws_cdk as cdk
from stacks.hive_stack import HiveStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-east-1",
)

HiveStack(app, "HiveStack", env=env)

app.synth()
