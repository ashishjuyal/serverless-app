# Serverless Observability — ELK-style Stack with Amazon OpenSearch Service

Gain full visibility into your AI document-processing pipeline with structured logging, custom metrics, and searchable dashboards — without managing any Elasticsearch infrastructure.

---

## How This Demo Maps to the ELK Stack

Before diving into the implementation, it helps to understand the classic ELK stack and exactly which AWS service replaces each component in this lab.

### What is the ELK Stack?

ELK is a widely adopted open-source observability trio used to collect, store, search, and visualise logs at scale.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Classic ELK Stack                                    │
│                                                                             │
│   Applications / Servers                                                    │
│          │                                                                  │
│          ▼                                                                  │
│   ┌─────────────┐    ship &     ┌───────────────┐   index &   ┌──────────┐ │
│   │  Logstash   │  ─────────▶  │ Elasticsearch │  ────────▶  │  Kibana  │ │
│   │  (ingest)   │   transform   │  (store/search)│   query     │  (UI)    │ │
│   └─────────────┘               └───────────────┘             └──────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Component | Role |
|-----------|------|
| **Logstash** | Collects logs from many sources, parses and transforms them (e.g. JSON extraction, field enrichment), then ships them to Elasticsearch. Acts as the pipeline glue. |
| **Elasticsearch** | Distributed search and analytics engine. Stores log documents as JSON, builds inverted indexes for fast full-text search, and exposes a REST API for queries and aggregations. |
| **Kibana** | Web UI for Elasticsearch. Lets you explore raw logs (Discover), build charts/dashboards (Visualise), set up alerts, and create index patterns to describe the data shape. |

> **Why not use the ELK stack directly?**  Running Elasticsearch on EC2 means you manage JVM tuning, cluster sizing, OS patches, snapshots, and HA yourself — typically a dedicated ops task. OpenSearch Service eliminates that operational burden while remaining API-compatible with Elasticsearch 7.x.

---

### ELK → AWS Component Mapping

Every role played by an ELK component is covered by a managed AWS service in this lab.

```
┌──────────────────┬────────────────────────────────┬──────────────────────────────────────────────┐
│  ELK Component   │  AWS Equivalent                │  What it does in this demo                   │
├──────────────────┼────────────────────────────────┼──────────────────────────────────────────────┤
│ Log producer     │ Orchestrator Lambda            │ Emits structured JSON logs via                │
│ (application)    │ + AWS Lambda Powertools Logger │ Powertools instead of print()                │
├──────────────────┼────────────────────────────────┼──────────────────────────────────────────────┤
│                  │ CloudWatch Logs                │ Automatically captures every stdout/stderr   │
│ Logstash         │ Subscription Filter            │ line and forwards compressed log batches     │
│ (collect)        ├────────────────────────────────┤ to the Log Forwarder within ~15 seconds      │
│                  │ Log Forwarder Lambda           │ Decodes, decompresses, parses JSON,          │
│                  │ (common_services)              │ enriches with CW metadata, bulk-indexes      │
├──────────────────┼────────────────────────────────┼──────────────────────────────────────────────┤
│ Elasticsearch    │ Amazon OpenSearch Service      │ Managed single-node cluster (t3.small),      │
│ (store & search) │ (index: lambda-logs)           │ stores log documents, full-text search,      │
│                  │                                │ aggregations via OpenSearch REST API         │
├──────────────────┼────────────────────────────────┼──────────────────────────────────────────────┤
│ Kibana           │ OpenSearch Dashboards          │ Bundled with OpenSearch Service; same        │
│ (visualise)      │                                │ Discover/Visualise/Alerts workflow           │
├──────────────────┼────────────────────────────────┼──────────────────────────────────────────────┤
│ Beats / agents   │ (not needed)                   │ CloudWatch natively captures Lambda stdout — │
│ (sidecar shippers│                                │ no agent installation or sidecar required    │
└──────────────────┴────────────────────────────────┴──────────────────────────────────────────────┘
```

### Side-by-side Data Flow

```
Classic ELK                             This Demo
───────────────────────────────         ─────────────────────────────────────
App writes log line                     Orchestrator Lambda writes JSON log
       │                                       │  (Powertools Logger)
       ▼                                       ▼
Filebeat / Logstash agent          CloudWatch Logs (automatic capture)
       │  parse + enrich                       │  Subscription Filter
       ▼                                       ▼
Logstash pipeline                   Log Forwarder Lambda
       │  bulk index                            │  decode → parse → enrich → bulk index
       ▼                                       ▼
Elasticsearch cluster               Amazon OpenSearch Service
       │  REST API                              │  OpenSearch REST API
       ▼                                       ▼
Kibana                              OpenSearch Dashboards
       │  Discover / Visualise                  │  Discover / Visualise / Alerts
       ▼                                       ▼
  Developer / SRE                       Developer / SRE
```

### Key Differences from Classic ELK

| Aspect | Classic ELK | This Demo |
|--------|-------------|-----------|
| **Infrastructure** | You provision and patch Elasticsearch nodes | AWS manages the OpenSearch cluster |
| **Log shipping agent** | Filebeat or Logstash agent on each server | CloudWatch Logs subscription filter — no agent |
| **Pipeline code** | Logstash configuration DSL (grok filters, mutate) | Python Lambda function (full language flexibility) |
| **Authentication** | X-Pack security or open | FGAC — username/password + IAM; admin password stored in Secrets Manager |
| **Scaling** | Manual shard/replica tuning | AWS handles scaling within instance class |
| **Cost model** | EC2 + EBS + Elastic licence | Pay-per-node-hour, no licence fee |
| **Index pattern** | `logstash-*` (conventional) | `lambda-logs` (explicit) |

---

## Table of Contents

1. [What This Lab Covers](#what-this-lab-covers)
2. [Architecture](#architecture)
3. [How the Observability Stack Works](#how-the-observability-stack-works)
4. [Prerequisites](#prerequisites)
5. [Part 1 — Structured Logging with AWS Lambda Powertools](#part-1--structured-logging-with-aws-lambda-powertools)
6. [Part 2 — Log Forwarder Lambda (common_services)](#part-2--log-forwarder-lambda-common_services)
7. [Part 3 — CDK Infrastructure Changes](#part-3--cdk-infrastructure-changes)
   - [3a — LogForwarderStack (common_services)](#part-3a--logforwarderstack-common_services)
   - [3b — AiDocProcessorStack (services)](#part-3b--aidocprocessorstack-services)
8. [Part 4 — CDK Deployment Steps](#part-4--cdk-deployment-steps)
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
| Dashboard authentication | **Fine-Grained Access Control (FGAC)** — username/password login; admin password auto-generated and stored in **AWS Secrets Manager** |

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

## Part 2 — Log Forwarder Lambda (common_services)

The Log Forwarder is a **shared service** — any service in the mono-repo can subscribe its CloudWatch Log Group to it. It lives under `common_services/` rather than inside any single service's `app/` folder.

```
common_services/
└── log-forwarder/
    ├── app/
    │   └── log_forwarder/
    │       ├── lambda_function.py     ← Lambda handler
    │       └── requirements.txt       ← opensearch-py, boto3
    └── infra/
        ├── app.py                     ← CDK entry point
        ├── cdk.json
        ├── requirements.txt           ← aws-cdk-lib, constructs
        ├── requirements-dev.txt       ← pytest
        └── stack/
            └── log_forwarder_stack.py ← owns OpenSearch domain + Lambda
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

The observability stack spans **two independent CDK stacks** in this mono-repo:

| Stack | Location | Owns |
|---|---|---|
| `LogForwarderStack` | `common_services/log-forwarder/infra/` | OpenSearch domain + Log Forwarder Lambda |
| `AiDocProcessorStack` | `services/ai-doc-processor/infra/` | Log Group, Subscription Filter, CloudWatch Alarms |

The stacks are linked by a **named CloudFormation export**: `LogForwarderStack` exports the Lambda ARN; `AiDocProcessorStack` imports it with `cdk.Fn.import_value()`.

---

### Part 3a — LogForwarderStack (common_services)

File: `common_services/log-forwarder/infra/stack/log_forwarder_stack.py`

#### Step 1: Imports

```python
import json

import aws_cdk as cdk
from aws_cdk import (
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_opensearchservice as opensearch,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
    Duration,
    RemovalPolicy,
)
from constructs import Construct
from constructs_lib.base_lambda_stack import BaseServiceStack
```

> **Why `json` and `secretsmanager`?** FGAC requires a master-user password. Secrets Manager auto-generates a random password at deploy time; `json.dumps()` is used when building the secret template string.

#### Step 2: Secrets Manager — master-user password

A random 16-character password is auto-generated at deploy time and stored in Secrets Manager. The domain master user is `admin`.

```python
master_user_secret = secretsmanager.Secret(
    self,
    "OpenSearchMasterUserSecret",
    secret_name=f"/opensearch/common-logs-{self.env_name}/master-user",
    generate_secret_string=secretsmanager.SecretStringGenerator(
        secret_string_template=json.dumps({"username": "admin"}),
        generate_string_key="password",
        exclude_characters=' %+~`#$&*()|[]{}:;<>?!\'/@"\\',
        password_length=16,
    ),
    removal_policy=RemovalPolicy.DESTROY,
)
```

> **Retrieve the password after deploy:**
> ```bash
> aws secretsmanager get-secret-value \
>   --secret-id /opensearch/common-logs-dev/master-user \
>   --region ap-southeast-2 \
>   --query SecretString --output text
> # {"username":"admin","password":"<generated-password>"}
> ```

#### Step 3: OpenSearch domain with Fine-Grained Access Control (FGAC)

FGAC enables a native username/password login screen on Dashboards so browser
requests work without IAM credentials. It requires `encryption_at_rest`,
`node_to_node_encryption`, and `enforce_https` to all be `True`.

```python
domain = opensearch.Domain(
    self,
    "ObservabilityDomain",
    domain_name=f"common-logs-{self.env_name}",
    version=opensearch.EngineVersion.OPENSEARCH_2_11,
    capacity=opensearch.CapacityConfig(
        data_nodes=1,
        data_node_instance_type="t3.small.search",
        multi_az_with_standby_enabled=False,  # T3 instances don't support Multi-AZ with standby
    ),
    ebs=opensearch.EbsOptions(
        enabled=True,
        volume_size=20,   # GB
    ),
    encryption_at_rest=opensearch.EncryptionAtRestOptions(enabled=True),
    node_to_node_encryption=True,
    enforce_https=True,
    # FGAC requires all three security options above to be enabled.
    fine_grained_access_control=opensearch.AdvancedSecurityOptions(
        master_user_name="admin",
        master_user_password=master_user_secret.secret_value_from_json("password"),
    ),
    removal_policy=RemovalPolicy.DESTROY,
)

# Open domain-level access policy — FGAC handles fine-grained authorisation.
# Without this, the domain would require every browser request to carry IAM
# credentials. AnyPrincipal is safe here because FGAC is the real gate.
domain.add_access_policies(
    iam.PolicyStatement(
        principals=[iam.AnyPrincipal()],
        actions=["es:*"],
        resources=[f"{domain.domain_arn}/*"],
    )
)
```

> **Provisioning time:** OpenSearch domains take 10–15 minutes to provision on first deploy. CDK will show `CREATE_IN_PROGRESS` — this is normal.

> **Dev vs production sizing:**
>
> | Config | Dev (this lab) | Production |
> |---|---|---|
> | Instance type | `t3.small.search` | `m6g.large.search` or larger |
> | Data nodes | 1 | 3+ (Multi-AZ) |
> | EBS volume | 20 GB | 100+ GB |
> | Dedicated master | No | Yes (3 nodes) |
> | Fine-grained access control | Yes — FGAC (username/password login) | Yes (SSO/SAML via identity provider) |

> **Important:** FGAC **cannot be enabled on an existing domain**. If the domain was
> created without FGAC, destroy the stack first (`cdk destroy`) before redeploying.

#### Step 4: Log Forwarder Lambda

`_LocalPipBundler` is tried first (host pip, no Docker needed); Docker is the fallback:

```python
log_forwarder_lambda = _lambda.Function(
    self,
    "LogForwarderLambda",
    function_name=f"LogForwarder-{self.env_name}",
    runtime=_lambda.Runtime.PYTHON_3_12,
    handler="lambda_function.lambda_handler",
    code=_lambda.Code.from_asset(
        _APP_DIR,
        bundling=cdk.BundlingOptions(
            local=_LocalPipBundler(),
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
        # AWS_REGION is injected automatically by the Lambda runtime.
    },
)

# Grant the forwarder Lambda read/write access to OpenSearch
domain.grant_read_write(log_forwarder_lambda)
```

#### Step 5: Export outputs for cross-stack use

```python
CfnOutput(
    self, "LogForwarderArn",
    value=log_forwarder_lambda.function_arn,
    export_name=f"LogForwarderArn-{self.env_name}",      # ← consumed by AiDocProcessorStack
)
CfnOutput(
    self, "OpenSearchDashboardUrl",
    value=f"https://{domain.domain_endpoint}/_dashboards",
    export_name=f"OpenSearchDashboardUrl-{self.env_name}",
    description="Sign in with username 'admin' and the password from the master-user secret",
)
CfnOutput(
    self, "OpenSearchDomainEndpoint",
    value=domain.domain_endpoint,
    export_name=f"OpenSearchEndpoint-{self.env_name}",
)
CfnOutput(
    self, "OpenSearchMasterUserSecretArn",
    value=master_user_secret.secret_arn,
    description=(
        "Retrieve Dashboards admin password: "
        "aws secretsmanager get-secret-value "
        "--secret-id /opensearch/common-logs-<env>/master-user "
        "--query SecretString --output text"
    ),
)
```

---

### Part 3b — AiDocProcessorStack (services)

File: `services/ai-doc-processor/infra/stack/ai_doc_processor_stack.py`

#### Step 1: Update imports — add observability modules

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
    aws_cloudwatch as cloudwatch,
)
```

> **Note:** `aws_opensearchservice` is **not** imported here — OpenSearch is owned by `LogForwarderStack`.

#### Step 2: Add SERVICE_NAME build arg and Powertools env vars to the orchestrator Lambda

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

#### Step 3: Grant the orchestrator Lambda permission to publish EMF metrics

```python
orchestrator_lambda.add_to_role_policy(
    iam.PolicyStatement(
        actions=["cloudwatch:PutMetricData"],
        resources=["*"],
        conditions={"StringEquals": {"cloudwatch:namespace": "AIDocProcessor"}},
    )
)
```

#### Step 4: Declare the CloudWatch Log Group explicitly

```python
log_group = logs.LogGroup(
    self,
    "OrchestratorLogGroup",
    log_group_name=f"/aws/lambda/{orchestrator_lambda_name}",
    retention=logs.RetentionDays.ONE_MONTH,
    removal_policy=RemovalPolicy.DESTROY,
)
```

> **Why declare it explicitly?** By default, Lambda auto-creates its log group with no retention policy — logs accumulate forever. Declaring it in CDK sets `retention` and makes it the subscription filter attachment point.

#### Step 5: Import the Log Forwarder Lambda via cross-stack reference

```python
# Import the ARN exported by LogForwarderStack — no direct stack dependency needed
log_forwarder_fn = _lambda.Function.from_function_arn(
    self,
    "ImportedLogForwarder",
    function_arn=cdk.Fn.import_value(f"LogForwarderArn-{self.env_name}"),
)
```

> **Deployment prerequisite:** `LogForwarderStack` must be deployed first so the CloudFormation export `LogForwarderArn-{env_name}` exists. The CI/CD pipeline enforces this via the `needs` dependency.

#### Step 6: Wire the CloudWatch Logs subscription filter

```python
logs.SubscriptionFilter(
    self,
    "OrchestratorLogSubscription",
    log_group=log_group,
    destination=logs_destinations.LambdaDestination(log_forwarder_fn),
    filter_pattern=logs.FilterPattern.all_events(),
)
```

To forward only errors and warnings instead of all events:

```python
filter_pattern=logs.FilterPattern.any_term("ERROR", "WARNING", "CRITICAL")
```

#### Step 7: Add CloudWatch Alarms

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

#### Step 8: Add CloudFormation outputs

```python
CfnOutput(self, "ApiUrl", value=api.url)

CfnOutput(
    self, "LogGroupName",
    value=log_group.log_group_name,
    description="CloudWatch Log Group for the orchestrator Lambda",
)

# Re-surface the OpenSearch Dashboards URL from the shared stack
CfnOutput(
    self, "OpenSearchDashboardUrl",
    value=cdk.Fn.import_value(f"OpenSearchDashboardUrl-{self.env_name}"),
    description="OpenSearch Dashboards URL (provisioned by LogForwarderStack)",
)
```

---

## Part 4 — CDK Deployment Steps

> **Deploy order is mandatory.** `LogForwarderStack` must be deployed before `AiDocProcessorStack` because the service stack imports the Log Forwarder Lambda ARN via a CloudFormation named export. The CI/CD pipeline enforces this automatically via job dependencies.

### Prerequisites — set up virtual environments

Each CDK app has its own Python environment. Set them up once:

```bash
# ── Log Forwarder (common_services) ──────────────────────────────────────────
cd common_services/log-forwarder/infra
python -m venv .venv

# Activate
source .venv/bin/activate       # Linux / macOS / WSL
.venv\Scripts\activate          # Windows PowerShell

pip install -r requirements.txt
pip install -e ../../../shared   # shared constructs_lib

deactivate

# ── AI Doc Processor (services) ──────────────────────────────────────────────
cd ../../../services/ai-doc-processor/infra
python -m venv .venv

source .venv/bin/activate
pip install -r requirements.txt
pip install -e ../../../shared

deactivate
```

---

### Step 1 — Synth both stacks (validates templates, no AWS calls)

```bash
# Synth LogForwarderStack
cd common_services/log-forwarder/infra
source .venv/bin/activate

cdk synth \
  -c account=<ACCOUNT_ID> \
  -c region=ap-southeast-2

deactivate
```

Expected: CloudFormation template printed to stdout with no errors. Confirm the three exports appear:

```bash
cdk synth -c account=<ACCOUNT_ID> -c region=ap-southeast-2 2>/dev/null \
  | grep -A2 "Export"
# Expected: LogForwarderArn-dev, OpenSearchDashboardUrl-dev, OpenSearchEndpoint-dev
```

```bash
# Synth AiDocProcessorStack
cd services/ai-doc-processor/infra
source .venv/bin/activate

cdk synth \
  -c account=<ACCOUNT_ID> \
  -c region=ap-southeast-2

deactivate
```

Expected: template synthesises without error. The `Fn::ImportValue` references for `LogForwarderArn-dev` and `OpenSearchDashboardUrl-dev` will be visible in the template.

---

### Step 2 — Deploy LogForwarderStack (first, always)

```bash
cd common_services/log-forwarder/infra
source .venv/bin/activate

cdk deploy LogForwarderStack \
  -c account=<ACCOUNT_ID> \
  -c region=ap-southeast-2
```

> **This step takes 10–15 minutes** on a first deploy while CloudFormation provisions the OpenSearch domain. Subsequent deploys are fast (Lambda code update only).

Watch for the progress output:

```
LogForwarderStack: deploying...
LogForwarderStack | 0/7 | CREATE_IN_PROGRESS  | AWS::SecretsManager::Secret    | OpenSearchMasterUserSecret
LogForwarderStack | 1/7 | CREATE_COMPLETE     | AWS::SecretsManager::Secret    | OpenSearchMasterUserSecret
LogForwarderStack | 1/7 | CREATE_IN_PROGRESS  | AWS::OpenSearchService::Domain | ObservabilityDomain
LogForwarderStack | 1/7 | CREATE_IN_PROGRESS  | AWS::Lambda::Function          | LogForwarderLambda
...
LogForwarderStack | 7/7 | CREATE_COMPLETE

 ✅  LogForwarderStack

Outputs:
LogForwarderStack.LogForwarderArn              = arn:aws:lambda:ap-southeast-2:<ACCOUNT>:function:LogForwarder-dev
LogForwarderStack.OpenSearchDashboardUrl       = https://search-common-logs-dev-<hash>.ap-southeast-2.es.amazonaws.com/_dashboards
LogForwarderStack.OpenSearchDomainEndpoint     = search-common-logs-dev-<hash>.ap-southeast-2.es.amazonaws.com
LogForwarderStack.OpenSearchMasterUserSecretArn= arn:aws:secretsmanager:ap-southeast-2:<ACCOUNT>:secret:/opensearch/common-logs-dev/master-user-<id>
```

### Step 2a — Retrieve the Dashboards admin password

Run this immediately after the deploy completes:

```bash
aws secretsmanager get-secret-value \
  --secret-id /opensearch/common-logs-dev/master-user \
  --region ap-southeast-2 \
  --query SecretString \
  --output text
```

Expected output:
```json
{"username":"admin","password":"<your-generated-password>"}
```

> Save this password — you'll need it to log into OpenSearch Dashboards in Part 5.

Confirm the CloudFormation exports are live:

```bash
aws cloudformation list-exports \
  --region ap-southeast-2 \
  --query 'Exports[?starts_with(Name, `LogForwarder`) || starts_with(Name, `OpenSearch`)].{Name:Name,Value:Value}' \
  --output table
```

Expected:

```
---------------------------------------------------------------------------
|                             ListExports                                 |
+----------------------------------+--------------------------------------+
|  Name                            |  Value                               |
+----------------------------------+--------------------------------------+
|  LogForwarderArn-dev             |  arn:aws:lambda:ap-southeast-2:...  |
|  OpenSearchDashboardUrl-dev      |  https://search-common-logs-dev-... |
|  OpenSearchEndpoint-dev          |  search-common-logs-dev-...          |
+----------------------------------+--------------------------------------+
```

---

### Step 3 — Deploy AiDocProcessorStack (after LogForwarderStack is live)

```bash
cd services/ai-doc-processor/infra
source .venv/bin/activate

cdk deploy AIDocProcessorStack \
  -c account=<ACCOUNT_ID> \
  -c region=ap-southeast-2
```

```
AIDocProcessorStack: deploying...
AIDocProcessorStack | 1/8 | CREATE_COMPLETE | AWS::Logs::LogGroup              | OrchestratorLogGroup
AIDocProcessorStack | 2/8 | CREATE_COMPLETE | AWS::Logs::SubscriptionFilter    | OrchestratorLogSubscription
AIDocProcessorStack | 3/8 | CREATE_COMPLETE | AWS::CloudWatch::Alarm           | OrchestratorErrorAlarm
...
AIDocProcessorStack | 8/8 | UPDATE_COMPLETE

 ✅  AIDocProcessorStack

Outputs:
AIDocProcessorStack.ApiUrl               = https://xxxx.execute-api.ap-southeast-2.amazonaws.com/prod/
AIDocProcessorStack.LogGroupName         = /aws/lambda/OrchestratorContainer-dev
AIDocProcessorStack.OpenSearchDashboardUrl = https://search-common-logs-dev-.../_dashboards
```

---

### Step 4 — Confirm all outputs

```bash
# LogForwarderStack outputs
aws cloudformation describe-stacks \
  --stack-name LogForwarderStack \
  --region ap-southeast-2 \
  --query 'Stacks[0].Outputs' \
  --output table

# AiDocProcessorStack outputs
aws cloudformation describe-stacks \
  --stack-name AIDocProcessorStack \
  --region ap-southeast-2 \
  --query 'Stacks[0].Outputs' \
  --output table
```

---

### Step 5 — Trigger a test invocation

```bash
# Get the S3 bucket name
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name AIDocProcessorStack \
  --region ap-southeast-2 \
  --query 'Stacks[0].Outputs[?contains(OutputKey,`Bucket`)].OutputValue' \
  --output text)

# Upload a test invoice to trigger the orchestrator Lambda
echo '{"invoice_number": "INV-001", "amount": 1500}' > test-invoice.json
aws s3 cp test-invoice.json s3://${BUCKET}/test-invoice.json
```

---

### Step 6 — Verify logs are flowing

```bash
# 1. Structured JSON logs from the orchestrator Lambda
aws logs tail /aws/lambda/OrchestratorContainer-dev \
  --follow \
  --format short \
  --region ap-southeast-2
```

Expected structured JSON output:

```json
{"level":"INFO","message":"Lambda handler started","service":"ai-doc-processor","cold_start":true,...}
{"level":"INFO","message":"S3 trigger detected — beginning invoice processing pipeline",...}
{"level":"INFO","message":"Processing S3 object","bucket":"...","key":"test-invoice.json",...}
```

```bash
# 2. Log Forwarder Lambda confirming it indexed into OpenSearch
aws logs tail /aws/lambda/LogForwarder-dev \
  --follow \
  --format short \
  --region ap-southeast-2
```

Expected:

```
Forwarded 4/4 log events from /aws/lambda/OrchestratorContainer-dev → lambda-logs
```

---

### Redeploying after code changes

| What changed | Command |
|---|---|
| Log Forwarder Lambda code only | `cd common_services/log-forwarder/infra && cdk deploy LogForwarderStack ...` |
| Orchestrator Lambda code only | `cd services/ai-doc-processor/infra && cdk deploy AIDocProcessorStack ...` |
| Both | Deploy `LogForwarderStack` first, then `AIDocProcessorStack` |
| OpenSearch config | Deploy `LogForwarderStack` — domain update may take 10+ min |

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

2. Open the URL in a browser. On the login screen enter:
   - **Username:** `admin`
   - **Password:** the value retrieved in **Step 2a** above

   > The domain uses Fine-Grained Access Control (FGAC). The domain-level policy is open to `*`, but FGAC governs what each user can read or write — only the `admin` master user has full access by default.

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
# Option A: basic auth with the admin password (simplest with FGAC enabled)
OPENSEARCH_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name LogForwarderStack \
  --region ap-southeast-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`OpenSearchDomainEndpoint`].OutputValue' \
  --output text)

curl -X GET \
  "https://${OPENSEARCH_ENDPOINT}/lambda-logs/_count" \
  -u "admin:<your-password>"

# Option B: AWS SigV4 (works when FGAC is bypassed by an IAM-mapped role)
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

#### `User: anonymous is not authorized to perform: es:ESHttpGet`

This error appears when you open the Dashboards URL in a browser and the domain does
**not** have Fine-Grained Access Control enabled — browser requests arrive without IAM
credentials and are rejected as "anonymous".

**Fix:** FGAC must be enabled on the domain. FGAC **cannot** be enabled on a
running domain — you must destroy and redeploy:

```bash
cd common_services/log-forwarder/infra
source .venv/bin/activate

# 1. Destroy (RemovalPolicy.DESTROY deletes domain + secret)
cdk destroy -c account=<ACCOUNT_ID> -c region=ap-southeast-2

# 2. Redeploy with FGAC (included in the current stack definition)
cdk deploy -c account=<ACCOUNT_ID> -c region=ap-southeast-2

# 3. Retrieve the new admin password
aws secretsmanager get-secret-value \
  --secret-id /opensearch/common-logs-dev/master-user \
  --region ap-southeast-2 \
  --query SecretString --output text
```

---

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

The domain access policy is open (`iam.AnyPrincipal()`), so IAM denials from the
domain policy itself are unlikely. If you see access denied errors:

1. Verify `domain.grant_read_write(log_forwarder_lambda)` is present in the CDK stack — this adds the necessary `es:ESHttp*` IAM policy to the Lambda execution role.
2. Check there are no SCPs (Service Control Policies) in the organisation blocking `es:*`.
3. If FGAC is enabled, confirm the forwarder Lambda's IAM role is mapped to a backend role in OpenSearch Dashboards → Security → Roles (or use the `admin` user for the Lambda role temporarily during testing).

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
| Fine-grained access control | Enabled — FGAC with `admin` master user | FGAC + SSO/SAML via identity provider (Okta, Azure AD, etc.) |
| VPC placement | Public endpoint | Place in private subnets; access via VPN or bastion |
| Index lifecycle | No policy | Configure ISM (Index State Management) to roll over at 10 GB and delete after 90 days |
| Log retention | 1 month (CloudWatch) | Match your compliance requirement; configure OpenSearch ISM |
| Alarm notifications | None | Add SNS topic → email / Slack / PagerDuty |
| Dashboard access | AWS IAM | SAML/SSO via FGAC + identity provider |
| Backup | None | Enable automated snapshots to S3 |
| Cost optimisation | N/A | Use `UltraWarm` storage tier for logs older than 7 days (10× cheaper than hot storage) |
