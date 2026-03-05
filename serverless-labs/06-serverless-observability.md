# Serverless Observability — ELK-style Stack with Amazon OpenSearch Service

Gain full visibility into your AI document-processing pipeline with structured logging, custom metrics, and searchable dashboards — without managing any Elasticsearch infrastructure.

---

## Table of Contents

1. [What This Lab Covers](#what-this-lab-covers)
2. [Architecture](#architecture)
3. [How the Observability Stack Works](#how-the-observability-stack-works)
4. [Prerequisites](#prerequisites)
5. [Part 1 — Structured Logging with AWS Lambda Powertools](#part-1--structured-logging-with-aws-lambda-powertools)
6. [Part 2 — Log Forwarder Lambda](#part-2--log-forwarder-lambda)
7. [Part 3 — CDK Infrastructure Changes](#part-3--cdk-infrastructure-changes)
8. [Part 4 — Deploy & Verify](#part-4--deploy--verify)
9. [Part 5 — OpenSearch Dashboards](#part-5--opensearch-dashboards)
10. [Verify & Validate](#verify--validate)
11. [Troubleshooting](#troubleshooting)
12. [Production Considerations](#production-considerations)

---

## What This Lab Covers

| Capability | Implementation |
|---|---|
| Structured JSON logs | **AWS Lambda Powertools** `Logger` — replaces all `print()` statements |
| Custom business metrics | **Powertools** `Metrics` + Embedded Metrics Format (EMF) → CloudWatch |
| Distributed tracing | **Powertools** `Tracer` → AWS X-Ray |
| Log storage + search | **Amazon OpenSearch Service** (managed Elasticsearch-compatible cluster) |
| Log shipping pipeline | **CloudWatch Logs subscription filter** → **Log Forwarder Lambda** → OpenSearch |
| Visualisation | **OpenSearch Dashboards** (managed Kibana equivalent) |
| Alerting | **CloudWatch Alarms** — errors, duration p95, throttles |

After completing this lab your observability pipeline looks like this:

```
Orchestrator Lambda
       │
       │  structured JSON via Powertools Logger + EMF Metrics
       │
       ▼
CloudWatch Logs (/aws/lambda/OrchestratorContainer-dev)
       │
       │  Subscription Filter  (near-real-time, < 15 s)
       │
       ▼
Log Forwarder Lambda
       │  decode base64 → decompress gzip → parse JSON → bulk index
       │
       ▼
Amazon OpenSearch Service  (index: lambda-logs)
       │
       ▼
OpenSearch Dashboards  ─────────────────── Discover · Visualise · Alerts
```

---

## Architecture

### Why OpenSearch Service (Option A)?

| Concern | Self-hosted ELK | Elastic Cloud | OpenSearch Service (this lab) |
|---|---|---|---|
| Infrastructure management | You manage EC2/ECS | Elastic manages | AWS manages |
| AWS IAM integration | Manual | Via proxy | Native |
| Cost model | EC2 + storage | Elastic subscription | Pay-per-use, no license fee |
| Kibana equivalent | OSS Kibana | Kibana | OpenSearch Dashboards |
| CDK support | EC2/ECS constructs | Not available | `aws_opensearchservice.Domain` |
| Data stays in AWS | Yes | No | Yes |

### Component map

```
┌─────────────────────────────────────────────────────────────────────┐
│  AWS Account (ap-southeast-2)                                       │
│                                                                     │
│  ┌──────────────────────┐     ┌──────────────────────────────────┐  │
│  │  Orchestrator Lambda │     │  CloudWatch                      │  │
│  │  (Docker, Python 3.12│────▶│  Log Group:                      │  │
│  │   + Powertools)      │     │  /aws/lambda/OrchestratorCont... │  │
│  └──────────────────────┘     └──────────┬───────────────────────┘  │
│                                          │ Subscription Filter      │
│                                          ▼                          │
│                               ┌──────────────────────┐             │
│                               │  Log Forwarder Lambda │             │
│                               │  (Python 3.12,        │             │
│                               │   opensearch-py)      │             │
│                               └──────────┬────────────┘             │
│                                          │ Bulk index               │
│                                          ▼                          │
│                               ┌──────────────────────┐             │
│                               │  OpenSearch Service   │             │
│                               │  (t3.small, 20 GB)    │             │
│                               │  index: lambda-logs   │             │
│                               └──────────┬────────────┘             │
│                                          │                          │
│                               ┌──────────▼────────────┐             │
│                               │  OpenSearch Dashboards│             │
│                               │  (managed Kibana)     │             │
│                               └───────────────────────┘             │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  CloudWatch Alarms:  Errors · Duration-p95 · Throttles        │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## How the Observability Stack Works

### Structured logging with Powertools

AWS Lambda Powertools replaces unstructured `print()` calls with a JSON-serialising logger that automatically captures:

- Log level (`INFO`, `WARNING`, `ERROR`)
- Service name and function name
- AWS request ID and correlation ID
- Cold start indicator
- Any `extra={}` fields you add

Every log line becomes a searchable JSON document in OpenSearch.

**Before (unstructured):**
```
Processing file 'invoice-001.pdf' from bucket 'ai-doc-bucket-dev'.
```

**After (structured JSON via Powertools):**
```json
{
  "level": "INFO",
  "location": "lambda_handler:133",
  "message": "Processing S3 object",
  "service": "ai-doc-processor",
  "timestamp": "2026-03-04T10:15:30.412Z",
  "xray_trace_id": "1-6789-...",
  "cold_start": false,
  "function_request_id": "abc-123-...",
  "bucket": "ai-doc-bucket-dev",
  "key": "invoice-001.pdf"
}
```

### Embedded Metrics Format (EMF)

Powertools `Metrics` writes business metrics inline with log output using CloudWatch's EMF specification. The Lambda runtime automatically extracts the metrics and publishes them to CloudWatch — zero API calls, zero extra latency.

```json
{
  "_aws": {
    "Timestamp": 1741086930000,
    "CloudWatchMetrics": [{
      "Namespace": "AIDocProcessor",
      "Dimensions": [["service"]],
      "Metrics": [{"Name": "InvoicesReceived", "Unit": "Count"}]
    }]
  },
  "service": "ai-doc-processor",
  "InvoicesReceived": 1
}
```

### Log shipping pipeline

```
CloudWatch Logs  →  Subscription Filter  →  Log Forwarder Lambda
```

1. CloudWatch Logs batches recent log events and compresses them with gzip.
2. The batch is base64-encoded and delivered to the Log Forwarder Lambda.
3. The forwarder decodes, decompresses, and parses each log event.
4. Structured JSON messages (from Powertools) are unpacked so every field is top-level in OpenSearch.
5. The forwarder bulk-indexes all events in a single OpenSearch API call.

---

## Prerequisites

- Completed [Lab 04 — GitHub Actions CI/CD](./04-github-actions-cicd.md)
- AWS CDK v2 installed (`npm install -g aws-cdk`)
- Python 3.12 virtual environment active in `services/ai-doc-processor/infra/`
- Docker running locally (for CDK bundling of the Log Forwarder Lambda)

---

## Part 1 — Structured Logging with AWS Lambda Powertools

All changes in this part are in `services/ai-doc-processor/app/orchestrator/`.

### Step 1: Add Powertools to requirements.txt

```
# services/ai-doc-processor/app/orchestrator/requirements.txt
boto3
strands-agents
strands-agents-tools
aws-lambda-powertools[all]
# Dependencies for AWS Textract and AWS Bedrock are included in boto3
```

The `[all]` extra installs the optional dependencies needed for X-Ray tracing (`aws-xray-sdk`) and validation utilities.

### Step 2: Update the Dockerfile

Add `SERVICE_NAME` and the Powertools environment variables so the logger picks them up automatically at runtime without any code change:

```dockerfile
# Build-time args (provided by CDK)
ARG LOG_LEVEL=INFO
ARG MODEL_ID
ARG PROMPT_BUCKET
ARG PROMPT_KEY
ARG AWS_REGION=ap-southeast-2
ARG SERVICE_NAME=ai-doc-processor
ARG OTEL_SERVICE_NAME=ai-doc-processor   # ← activated (was AgentDefault placeholder)

# Runtime env
ENV LOG_LEVEL=$LOG_LEVEL
ENV MODEL_ID=$MODEL_ID
ENV PROMPT_BUCKET=$PROMPT_BUCKET
ENV PROMPT_KEY=$PROMPT_KEY
ENV AWS_REGION=$AWS_REGION
ENV AWS_DEFAULT_REGION=$AWS_REGION
ENV SERVICE_NAME=$SERVICE_NAME
ENV OTEL_SERVICE_NAME=$OTEL_SERVICE_NAME
ENV POWERTOOLS_SERVICE_NAME=$SERVICE_NAME       # ← read by Powertools Logger
ENV POWERTOOLS_METRICS_NAMESPACE=AIDocProcessor  # ← read by Powertools Metrics
ENV DOCKER_CONTAINER=1
```

### Step 3: Update lambda_function.py

#### 3a. Add imports at the top of the file

```python
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
```

#### 3b. Add a `SERVICE_NAME` constant and initialise the three Powertools clients

Add this block directly after the existing environment variable reads:

```python
SERVICE_NAME = os.getenv("SERVICE_NAME", "ai-doc-processor")

# ── Observability clients ─────────────────────────────────────────────────────
logger  = Logger(service=SERVICE_NAME, level=LOG_LEVEL)
metrics = Metrics(namespace="AIDocProcessor", service=SERVICE_NAME)
tracer  = Tracer(service=SERVICE_NAME)
```

All three clients are **module-level singletons** — they are initialised once during the Lambda cold start and reused across warm invocations.

#### 3c. Replace `print()` with `logger` calls in every tool function

| Old | New |
|---|---|
| `print("Sending WhatsApp notification with the following data:", extracted_data)` | `logger.info("Sending WhatsApp notification", extra={"tool": "send_whatsapp_notification", "process_id": processId})` |
| `print("Posting the following data to SAP system:", extracted_data)` | `logger.info("Posting invoice to SAP", extra={"tool": "perform_invoice_posting_to_sap", "process_id": processId})` |
| `print("Validation is performed on the extracted data:", required_fields)` | `logger.info("Validating invoice data", extra={"tool": "validate_invoice_data", "process_id": processId, "required_fields": required_fields})` |
| `print("Invoking extraction Lambda:", ...)` | `logger.info("Invoking Textract extraction Lambda", extra={"tool": "textract_extraction_agent", "process_id": processId, ...})` |

Add a `metrics.add_metric()` call inside each tool to track invocation counts:

```python
metrics.add_metric(name="TextractExtractionAttempts", unit=MetricUnit.Count, value=1)
metrics.add_metric(name="InvoiceValidationAttempts",  unit=MetricUnit.Count, value=1)
metrics.add_metric(name="SapPostingAttempts",          unit=MetricUnit.Count, value=1)
metrics.add_metric(name="WhatsAppNotificationAttempts",unit=MetricUnit.Count, value=1)
```

#### 3d. Decorate the `lambda_handler` function

The three decorators must be applied in this exact order (outermost → innermost):

```python
@logger.inject_lambda_context(log_event=False)
@metrics.log_metrics(capture_cold_start_metric=True)
@tracer.capture_lambda_handler
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """..."""
```

**`inject_lambda_context`** — adds `function_request_id`, `function_name`, `cold_start` to every log line automatically.

**`log_metrics`** — flushes the EMF metric buffer at the end of every invocation. Setting `capture_cold_start_metric=True` emits a `ColdStart` metric automatically.

**`capture_lambda_handler`** — wraps the handler in an X-Ray subsegment so you can see it in the X-Ray service map.

#### 3e. Replace `print()` in the handler body

```python
# BEFORE
print("Starting Lambda handler execution.")
print(f"Received event: {json.dumps(event)}")
print("Invocation from S3 detected.")
print(f"Processing file '{object_key}' from bucket '{bucket_name}'.")
print("Orchestration result:", result)

# AFTER
logger.info("Lambda handler started", extra={"env": ENV_NAME, "model_id": MODEL_ID})
logger.info("S3 trigger detected — beginning invoice processing pipeline")
logger.info("Processing S3 object", extra={"bucket": bucket_name, "key": object_key})
metrics.add_metric(name="InvoicesReceived", unit=MetricUnit.Count, value=1)
logger.info("Orchestration pipeline completed successfully", extra={"result": str(result)})
metrics.add_metric(name="InvoicesProcessed", unit=MetricUnit.Count, value=1)
```

Wrap the agent call in a `try/except` to capture errors:

```python
try:
    result = orchestrator(...)
    logger.info("Orchestration pipeline completed successfully")
    metrics.add_metric(name="InvoicesProcessed", unit=MetricUnit.Count, value=1)
except Exception as exc:
    logger.exception(
        "Orchestration pipeline failed",
        extra={"bucket": bucket_name, "key": object_key, "error": str(exc)},
    )
    metrics.add_metric(name="InvoiceProcessingErrors", unit=MetricUnit.Count, value=1)
    raise
```

`logger.exception()` automatically attaches the full stack trace to the log event.

---

## Part 2 — Log Forwarder Lambda

Create a new directory for the forwarder:

```
services/ai-doc-processor/app/log_forwarder/
├── lambda_function.py
└── requirements.txt
```

### log_forwarder/requirements.txt

```
boto3
opensearch-py>=2.4.0
requests-aws4auth>=1.3.0
```

`opensearch-py` is the official OpenSearch Python client. It ships with `AWSV4SignerAuth` — a drop-in replacement for `requests-aws4auth` that uses the Lambda execution role's temporary credentials automatically.

### log_forwarder/lambda_function.py

The forwarder has three responsibilities:

1. **Decode** the CloudWatch Logs payload (base64 → gzip → JSON)
2. **Parse** structured log events from Powertools
3. **Bulk index** into OpenSearch

```python
"""
Log Forwarder Lambda
====================
Triggered by a CloudWatch Logs subscription filter. Decodes the compressed
log batch and bulk-indexes each event into Amazon OpenSearch Service.
"""

import base64
import gzip
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection, helpers

OPENSEARCH_ENDPOINT = os.environ["OPENSEARCH_ENDPOINT"]
INDEX_NAME           = os.environ.get("INDEX_NAME", "lambda-logs")
REGION               = os.environ.get("AWS_REGION",  "ap-southeast-2")


def _build_client() -> OpenSearch:
    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, REGION, "es")
    return OpenSearch(
        hosts=[{"host": OPENSEARCH_ENDPOINT, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


def _decode_cw_record(encoded: str) -> Dict[str, Any]:
    """Base64-decode and gzip-decompress a CloudWatch Logs payload."""
    compressed   = base64.b64decode(encoded)
    decompressed = gzip.decompress(compressed)
    return json.loads(decompressed)


def _build_documents(cw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert a CW Logs envelope into a list of OpenSearch documents.
    Structured JSON messages (from Powertools) are unpacked so every
    field becomes a top-level OpenSearch field.
    """
    log_group  = cw_data.get("logGroup",  "")
    log_stream = cw_data.get("logStream", "")
    documents  = []

    for event in cw_data.get("logEvents", []):
        try:
            doc = json.loads(event["message"])   # Powertools JSON
        except (json.JSONDecodeError, KeyError):
            doc = {"message": event.get("message", "")}

        # Enrich with CloudWatch metadata
        doc.setdefault("@timestamp", _epoch_ms_to_iso(event.get("timestamp")))
        doc["cw_log_group"]  = log_group
        doc["cw_log_stream"] = log_stream
        doc["cw_event_id"]   = event.get("id", "")
        documents.append(doc)

    return documents


def _epoch_ms_to_iso(epoch_ms: Any) -> str:
    if not epoch_ms:
        return datetime.now(timezone.utc).isoformat()
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    client   = _build_client()
    raw_data = event.get("awslogs", {}).get("data", "")

    if not raw_data:
        return {"statusCode": 200, "forwarded": 0}

    cw_data = _decode_cw_record(raw_data)

    if cw_data.get("messageType") == "CONTROL_MESSAGE":
        return {"statusCode": 200, "forwarded": 0}   # heartbeat — ignore

    documents = _build_documents(cw_data)
    if not documents:
        return {"statusCode": 200, "forwarded": 0}

    actions = [{"_index": INDEX_NAME, "_source": doc} for doc in documents]
    success_count, errors = helpers.bulk(client, actions, raise_on_error=False)

    if errors:
        print(f"OpenSearch bulk errors: {json.dumps(errors[:3])}")

    return {"statusCode": 200, "forwarded": success_count, "errors": len(errors)}
```

> **Note on the CloudWatch Logs event format:** CloudWatch Logs delivers log data to a subscription filter destination under the key `awslogs.data`. The value is a single base64-encoded, gzip-compressed JSON blob containing all log events buffered since the last delivery. The forwarder decodes this envelope and processes each event individually.

---

## Part 3 — CDK Infrastructure Changes

All changes are in `services/ai-doc-processor/infra/stack/ai_doc_processor_stack.py`.

### Step 1: Update the imports

Add four new services to the existing `aws_cdk` import tuple, and add `aws_cdk as cdk` at the top:

```python
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
    # ── Observability additions ──────────────────────────────────────────
    aws_logs as logs,
    aws_logs_destinations as logs_destinations,
    aws_opensearchservice as opensearch,
    aws_cloudwatch as cloudwatch,
)
```

All four are part of `aws-cdk-lib` — no changes to `infra/requirements.txt` are needed.

### Step 2: Add `SERVICE_NAME` build arg to the orchestrator Lambda

In the `DockerImageCode.from_image_asset()` call, add `"SERVICE_NAME"` to `build_args` and pass the Powertools environment variables as Lambda environment variables:

```python
orchestrator_lambda = _lambda.DockerImageFunction(
    self,
    "DocumentProcessingOrchestrator",
    function_name=orchestrator_lambda_name,
    code=_lambda.DockerImageCode.from_image_asset(
        "../app/orchestrator",
        build_args={
            "MODEL_ID": f"arn:aws:bedrock:{region}:{account}:...",
            "PROMPT_BUCKET": "prompts-dev",
            "PROMPT_KEY": "orchestrator/Orchestrator.txt",
            "SERVICE_NAME": "ai-doc-processor",    # ← ADD
        },
    ),
    timeout=Duration.minutes(10),
    reserved_concurrent_executions=1,
    environment={                                   # ← ADD
        "ENV_NAME": self.env_name,
        "SERVICE_NAME": "ai-doc-processor",
        "POWERTOOLS_SERVICE_NAME": "ai-doc-processor",
        "POWERTOOLS_METRICS_NAMESPACE": "AIDocProcessor",
        "LOG_LEVEL": "INFO",
    },
)
```

### Step 3: Grant the orchestrator Lambda permission to publish EMF metrics

```python
orchestrator_lambda.add_to_role_policy(
    iam.PolicyStatement(
        actions=["cloudwatch:PutMetricData"],
        resources=["*"],
        conditions={"StringEquals": {"cloudwatch:namespace": "AIDocProcessor"}},
    )
)
```

The condition restricts the permission to only the `AIDocProcessor` namespace — following least-privilege.

### Step 4: Declare the CloudWatch Log Group explicitly

```python
log_group = logs.LogGroup(
    self,
    "OrchestratorLogGroup",
    log_group_name=f"/aws/lambda/{orchestrator_lambda_name}",
    retention=logs.RetentionDays.ONE_MONTH,
    removal_policy=RemovalPolicy.DESTROY,
)
```

> **Why declare it explicitly?** By default, Lambda auto-creates its log group with no retention policy — logs accumulate forever. Declaring the log group in CDK lets you set `retention` and a `removal_policy`, and it becomes the object you attach the subscription filter to.

### Step 5: Create the OpenSearch domain

```python
domain = opensearch.Domain(
    self,
    "ObservabilityDomain",
    domain_name=f"ai-doc-logs-{self.env_name}",
    version=opensearch.EngineVersion.OPENSEARCH_2_11,
    capacity=opensearch.CapacityConfig(
        data_nodes=1,
        data_node_instance_type="t3.small.search",
    ),
    ebs=opensearch.EbsOptions(
        enabled=True,
        volume_size=20,   # GB
    ),
    encryption_at_rest=opensearch.EncryptionAtRestOptions(enabled=True),
    node_to_node_encryption=True,
    enforce_https=True,
    removal_policy=RemovalPolicy.DESTROY,
)

# Allow all IAM principals in this account to access the domain
domain.add_access_policies(
    iam.PolicyStatement(
        principals=[iam.AccountPrincipal(account)],
        actions=["es:*"],
        resources=[f"{domain.domain_arn}/*"],
    )
)
```

> **Provisioning time:** OpenSearch domains take 10–15 minutes to provision. CDK will show `CREATE_IN_PROGRESS` during this time — this is normal.

> **Dev vs production sizing:**
>
> | Config | Dev (this lab) | Production |
> |---|---|---|
> | Instance type | `t3.small.search` | `m6g.large.search` or larger |
> | Data nodes | 1 | 3+ (Multi-AZ) |
> | EBS volume | 20 GB | 100+ GB |
> | Dedicated master | No | Yes (3 nodes) |
> | Fine-grained access control | No | Yes (Kibana master user) |

### Step 6: Create the Log Forwarder Lambda

CDK's `BundlingOptions` installs the Python dependencies at deploy time using the Lambda build image (Docker must be running):

```python
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
                "bash", "-c",
                "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
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

# Grant the forwarder Lambda read/write access to the OpenSearch domain
domain.grant_read_write(log_forwarder_lambda)
```

### Step 7: Wire the subscription filter

```python
logs.SubscriptionFilter(
    self,
    "OrchestratorLogSubscription",
    log_group=log_group,
    destination=logs_destinations.LambdaDestination(log_forwarder_lambda),
    filter_pattern=logs.FilterPattern.all_events(),
)
```

`filter_pattern=logs.FilterPattern.all_events()` forwards every log line.  To forward only errors and warnings, use:

```python
filter_pattern=logs.FilterPattern.any_term("ERROR", "WARNING", "CRITICAL")
```

### Step 8: Add CloudWatch Alarms

```python
error_alarm = cloudwatch.Alarm(
    self, "OrchestratorErrorAlarm",
    alarm_name=f"OrchestratorContainer-{self.env_name}-Errors",
    metric=orchestrator_lambda.metric_errors(period=Duration.minutes(1), statistic="Sum"),
    threshold=1,
    evaluation_periods=1,
    datapoints_to_alarm=1,
    comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
)

duration_alarm = cloudwatch.Alarm(
    self, "OrchestratorDurationAlarm",
    alarm_name=f"OrchestratorContainer-{self.env_name}-Duration-p95",
    metric=orchestrator_lambda.metric_duration(period=Duration.minutes(5), statistic="p95"),
    threshold=300_000,   # 5 minutes in milliseconds (half the 10-min timeout)
    evaluation_periods=1,
    comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
)

throttle_alarm = cloudwatch.Alarm(
    self, "OrchestratorThrottleAlarm",
    alarm_name=f"OrchestratorContainer-{self.env_name}-Throttles",
    metric=orchestrator_lambda.metric_throttles(period=Duration.minutes(5), statistic="Sum"),
    threshold=1,
    evaluation_periods=1,
    comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
)
```

### Step 9: Add CloudFormation outputs

```python
CfnOutput(self, "ApiUrl", value=api.url)

CfnOutput(
    self, "OpenSearchDashboardUrl",
    value=f"https://{domain.domain_endpoint}/_dashboards",
    description="OpenSearch Dashboards URL",
)
CfnOutput(
    self, "OpenSearchDomainEndpoint",
    value=domain.domain_endpoint,
    description="OpenSearch domain endpoint for direct API access",
)
CfnOutput(
    self, "LogGroupName",
    value=log_group.log_group_name,
    description="CloudWatch Log Group for the orchestrator Lambda",
)
```

---

## Part 4 — Deploy & Verify

### Synth first (validates template without deploying)

```bash
cd services/ai-doc-processor/infra

# Activate virtual environment
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# Synth to validate CDK template
cdk synth -c account=<ACCOUNT_ID> -c region=ap-southeast-2
```

Expected output: no errors, a CloudFormation template printed to stdout.

### Deploy

```bash
cdk deploy AIDocProcessorStack \
  -c account=<ACCOUNT_ID> \
  -c region=ap-southeast-2
```

> **First deploy with OpenSearch will take 10–15 minutes** while the domain provisions. Subsequent deploys (code changes only) are much faster.

### Confirm the CloudFormation outputs

```bash
aws cloudformation describe-stacks \
  --stack-name AIDocProcessorStack \
  --region ap-southeast-2 \
  --query 'Stacks[0].Outputs' \
  --output table
```

Expected output:

```
---------------------------------------------------------------------
|                        DescribeStacks                             |
+----------------------------+--------------------------------------+
|  OutputKey                 |  OutputValue                         |
+----------------------------+--------------------------------------+
|  ApiUrl                    |  https://xxxx.execute-api.ap-...    |
|  OpenSearchDashboardUrl    |  https://search-ai-doc-logs-dev-... |
|  OpenSearchDomainEndpoint  |  search-ai-doc-logs-dev-xxx...      |
|  LogGroupName              |  /aws/lambda/OrchestratorContainer.. |
+----------------------------+--------------------------------------+
```

### Trigger a test invocation

Upload a file to the S3 bucket to trigger the orchestrator:

```bash
# Get the bucket name from CDK output or CLI
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name AIDocProcessorStack \
  --region ap-southeast-2 \
  --query 'Stacks[0].Outputs[?contains(OutputKey,`Bucket`)].OutputValue' \
  --output text)

# Upload a test invoice
echo '{"invoice_number": "INV-001", "amount": 1500}' > test-invoice.json
aws s3 cp test-invoice.json s3://${BUCKET}/test-invoice.json
```

### Check logs are flowing

```bash
# 1. Verify structured logs in CloudWatch
aws logs tail /aws/lambda/OrchestratorContainer-dev \
  --follow \
  --format short \
  --region ap-southeast-2
```

You should see JSON-formatted log lines, e.g.:

```json
{"level":"INFO","message":"Lambda handler started","service":"ai-doc-processor","cold_start":true,...}
{"level":"INFO","message":"S3 trigger detected — beginning invoice processing pipeline",...}
{"level":"INFO","message":"Processing S3 object","bucket":"...","key":"test-invoice.json",...}
```

```bash
# 2. Verify the Log Forwarder Lambda is being invoked
aws logs tail /aws/lambda/LogForwarder-dev \
  --follow \
  --format short \
  --region ap-southeast-2
```

Expected: lines like:
```
Forwarded 4/4 log events from /aws/lambda/OrchestratorContainer-dev → lambda-logs
```

---

## Part 5 — OpenSearch Dashboards

### Access Dashboards

1. Get the dashboard URL from the CloudFormation output:

```bash
aws cloudformation describe-stacks \
  --stack-name AIDocProcessorStack \
  --region ap-southeast-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`OpenSearchDashboardUrl`].OutputValue' \
  --output text
```

2. Open the URL in a browser. Sign in with your AWS IAM credentials (the domain access policy allows all account principals).

### Create an index pattern

1. In OpenSearch Dashboards, go to **Management → Index Patterns**.
2. Click **Create index pattern**.
3. Enter `lambda-logs*` as the pattern and click **Next step**.
4. Select `@timestamp` as the time field and click **Create index pattern**.

### Explore logs in Discover

1. Go to **Discover**.
2. Select the `lambda-logs*` index pattern.
3. Set the time range to **Last 1 hour**.
4. You should see all log events from the orchestrator Lambda as searchable JSON documents.

**Useful KQL filters:**

```
# Show only errors
level: "ERROR"

# Filter by service
service: "ai-doc-processor"

# Show cold starts
cold_start: true

# Show a specific tool invocation
tool: "textract_extraction_agent"

# Filter by S3 bucket
bucket: "ai-doc-processing-bucket-dev"
```

### Build a dashboard

Go to **Dashboard → Create dashboard → Add panel** and create:

**Panel 1 — Invoice Processing Rate (Line chart)**
- Metric: Count
- Split series by: `@timestamp` (Date histogram)
- Filter: `message: "InvoicesProcessed"`

**Panel 2 — Tool Invocation Counts (Bar chart)**
- Metric: Count
- Split series by: `tool.keyword`

**Panel 3 — Error Rate (Metric)**
- Metric: Count
- Filter: `level: "ERROR"`

**Panel 4 — Cold Starts (Metric)**
- Metric: Count
- Filter: `cold_start: true`

**Panel 5 — Log Table (Data table)**
- Columns: `@timestamp`, `level`, `message`, `tool`, `process_id`, `bucket`, `key`

### Create index template for better field mapping

Run this command to create an index template that maps timestamp and numeric fields correctly:

```bash
OPENSEARCH_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name AIDocProcessorStack \
  --region ap-southeast-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`OpenSearchDomainEndpoint`].OutputValue' \
  --output text)

# Create index template
aws es create-elasticsearch-domain \
  ... # use the REST API directly with AWS SigV4

# Or use the Dev Tools console in OpenSearch Dashboards:
# Go to Management → Dev Tools and paste:
PUT _index_template/lambda-logs-template
{
  "index_patterns": ["lambda-logs*"],
  "template": {
    "mappings": {
      "properties": {
        "@timestamp":   { "type": "date" },
        "level":        { "type": "keyword" },
        "message":      { "type": "text" },
        "service":      { "type": "keyword" },
        "tool":         { "type": "keyword" },
        "process_id":   { "type": "keyword" },
        "bucket":       { "type": "keyword" },
        "key":          { "type": "keyword" },
        "cold_start":   { "type": "boolean" },
        "cw_log_group": { "type": "keyword" }
      }
    }
  }
}
```

---

## Verify & Validate

Run these checks after a successful deployment:

#### ✅ 1. OpenSearch domain is active

```bash
aws opensearch describe-domain \
  --domain-name ai-doc-logs-dev \
  --region ap-southeast-2 \
  --query 'DomainStatus.Processing'
```

Expected: `false` (domain is ready when Processing = false).

#### ✅ 2. Log Forwarder Lambda exists and is configured

```bash
aws lambda get-function-configuration \
  --function-name LogForwarder-dev \
  --region ap-southeast-2 \
  --query '{State: State, Env: Environment.Variables}'
```

Expected: `State: "Active"` and `OPENSEARCH_ENDPOINT` set in environment variables.

#### ✅ 3. Subscription filter is active on the log group

```bash
aws logs describe-subscription-filters \
  --log-group-name /aws/lambda/OrchestratorContainer-dev \
  --region ap-southeast-2
```

Expected output includes a filter with `destinationArn` pointing to the Log Forwarder Lambda.

#### ✅ 4. OpenSearch index has documents

```bash
# Check document count in the lambda-logs index
curl -X GET \
  "https://${OPENSEARCH_ENDPOINT}/lambda-logs/_count" \
  --aws-sigv4 "aws:amz:ap-southeast-2:es" \
  --user "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}" \
  -H "x-amz-security-token: ${AWS_SESSION_TOKEN}"
```

Or use the Dev Tools console in OpenSearch Dashboards:

```
GET lambda-logs/_count
```

Expected: `{"count": N}` where N > 0 after at least one orchestrator invocation.

#### ✅ 5. CloudWatch Alarms are in OK state

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix OrchestratorContainer-dev \
  --region ap-southeast-2 \
  --query 'MetricAlarms[*].{Name:AlarmName, State:StateValue}'
```

Expected: all three alarms in `"OK"` or `"INSUFFICIENT_DATA"` state.

#### ✅ 6. Custom metrics are visible in CloudWatch

```bash
aws cloudwatch list-metrics \
  --namespace AIDocProcessor \
  --region ap-southeast-2
```

Expected: metrics like `InvoicesReceived`, `InvoicesProcessed`, `ColdStart`, `TextractExtractionAttempts`.

---

## Troubleshooting

#### `Domain creation failed: ValidationException`

OpenSearch domain names must be 3–28 characters, start with a lowercase letter, and contain only lowercase letters, numbers, and hyphens.

```bash
# Check the domain name length
echo -n "ai-doc-logs-dev" | wc -c   # must be ≤ 28
```

---

#### Log Forwarder Lambda times out

The default timeout is 1 minute. If OpenSearch is slow to respond:

1. Check the domain is not in `Processing` state.
2. Check network connectivity (if the domain is in a VPC, ensure the forwarder Lambda is in the same VPC).
3. Increase the forwarder timeout to 2 minutes in the CDK stack.

---

#### `No logs appearing in OpenSearch` after triggering the orchestrator

Check the subscription filter is invoking the forwarder:

```bash
aws logs tail /aws/lambda/LogForwarder-dev \
  --since 30m \
  --region ap-southeast-2
```

If no logs appear, the subscription filter may not be attached. Re-deploy and verify Step 7 of Part 3.

---

#### `AccessDeniedException` when forwarder tries to write to OpenSearch

The domain access policy allows all account principals via `iam.AccountPrincipal(account)`. If you see access denied errors:

1. Confirm the forwarder Lambda execution role ARN belongs to the correct AWS account.
2. Check there are no SCPs (Service Control Policies) in the organisation blocking `es:*`.
3. Verify `domain.grant_read_write(log_forwarder_lambda)` is present in the CDK stack.

---

#### `ModuleNotFoundError: opensearch` in the forwarder Lambda

The bundling step (`pip install -r requirements.txt`) may have failed silently. Check the CDK deploy output for bundling errors.

Manually test bundling:

```bash
docker run --rm \
  -v "$(pwd)/app/log_forwarder:/asset-input" \
  -v /tmp/lambda-bundle:/asset-output \
  public.ecr.aws/sam/build-python3.12 \
  bash -c "pip install -r /asset-input/requirements.txt -t /asset-output"

ls /tmp/lambda-bundle | grep opensearch
# Expected: opensearch  opensearch_py-2.x.x.dist-info
```

---

#### CloudWatch Alarm fires immediately on first deploy (`INSUFFICIENT_DATA → ALARM`)

This can happen if `treat_missing_data` is set to `BREACHING`. Verify the alarm configuration:

```bash
aws cloudwatch describe-alarms \
  --alarm-names "OrchestratorContainer-dev-Errors" \
  --region ap-southeast-2 \
  --query 'MetricAlarms[0].TreatMissingData'
```

Expected: `"notBreaching"`. If it shows `"breaching"`, the CDK change was not deployed correctly.

---

## Production Considerations

| Concern | Dev (this lab) | Production recommendation |
|---|---|---|
| OpenSearch sizing | `t3.small`, 1 node, 20 GB | `m6g.large` (or larger), 3+ nodes, Multi-AZ, dedicated master |
| Fine-grained access control | Disabled (IAM-only) | Enable FGAC with master user + role-based access |
| VPC placement | Public endpoint | Place in private subnets; access via VPN or bastion |
| Index lifecycle | No policy | Configure ISM (Index State Management) to roll over at 10 GB and delete after 90 days |
| Log retention | 1 month (CloudWatch) | Match your compliance requirement; configure OpenSearch ISM |
| Alarm notifications | None | Add SNS topic → email / Slack / PagerDuty |
| Dashboard access | AWS IAM | SAML/SSO via FGAC + identity provider |
| Backup | None | Enable automated snapshots to S3 |
| Cost optimisation | N/A | Use `UltraWarm` storage tier for logs older than 7 days (10× cheaper than hot storage) |
