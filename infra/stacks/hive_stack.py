# Copyright (c) 2026 John Carter. All rights reserved.
"""
Hive CDK Stack — defines all AWS infrastructure.

Resources:
  - DynamoDB table (single-table design) with GSIs and TTL
  - Lambda function for the MCP server (FastMCP + Mangum)
  - Lambda function for the management API (FastAPI + Mangum)
  - Function URLs for both Lambdas (auth=NONE, TLS enforced)
  - IAM roles scoped to DynamoDB table and SSM access
  - SSM Parameter for JWT secret
  - S3 bucket + CloudFront distribution for the React management UI
  - GitHub Actions OIDC deploy role (one per environment)

Multi-environment usage:
  cdk deploy HiveStack         -c env=prod   # production
  cdk deploy HiveStack-dev     -c env=dev    # development
  cdk deploy HiveStack-staging -c env=staging
"""

from __future__ import annotations

import os

import aws_cdk as cdk
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as route53_targets
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_sns as sns
from aws_cdk import aws_ssm as ssm
from constructs import Construct

GITHUB_REPO = "warlordofmars/hive"


HOSTED_ZONE_NAME = "warlordofmars.net"


class HiveStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str = "prod",
        hosted_zone_id: str = "",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Apply cost-allocation tags to every resource in the stack.
        cdk.Tags.of(self).add("project", "hive")
        cdk.Tags.of(self).add("env", env_name)

        is_prod = env_name == "prod"

        # Non-prod stacks destroy resources on `cdk destroy` for easy teardown.
        # The JWT secret is always retained to prevent accidental key loss.
        data_removal = cdk.RemovalPolicy.RETAIN if is_prod else cdk.RemovalPolicy.DESTROY

        # GitHub Actions environment name used in the OIDC trust condition.
        # Must match the `environment:` key in the workflow job exactly.
        # prod → "production", dev → "development", others → env_name as-is.
        _github_env_map = {"prod": "production", "dev": "development"}
        github_env = _github_env_map.get(env_name, env_name)

        # ----------------------------------------------------------------
        # DynamoDB single table
        # ----------------------------------------------------------------
        # Table name is derived from env_name so arbitrary envs never conflict.
        # Prod keeps "hive" for backward compatibility with existing data.
        table_name = "hive" if is_prod else f"hive-{env_name}"

        table = dynamodb.Table(
            self,
            "HiveTable",
            table_name=table_name,
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=data_removal,
            # PITR is expensive — only enable in prod
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=is_prod
            ),
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

        # GSI 3 — ClientIndex: OAuth client lookups
        table.add_global_secondary_index(
            index_name="ClientIndex",
            partition_key=dynamodb.Attribute(name="GSI3PK", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ----------------------------------------------------------------
        # SSM Parameters
        # ----------------------------------------------------------------
        # All parameters use per-environment paths to prevent secret sharing.
        # Prod keeps legacy paths (no env suffix) for backward compatibility.
        def _ssm_path(name: str) -> str:
            return f"/hive/{name}" if is_prod else f"/hive/{env_name}/{name}"

        ssm_param_name = _ssm_path("jwt-secret")

        jwt_secret_param = ssm.StringParameter(
            self,
            "JwtSecret",
            parameter_name=ssm_param_name,
            string_value="CHANGE_ME_ON_FIRST_DEPLOY",
            description=f"Hive JWT signing secret ({env_name}) — rotate after first deploy",
            tier=ssm.ParameterTier.STANDARD,
        )
        # Always retain the JWT secret — losing it invalidates all issued tokens.
        jwt_secret_param.apply_removal_policy(cdk.RemovalPolicy.RETAIN)

        google_client_id_param = ssm.StringParameter(
            self,
            "GoogleClientId",
            parameter_name=_ssm_path("google-client-id"),
            string_value="CHANGE_ME_ON_FIRST_DEPLOY",
            description=f"Google OAuth 2.0 client ID ({env_name})",
            tier=ssm.ParameterTier.STANDARD,
        )
        google_client_id_param.apply_removal_policy(cdk.RemovalPolicy.RETAIN)

        google_client_secret_param = ssm.StringParameter(
            self,
            "GoogleClientSecret",
            parameter_name=_ssm_path("google-client-secret"),
            string_value="CHANGE_ME_ON_FIRST_DEPLOY",
            description=f"Google OAuth 2.0 client secret ({env_name})",
            tier=ssm.ParameterTier.STANDARD,
        )
        google_client_secret_param.apply_removal_policy(cdk.RemovalPolicy.RETAIN)

        allowed_emails_param = ssm.StringParameter(
            self,
            "AllowedEmails",
            parameter_name=_ssm_path("allowed-emails"),
            string_value="[]",
            description=f"JSON array of Google email addresses allowed to access Hive ({env_name}); empty = allow all",
            tier=ssm.ParameterTier.STANDARD,
        )
        allowed_emails_param.apply_removal_policy(cdk.RemovalPolicy.RETAIN)

        # ----------------------------------------------------------------
        # Shared Lambda code (Docker-bundled at cdk deploy time)
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

        # JWT issuer URL embedded in tokens — must be unique per environment.
        issuer_host = "hive" if is_prod else f"hive-{env_name}"
        custom_domain = f"{issuer_host}.{HOSTED_ZONE_NAME}"

        # ----------------------------------------------------------------
        # Route53 hosted zone + ACM certificate
        # ----------------------------------------------------------------
        # hosted_zone_id is passed as CDK context (-c hosted_zone_id=...) so that
        # the synth step in CI works without live AWS credentials.
        hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "HostedZone",
            hosted_zone_id=hosted_zone_id,
            zone_name=HOSTED_ZONE_NAME,
        )

        # ACM certificate must be in us-east-1 for CloudFront — this stack
        # deploys to us-east-1 by default, so no cross-region cert needed.
        certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=custom_domain,
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )

        app_version = os.environ.get("APP_VERSION", "dev")
        common_env = {
            "HIVE_TABLE_NAME": table.table_name,
            # Custom domain is the canonical issuer URL for all environments.
            "HIVE_ISSUER": f"https://{custom_domain}",
            # Tell both Lambdas which SSM parameter holds the JWT secret.
            "HIVE_JWT_SECRET_PARAM": ssm_param_name,
            # Google OAuth 2.0 SSM parameter paths
            "GOOGLE_CLIENT_ID_PARAM": google_client_id_param.parameter_name,
            "GOOGLE_CLIENT_SECRET_PARAM": google_client_secret_param.parameter_name,
            "ALLOWED_EMAILS_PARAM": allowed_emails_param.parameter_name,
            # APP_VERSION is injected at deploy time via the APP_VERSION env var.
            # Falls back to "dev" for local synth/deploy without a version set.
            "APP_VERSION": app_version,
            # Used by EMF metrics as the "Environment" dimension.
            "HIVE_ENV": env_name,
        }

        # In non-prod environments, bypass Google OAuth so automated e2e tests
        # can complete the PKCE flow without a real Google account.
        if not is_prod:
            common_env["HIVE_BYPASS_GOOGLE_AUTH"] = "1"

        # Tag every resource with the deployed version for operational visibility.
        cdk.Tags.of(self).add("version", app_version)

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
        google_client_id_param.grant_read(mcp_role)
        google_client_secret_param.grant_read(mcp_role)
        allowed_emails_param.grant_read(mcp_role)

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
            description=f"Hive MCP server (FastMCP) [{env_name}]",
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
        google_client_id_param.grant_read(api_role)
        google_client_secret_param.grant_read(api_role)
        allowed_emails_param.grant_read(api_role)

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
            description=f"Hive management API (FastAPI) [{env_name}]",
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
        # S3 bucket + CloudFront distribution for the React management UI
        # ----------------------------------------------------------------
        ui_bucket = s3.Bucket(
            self,
            "UiBucket",
            removal_policy=data_removal,
            auto_delete_objects=not is_prod,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # API origin — strip "https://" prefix and trailing "/" from the function URL
        api_origin_domain = cdk.Fn.select(2, cdk.Fn.split("/", api_url.url))
        mcp_origin_domain = cdk.Fn.select(2, cdk.Fn.split("/", mcp_url.url))

        api_cf_origin = origins.HttpOrigin(
            api_origin_domain,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
            origin_ssl_protocols=[cloudfront.OriginSslPolicy.TLS_V1_2],
        )
        mcp_cf_origin = origins.HttpOrigin(
            mcp_origin_domain,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
            origin_ssl_protocols=[cloudfront.OriginSslPolicy.TLS_V1_2],
        )

        api_behavior = cloudfront.BehaviorOptions(
            origin=api_cf_origin,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
        )
        mcp_behavior = cloudfront.BehaviorOptions(
            origin=mcp_cf_origin,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
        )

        distribution = cloudfront.Distribution(
            self,
            "UiDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(ui_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            additional_behaviors={
                "/api/*": api_behavior,
                "/oauth/*": api_behavior,
                "/.well-known/*": cloudfront.BehaviorOptions(
                    origin=api_cf_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
                "/health": cloudfront.BehaviorOptions(
                    origin=api_cf_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
                "/mcp*": mcp_behavior,
            },
            domain_names=[custom_domain],
            certificate=certificate,
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_page_path="/index.html",
                    response_http_status=200,
                ),
            ],
        )

        # Deploy built UI assets — only if ui/dist exists (built in CI before cdk deploy)
        ui_dist_path = os.path.join(os.path.dirname(__file__), "../../ui/dist")
        if os.path.exists(ui_dist_path):
            s3deploy.BucketDeployment(
                self,
                "DeployUi",
                sources=[s3deploy.Source.asset(ui_dist_path)],
                destination_bucket=ui_bucket,
                distribution=distribution,
                distribution_paths=["/*"],
            )

        # ----------------------------------------------------------------
        # Route53 alias records — A + AAAA → CloudFront distribution
        # ----------------------------------------------------------------
        cf_alias_target = route53.RecordTarget.from_alias(
            route53_targets.CloudFrontTarget(distribution)
        )
        route53.ARecord(
            self,
            "AliasRecord",
            zone=hosted_zone,
            record_name=issuer_host,
            target=cf_alias_target,
        )
        route53.AaaaRecord(
            self,
            "AliasRecordAAAA",
            zone=hosted_zone,
            record_name=issuer_host,
            target=cf_alias_target,
        )

        # ----------------------------------------------------------------
        # GitHub Actions OIDC deploy role
        # ----------------------------------------------------------------
        # One role per environment, scoped to its GitHub Actions environment.
        # The OIDC provider must already exist in the account (created once via
        # AWS console or: aws iam create-open-id-connect-provider).
        github_oidc = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
            self,
            "GitHubOidcProvider",
            f"arn:aws:iam::{self.account}:oidc-provider/token.actions.githubusercontent.com",
        )

        deploy_role = iam.Role(
            self,
            "GitHubActionsDeployRole",
            assumed_by=iam.WebIdentityPrincipal(
                github_oidc.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{GITHUB_REPO}:environment:{github_env}"
                        ),
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    }
                },
            ),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AdministratorAccess")
            ],
            description=f"GitHub Actions OIDC deploy role for Hive ({env_name})",
        )

        # ----------------------------------------------------------------
        # CloudWatch log groups — 30-day retention + saved Insights queries
        # ----------------------------------------------------------------
        mcp_log_group = logs.LogGroup(
            self,
            "McpLogGroup",
            log_group_name=f"/aws/lambda/{mcp_fn.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=data_removal,
        )

        api_log_group = logs.LogGroup(
            self,
            "ApiLogGroup",
            log_group_name=f"/aws/lambda/{api_fn.function_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=data_removal,
        )

        # Saved CloudWatch Insights queries for operational visibility.
        logs.QueryDefinition(
            self,
            "QueryErrors",
            query_definition_name=f"Hive/{env_name}/errors",
            query_string=logs.QueryString(
                fields=["@timestamp", "client_id", "tool", "error_message"],
                filter_statements=['level = "ERROR"'],
                sort="@timestamp desc",
            ),
            log_groups=[mcp_log_group, api_log_group],
        )

        logs.QueryDefinition(
            self,
            "QueryToolLatency",
            query_definition_name=f"Hive/{env_name}/tool-latency-p99",
            query_string=logs.QueryString(
                stats_statements=["pct(duration_ms, 99) as p99 by tool"],
                sort="p99 desc",
            ),
            log_groups=[mcp_log_group],
        )

        logs.QueryDefinition(
            self,
            "QueryTopClients",
            query_definition_name=f"Hive/{env_name}/top-clients",
            query_string=logs.QueryString(
                stats_statements=["count(*) as requests by client_id"],
                sort="requests desc",
            ),
            log_groups=[mcp_log_group, api_log_group],
        )

        logs.QueryDefinition(
            self,
            "QueryApiLatency",
            query_definition_name=f"Hive/{env_name}/api-latency",
            query_string=logs.QueryString(
                fields=["@timestamp", "method", "path", "status_code", "duration_ms"],
                filter_statements=["ispresent(method)"],
                sort="duration_ms desc",
                limit=100,
            ),
            log_groups=[api_log_group],
        )

        # ----------------------------------------------------------------
        # CloudWatch dashboard + alarms
        # ----------------------------------------------------------------
        dashboard_name = "Hive" if is_prod else f"Hive-{env_name}"

        # SNS topic for alarm notifications — prod only gets an email subscription
        # (subscription address can be set via the console after first deploy).
        alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            display_name=f"Hive alarms ({env_name})",
        )

        def _error_rate_alarm(
            construct_id: str,
            fn: lambda_.Function,
            label: str,
        ) -> cw.Alarm:
            """Lambda error rate alarm: > 5% over two consecutive 5-min periods."""
            errors = fn.metric_errors(period=cdk.Duration.minutes(5), statistic="Sum")
            invocations = fn.metric_invocations(
                period=cdk.Duration.minutes(5), statistic="Sum"
            )
            error_rate = cw.MathExpression(
                expression="100 * errors / MAX([errors, invocations])",
                using_metrics={"errors": errors, "invocations": invocations},
                label=f"{label} error rate %",
                period=cdk.Duration.minutes(5),
            )
            alarm = cw.Alarm(
                self,
                construct_id,
                metric=error_rate,
                threshold=5,
                evaluation_periods=2,
                datapoints_to_alarm=2,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                alarm_description=f"Hive {label} error rate > 5% ({env_name})",
            )
            if is_prod:
                alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))
            return alarm

        mcp_error_alarm = _error_rate_alarm("McpErrorRateAlarm", mcp_fn, "MCP")
        api_error_alarm = _error_rate_alarm("ApiErrorRateAlarm", api_fn, "API")

        # MCP P99 duration alarm: > 25s (out of 30s timeout)
        mcp_p99_alarm = cw.Alarm(
            self,
            "McpP99DurationAlarm",
            metric=mcp_fn.metric_duration(
                period=cdk.Duration.minutes(5), statistic="p99"
            ),
            threshold=25_000,  # milliseconds
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=f"Hive MCP P99 duration > 25s ({env_name})",
        )
        if is_prod:
            mcp_p99_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))

        # DynamoDB throttle alarm: any throttled requests over 5 min
        ddb_throttle_alarm = cw.Alarm(
            self,
            "DdbThrottleAlarm",
            metric=cw.Metric(
                namespace="AWS/DynamoDB",
                metric_name="ThrottledRequests",
                dimensions_map={"TableName": table.table_name},
                period=cdk.Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=f"Hive DynamoDB throttled requests > 0 ({env_name})",
        )
        if is_prod:
            ddb_throttle_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))

        # CloudFront 5xx error rate alarm: > 1% over 5 min
        cf_5xx_alarm = cw.Alarm(
            self,
            "CloudFront5xxAlarm",
            metric=cw.Metric(
                namespace="AWS/CloudFront",
                metric_name="5xxErrorRate",
                dimensions_map={
                    "DistributionId": distribution.distribution_id,
                    "Region": "Global",
                },
                period=cdk.Duration.minutes(5),
                statistic="Average",
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=f"Hive CloudFront 5xx rate > 1% ({env_name})",
        )
        if is_prod:
            cf_5xx_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))

        # Dashboard
        dashboard = cw.Dashboard(
            self,
            "HiveDashboard",
            dashboard_name=dashboard_name,
        )

        dashboard.add_widgets(
            cw.Row(
                cw.TextWidget(
                    markdown=f"# Hive — {env_name}  \nLambda · DynamoDB · CloudFront",
                    width=24,
                    height=1,
                ),
            ),
            # MCP Lambda row
            cw.Row(
                cw.TextWidget(markdown="## MCP Lambda", width=24, height=1),
            ),
            cw.Row(
                cw.GraphWidget(
                    title="MCP Invocations & Errors",
                    left=[
                        mcp_fn.metric_invocations(
                            period=cdk.Duration.minutes(5), statistic="Sum"
                        )
                    ],
                    right=[
                        mcp_fn.metric_errors(
                            period=cdk.Duration.minutes(5), statistic="Sum"
                        )
                    ],
                    width=8,
                ),
                cw.GraphWidget(
                    title="MCP Duration (ms)",
                    left=[
                        mcp_fn.metric_duration(
                            period=cdk.Duration.minutes(5), statistic="p50"
                        ),
                        mcp_fn.metric_duration(
                            period=cdk.Duration.minutes(5), statistic="p95"
                        ),
                        mcp_fn.metric_duration(
                            period=cdk.Duration.minutes(5), statistic="p99"
                        ),
                    ],
                    width=8,
                ),
                cw.GraphWidget(
                    title="MCP Throttles",
                    left=[
                        mcp_fn.metric_throttles(
                            period=cdk.Duration.minutes(5), statistic="Sum"
                        )
                    ],
                    width=8,
                ),
            ),
            # API Lambda row
            cw.Row(
                cw.TextWidget(markdown="## API Lambda", width=24, height=1),
            ),
            cw.Row(
                cw.GraphWidget(
                    title="API Invocations & Errors",
                    left=[
                        api_fn.metric_invocations(
                            period=cdk.Duration.minutes(5), statistic="Sum"
                        )
                    ],
                    right=[
                        api_fn.metric_errors(
                            period=cdk.Duration.minutes(5), statistic="Sum"
                        )
                    ],
                    width=8,
                ),
                cw.GraphWidget(
                    title="API Duration (ms)",
                    left=[
                        api_fn.metric_duration(
                            period=cdk.Duration.minutes(5), statistic="p50"
                        ),
                        api_fn.metric_duration(
                            period=cdk.Duration.minutes(5), statistic="p95"
                        ),
                        api_fn.metric_duration(
                            period=cdk.Duration.minutes(5), statistic="p99"
                        ),
                    ],
                    width=8,
                ),
                cw.GraphWidget(
                    title="API Throttles",
                    left=[
                        api_fn.metric_throttles(
                            period=cdk.Duration.minutes(5), statistic="Sum"
                        )
                    ],
                    width=8,
                ),
            ),
            # DynamoDB row
            cw.Row(
                cw.TextWidget(markdown="## DynamoDB", width=24, height=1),
            ),
            cw.Row(
                cw.GraphWidget(
                    title="DDB Read/Write Capacity",
                    left=[
                        cw.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="ConsumedReadCapacityUnits",
                            dimensions_map={"TableName": table.table_name},
                            period=cdk.Duration.minutes(5),
                            statistic="Sum",
                        ),
                        cw.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="ConsumedWriteCapacityUnits",
                            dimensions_map={"TableName": table.table_name},
                            period=cdk.Duration.minutes(5),
                            statistic="Sum",
                        ),
                    ],
                    width=8,
                ),
                cw.GraphWidget(
                    title="DDB Throttled Requests",
                    left=[
                        cw.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="ThrottledRequests",
                            dimensions_map={"TableName": table.table_name},
                            period=cdk.Duration.minutes(5),
                            statistic="Sum",
                        )
                    ],
                    width=8,
                ),
                cw.GraphWidget(
                    title="DDB System Errors",
                    left=[
                        cw.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="SystemErrors",
                            dimensions_map={"TableName": table.table_name},
                            period=cdk.Duration.minutes(5),
                            statistic="Sum",
                        )
                    ],
                    width=8,
                ),
            ),
            # CloudFront row
            cw.Row(
                cw.TextWidget(markdown="## CloudFront", width=24, height=1),
            ),
            cw.Row(
                cw.GraphWidget(
                    title="CF Requests",
                    left=[
                        cw.Metric(
                            namespace="AWS/CloudFront",
                            metric_name="Requests",
                            dimensions_map={
                                "DistributionId": distribution.distribution_id,
                                "Region": "Global",
                            },
                            period=cdk.Duration.minutes(5),
                            statistic="Sum",
                        )
                    ],
                    width=6,
                ),
                cw.GraphWidget(
                    title="CF Cache Hit Rate %",
                    left=[
                        cw.Metric(
                            namespace="AWS/CloudFront",
                            metric_name="CacheHitRate",
                            dimensions_map={
                                "DistributionId": distribution.distribution_id,
                                "Region": "Global",
                            },
                            period=cdk.Duration.minutes(5),
                            statistic="Average",
                        )
                    ],
                    width=6,
                ),
                cw.GraphWidget(
                    title="CF 4xx / 5xx Error Rate %",
                    left=[
                        cw.Metric(
                            namespace="AWS/CloudFront",
                            metric_name="4xxErrorRate",
                            dimensions_map={
                                "DistributionId": distribution.distribution_id,
                                "Region": "Global",
                            },
                            period=cdk.Duration.minutes(5),
                            statistic="Average",
                        ),
                        cw.Metric(
                            namespace="AWS/CloudFront",
                            metric_name="5xxErrorRate",
                            dimensions_map={
                                "DistributionId": distribution.distribution_id,
                                "Region": "Global",
                            },
                            period=cdk.Duration.minutes(5),
                            statistic="Average",
                        ),
                    ],
                    width=6,
                ),
                cw.GraphWidget(
                    title="CF Origin Latency (ms)",
                    left=[
                        cw.Metric(
                            namespace="AWS/CloudFront",
                            metric_name="OriginLatency",
                            dimensions_map={
                                "DistributionId": distribution.distribution_id,
                                "Region": "Global",
                            },
                            period=cdk.Duration.minutes(5),
                            statistic="p99",
                        )
                    ],
                    width=6,
                ),
            ),
            # EMF custom metrics row
            cw.Row(
                cw.TextWidget(markdown="## Hive Custom Metrics", width=24, height=1),
            ),
            cw.Row(
                cw.GraphWidget(
                    title="Tool Invocations",
                    left=[
                        cw.Metric(
                            namespace="Hive",
                            metric_name="ToolInvocations",
                            dimensions_map={"Environment": env_name},
                            period=cdk.Duration.minutes(5),
                            statistic="Sum",
                        )
                    ],
                    width=8,
                ),
                cw.GraphWidget(
                    title="Tool Errors",
                    left=[
                        cw.Metric(
                            namespace="Hive",
                            metric_name="ToolErrors",
                            dimensions_map={"Environment": env_name},
                            period=cdk.Duration.minutes(5),
                            statistic="Sum",
                        )
                    ],
                    width=8,
                ),
                cw.GraphWidget(
                    title="Token Validation Failures",
                    left=[
                        cw.Metric(
                            namespace="Hive",
                            metric_name="TokenValidationFailures",
                            dimensions_map={"Environment": env_name},
                            period=cdk.Duration.minutes(5),
                            statistic="Sum",
                        )
                    ],
                    width=8,
                ),
            ),
            # Alarms row
            cw.Row(
                cw.TextWidget(markdown="## Alarms", width=24, height=1),
            ),
            cw.Row(
                cw.AlarmWidget(alarm=mcp_error_alarm, title="MCP Error Rate", width=6),
                cw.AlarmWidget(alarm=api_error_alarm, title="API Error Rate", width=6),
                cw.AlarmWidget(alarm=mcp_p99_alarm, title="MCP P99 Duration", width=6),
                cw.AlarmWidget(alarm=ddb_throttle_alarm, title="DDB Throttles", width=6),
            ),
        )

        # ----------------------------------------------------------------
        # Outputs
        # ----------------------------------------------------------------
        cdk.CfnOutput(self, "McpFunctionUrl", value=mcp_url.url, description="MCP Lambda URL (direct)")
        cdk.CfnOutput(self, "ApiFunctionUrl", value=api_url.url, description="API Lambda URL (direct)")
        cdk.CfnOutput(self, "TableName", value=table.table_name, description="DynamoDB table name")
        cdk.CfnOutput(
            self,
            "HiveUrl",
            value=f"https://{custom_domain}",
            description="Hive base URL (custom domain)",
        )
        cdk.CfnOutput(
            self,
            "McpUrl",
            value=f"https://{custom_domain}/mcp",
            description="MCP server URL — use this in MCP client config",
        )
        cdk.CfnOutput(
            self,
            "UiUrl",
            value=f"https://{custom_domain}",
            description="Management UI URL",
        )
        cdk.CfnOutput(
            self,
            "DeployRoleArn",
            value=deploy_role.role_arn,
            description=f"GitHub Actions OIDC deploy role ARN ({env_name})",
        )
        cdk.CfnOutput(
            self,
            "AppVersion",
            value=app_version,
            description="Deployed application version",
        )
        cdk.CfnOutput(
            self,
            "DashboardUrl",
            value=f"https://{self.region}.console.aws.amazon.com/cloudwatch/home#dashboards:name={dashboard_name}",
            description="CloudWatch dashboard URL",
        )
