import aws_cdk as cdk
from aws_cdk import (
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_apigateway as apigw,
    CfnOutput,
    aws_ecr as ecr,
    aws_iam as iam,
    RemovalPolicy,
    Duration,
    # ── Observability additions ────────────────────────────────────────────
    aws_logs as logs,
    aws_logs_destinations as logs_destinations,
    aws_cloudwatch as cloudwatch,
)
from constructs import Construct
from constructs_lib.base_lambda_stack import BaseServiceStack


class AiDocProcessorStack(BaseServiceStack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, service_name="ai-doc-processor", **kwargs)

        account = self.node.try_get_context("account") or self.account
        region = self.node.try_get_context("region") or self.region

        print(f"Account: {account}, Region: {region}, Env Name: {self.env_name}")

        # ── ECR repository ─────────────────────────────────────────────────
        imagerepo = ecr.Repository(
            self,
            "AIDocProcessorImageRepo",
        )

        # ── S3 bucket (document uploads trigger the pipeline) ──────────────
        bucket = s3.Bucket(
            self,
            "AIDocProcessingBucket",
            removal_policy=RemovalPolicy.DESTROY,  # NOT for production
            auto_delete_objects=True,              # NOT for production
        )

        # ── Orchestrator Lambda (Docker image) ─────────────────────────────
        orchestrator_lambda_name = f"OrchestratorContainer-{self.env_name}"

        # ── CloudWatch Log Group (created before Lambda so CDK uses it) ───────
        # Passing log_group= to the Lambda constructor prevents CDK from
        # auto-generating a second log group that would conflict with this one.
        log_group = logs.LogGroup(
            self,
            "OrchestratorLogGroup",
            log_group_name=f"/aws/lambda/{orchestrator_lambda_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        orchestrator_lambda = _lambda.DockerImageFunction(
            self,
            "DocumentProcessingOrchestrator",
            function_name=orchestrator_lambda_name,
            log_group=log_group,
            code=_lambda.DockerImageCode.from_image_asset(
                "../app/orchestrator",  # folder containing Dockerfile
                build_args={
                    "MODEL_ID": (
                        f"arn:aws:bedrock:{region}:{account}:"
                        "inference-profile/apac.anthropic.claude-sonnet-4-20250514-v1:0"
                    ),
                    "PROMPT_BUCKET": "prompts-dev",
                    "PROMPT_KEY": "orchestrator/Orchestrator.txt",
                    "SERVICE_NAME": "ai-doc-processor",
                },
            ),
            timeout=Duration.minutes(10),
            reserved_concurrent_executions=1,  # limit to 1 concurrent execution
            environment={
                "ENV_NAME": self.env_name,
                "SERVICE_NAME": "ai-doc-processor",
                "POWERTOOLS_SERVICE_NAME": "ai-doc-processor",
                "POWERTOOLS_METRICS_NAMESPACE": "AIDocProcessor",
                "LOG_LEVEL": "INFO",
            },
        )

        # ── S3 trigger ─────────────────────────────────────────────────────
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(orchestrator_lambda),
        )

        # Grant the Lambda function read permissions on the S3 bucket
        bucket.grant_read(orchestrator_lambda)

        # ── IAM policies for Textract and Bedrock ──────────────────────────
        textract_policy = iam.PolicyStatement(
            actions=["textract:*"],
            resources=["*"],
        )
        bedrock_policy = iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
                "bedrock:ListFoundationModels",
                "bedrock:ListPrompts",
                "bedrock:GetPrompt",
                "bedrock:ListPromptVersions",
                "bedrock-agentcore:InvokeAgentRuntime",
            ],
            resources=["*"],
        )

        orchestrator_lambda.add_to_role_policy(textract_policy)
        orchestrator_lambda.add_to_role_policy(bedrock_policy)

        # Allow Lambda Powertools to publish custom EMF metrics to CloudWatch
        orchestrator_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "AIDocProcessor"}},
            )
        )

        # ── API Gateway ────────────────────────────────────────────────────
        api = apigw.LambdaRestApi(
            self,
            "AIDocProcessorApi",
            handler=orchestrator_lambda,
            proxy=False,
        )

        items = api.root.add_resource("items")
        items.add_method("GET")

        # ══════════════════════════════════════════════════════════════════
        # OBSERVABILITY — wires this service into the shared LogForwarderStack
        # ══════════════════════════════════════════════════════════════════

        # ── 2. Import the shared Log Forwarder Lambda (cross-stack) ────────
        # LogForwarderStack (common_services/log-forwarder) exports this ARN
        # as a named CloudFormation export.  Deploy LogForwarderStack first.
        log_forwarder_fn = _lambda.Function.from_function_arn(
            self,
            "ImportedLogForwarder",
            function_arn=cdk.Fn.import_value(f"LogForwarderArn-{self.env_name}"),
        )

        # ── 3. Grant CloudWatch Logs permission to invoke the forwarder ───────
        # add_permission() on an imported function is a no-op in CDK (it can't
        # verify the account, so it silently skips creating the resource).
        # CfnPermission always creates the AWS::Lambda::Permission resource.
        invoke_permission = _lambda.CfnPermission(
            self,
            "AllowCloudWatchLogsInvoke",
            action="lambda:InvokeFunction",
            function_name=cdk.Fn.import_value(f"LogForwarderArn-{self.env_name}"),
            principal=f"logs.{region}.amazonaws.com",
            source_arn=log_group.log_group_arn,
            source_account=account,
        )

        # ── 4. Subscription Filter → shared Log Forwarder Lambda ──────────
        # Every log line written by the orchestrator is forwarded to the
        # Log Forwarder Lambda in near-real time (< 15 s typical latency).
        # Explicit DependsOn ensures the Lambda::Permission exists before
        # CloudFormation attempts to create the SubscriptionFilter — AWS
        # validates invoke access at subscription creation time.
        subscription_filter = logs.SubscriptionFilter(
            self,
            "OrchestratorLogSubscription",
            log_group=log_group,
            destination=logs_destinations.LambdaDestination(log_forwarder_fn),
            filter_pattern=logs.FilterPattern.all_events(),
        )
        subscription_filter.node.add_dependency(invoke_permission)

        # ── 5. CloudWatch Alarms ───────────────────────────────────────────
        error_alarm = cloudwatch.Alarm(
            self,
            "OrchestratorErrorAlarm",
            alarm_name=f"OrchestratorContainer-{self.env_name}-Errors",
            alarm_description=(
                "Fires when the orchestrator Lambda reports one or more errors "
                "within a 1-minute window. Review OpenSearch Dashboards for details."
            ),
            metric=orchestrator_lambda.metric_errors(
                period=Duration.minutes(1),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        duration_alarm = cloudwatch.Alarm(
            self,
            "OrchestratorDurationAlarm",
            alarm_name=f"OrchestratorContainer-{self.env_name}-Duration-p95",
            alarm_description=(
                "Fires when the p95 execution duration exceeds 5 minutes "
                "(half the 10-minute timeout), signalling potential performance issues."
            ),
            metric=orchestrator_lambda.metric_duration(
                period=Duration.minutes(5),
                statistic="p95",
            ),
            threshold=300_000,  # 5 minutes in milliseconds
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        throttle_alarm = cloudwatch.Alarm(
            self,
            "OrchestratorThrottleAlarm",
            alarm_name=f"OrchestratorContainer-{self.env_name}-Throttles",
            alarm_description=(
                "Fires when the orchestrator Lambda is throttled. "
                "Consider increasing reserved_concurrent_executions."
            ),
            metric=orchestrator_lambda.metric_throttles(
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # ── 6. CloudFormation Outputs ──────────────────────────────────────
        CfnOutput(self, "ApiUrl", value=api.url)

        CfnOutput(
            self,
            "LogGroupName",
            value=log_group.log_group_name,
            description="CloudWatch Log Group for the orchestrator Lambda",
        )

        # Re-surface the OpenSearch Dashboards URL from the shared stack
        CfnOutput(
            self,
            "OpenSearchDashboardUrl",
            value=cdk.Fn.import_value(f"OpenSearchDashboardUrl-{self.env_name}"),
            description="OpenSearch Dashboards URL (provisioned by LogForwarderStack)",
        )
