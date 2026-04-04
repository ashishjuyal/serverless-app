# Day 1 — Serverless Foundations

> **Patterns 1–6 | Duration: 2.5–3 hours**  
> Build the core serverless stack incrementally. Each pattern adds one new service on top of the previous, producing a testable result before you move on.

---

## Day 1 at a Glance

```
Pattern 1 → Lambda + API Gateway + DynamoDB        (CRUD REST API)
Pattern 2 → + Cognito + Lambda Authorizer          (Secured API)
Pattern 3 → + EventBridge                          (Event-Driven Decoupling)
Pattern 4 → + SQS + Dead-Letter Queue              (Load Leveling)
Pattern 5 → + SNS                                  (Fan-Out Parallel Processing)
Pattern 6 → + S3                                   (File Pipeline)
```

> **Resource note:** All Day 1 resources are self-contained. Resources deleted after 4 hours have zero impact on Day 2 — Day 2 starts fresh.

---

## Start-of-Day Setup (5 minutes)

Before beginning Pattern 1, confirm your environment is ready:

```bash
# In CloudShell — verify identity and role
aws sts get-caller-identity
aws iam get-role --role-name LambdaLabRole --query 'Role.RoleName'
```

Both commands should return without errors. If `LambdaLabRole` is missing, see the **Environment Setup** section in `00-overview-and-prerequisites.md`.

---

## Pattern 1: API-Driven Backend

> **The Foundation of Serverless Microservices**

### What This Pattern Solves

The most fundamental serverless architecture. Clients call API Gateway, which triggers a Lambda function, which reads and writes to DynamoDB — all without managing any servers. Handles CRUD services, mobile backends, e-commerce APIs, and any standard request/response workload.

### Architecture

```
Client  →  API Gateway  →  Lambda  →  DynamoDB
```

---

### Step 1 — Create Your First Lambda Function

We start with Lambda alone (no API Gateway yet) to understand the base compute unit.

1. Navigate to **Lambda → Create function**
2. Select **Author from scratch**
3. Fill in:
   - Function name: `HelloServerless`
   - Runtime: `Python 3.12`
   - Execution role: **Use an existing role** → `LambdaLabRole`
4. Click **Create function**
5. In the code editor, replace the default code with:

```python
import json

def lambda_handler(event, context):
    name = event.get('name', 'World')
    return {
        'statusCode': 200,
        'body': json.dumps({'message': f'Hello, {name}! Welcome to Serverless.'})
    }
```

6. Click **Deploy**
7. Click **Test** → **Create new test event**
   - Event name: `TestEvent`
   - Payload: `{"name": "Trainee"}`
8. Click **Test** — you should see a green success banner with the JSON response

---

### Step 2 — Add DynamoDB for Persistence

1. Navigate to **DynamoDB → Create table**
   - Table name: `Products`
   - Partition key: `productId` (String)
   - Leave all other settings as default
   - Click **Create table**

2. Return to your `HelloServerless` Lambda function. Replace the code with:

```python
import json, boto3, uuid
from decimal import Decimal

dynamo = boto3.resource('dynamodb').Table('Products')

def lambda_handler(event, context):
    action = event.get('action', 'list')

    if action == 'create':
        item = {
            'productId': str(uuid.uuid4()),
            'name': event['name'],
            'price': Decimal(str(event['price']))
        }
        dynamo.put_item(Item=item)
        return {'statusCode': 201, 'body': json.dumps(item, default=str)}

    elif action == 'list':
        result = dynamo.scan()
        return {'statusCode': 200, 'body': json.dumps(result['Items'], default=str)}
```

3. Click **Deploy**
4. Test with: `{"action": "create", "name": "Widget", "price": 9.99}`
5. Test with: `{"action": "list"}` — verify your item appears

---

### Step 3 — Expose via API Gateway

1. Navigate to **API Gateway → Create API → REST API → Build**
   - API name: `ProductsAPI`
   - Click **Create API**

2. Click **Create Resource**
   - Resource name: `products`
   - Click **Create Resource**

3. With `/products` selected, click **Create Method**:
   - Method: `GET` → Integration type: Lambda Function → enter `HelloServerless` → Save
   - Repeat for `POST` → same Lambda → Save

4. Click **Deploy API**
   - Stage: **New Stage**
   - Stage name: `dev`
   - Click **Deploy**

5. Copy the **Invoke URL** (e.g. `https://xxxxx.execute-api.us-east-1.amazonaws.com/dev`)

---

### ✅ Verify — Pattern 1

```bash
# In CloudShell — replace with your actual URL
API_URL="https://YOUR_ID.execute-api.us-east-1.amazonaws.com/dev"

# List products (should return empty array initially)
curl "$API_URL/products"

# Create a product
curl -X POST "$API_URL/products" \
  -H "Content-Type: application/json" \
  -d '{"action":"create","name":"Gadget","price":49.99}'

# List again — confirm your product appears
curl "$API_URL/products"
```

- In the **DynamoDB console → Products → Explore items** confirm data is persisted
- In **CloudWatch → Log groups** find `/aws/lambda/HelloServerless` and review the execution logs

---

## Pattern 2: Secure API Backend with Authorization

> **JWT Authentication via Amazon Cognito**

### What This Pattern Solves

Production APIs need security. Cognito manages user identity and issues JWT tokens. A Lambda Authorizer validates those tokens at the API Gateway level before any request reaches your business logic.

### Architecture

```
Client  →  Cognito (JWT)  →  API Gateway (Lambda Authorizer)  →  Lambda  →  DynamoDB
```

---

### Step 1 — Create a Cognito User Pool

1. Navigate to **Cognito → Create user pool**
2. Sign-in option: **Email**
3. Leave MFA disabled for the lab
4. App client name: `ProductsApp`
5. Click through all screens and **Create user pool**
6. Note the **User Pool ID** and **App Client ID** — shown on the User Pool overview page

---

### Step 2 — Create a Lambda Authorizer

1. Navigate to **Lambda → Create function**
   - Name: `TokenAuthorizer`
   - Runtime: `Python 3.12`
   - Execution role: `LambdaLabRole`

2. Replace the code with:

```python
import json

def lambda_handler(event, context):
    token = event.get('authorizationToken', '')
    
    # Simplified: accept any Bearer token with sufficient length
    # In production: validate JWT signature against Cognito JWKS endpoint
    if token.startswith('Bearer ') and len(token) > 10:
        effect = 'Allow'
    else:
        effect = 'Deny'

    print(f'Authorization decision: {effect} for token length {len(token)}')

    return {
        'principalId': 'user',
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [{
                'Action': 'execute-api:Invoke',
                'Effect': effect,
                'Resource': event['methodArn']
            }]
        },
        'context': {'authorized': str(effect == 'Allow')}
    }
```

3. Click **Deploy**

---

### Step 3 — Attach the Authorizer to API Gateway

1. Navigate to **API Gateway → ProductsAPI**
2. Click **Authorizers → Create Authorizer**
   - Name: `JWTAuthorizer`
   - Type: **Lambda**
   - Lambda function: `TokenAuthorizer`
   - Lambda Event Payload: **Token**
   - Token source: `Authorization`
   - TTL: `300`
   - Click **Create Authorizer**

3. Go to **Resources → /products → GET → Method Request**
   - Click the pencil icon next to **Authorization**
   - Select `JWTAuthorizer`
   - Click the checkmark to save

4. Repeat for the **POST** method

5. **Deploy API**: Actions → Deploy API → Stage: `dev` → Deploy

---

### ✅ Verify — Pattern 2

```bash
API_URL="https://YOUR_ID.execute-api.us-east-1.amazonaws.com/dev"

# Without a token — should return 401 Unauthorized
curl -i "$API_URL/products"

# With a valid token — should return 200 with data
curl -i -H "Authorization: Bearer myvalidtoken12345" "$API_URL/products"

# With a short/invalid token — should return 401
curl -i -H "Authorization: Bearer x" "$API_URL/products"
```

- Open **CloudWatch → Log groups → /aws/lambda/TokenAuthorizer** — confirm authorization decisions are logged
- Note the **cached response**: the same token within 300 seconds reuses the cached policy (no Lambda invocation)

---

## Pattern 3: Event-Driven Microservice

> **Decoupled Processing via Amazon EventBridge**

### What This Pattern Solves

Instead of services calling each other directly, they publish events to EventBridge. Subscribers react only to the events they care about. Services can be added, changed, or removed without touching other services.

### Architecture

```
Event Source (Lambda)  →  EventBridge (custom bus)  →  Subscriber Lambda(s)
```

---

### Step 1 — Create a Custom EventBridge Bus

1. Navigate to **EventBridge → Event buses → Create event bus**
   - Name: `ecommerce-events`
   - Logs: Select `CloudWatch logs`
   - Click **Create**

> A dedicated bus keeps your domain events separate from AWS system events on the default bus.

---

### Step 2 — Create the Subscriber Lambda

Create Lambda: Name `OrderNotifier`, Runtime `Python 3.12`, Role `LambdaLabRole`

```python
import json

def lambda_handler(event, context):
    detail = event.get('detail', {})
    order_id = detail.get('orderId', 'unknown')
    amount = detail.get('amount', 0)
    customer = detail.get('customerId', 'unknown')
    
    print(f'[NOTIFY] Order {order_id} placed by {customer} for ${amount}')
    print(f'Sending confirmation email for order: {order_id}')
    
    return {'status': 'notification sent', 'orderId': order_id}
```

---

### Step 3 — Create an EventBridge Rule

1. Navigate to **EventBridge → Rules → Create rule**
   - Name: `OrderPlacedRule`
   - Event bus: `ecommerce-events`
   - Rule type: **Rule with an event pattern**

2. Event pattern — choose **Custom pattern** and paste:

```json
{
  "source": ["ecommerce.orders"],
  "detail-type": ["OrderPlaced"]
}
```

3. Target: **Lambda function** → `OrderNotifier`
4. Click **Create rule**

---

### Step 4 — Create the Publisher Lambda

Create Lambda: Name `OrderService`, Runtime `Python 3.12`, Role `LambdaLabRole`

```python
import json, boto3, uuid

events = boto3.client('events')

def lambda_handler(event, context):
    order = {
        'orderId': str(uuid.uuid4())[:8],
        'amount': event.get('amount', 100.00),
        'customerId': event.get('customerId', 'cust-001')
    }
    events.put_events(Entries=[{
        'Source': 'ecommerce.orders',
        'DetailType': 'OrderPlaced',
        'Detail': json.dumps(order),
        'EventBusName': 'ecommerce-events'
    }])
    print(f'Published OrderPlaced event: {order["orderId"]}')
    return {'statusCode': 200, 'body': json.dumps(order)}
```

---
```bash
# In CloudShell
# change the account ID in the below command. You will get it from top right, use without hyphens

aws lambda add-permission \
  --function-name OrderNotifier \
  --statement-id EventBridgeInvoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:775937640988:rule/ecommerce-events/OrderPlacedRule


# change the account ID in the below command. You will get it from top right, use without hyphens
aws events put-targets \
  --event-bus-name ecommerce-events \
  --rule OrderPlacedRule \
  --targets "Id=OrderNotifierTarget,Arn=arn:aws:lambda:us-east-1:775937640988:function:OrderNotifier"

```
---

### ✅ Verify — Pattern 3

1. Test `OrderService` with: `{"amount": 249.99, "customerId": "cust-007"}`
2. Navigate to **CloudWatch → Log groups → /aws/lambda/OrderNotifier** — confirm the notification was logged
3. Go to **EventBridge → Event buses → ecommerce-events → Monitoring** — confirm events were received

**Extension:** Create a second Lambda called `InventoryReducer` that prints `[INVENTORY] Reducing stock for order X` and subscribe it to the same rule. Run `OrderService` again — both Lambdas receive the same event simultaneously.

---

## Pattern 4: Queue-Based Load Leveling

> **Protecting Downstream Services with Amazon SQS**

### What This Pattern Solves

Traffic spikes result in queued messages rather than overwhelming downstream services. Lambda polls SQS and processes at a controlled rate. Built-in retry logic and a dead-letter queue capture failed messages for investigation.

### Architecture

```
Producer Lambda  →  SQS Queue  →  Consumer Lambda  →  DynamoDB
                        |
                  (after 3 failures)
                        |
                   Dead-Letter Queue
```

---

### Step 1 — Create SQS Queues

**Create the Dead-Letter Queue first:**

1. Navigate to **SQS → Create queue**
   - Type: **Standard**
   - Name: `PaymentQueue-DLQ`
   - Click **Create queue**

**Create the main queue:**

1. Click **Create queue** again
   - Type: **Standard**
   - Name: `PaymentQueue`
2. Scroll to **Dead-letter queue** → Enable
   - Choose queue: `PaymentQueue-DLQ`
   - Maximum receives: `3`
3. Click **Create queue**
4. Copy the **PaymentQueue URL** — you will need it in the producer Lambda

---

### Step 2 — Create the Producer Lambda

Create Lambda: Name `PaymentProducer`, Runtime `Python 3.12`, Role `LambdaLabRole`  
Replace `YOUR_PAYMENTQUEUE_URL` with your actual URL:

```python
import json, boto3, uuid

sqs = boto3.client('sqs')
QUEUE_URL = 'YOUR_PAYMENTQUEUE_URL'  # Replace with your actual queue URL

def lambda_handler(event, context):
    count = event.get('count', 5)
    sent = []
    for i in range(count):
        payment = {
            'paymentId': str(uuid.uuid4())[:8],
            'amount': round(10 + i * 5.5, 2),
            'customerId': f'cust-{i+1:03d}'
        }
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(payment)
        )
        sent.append(payment['paymentId'])
    print(f'Sent {count} payment messages to SQS')
    return {'statusCode': 200, 'sent': sent}
```

---

### Step 3 — Create the Consumer Lambda

Create Lambda: Name `PaymentProcessor`, Runtime `Python 3.12`, Role `LambdaLabRole`

```python
import json

def lambda_handler(event, context):
    for record in event['Records']:
        payment = json.loads(record['body'])
        print(f"Processing payment {payment['paymentId']} "
              f"for ${payment['amount']} from {payment['customerId']}")
        # In production: call payment gateway here
    
    print(f'Batch complete: {len(event["Records"])} payments processed')
    return {'processed': len(event['Records'])}
```

Add the SQS trigger: In `PaymentProcessor` → **Add trigger**
- Source: **SQS**
- Queue: `PaymentQueue`
- Batch size: `5`
- Enabled: Yes
- Click **Add**

---

### ✅ Verify — Pattern 4

1. Test `PaymentProducer` with: `{"count": 10}` — should return 10 payment IDs
2. Navigate to **SQS → PaymentQueue → Send and receive messages → Poll for messages** — watch messages appear then drain rapidly as Lambda processes them
3. Check **CloudWatch → /aws/lambda/PaymentProcessor** — confirm all 10 payments were processed in batches of 5

**Test the DLQ:**
1. Temporarily add `raise Exception("Simulated failure")` to `PaymentProcessor`, deploy it
2. Send 3 messages via `PaymentProducer`
3. After 3 retries each, messages appear in `PaymentQueue-DLQ`
4. Remove the exception and redeploy before continuing

---

## Pattern 5: Fan-Out / Fan-In

> **Parallel Processing via Amazon SNS**

### What This Pattern Solves

When a single event needs to trigger multiple independent processes simultaneously, SNS broadcasts to all subscribers in parallel. What would take minutes sequentially completes in seconds when every processor runs at the same time.

### Architecture

```
Trigger Lambda  →  SNS Topic  →  ThumbnailGenerator  (parallel)
                             →  MetadataExtractor   (parallel)
                             →  ImageClassifier     (parallel)
```

---

### Step 1 — Create the SNS Topic

1. Navigate to **SNS → Create topic**
   - Type: **Standard**
   - Name: `ImageProcessingTopic`
   - Click **Create topic**
2. Copy the **Topic ARN** — you will use it in the publisher Lambda

---

### Step 2 — Create Subscriber Lambdas

**Lambda 1:** Name `ThumbnailGenerator`, Runtime `Python 3.12`, Role `LambdaLabRole`

```python
import json

def lambda_handler(event, context):
    for record in event['Records']:
        msg = json.loads(record['Sns']['Message'])
        filename = msg.get('filename', 'unknown')
        print(f'[THUMBNAIL] Generating 128x128 thumbnail for {filename}')
        print(f'[THUMBNAIL] Writing to thumbnails/{filename}')
    return {'task': 'thumbnail', 'status': 'complete'}
```

**Lambda 2:** Name `MetadataExtractor`, Runtime `Python 3.12`, Role `LambdaLabRole`

```python
import json

def lambda_handler(event, context):
    for record in event['Records']:
        msg = json.loads(record['Sns']['Message'])
        filename = msg.get('filename', 'unknown')
        print(f'[METADATA] Extracting EXIF data from {filename}')
        print(f'[METADATA] Camera: Canon EOS R5, ISO: 400, f/2.8')
    return {'task': 'metadata', 'status': 'complete'}
```

**Lambda 3:** Name `ImageClassifier`, Runtime `Python 3.12`, Role `LambdaLabRole`

```python
import json

def lambda_handler(event, context):
    for record in event['Records']:
        msg = json.loads(record['Sns']['Message'])
        filename = msg.get('filename', 'unknown')
        print(f'[CLASSIFY] Running ML classification on {filename}')
        print(f'[CLASSIFY] Labels: outdoor (0.97), landscape (0.91), sunset (0.84)')
    return {'task': 'classify', 'status': 'complete'}
```

---

### Step 3 — Subscribe All Three Lambdas to SNS

For each Lambda above:

1. Navigate to **SNS → ImageProcessingTopic → Create subscription**
   - Protocol: **AWS Lambda**
   - Endpoint: (ARN of the Lambda)
   - Click **Create subscription**

Repeat 3 times — one subscription per Lambda.

---

### Step 4 — Create the Fan-Out Publisher Lambda

Create Lambda: Name `ImageUploadHandler`, Runtime `Python 3.12`, Role `LambdaLabRole`  
Replace `YOUR_IMAGEPROCESSINGTOPIC_ARN`:

```python
import json, boto3

sns = boto3.client('sns')
SNS_ARN = 'YOUR_IMAGEPROCESSINGTOPIC_ARN'  # Replace with your Topic ARN

def lambda_handler(event, context):
    filename = event.get('filename', 'photo.jpg')
    message = {
        'filename': filename,
        'bucket': 'my-image-bucket',
        'size': '2.4MB',
        'uploadedAt': '2025-02-25T10:00:00Z'
    }
    response = sns.publish(
        TopicArn=SNS_ARN,
        Message=json.dumps(message),
        Subject='New Image Uploaded'
    )
    print(f'Published image event for {filename}')
    print(f'SNS MessageId: {response["MessageId"]}')
    return {'statusCode': 200, 'messageId': response['MessageId']}
```

---

### ✅ Verify — Pattern 5

1. Test `ImageUploadHandler` with: `{"filename": "vacation.jpg"}`
2. Within seconds, check CloudWatch logs for all three processors — they should all show log entries with **nearly identical timestamps**, confirming parallel execution
3. Try sending 3 different images quickly and observe 9 total Lambda invocations (3 images × 3 processors) all overlapping in time

**Key insight:** All three Lambdas received the **same SNS message independently**. Adding a fourth processor requires only a new Lambda and one new SNS subscription — zero changes to existing code.

---

## Pattern 6: File & Document Processing

> **S3 Event Pipeline — Automatic Processing on Upload**

### What This Pattern Solves

S3 invokes Lambda automatically when files arrive. No polling, no scheduling — processing begins within milliseconds of upload. You pay only for the compute time used to process each file. Scales from zero to thousands of files per second automatically.

### Architecture

```
S3 Upload  →  S3 Event Notification  →  Lambda  →  S3 (Processed Bucket)
```

---

### Step 1 — Create S3 Buckets

1. Navigate to **S3 → Create bucket**
   - Name: `serverless-uploads-[YOUR_INITIALS]-[4_RANDOM_DIGITS]`
     *(e.g. `serverless-uploads-jd-4821` — bucket names must be globally unique)*
   - Region: same as your Lambda functions
   - All other settings: default
   - Click **Create bucket**

2. Create a second bucket:
   - Name: `serverless-processed-[YOUR_INITIALS]-[4_RANDOM_DIGITS]`
   - Same region, same defaults

Note both bucket names — you will use them in the Lambda code.

---

### Step 2 — Create the File Processor Lambda

1. Create Lambda: Name `DocumentProcessor`, Runtime `Python 3.12`, Role `LambdaLabRole`
2. Set timeout to **30 seconds**: Configuration → General configuration → Edit → Timeout: `0 min 30 sec` → Save
3. Replace `serverless-processed-YOUR-SUFFIX` with your actual processed bucket name:

```python
import json, boto3

s3 = boto3.client('s3')
PROCESSED_BUCKET = 'serverless-processed-YOUR-SUFFIX'  # Replace

def lambda_handler(event, context):
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        size = record['s3']['object']['size']
        
        print(f'Processing: s3://{bucket}/{key} ({size} bytes)')
        
        # Read the uploaded file
        obj = s3.get_object(Bucket=bucket, Key=key)
        content = obj['Body'].read().decode('utf-8', errors='ignore')[:500]
        
        # Write enriched result to processed bucket
        result = {
            'source': key,
            'sourceBucket': bucket,
            'sizeBytes': size,
            'contentPreview': content,
            'status': 'processed'
        }
        out_key = f'processed/{key}.json'
        s3.put_object(
            Bucket=PROCESSED_BUCKET,
            Key=out_key,
            Body=json.dumps(result, indent=2),
            ContentType='application/json'
        )
        print(f'Result written to s3://{PROCESSED_BUCKET}/{out_key}')
    
    return {'processed': len(event['Records'])}
```

---

### Step 3 — Configure the S3 Event Trigger

1. Navigate to your **uploads bucket → Properties**
2. Scroll to **Event notifications → Create event notification**
   - Name: `NewFileUploaded`
   - Event types: ✅ **All object create events**
   - Destination: **Lambda function** → `DocumentProcessor`
3. Click **Save changes**

---

### ✅ Verify — Pattern 6

1. Navigate to your uploads bucket → **Upload** → Choose any `.txt` or `.csv` file → **Upload**
2. Check **CloudWatch → /aws/lambda/DocumentProcessor** — you should see the file name, size, and `Result written to s3://...`
3. Navigate to your **processed bucket** → `processed/` prefix → open the `.json` output file
4. Verify it contains the source filename, size, and content preview
5. Check **Lambda → DocumentProcessor → Monitor → Invocations** — confirms S3 triggered the function automatically

**Extension:** Upload two files at the same time — confirm two separate Lambda invocations appear in CloudWatch with overlapping timestamps.

---

## End of Day 1

You have built the complete serverless foundation, incrementally:

| Pattern | What You Added | You Can Now |
|---------|---------------|-------------|
| 1 | Lambda + API Gateway + DynamoDB | Expose a working REST API backed by a serverless database |
| 2 | Cognito + Lambda Authorizer | Require valid JWT tokens to access API endpoints |
| 3 | EventBridge | Decouple services so they publish and subscribe to events |
| 4 | SQS + DLQ | Buffer traffic spikes and handle failures gracefully |
| 5 | SNS Fan-Out | Broadcast one event to multiple parallel processors |
| 6 | S3 Events | Trigger processing automatically on file upload |

> **Resources will be deleted automatically in ~4 hours.**  
> Day 2 starts completely fresh — no dependency on any of today's resources.

---

*Continue to **Day 2** for advanced patterns: stream processing, orchestration, AI integration, document intelligence, and event sourcing.*
