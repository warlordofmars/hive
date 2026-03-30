"""
Hive CDK Stack — defines all AWS infrastructure.

Resources:
  - DynamoDB table (single-table design) with GSIs and TTL
  - Lambda function for the MCP server (FastMCP + FastAPI via Mangum)
  - Lambda function for the management API (FastAPI via Mangum)
  - Function URLs for both Lambdas (auth=NONE, TLS enforced)
  - IAM roles scoped to DynamoDB table access
  - SSM Parameter for JWT secret
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_ssm as ssm,
)
from constructs import Construct


class HiveStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ----------------------------------------------------------------
        # DynamoDB single table
        # ----------------------------------------------------------------
        table = dynamodb.Table(
            self,
            "HiveTable",
            table_name="hive",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
            # TTL attribute used by token and auth-code items
            time_to_live_attribute="ttl",
        )

        # GSI 1 — KeyIndex: look up memories by key
        table.add_global_secondary_index(
            index_name="KeyIndex",
            partition_key=dynamodb.Attribute(name="GSI1PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="GSI1SK", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI 2 — TagIndex: list memories by tag
        table.add_global_secondary_index(
            index_name="TagIndex",
            partition_key=dynamodb.Attribute(name="GSI2PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="GSI2SK", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI 3 — ClientIndex: client lookups (reserved for future cross-entity queries)
        table.add_global_secondary_index(
            index_name="ClientIndex",
            partition_key=dynamodb.Attribute(name="GSI3PK", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ----------------------------------------------------------------
        # SSM Parameter — JWT secret
        # ----------------------------------------------------------------
        jwt_secret_param = ssm.StringParameter(
            self,
            "JwtSecret",
            parameter_name="/hive/jwt-secret",
            string_value="CHANGE_ME_ON_FIRST_DEPLOY",
            description="Hive JWT signing secret — rotate after first deploy",
            tier=ssm.ParameterTier.STANDARD,
        )

        # ----------------------------------------------------------------
        # Shared Lambda code (from the built package)
        # ----------------------------------------------------------------
        lambda_code = lambda_.Code.from_asset(
            "..",
            bundling=cdk.BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                command=[
                    "bash",
                    "-c",
                    " && ".join(
                        [
                            "pip install uv --quiet --no-cache-dir",
                            # Export only runtime deps — exclude dev and infra (CDK) groups
                            "UV_CACHE_DIR=/tmp/uv-cache uv export --no-hashes --no-group dev --no-group infra -o /tmp/requirements.txt",
                            "pip install -r /tmp/requirements.txt -t /asset-output --quiet --no-cache-dir",
                            "cp -r src/hive /asset-output/hive",
                        ]
                    ),
                ],
            ),
        )

        common_env = {
            "HIVE_TABLE_NAME": table.table_name,
            # AWS_REGION is reserved by the Lambda runtime — do not set it
            "HIVE_ISSUER": f"https://hive.{self.account}.{self.region}.on.aws",
        }

        # ----------------------------------------------------------------
        # MCP Lambda
        # ----------------------------------------------------------------
        mcp_role = iam.Role(
            self,
            "McpLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        table.grant_read_write_data(mcp_role)
        jwt_secret_param.grant_read(mcp_role)

        mcp_fn = lambda_.Function(
            self,
            "McpFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="hive.server.lambda_handler",
            code=lambda_code,
            role=mcp_role,
            environment=common_env,
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            description="Hive MCP server (FastMCP)",
        )

        mcp_url = mcp_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.ALL],
                allowed_headers=["*"],
            ),
        )

        # ----------------------------------------------------------------
        # Management API Lambda
        # ----------------------------------------------------------------
        api_role = iam.Role(
            self,
            "ApiLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        table.grant_read_write_data(api_role)
        jwt_secret_param.grant_read(api_role)

        api_fn = lambda_.Function(
            self,
            "ApiFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="hive.api.main.lambda_handler",
            code=lambda_code,
            role=api_role,
            environment=common_env,
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            description="Hive management API (FastAPI)",
        )

        api_url = api_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.ALL],
                allowed_headers=["*"],
            ),
        )

        # ----------------------------------------------------------------
        # Outputs
        # ----------------------------------------------------------------
        cdk.CfnOutput(self, "McpFunctionUrl", value=mcp_url.url, description="MCP server URL")
        cdk.CfnOutput(self, "ApiFunctionUrl", value=api_url.url, description="Management API URL")
        cdk.CfnOutput(self, "TableName", value=table.table_name, description="DynamoDB table name")
