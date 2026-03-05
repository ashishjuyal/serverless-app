"""
Unit tests for LogForwarderStack.

Code.from_asset (with BundlingOptions) is patched to return a trivial InlineCode
so the suite runs without a Docker daemon.  All significant resources
(OpenSearch domain, Lambda, IAM policies, CloudFormation exports)
are asserted against the synthesised CloudFormation template.

Run:
    cd common_services/log-forwarder/infra
    pytest tests/ -v
"""
import aws_cdk as core
import aws_cdk.assertions as assertions
import aws_cdk.aws_lambda as _lambda
import pytest
from unittest.mock import patch

from stack.log_forwarder_stack import LogForwarderStack

# ── Constants ─────────────────────────────────────────────────────────────────

TEST_ACCOUNT = "123456789012"
TEST_REGION  = "ap-southeast-2"
TEST_ENV     = core.Environment(account=TEST_ACCOUNT, region=TEST_REGION)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_from_asset(*args, **kwargs) -> _lambda.InlineCode:
    """Replace Code.from_asset (which triggers Docker bundling) with inline code."""
    return _lambda.InlineCode("def handler(e, c): pass")


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    """Synthesise LogForwarderStack once and share the template across all tests.

    Module scope means CDK synthesis runs only once for the entire file,
    keeping the suite fast even as more tests are added.
    """
    app = core.App(context={"env_name": "test"})
    # Patch Code.from_asset so BundlingOptions never invokes Docker
    with patch.object(_lambda.Code, "from_asset", side_effect=_fake_from_asset):
        stack = LogForwarderStack(app, "TestStack", env=TEST_ENV)
    return assertions.Template.from_stack(stack)


# ── OpenSearch Domain ─────────────────────────────────────────────────────────

def test_opensearch_domain_created(template):
    """Stack must define exactly one OpenSearch domain."""
    template.resource_count_is("AWS::OpenSearchService::Domain", 1)


def test_opensearch_domain_name_includes_env(template):
    """OpenSearch domain name must be common-logs-<env_name>."""
    template.has_resource_properties("AWS::OpenSearchService::Domain", {
        "DomainName": "common-logs-test",
    })


def test_opensearch_engine_version_is_opensearch_2_11(template):
    """OpenSearch domain must use OpenSearch 2.11."""
    template.has_resource_properties("AWS::OpenSearchService::Domain", {
        "EngineVersion": "OpenSearch_2.11",
    })


def test_opensearch_data_node_instance_type(template):
    """OpenSearch data node must use t3.small.search for cost efficiency."""
    template.has_resource_properties("AWS::OpenSearchService::Domain", {
        "ClusterConfig": assertions.Match.object_like({
            "InstanceType": "t3.small.search",
            "InstanceCount": 1,
        }),
    })


def test_opensearch_ebs_enabled(template):
    """OpenSearch EBS storage must be enabled with a 20 GB volume."""
    template.has_resource_properties("AWS::OpenSearchService::Domain", {
        "EBSOptions": assertions.Match.object_like({
            "EBSEnabled": True,
            "VolumeSize": 20,
        }),
    })


def test_opensearch_encryption_at_rest_enabled(template):
    """Encryption at rest must be enabled on the OpenSearch domain."""
    template.has_resource_properties("AWS::OpenSearchService::Domain", {
        "EncryptionAtRestOptions": {"Enabled": True},
    })


def test_opensearch_node_to_node_encryption_enabled(template):
    """Node-to-node encryption must be enabled on the OpenSearch domain."""
    template.has_resource_properties("AWS::OpenSearchService::Domain", {
        "NodeToNodeEncryptionOptions": {"Enabled": True},
    })


def test_opensearch_https_enforced(template):
    """HTTPS must be enforced (TLSSecurityPolicy set)."""
    template.has_resource_properties("AWS::OpenSearchService::Domain", {
        "DomainEndpointOptions": assertions.Match.object_like({
            "EnforceHTTPS": True,
        }),
    })


# ── Log Forwarder Lambda ──────────────────────────────────────────────────────

def test_lambda_function_created(template):
    """Stack must define exactly one Lambda function (the log forwarder)."""
    template.resource_count_is("AWS::Lambda::Function", 1)


def test_lambda_function_name_includes_env(template):
    """Log Forwarder Lambda name must be LogForwarder-<env_name>."""
    template.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": "LogForwarder-test",
    })


def test_lambda_runtime_is_python_3_12(template):
    """Log Forwarder Lambda must use the Python 3.12 runtime."""
    template.has_resource_properties("AWS::Lambda::Function", {
        "Runtime": "python3.12",
    })


def test_lambda_timeout_is_60_seconds(template):
    """Log Forwarder Lambda timeout must be 60 s (1 minute)."""
    template.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": "LogForwarder-test",
        "Timeout": 60,
    })


def test_lambda_memory_is_256_mb(template):
    """Log Forwarder Lambda memory must be 256 MB."""
    template.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": "LogForwarder-test",
        "MemorySize": 256,
    })


def test_lambda_env_has_index_name(template):
    """Log Forwarder Lambda must have INDEX_NAME environment variable set."""
    template.has_resource_properties("AWS::Lambda::Function", {
        "Environment": assertions.Match.object_like({
            "Variables": assertions.Match.object_like({
                "INDEX_NAME": "lambda-logs",
            })
        })
    })


def test_lambda_env_has_aws_region(template):
    """Log Forwarder Lambda must have AWS_REGION environment variable set."""
    template.has_resource_properties("AWS::Lambda::Function", {
        "Environment": assertions.Match.object_like({
            "Variables": assertions.Match.object_like({
                "AWS_REGION": TEST_REGION,
            })
        })
    })


# ── IAM ───────────────────────────────────────────────────────────────────────

def test_lambda_role_can_write_to_opensearch(template):
    """Lambda execution role must be granted ES HTTP write access to OpenSearch."""
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": assertions.Match.array_with(["es:ESHttpPut"]),
                    "Effect": "Allow",
                })
            ])
        }
    })


def test_lambda_role_can_read_from_opensearch(template):
    """Lambda execution role must be granted ES HTTP read access to OpenSearch."""
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": assertions.Match.array_with(["es:ESHttpGet"]),
                    "Effect": "Allow",
                })
            ])
        }
    })


# ── CloudFormation Outputs & Exports ─────────────────────────────────────────

def test_log_forwarder_arn_output_exists(template):
    """Stack must export the Log Forwarder Lambda ARN for cross-stack use."""
    template.has_output("LogForwarderArn", {})


def test_log_forwarder_arn_export_name(template):
    """LogForwarderArn export name must be LogForwarderArn-<env_name>."""
    template.has_output("LogForwarderArn", {
        "Export": {"Name": "LogForwarderArn-test"},
    })


def test_opensearch_dashboard_url_output_exists(template):
    """Stack must export the OpenSearch Dashboards URL."""
    template.has_output("OpenSearchDashboardUrl", {})


def test_opensearch_dashboard_url_export_name(template):
    """OpenSearchDashboardUrl export name must be OpenSearchDashboardUrl-<env_name>."""
    template.has_output("OpenSearchDashboardUrl", {
        "Export": {"Name": "OpenSearchDashboardUrl-test"},
    })


def test_opensearch_endpoint_output_exists(template):
    """Stack must export the OpenSearch domain endpoint."""
    template.has_output("OpenSearchDomainEndpoint", {})


def test_opensearch_endpoint_export_name(template):
    """OpenSearchDomainEndpoint export name must be OpenSearchEndpoint-<env_name>."""
    template.has_output("OpenSearchDomainEndpoint", {
        "Export": {"Name": "OpenSearchEndpoint-test"},
    })
