"""
Unit tests for AiDocProcessorStack.

DockerImageFunction is replaced with a lightweight stand-in (inline Python)
so that the suite runs without a Docker daemon.  All significant resources
(ECR repo, S3, Lambda, API Gateway, IAM policies, CloudFormation outputs)
are asserted against the synthesised CloudFormation template.

Run:
    cd services/ai-doc-processor/infra
    pytest tests/ -v
"""
import aws_cdk as core
import aws_cdk.assertions as assertions
import aws_cdk.aws_lambda as _lambda
import pytest
from unittest.mock import patch

from stack.ai_doc_processor_stack import AiDocProcessorStack

# ── Constants ─────────────────────────────────────────────────────────────────

TEST_ACCOUNT = "123456789012"
TEST_REGION  = "ap-southeast-2"
TEST_ENV     = core.Environment(account=TEST_ACCOUNT, region=TEST_REGION)


# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeDockerImageFunction(_lambda.Function):
    """Stand-in for DockerImageFunction that avoids a real Docker build.

    Accepts the same constructor arguments as DockerImageFunction but discards
    the ``code`` kwarg and substitutes a trivial inline handler so that CDK
    can synthesise the CloudFormation template without a running Docker daemon.

    All other properties (function_name, timeout, reserved_concurrent_executions)
    are forwarded to the parent Function constructor so that every assertion
    about those properties still holds.
    """

    def __init__(self, scope, id, *, function_name=None, timeout=None,
                 reserved_concurrent_executions=None, **kwargs):
        kwargs.pop("code", None)   # discard DockerImageCode — not needed in tests
        super().__init__(
            scope, id,
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=_lambda.InlineCode("def handler(e, c): pass"),
            function_name=function_name,
            timeout=timeout,
            reserved_concurrent_executions=reserved_concurrent_executions,
        )


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    """Synthesise AiDocProcessorStack once and share the template across all tests.

    Module scope means the CDK synthesis step runs only once for the entire
    file, keeping the suite fast even as more tests are added.
    """
    app = core.App(context={"env_name": "test"})
    with patch("stack.ai_doc_processor_stack._lambda.DockerImageFunction", _FakeDockerImageFunction):
        stack = AiDocProcessorStack(app, "TestStack", env=TEST_ENV)
    return assertions.Template.from_stack(stack)


# ── Lambda ────────────────────────────────────────────────────────────────────

def test_lambda_function_name(template):
    """Orchestrator Lambda name must follow OrchestratorContainer-<env_name>."""
    template.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": "OrchestratorContainer-test",
    })


def test_lambda_timeout_is_ten_minutes(template):
    """Lambda timeout must be 600 s (10 min) to accommodate long-running Bedrock calls."""
    template.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": "OrchestratorContainer-test",
        "Timeout": 600,
    })


def test_lambda_reserved_concurrency_is_one(template):
    """Reserved concurrency must be 1 to prevent runaway parallel invocations."""
    template.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": "OrchestratorContainer-test",
        "ReservedConcurrentExecutions": 1,
    })


# ── IAM ───────────────────────────────────────────────────────────────────────

def test_textract_policy_attached(template):
    """Lambda execution role must grant textract:* on all resources."""
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": "textract:*",
                    "Effect": "Allow",
                    "Resource": "*",
                })
            ])
        }
    })


def test_bedrock_invoke_model_policy_attached(template):
    """Lambda execution role must include bedrock:InvokeModel."""
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": assertions.Match.array_with(["bedrock:InvokeModel"]),
                    "Effect": "Allow",
                    "Resource": "*",
                })
            ])
        }
    })


def test_bedrock_streaming_policy_attached(template):
    """Lambda execution role must include bedrock:InvokeModelWithResponseStream."""
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": assertions.Match.array_with(
                        ["bedrock:InvokeModelWithResponseStream"]
                    ),
                    "Effect": "Allow",
                    "Resource": "*",
                })
            ])
        }
    })


# ── ECR ───────────────────────────────────────────────────────────────────────

def test_ecr_repository_created(template):
    """Stack must contain exactly one ECR repository."""
    template.resource_count_is("AWS::ECR::Repository", 1)


def test_ecr_repository_name_is_auto_generated(template):
    """ECR repository name is auto-generated by CDK (no hardcoded name) to avoid collisions."""
    resources = template.find_resources("AWS::ECR::Repository")
    assert len(resources) == 1
    repo = list(resources.values())[0]
    assert "RepositoryName" not in repo.get("Properties", {})


# ── S3 ────────────────────────────────────────────────────────────────────────

def test_s3_bucket_created(template):
    """Stack must contain at least one S3 bucket (the document-processing bucket)."""
    buckets = template.find_resources("AWS::S3::Bucket")
    assert len(buckets) >= 1, "Expected at least one S3::Bucket resource in the stack"


# ── API Gateway ───────────────────────────────────────────────────────────────

def test_api_gateway_rest_api_created(template):
    """Stack must define exactly one REST API."""
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)


def test_api_gateway_items_resource_path(template):
    """The /items path part must be defined in the REST API."""
    template.has_resource_properties("AWS::ApiGateway::Resource", {
        "PathPart": "items",
    })


def test_api_gateway_get_method_exists(template):
    """A GET method must be wired to the /items resource."""
    template.has_resource_properties("AWS::ApiGateway::Method", {
        "HttpMethod": "GET",
    })


# ── Outputs ───────────────────────────────────────────────────────────────────

def test_api_url_output_exported(template):
    """CloudFormation stack must export ApiUrl so callers can discover the endpoint."""
    template.has_output("ApiUrl", {})
