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
    # aws_logs_destinations not used — CfnSubscriptionFilter avoids Fn::ImportValue
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
            repository_name=f"ai-doc-processor-repo-{self.env_name}",
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
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

        orchestrator_lambda = _lambda.DockerImageFunction(
            self,
            "DocumentProcessingOrchestrator",
            function_name=orchestrator_lambda_name,
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

        # ── 1. Use the CDK-managed log group ──────────────────────────────────
        # cdk.json has useCdkManagedLogGroup:true, so CDK already creates a
        # LogGroup for this Lambda.  Do NOT create a second one — duplicate
        # LogGroupName in the same template causes ChangeSet validation to fail.
        log_group = orchestrator_lambda.log_group

        # ── 2. Construct the log-forwarder ARN directly ────────────────────
        # Using Fn::ImportValue("LogForwarderArn-dev") as DestinationArn in
        # AWS::Logs::SubscriptionFilter triggers EarlyValidation::ResourceExistenceCheck
        # failures at ChangeSet creation time.  Build the ARN from known values
        # (region/account/env_name) to give CloudFormation a plain resolvable string.
        log_forwarder_fn_name = f"LogForwarder-{self.env_name}"
        log_forwarder_arn = (
            f"arn:aws:lambda:{region}:{account}:function:{log_forwarder_fn_name}"
        )

        # ── 3a. Grant CloudWatch Logs permission to invoke the log-forwarder ─
        cfn_invoke_permission = _lambda.CfnPermission(
            self,
            "CloudWatchLogsInvokeLogForwarder",
            action="lambda:InvokeFunction",
            function_name=log_forwarder_fn_name,
            principal=f"logs.{region}.amazonaws.com",
            source_account=account,
            source_arn=log_group.log_group_arn,
        )

        # ── 3b. Subscription Filter → shared Log Forwarder Lambda ──────────
        # CfnSubscriptionFilter with a plain destination_arn avoids Fn::ImportValue.
        cfn_subscription = logs.CfnSubscriptionFilter(
            self,
            "OrchestratorLogSubscription",
            log_group_name=log_group.log_group_name,
            destination_arn=log_forwarder_arn,
            filter_pattern="",
        )
        cfn_subscription.add_depends_on(cfn_invoke_permission)

        # ── 4. CloudWatch Alarms ───────────────────────────────────────────
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

        # ── 5. CloudFormation Outputs ──────────────────────────────────────
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
