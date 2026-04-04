# AWS Serverless Patterns — Workshop Overview

> **Empowering High Performance Technology Teams**  
> A two-day, hands-on workshop covering 15 battle-tested serverless architectural patterns on AWS.

---

## Table of Contents

- [What You'll Learn](#what-youll-learn)
- [Workshop Structure](#workshop-structure)
- [How Each Lab Works](#how-each-lab-works)
- [Pattern Map](#pattern-map)
- [Resource Deletion Strategy](#resource-deletion-strategy)
- [Pre-requisites](#pre-requisites)
- [Environment Setup](#environment-setup)

---

## What You'll Learn

Serverless systems follow predictable architectural patterns that dramatically simplify how we build modern applications. These patterns aren't just theoretical constructs — they're battle-tested blueprints that help engineering teams reason systematically about system behaviour, scalability, reliability, and cost optimisation.

By the end of this workshop you will be able to:

- **Recognise** which serverless pattern fits a given use case
- **Build** each pattern hands-on using AWS Console and CloudShell
- **Test and verify** each integration before moving to the next
- **Combine** patterns to design real-world production architectures
- **Reason about trade-offs** — cost, coupling, complexity, and consistency

---

## Workshop Structure

| | Day 1 | Day 2++ |
|---|---|---|
| **Theme** | Serverless Foundations | Advanced Patterns |
| **Patterns** | 1 – 6 | 7 – 15 |
| **Duration** | 2.5 – 3 hours | 2.5 – 3 hours |
| **Focus** | Lambda, API Gateway, DynamoDB, Cognito, EventBridge, SQS, SNS, S3 | Kinesis, Step Functions, Bedrock, Textract, Glue, Athena, DynamoDB Streams |
| **Approach** | Incremental — each pattern builds on the previous | Independent — each lab starts fresh |

---

## How Each Lab Works

Every pattern follows the same structure:

```
1. Overview         — what the pattern solves and when to use it
2. Architecture     — the flow diagram (e.g. Client → API GW → Lambda → DynamoDB)
3. Step-by-step     — numbered console instructions with exact navigation
4. Code             — ready-to-paste Lambda code (Python 3.12)
5. Verify & Test    — specific things to check before moving on
```

> **Tip:** Don't skip the Verify step. Confirming each integration before layering the next one saves significant debugging time.

---

## Pattern Map

### Day 1 — Foundations

| # | Pattern | Core Services | What You Build |
|---|---------|--------------|----------------|
| 1 | API-Driven Backend | Lambda · API Gateway · DynamoDB | A working REST CRUD API with persistent storage |
| 2 | Secure API Backend | + Cognito · Lambda Authorizer | JWT-protected endpoints with access control |
| 3 | Event-Driven Microservice | + EventBridge | Decoupled pub/sub between services |
| 4 | Queue-Based Load Leveling | + SQS · DLQ | Buffered, retry-safe message processing |
| 5 | Fan-Out / Fan-In | + SNS | Parallel broadcast to multiple processors |
| 6 | File & Document Processing | + S3 | Automatic processing triggered on file upload |

### Day 2 — Advanced Patterns

| # | Pattern | Core Services | What You Build |
|---|---------|--------------|----------------|
| 7 | Stream Processing | Kinesis · Lambda · DynamoDB | Real-time IoT sensor analytics with alerting |
| 8 | Orchestration Workflow | Step Functions · Lambda | Multi-step order pipeline with error handling |
| 9 | Choreography with EventBridge | EventBridge · Lambda | Fully decoupled microservice chain |
| 10 | Scheduled Automation | EventBridge Scheduler · Lambda | Serverless cron jobs |
| 11 | Serverless RAG | Bedrock · DynamoDB · Lambda | AI assistant grounded in private documents |
| 12 | Agentic AI | Bedrock · Lambda · Step Functions | Autonomous agent that selects and calls tools |
| 13 | Document Intelligence | Textract · S3 · Lambda | Automated extraction from uploaded documents |
| 14 | Serverless ETL & Data Lake | S3 · Lambda · Athena | SQL analytics on raw data without a database |
| 15 | Event Sourcing & CQRS | DynamoDB · Streams · Lambda | Immutable event log with separate read model |

---

## Resource Deletion Strategy

> **Important:** AWS lab environments delete resources automatically after **~4 hours**. The workshop is designed around this constraint.

**Why this works:**

- **Day 1 patterns are incremental** — each lab adds a service on top of the previous. All Day 1 resources are created within the session window and tested before deletion.
- **Day 2 patterns are independent** — each lab creates its own fresh resources. There is no dependency on Day 1 infrastructure.
- **Cross-day dependencies are zero** — Day 2 begins with a clean environment. The only shared item is the IAM role, which takes 2 minutes to recreate.

**What this means for participants:**

- You do **not** need to manually clean up between labs within the same day.
- You **do** need to re-create the `LambdaLabRole` at the start of Day 2 if it was deleted.
- If a pattern's resources are deleted mid-lab, the lab is short enough to restart from scratch.

---

## Pre-requisites

### Knowledge

- Basic familiarity with AWS Console navigation
- Understanding of what a function / API / database is conceptually
- No prior serverless experience required — patterns are explained from first principles

### AWS Account Access

- An AWS account with **console access** in `us-east-1` (N. Virginia) or `eu-west-1` (Ireland)
- Permissions to create: Lambda, API Gateway, DynamoDB, Cognito, EventBridge, SQS, SNS, S3, Step Functions, Kinesis, Bedrock, Textract, Glue, Athena, IAM roles
- If using a shared/training account, confirm the above services are **not restricted** before the session

### For Day 2 — Bedrock (Patterns 11 & 12)

Bedrock model access must be enabled **before** the session — activation can take a few minutes.

1. Open **Amazon Bedrock Console**
2. Go to **Model access** (left sidebar)
3. Click **Modify model access**
4. Enable:
   - `Amazon Titan Text Embeddings V2` (for RAG embeddings)
   - `Anthropic Claude 3 Haiku` (for LLM queries and tool use)
5. Submit — activation typically takes 1–5 minutes

> If Bedrock is unavailable in your account, Patterns 11 and 12 can be followed conceptually. The architecture and code are fully documented.

---

## Environment Setup

Complete these steps **once** at the start of Day 1. They take approximately 10 minutes.

### Step 1 — Sign in and Set Region

1. Sign in to the **AWS Management Console**
2. In the top-right region selector, choose **us-east-1 (N. Virginia)**
3. Keep this region consistent across all labs

### Step 2 — Open AWS CloudShell

CloudShell gives you a pre-authenticated browser terminal — no local setup required.

1. Click the **CloudShell icon** in the top navigation bar (looks like `>_`)
2. Wait for the environment to initialise (~30 seconds)
3. Verify your identity:

```bash
aws sts get-caller-identity
```

You should see your `Account`, `UserId`, and `Arn`. If you see an error, contact your AWS administrator.

### Step 3 — Create the Lab IAM Role

All Lambda functions in this workshop use a single role: `LambdaLabRole`.

**Option A — AWS Console (recommended for beginners):**

1. Navigate to **IAM → Roles → Create role**
2. Trusted entity: **AWS service → Lambda**
3. Attach the following managed policies:
   - `AWSLambdaBasicExecutionRole`
   - `AmazonDynamoDBFullAccess`
   - `AmazonSQSFullAccess`
   - `AmazonSNSFullAccess`
   - `AmazonS3FullAccess`
   - `AWSStepFunctionsFullAccess`
   - `AmazonKinesisFullAccess`
   - `AmazonTextractFullAccess`
   - `AmazonAthenaFullAccess`
   - `AWSGlueServiceRole`
   - `AmazonBedrockFullAccess` *(if available in your account)*
4. Role name: `LambdaLabRole`
5. Click **Create role**

**Option B — CloudShell (faster):**

```bash
# Create the role with Lambda trust policy
aws iam create-role \
  --role-name LambdaLabRole \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Principal":{"Service":"lambda.amazonaws.com"},
      "Action":"sts:AssumeRole"
    }]
  }'
```

```bash
# Attach all required policies
for policy in \
  AWSLambdaBasicExecutionRole \
  AmazonDynamoDBFullAccess \
  AmazonSQSFullAccess \
  AmazonSNSFullAccess \
  AmazonS3FullAccess \
  AWSStepFunctionsFullAccess \
  AmazonKinesisFullAccess \
  AmazonTextractFullAccess \
  AmazonAthenaFullAccess \
  AWSGlueServiceRole \
  AmazonBedrockFullAccess; do
  aws iam attach-role-policy \
    --role-name LambdaLabRole \
    --policy-arn "arn:aws:iam::aws:policy/${policy}" 2>/dev/null || true
done
```

```bash
# grant permission for putting events to EventBridge
aws iam put-role-policy \
  --role-name LambdaLabRole \
  --policy-name EventBridgePutEvents \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "events:PutEvents",
      "Resource": "*"
    }]
  }'

echo "LambdaLabRole created successfully"
```

### Step 4 — Verify Setup

Run this quick check in CloudShell:

```bash
# Confirm the role exists
aws iam get-role --role-name LambdaLabRole --query 'Role.RoleName'

# Confirm Lambda service is accessible
aws lambda list-functions --query 'length(Functions)'

# Confirm DynamoDB is accessible
aws dynamodb list-tables --query 'TableNames'
```

All three commands should return without errors. You are ready to begin.

---

## Quick Reference — Console Navigation

| Service | Console Path |
|---------|-------------|
| Lambda | Services → Compute → Lambda |
| API Gateway | Services → Networking → API Gateway |
| DynamoDB | Services → Database → DynamoDB |
| Cognito | Services → Security → Cognito |
| EventBridge | Services → Application Integration → EventBridge |
| SQS | Services → Application Integration → SQS |
| SNS | Services → Application Integration → SNS |
| S3 | Services → Storage → S3 |
| Step Functions | Services → Application Integration → Step Functions |
| Kinesis | Services → Analytics → Kinesis |
| Bedrock | Services → Machine Learning → Bedrock |
| Textract | Services → Machine Learning → Textract |
| Athena | Services → Analytics → Athena |
| Glue | Services → Analytics → Glue |
| CloudWatch Logs | Services → Management → CloudWatch → Log groups |

---

*Proceed to **Day 1** when your environment setup is complete.*
