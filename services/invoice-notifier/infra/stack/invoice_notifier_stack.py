from aws_cdk import (
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_s3 as s3,
    CfnOutput,
    Duration,
    RemovalPolicy,
)
from constructs import Construct
from constructs_lib.base_lambda_stack import BaseServiceStack


class InvoiceNotifierStack(BaseServiceStack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, service_name="invoice-notifier", **kwargs)

        account = self.node.try_get_context("account") or self.account
        region = self.node.try_get_context("region") or self.region

        # S3 bucket to store processed invoices
        processed_bucket = s3.Bucket(
            self,
            "ProcessedInvoiceBucket",
            removal_policy=RemovalPolicy.DESTROY,  # safe cleanup for dev
            auto_delete_objects=True,
        )

        notifier_fn = _lambda.DockerImageFunction(
            self,
            "InvoiceNotifier",
            function_name=f"InvoiceNotifier-{self.env_name}",
            code=_lambda.DockerImageCode.from_image_asset(
                "../app/notifier",  # folder containing Dockerfile
                build_args={
                    "MODEL_ID": f"arn:aws:bedrock:{region}:{account}:inference-profile/apac.anthropic.claude-sonnet-4-20250514-v1:0",
                },
            ),
            timeout=Duration.minutes(5),
        )

        bedrock_policy = iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            resources=["*"],
        )
        notifier_fn.add_to_role_policy(bedrock_policy)

        api = apigw.LambdaRestApi(
            self, "InvoiceNotifierApi",
            handler=notifier_fn,
            proxy=False,
        )
        notify = api.root.add_resource("notify")
        notify.add_method("POST")

        CfnOutput(self, "NotifierApiUrl", value=api.url)
