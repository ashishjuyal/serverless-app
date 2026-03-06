# CloudWatch Native Observability — Dashboards, Log Insights & X-Ray Traces

> **Duration: 1.5–2 hours**
> Build a fully observable serverless service from scratch. Instrument a Lambda function with AWS Lambda Powertools, create a live CloudWatch Dashboard, write Log Insights queries, and trace end-to-end requests through X-Ray — all using the AWS Console and CloudShell.

---

## What This Lab Covers

```
Pattern: Serverless Observability

 API Gateway  →  Lambda (Powertools)  →  CloudWatch Logs
                      │                        │
                      │  EMF Metrics           │  Log Insights
                      ▼                        ▼
               CloudWatch Metrics      Structured JSON search
                      │
                      ▼
               CloudWatch Dashboard  ←  X-Ray Traces
                      │
                      ▼
               CloudWatch Alarms  →  (SNS / Email)
```

| Pillar | Tool | What you build |
|--------|------|----------------|
| **Logging** | CloudWatch Logs + Log Insights | Structured JSON logs; 6 ad-hoc queries |
| **Metrics** | CloudWatch Metrics + EMF | Custom business metrics via Lambda Powertools |
| **Tracing** | AWS X-Ray | Service map, segment timeline, latency histogram |
| **Dashboards** | CloudWatch Dashboards | Live 5-widget ops dashboard |
| **Alerting** | CloudWatch Alarms | Error count + duration alarms with SNS email |

---

## Prerequisites

- AWS Console access with permissions for Lambda, API Gateway, CloudWatch, X-Ray, IAM, SNS
- CloudShell available (used for CLI commands)
- No code editor required — all code is copy-paste into the Lambda console editor

---

## Setup — IAM Role (5 minutes)

Open **CloudShell** and run the following block to create a dedicated IAM role for this lab:

```bash
# Create the execution role
aws iam create-role \
  --role-name ObservabilityLabRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' 2>/dev/null || echo "Role already exists"

# Attach required policies
for policy in \
  AWSLambdaBasicExecutionRole \
  AWSXRayDaemonWriteAccess \
  AmazonAPIGatewayInvokeFullAccess; do
  aws iam attach-role-policy \
    --role-name ObservabilityLabRole \
    --policy-arn "arn:aws:iam::aws:policy/${policy}" 2>/dev/null || true
done

echo "ObservabilityLabRole ready"
```

Verify:
```bash
aws iam list-attached-role-policies \
  --role-name ObservabilityLabRole \
  --query "AttachedPolicies[*].PolicyName" \
  --output table
```

Expected output:
```
---------------------------------
|  ListAttachedRolePolicies     |
+-------------------------------+
|  AWSLambdaBasicExecutionRole  |
|  AWSXRayDaemonWriteAccess     |
|  AmazonAPIGatewayInvokeFullAccess |
+-------------------------------+
```

> **Why these policies?**
> `AWSLambdaBasicExecutionRole` — lets the Lambda write to CloudWatch Logs.
> `AWSXRayDaemonWriteAccess` — lets the Lambda send trace segments to X-Ray.
> EMF custom metrics are written to stdout (no extra permission needed — CloudWatch Logs extracts them automatically).

---

## Step 1 — Create the Lambda Function

1. Navigate to **Lambda → Create function**
2. Select **Author from scratch**
3. Fill in:
   - Function name: `OrderProcessor`
   - Runtime: `Python 3.12`
   - Architecture: `x86_64`
   - Execution role: **Use an existing role** → `ObservabilityLabRole`
4. Click **Create function**

5. In the **Code source** editor, replace the default code with the full function below and click **Deploy**:

```python
"""
OrderProcessor Lambda — Observability Demo
==========================================
Simulates an order processing service instrumented with AWS Lambda Powertools.

Emits:
  - Structured JSON logs  → CloudWatch Logs (Log Insights)
  - EMF custom metrics    → CloudWatch Metrics (namespace: ObservabilityLab)
  - X-Ray trace segments  → AWS X-Ray (service map + timeline)
"""

import json
import random
import time

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

# ── Powertools clients ────────────────────────────────────────────────────────
logger  = Logger(service="order-processor")
metrics = Metrics(namespace="ObservabilityLab", service="order-processor")
tracer  = Tracer(service="order-processor")


# ── Business logic ─────────────────────────────────────────────────────────────

@tracer.capture_method
def validate_order(order_id: str, amount: float) -> bool:
    """Validate the order fields and flag high-value orders."""
    logger.info("Validating order", extra={"order_id": order_id, "amount": amount})
    time.sleep(random.uniform(0.05, 0.15))   # Simulate DB lookup

    if amount <= 0:
        logger.error("Invalid order amount", extra={"order_id": order_id, "amount": amount})
        metrics.add_metric(name="ValidationErrors", unit=MetricUnit.Count, value=1)
        return False

    if amount > 1000:
        logger.warning("High-value order — flagged for review",
                       extra={"order_id": order_id, "amount": amount})
        metrics.add_metric(name="HighValueOrders", unit=MetricUnit.Count, value=1)

    metrics.add_metric(name="OrdersValidated", unit=MetricUnit.Count, value=1)
    return True


@tracer.capture_method
def process_payment(order_id: str, amount: float) -> dict:
    """Simulate a payment gateway call."""
    logger.info("Processing payment", extra={"order_id": order_id, "amount": amount})
    time.sleep(random.uniform(0.1, 0.4))   # Simulate payment gateway latency

    # Simulate an occasional payment failure (10 % of the time)
    if random.random() < 0.10:
        logger.error("Payment gateway timeout", extra={"order_id": order_id})
        metrics.add_metric(name="PaymentFailures", unit=MetricUnit.Count, value=1)
        raise RuntimeError(f"Payment gateway timeout for order {order_id}")

    metrics.add_metric(name="PaymentsProcessed", unit=MetricUnit.Count, value=1)
    return {"transaction_id": f"TXN-{random.randint(100000, 999999)}", "status": "success"}


@tracer.capture_method
def send_confirmation(order_id: str, transaction_id: str) -> None:
    """Simulate sending an order confirmation notification."""
    logger.info("Sending confirmation",
                extra={"order_id": order_id, "transaction_id": transaction_id})
    time.sleep(random.uniform(0.02, 0.08))
    metrics.add_metric(name="ConfirmationsSent", unit=MetricUnit.Count, value=1)


# ── Handler ────────────────────────────────────────────────────────────────────

@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics(capture_cold_start_metric=True)
@tracer.capture_lambda_handler
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    """
    Entry point.  Accepts two modes via the 'action' key:

      action=process  (default) — run the full order pipeline
      action=error              — deliberately raise an error (for alarm testing)
    """
    action    = event.get("action", "process")
    order_id  = event.get("order_id",  f"ORD-{random.randint(1000, 9999)}")
    amount    = float(event.get("amount", random.uniform(50, 1500)))

    logger.info("Handler invoked",
                extra={"action": action, "order_id": order_id, "amount": amount})

    # ── Deliberate error path (for alarm/error testing) ──────────────────────
    if action == "error":
        logger.error("Deliberate error triggered", extra={"action": action})
        metrics.add_metric(name="OrderErrors", unit=MetricUnit.Count, value=1)
        raise ValueError("Deliberate error — used to test CloudWatch alarms")

    # ── Normal processing path ───────────────────────────────────────────────
    try:
        if not validate_order(order_id, amount):
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Order validation failed", "order_id": order_id}),
            }

        payment = process_payment(order_id, amount)
        send_confirmation(order_id, payment["transaction_id"])

        logger.info("Order completed",
                    extra={"order_id": order_id, "transaction_id": payment["transaction_id"]})
        metrics.add_metric(name="OrdersCompleted", unit=MetricUnit.Count, value=1)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "order_id":       order_id,
                "transaction_id": payment["transaction_id"],
                "amount":         amount,
                "status":         "completed",
            }),
        }

    except RuntimeError as exc:
        logger.exception("Order processing failed", extra={"order_id": order_id})
        metrics.add_metric(name="OrderErrors", unit=MetricUnit.Count, value=1)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc), "order_id": order_id}),
        }
```

---

## Step 2 — Attach the AWS Lambda Powertools Layer

Powertools is published by AWS as a managed Lambda layer — no pip install needed.

1. In the `OrderProcessor` function page, scroll down to **Layers**
2. Click **Add a layer**
3. Select **AWS layers**
4. Search for and select: `AWSLambdaPowertoolsPythonV3`
5. Choose the **latest version** from the dropdown
6. Click **Add**

Confirm the layer appears in the Layers section before continuing.

> **Why a layer?** Lambda layers let you share dependencies across functions without bundling them into each deployment package. Powertools adds structured logging, EMF metrics, and X-Ray tracing with zero extra infrastructure.

---

## Step 3 — Enable X-Ray Active Tracing

1. In the `OrderProcessor` function page, click the **Configuration** tab
2. Click **Monitoring and operations tools** → **Edit**
3. Under **AWS X-Ray**, toggle **Active tracing** ON
4. Click **Save**

> Active tracing tells the Lambda runtime to start an X-Ray segment for every invocation. The `@tracer.capture_lambda_handler` decorator in the code then adds subsegments for each method.

---

## Step 4 — Add API Gateway Trigger

1. In the `OrderProcessor` function page, click **Add trigger**
2. Select **API Gateway**
3. Choose:
   - **Create a new API**
   - API type: **HTTP API**
   - Security: **Open**
4. Click **Add**

5. Note the **API endpoint URL** shown in the Triggers section — you will use this to send requests.

---

## Step 5 — Generate Traffic

Run all commands below in **CloudShell**. Replace `<YOUR_API_URL>` with the endpoint from Step 4.

```bash
API_URL="<YOUR_API_URL>"
```

### Send 10 normal orders

```bash
for i in $(seq 1 10); do
  AMOUNT=$(shuf -i 100-1500 -n 1)
  curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"process\",\"order_id\":\"ORD-${i}\",\"amount\":${AMOUNT}}" \
    | python3 -m json.tool
  sleep 1
done
```

### Send 3 high-value orders (triggers `HighValueOrders` metric)

```bash
for i in 1 2 3; do
  curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"process\",\"order_id\":\"VIP-${i}\",\"amount\":1200}" \
    | python3 -m json.tool
  sleep 1
done
```

### Trigger 2 deliberate errors (for alarm testing)

```bash
for i in 1 2; do
  curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d '{"action":"error"}' \
    | python3 -m json.tool
  sleep 1
done
```

Wait **2 minutes** after running the above before proceeding — CloudWatch metrics have a ~1-minute ingestion delay.

---

## Step 6 — CloudWatch Dashboard

### 6a — Open CloudWatch and verify metrics exist

1. Navigate to **CloudWatch → Metrics → All metrics**
2. Under **Custom Namespaces**, you should see **ObservabilityLab**
3. Click it → **Service** → `order-processor`
4. Confirm these metrics appear:

   | Metric | Expected after traffic |
   |--------|------------------------|
   | `ColdStart` | 1 (first invocation only) |
   | `OrdersValidated` | ~13 |
   | `OrdersCompleted` | ~10 |
   | `PaymentsProcessed` | ~10 |
   | `HighValueOrders` | 3 |
   | `ConfirmationsSent` | ~10 |
   | `OrderErrors` | 2+ |

### 6b — Create the dashboard

1. **CloudWatch → Dashboards → Create dashboard**
2. Name: `OrderProcessor-Observability`
3. Add the widgets below one by one using **+ Add widget**:

---

#### Widget 1 — Invocations & Errors (Line chart)

- Source: **Lambda → By Function Name → OrderProcessor**
- Metrics: `Invocations` (Sum) and `Errors` (Sum)
- Period: **1 minute**
- Title: `Invocations vs Errors`

---

#### Widget 2 — Duration p95 (Line chart)

- Source: **Lambda → By Function Name → OrderProcessor**
- Metric: `Duration` — statistic **p95**
- Period: **1 minute**
- Add a **horizontal annotation** at `500` ms (the expected SLA threshold)
- Title: `Latency p95 (ms)`

---

#### Widget 3 — Business Pipeline Metrics (Bar chart)

- Source: **ObservabilityLab → Service → order-processor**
- Metrics: `OrdersValidated`, `OrdersCompleted`, `OrderErrors`
- Period: **5 minutes**
- Title: `Order Pipeline Throughput`

---

#### Widget 4 — Payment & Notification Counts (Bar chart)

- Source: **ObservabilityLab → Service → order-processor**
- Metrics: `PaymentsProcessed`, `PaymentFailures`, `ConfirmationsSent`, `HighValueOrders`
- Period: **5 minutes**
- Title: `Payment & Notification Breakdown`

---

#### Widget 5 — Cold Starts (Number widget)

- Source: **ObservabilityLab → Service → order-processor**
- Metric: `ColdStart` — statistic **Sum**
- Period: **1 hour**
- Title: `Cold Starts (last hour)`

---

4. Click **Save dashboard**
5. Set auto-refresh: click the **Refresh** icon (top right) → **10 seconds**

---

## Step 7 — CloudWatch Log Insights

1. Navigate to **CloudWatch → Log Insights**
2. Select log group: `/aws/lambda/OrderProcessor`
3. Time range: **Last 30 minutes**

Run each query below and observe the results.

---

### Query 1 — All structured events (latest first)

```sql
fields @timestamp, level, message, service, cold_start, order_id, amount
| sort @timestamp desc
| limit 50
```

> Powertools injects `level`, `message`, `service`, `cold_start`, and `xray_trace_id` automatically into every log line.

---

### Query 2 — Errors only

```sql
fields @timestamp, level, message, order_id, error_type, location
| filter level = "ERROR"
| sort @timestamp desc
| limit 20
```

---

### Query 3 — High-value orders

```sql
fields @timestamp, message, order_id, amount
| filter message = "High-value order — flagged for review"
| sort amount desc
```

---

### Query 4 — Average payment processing latency

```sql
fields @timestamp, @duration
| filter message = "Processing payment"
| stats avg(@duration) as avg_ms,
        max(@duration) as max_ms,
        count()        as total
```

---

### Query 5 — Orders per minute (throughput over time)

```sql
fields @timestamp, message
| filter message = "Order completed"
| stats count() as orders_completed by bin(1m)
| sort @timestamp asc
```

---

### Query 6 — Error rate percentage

```sql
fields level
| stats sum(level = "ERROR")   as errors,
        count()                 as total,
        sum(level = "ERROR") / count() * 100 as error_rate_pct
  by bin(5m)
```

---

### Save a query

1. Run **Query 5** (throughput over time)
2. Click **Save** → name it `Order Throughput per Minute`
3. Add it to the dashboard:
   - Open `OrderProcessor-Observability` → **Add widget → Logs table**
   - Select the saved query
   - Title: `Order Throughput (Log Insights)`
   - Save the dashboard

---

## Step 8 — AWS X-Ray Traces

### 8a — Service Map

1. Navigate to **CloudWatch → X-Ray traces → Service Map**
   *(or search "X-Ray" in the console top bar)*
2. Time range: **Last 30 minutes**

You should see these nodes:
```
  API Gateway (client)
       │
       ▼
  OrderProcessor   [Lambda]
       │
       ├─▶  validate_order    [subsegment]
       ├─▶  process_payment   [subsegment]
       └─▶  send_confirmation [subsegment]
```

Each node shows **Requests**, **Faults**, **Errors**, **Throttles** and average latency.
Click a node → **View traces** to drill down.

---

### 8b — Trace List

1. **CloudWatch → X-Ray traces → Traces**
2. Time range: **Last 30 minutes**
3. Add a filter:
   ```
   service("order-processor")
   ```
4. Each row shows: **Trace ID**, **Duration**, **Status** (OK / Error / Fault)

---

### 8c — Inspect one trace in detail

1. Click any trace row
2. The **Segment Timeline** (Gantt chart) opens:

```
▼ OrderProcessor                          [full invocation duration]
   ├─ Initialization                      [cold start only]
   ├─ Invocation
   │   ├─ ## lambda_handler               [@tracer.capture_lambda_handler]
   │   │   ├─ ## validate_order           [@tracer.capture_method]
   │   │   ├─ ## process_payment          [@tracer.capture_method]
   │   │   └─ ## send_confirmation        [@tracer.capture_method]
   └─ Overhead
```

3. Click the `process_payment` subsegment — note the duration (100–400 ms)
4. Click a failed trace (red row) — expand the **Exception** section to see the full error

---

### 8d — Filter by cold starts

1. In the Traces view → **Add filter → Annotation → cold_start → true**
2. These are the invocations where Lambda needed to initialise a new execution environment
3. Compare their total duration against warm invocations — typically 500–1500 ms slower

---

### 8e — X-Ray Analytics — latency outliers

1. **CloudWatch → X-Ray traces → Analytics**
2. Time range: **Last 30 minutes**
3. The histogram shows latency distribution across all traces
4. **Drag** to select the slowest 20 % of traces — the list below auto-filters
5. Identify which subsegment (validate / payment / confirmation) is slowest in those outliers

---

### 8f — Add trace map to dashboard

1. Open `OrderProcessor-Observability` → **Add widget → Trace map**
2. Filter: `service("order-processor")`
3. Title: `X-Ray Service Map`
4. Save the dashboard

---

## Step 9 — CloudWatch Alarms

### 9a — Create an Errors alarm

1. Navigate to **CloudWatch → Alarms → Create alarm**
2. Click **Select metric**
3. Choose **Lambda → By Function Name → OrderProcessor → Errors**
4. Click **Select metric**
5. Configure:
   - Period: **1 minute**
   - Statistic: **Sum**
   - Threshold: **Greater than or equal to 1**
   - Missing data treatment: **Treat as good (not breaching)**
6. Click **Next**

**Notification:**
7. Create a new SNS topic:
   - Topic name: `OrderProcessorAlerts`
   - Email endpoint: `your-email@example.com`
8. Click **Next**

**Name:**
9. Alarm name: `OrderProcessor-Errors`
10. Click **Create alarm**

Check your email inbox and **confirm the SNS subscription**.

---

### 9b — Create a Duration (p95) alarm

1. **Create alarm → Select metric → Lambda → By Function Name → OrderProcessor → Duration**
2. Configure:
   - Period: **5 minutes**
   - Statistic: **p95**
   - Threshold: **Greater than 1000** (1 second)
   - Missing data: **Treat as good**
3. Notification: reuse the `OrderProcessorAlerts` topic (choose **Select an existing SNS topic**)
4. Alarm name: `OrderProcessor-Duration-p95`
5. Click **Create alarm**

---

### 9c — Test the alarm

Trigger 5 deliberate errors to push the alarm into ALARM state:

```bash
for i in $(seq 1 5); do
  curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d '{"action":"error"}'
  sleep 2
done
```

Watch **CloudWatch → Alarms** — the `OrderProcessor-Errors` alarm should transition from `OK` → `In alarm` within 1–2 minutes.
Check your email for the SNS notification.

Reset to OK by sending normal traffic:

```bash
for i in $(seq 1 5); do
  curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"process\",\"amount\":200}"
  sleep 2
done
```

---

### 9d — Add Alarm Status widget to dashboard

1. Open `OrderProcessor-Observability` → **Add widget → Alarm status**
2. Select both `OrderProcessor-Errors` and `OrderProcessor-Duration-p95`
3. Title: `Service Health`
4. Save the dashboard

---

## Final Dashboard Layout

Your completed `OrderProcessor-Observability` dashboard:

```
┌──────────────────────────┬──────────────────────────┐
│  Invocations vs Errors   │  Latency p95 (ms)         │
│  [Line chart]            │  [Line + 500 ms SLA line]  │
├──────────────────────────┼──────────────────────────┤
│  Order Pipeline          │  Payment & Notification    │
│  Throughput [Bar]        │  Breakdown [Bar]           │
├──────────────────────────┼──────────────────────────┤
│  Cold Starts [Number]    │  Service Health [Alarms]   │
├──────────────────────────┴──────────────────────────┤
│  Order Throughput (Log Insights)   [Logs table]      │
├─────────────────────────────────────────────────────┤
│  X-Ray Service Map                 [Trace map]       │
└─────────────────────────────────────────────────────┘
```

---

## Verify & Validate

Run this checklist before marking the lab complete:

- [ ] `OrderProcessor` Lambda deployed with Powertools code
- [ ] Powertools Lambda layer attached (AWSLambdaPowertoolsPythonV3)
- [ ] X-Ray active tracing enabled on the Lambda
- [ ] API Gateway trigger created and responding to POST requests
- [ ] CloudWatch namespace `ObservabilityLab` visible with custom metrics
- [ ] Dashboard `OrderProcessor-Observability` has 7 widgets
- [ ] Log Insights Query 2 (errors only) returns results
- [ ] X-Ray service map shows `validate_order`, `process_payment`, `send_confirmation` subsegments
- [ ] `OrderProcessor-Errors` alarm transitions to ALARM after 5 error triggers
- [ ] SNS email received when alarm fires

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No module named 'aws_lambda_powertools'` | Layer not attached | Add the `AWSLambdaPowertoolsPythonV3` layer (Step 2) |
| Custom metrics namespace `ObservabilityLab` missing | Lambda never completed successfully | Check Lambda logs for import errors; re-trigger |
| X-Ray service map empty | Active tracing not enabled | Enable in Configuration → Monitoring tools (Step 3) |
| Log Insights returns no results | Wrong log group | Use `/aws/lambda/OrderProcessor` |
| Alarm stays in `Insufficient data` | Not enough data points | Wait 2 minutes then re-trigger |
| SNS email not received | Subscription not confirmed | Check spam folder; re-confirm subscription link |

---

## Clean Up

```bash
# Delete Lambda function
aws lambda delete-function --function-name OrderProcessor

# Delete API Gateway (replace with your API ID from the console URL)
API_ID=$(aws apigatewayv2 get-apis \
  --query "Items[?Name=='OrderProcessor'].ApiId" \
  --output text)
aws apigatewayv2 delete-api --api-id "$API_ID"

# Delete CloudWatch alarms
aws cloudwatch delete-alarms \
  --alarm-names OrderProcessor-Errors OrderProcessor-Duration-p95

# Delete SNS topic
TOPIC_ARN=$(aws sns list-topics \
  --query "Topics[?contains(TopicArn,'OrderProcessorAlerts')].TopicArn" \
  --output text)
aws sns delete-topic --topic-arn "$TOPIC_ARN"

# Delete CloudWatch dashboard
aws cloudwatch delete-dashboards \
  --dashboard-names OrderProcessor-Observability

# Delete IAM role
for policy in \
  AWSLambdaBasicExecutionRole \
  AWSXRayDaemonWriteAccess \
  AmazonAPIGatewayInvokeFullAccess; do
  aws iam detach-role-policy \
    --role-name ObservabilityLabRole \
    --policy-arn "arn:aws:iam::aws:policy/${policy}" 2>/dev/null || true
done
aws iam delete-role --role-name ObservabilityLabRole

echo "Clean up complete"
```

---

## Key Takeaways

| Concept | What you learned |
|---------|-----------------|
| **Structured logging** | `Logger` auto-injects `request_id`, `cold_start`, `xray_trace_id` — makes Log Insights queries work without custom parsing |
| **EMF metrics** | `Metrics` writes metrics as JSON to stdout — CloudWatch Logs extracts them automatically; no `PutMetricData` API call needed |
| **X-Ray subsegments** | `@tracer.capture_method` wraps any function — Powertools handles segment lifecycle, error capture, and metadata |
| **Cold starts** | The `capture_cold_start_metric=True` flag publishes a `ColdStart` metric automatically — no manual detection needed |
| **Dashboard-driven ops** | Combining Lambda metrics, custom EMF metrics, Log Insights, and X-Ray in one dashboard gives full visibility without leaving CloudWatch |
