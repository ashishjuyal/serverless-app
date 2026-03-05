"""
LogForwarderStack
=================
A shared, reusable CDK stack that provisions:

  1. Amazon OpenSearch Service domain  — stores structured log documents
  2. Log Forwarder Lambda              — decodes CloudWatch Logs batches
                                         and bulk-indexes them into OpenSearch

Other service stacks (e.g. AiDocProcessorStack) subscribe their CloudWatch
Log Groups to the Forwarder Lambda ARN, which is exported as a CloudFormation
named export so any stack in the same account/region can reference it:

    Fn.import_value(f"LogForwarderArn-{env_name}")
    Fn.import_value(f"OpenSearchDashboardUrl-{env_name}")
    Fn.import_value(f"OpenSearchEndpoint-{env_name}")
"""

import aws_cdk as cdk
from aws_cdk import (
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_opensearchservice as opensearch,
    CfnOutput,
    Duration,
    RemovalPolicy,
)
from constructs import Construct
from constructs_lib.base_lambda_stack import BaseServiceStack


class LogForwarderStack(BaseServiceStack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, service_name="log-forwarder", **kwargs)

        account = self.node.try_get_context("account") or self.account
        region  = self.node.try_get_context("region")  or self.region

        # ── Amazon OpenSearch Service domain ──────────────────────────────
        # t3.small.search + 20 GB EBS is cost-efficient for a dev environment.
        # For production: upgrade to m6g.large.search + Multi-AZ + FGAC.
        domain = opensearch.Domain(
            self,
            "ObservabilityDomain",
            domain_name=f"common-logs-{self.env_name}",
            version=opensearch.EngineVersion.OPENSEARCH_2_11,
            capacity=opensearch.CapacityConfig(
                data_nodes=1,
                data_node_instance_type="t3.small.search",
            ),
            ebs=opensearch.EbsOptions(
                enabled=True,
                volume_size=20,  # GB — gp2 by default (adequate for dev)
            ),
            encryption_at_rest=opensearch.EncryptionAtRestOptions(enabled=True),
            node_to_node_encryption=True,
            enforce_https=True,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Allow all IAM principals in this account to access the domain.
        # In production, restrict this with fine-grained access control (FGAC)
        # and a Kibana master user bound to an SSO/SAML identity provider.
        domain.add_access_policies(
            iam.PolicyStatement(
                principals=[iam.AccountPrincipal(account)],
                actions=["es:*"],
                resources=[f"{domain.domain_arn}/*"],
            )
        )

        # ── Log Forwarder Lambda ───────────────────────────────────────────
        # Triggered by CloudWatch Logs subscription filters on any service
        # log group. Decodes the gzip+base64 envelope and bulk-indexes each
        # structured log event into the OpenSearch domain above.
        #
        # BundlingOptions installs opensearch-py at CDK deploy time using the
        # official Lambda build image (requires Docker to be running locally
        # and in CI).
        log_forwarder_lambda = _lambda.Function(
            self,
            "LogForwarderLambda",
            function_name=f"LogForwarder-{self.env_name}",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="lambda_function.lambda_handler",
            code=_lambda.Code.from_asset(
                "../app/log_forwarder",
                bundling=cdk.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        (
                            "pip install -r requirements.txt -t /asset-output "
                            "&& cp -au . /asset-output"
                        ),
                    ],
                ),
            ),
            timeout=Duration.minutes(1),
            memory_size=256,
            environment={
                "OPENSEARCH_ENDPOINT": domain.domain_endpoint,
                "INDEX_NAME": "lambda-logs",
                "AWS_REGION": region,
            },
        )

        # Grant the forwarder Lambda read/write access to OpenSearch
        domain.grant_read_write(log_forwarder_lambda)

        # ── CloudFormation Outputs (exported for cross-stack references) ───
        # Other stacks import these with:
        #   cdk.Fn.import_value(f"LogForwarderArn-{env_name}")
        #   cdk.Fn.import_value(f"OpenSearchDashboardUrl-{env_name}")
        #   cdk.Fn.import_value(f"OpenSearchEndpoint-{env_name}")

        CfnOutput(
            self,
            "LogForwarderArn",
            value=log_forwarder_lambda.function_arn,
            export_name=f"LogForwarderArn-{self.env_name}",
            description="Log Forwarder Lambda ARN — import into service stacks for subscription filters",
        )

        CfnOutput(
            self,
            "OpenSearchDashboardUrl",
            value=f"https://{domain.domain_endpoint}/_dashboards",
            export_name=f"OpenSearchDashboardUrl-{self.env_name}",
            description="OpenSearch Dashboards URL — sign in with AWS IAM credentials",
        )

        CfnOutput(
            self,
            "OpenSearchDomainEndpoint",
            value=domain.domain_endpoint,
            export_name=f"OpenSearchEndpoint-{self.env_name}",
            description="OpenSearch domain endpoint for direct REST API access",
        )
