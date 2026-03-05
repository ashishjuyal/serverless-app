
import json
import os
import time
import uuid
import hashlib
from typing import Any, Dict, Optional

import boto3
from strands import Agent, tool
from strands.models import BedrockModel
from datetime import datetime
from zoneinfo import ZoneInfo

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

MODEL_ID = os.getenv("MODEL_ID")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PROMPT_BUCKET = os.getenv("PROMPT_BUCKET")
PROMPT_KEY = os.getenv("PROMPT_KEY")
AWS_REGION = os.getenv("AWS_REGION")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", AWS_REGION)
SERVICE_NAME = os.getenv("SERVICE_NAME", "ai-doc-processor")

ENV_NAME = os.getenv("ENV_NAME", "dev")
lambda_client = boto3.client("lambda", region_name=AWS_REGION)

EXTRACTION_AGENT_LAMBDA = os.getenv("EXTRACTION_AGENT_LAMBDA", f"InvoiceExtractionContainer-{ENV_NAME}")

# ── Observability clients ────────────────────────────────────────────────────
logger = Logger(service=SERVICE_NAME, level=LOG_LEVEL)
metrics = Metrics(namespace="AIDocProcessor", service=SERVICE_NAME)
tracer = Tracer(service=SERVICE_NAME)


@tool(name="send_whatsapp_notification", description="Send WhatsApp notification with extracted invoice data")
def send_whatsapp_notification(
    extracted_data: str = None,
    processId: Optional[str] = None,
) -> str:
    # Simulate sending WhatsApp notification (to be replaced with actual implementation)
    logger.info(
        "Sending WhatsApp notification",
        extra={"tool": "send_whatsapp_notification", "process_id": processId},
    )
    metrics.add_metric(name="WhatsAppNotificationAttempts", unit=MetricUnit.Count, value=1)
    return json.dumps("Send WhatsApp Notification Tool Invoked Successfully")


@tool(name="perform_invoice_posting_to_sap", description="Post extracted invoice data to SAP system")
def perform_invoice_posting_to_sap(
    extracted_data: str = None,
    processId: Optional[str] = None,
) -> str:
    # Simulate posting to SAP (to be replaced with actual implementation)
    logger.info(
        "Posting invoice to SAP",
        extra={"tool": "perform_invoice_posting_to_sap", "process_id": processId},
    )
    metrics.add_metric(name="SapPostingAttempts", unit=MetricUnit.Count, value=1)
    return json.dumps("Perform Invoice Posting to SAP Tool Invoked Successfully")


@tool(name="validate_invoice_data", description="Validate extracted invoice data")
def validate_invoice_data(
    extracted_data: Optional[Dict[str, Any]] = None,
    processId: Optional[str] = None,
) -> str:
    # Simple validation logic (to be expanded as needed)
    required_fields = ["invoice_number", "date", "total_amount", "vendor_name"]
    # missing_fields = [field for field in required_fields if field not in extracted_data]

    # if missing_fields:
    #     validation_result = {
    #         "processId": processId,
    #         "is_valid": False,
    #         "missing_fields": missing_fields,
    #         "message": f"Missing required fields: {', '.join(missing_fields)}"
    #     }
    # else:
    #     validation_result = {
    #         "processId": processId,
    #         "is_valid": True,
    #         "message": "All required fields are present."
    #     }

    logger.info(
        "Validating invoice data",
        extra={
            "tool": "validate_invoice_data",
            "process_id": processId,
            "required_fields": required_fields,
        },
    )
    metrics.add_metric(name="InvoiceValidationAttempts", unit=MetricUnit.Count, value=1)
    return json.dumps("Validate Invoice Data Tool Invoked Successfully")


@tool(name="textract_extraction_agent", description="Extract text/data from document using Textract agent Lambda")
def textract_extraction_agent(
    bucket: Optional[str] = None,
    key: Optional[str] = None,
    processId: Optional[str] = None,
) -> str:

    payload = {
        "processId": processId,
        "tool": "extract_document",
        "parameters": {"s3_bucket": bucket, "s3_key": key, "imageOutputPath": "imageOutput"},
    }

    logger.info(
        "Invoking Textract extraction Lambda",
        extra={
            "tool": "textract_extraction_agent",
            "process_id": processId,
            "extraction_lambda": EXTRACTION_AGENT_LAMBDA,
            "s3_bucket": bucket,
            "s3_key": key,
        },
    )
    metrics.add_metric(name="TextractExtractionAttempts", unit=MetricUnit.Count, value=1)
    # resp = lambda_client.invoke(
    #     FunctionName=EXTRACTION_AGENT_LAMBDA,
    #     InvocationType="RequestResponse",
    #     Payload=json.dumps(payload),
    # )
    # raw = resp["Payload"].read().decode("utf-8")
    # parsed = json.loads(raw)
    # extract = parsed.get("extracted_table") or parsed.get("output") or parsed
    # kv = parsed.get("kv") or {}

    # result = {
    #     "processId": processId,
    #     "inputFile": f"{bucket}/{key}",
    #     "extracted_data": parsed,
    #     "meta-info": "extracted_data is the information in the document"
    # }

    return json.dumps("Extraction Lambda Tool Invoked Successfully")


@logger.inject_lambda_context(log_event=False)
@metrics.log_metrics(capture_cold_start_metric=True)
@tracer.capture_lambda_handler
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Orchestrator Lambda handler for the AI document processing pipeline.
    Triggered by S3 object upload events or invoked via API Gateway HTTP.
    """
    logger.info("Lambda handler started", extra={"env": ENV_NAME, "model_id": MODEL_ID})

    # ── S3 trigger ───────────────────────────────────────────────────────────
    if "Records" in event and event["Records"][0].get("eventSource") == "aws:s3":
        logger.info("S3 trigger detected — beginning invoice processing pipeline")

        s3_info = event["Records"][0]["s3"]
        bucket_name = s3_info["bucket"]["name"]
        object_key = s3_info["object"]["key"]

        logger.info(
            "Processing S3 object",
            extra={"bucket": bucket_name, "key": object_key},
        )
        metrics.add_metric(name="InvoicesReceived", unit=MetricUnit.Count, value=1)

        try:
            logger.info(
                "Initialising Bedrock orchestrator agent",
                extra={"model_id": MODEL_ID, "region": AWS_REGION},
            )
            bedrock_model = BedrockModel(model_id=MODEL_ID, region_name=AWS_REGION, streaming=False)
            orchestrator = Agent(
                model=bedrock_model,
                name="DocumentExtractionOrchestrator",
                description="Runs tool-driven pipeline for document extraction and processing.",
                system_prompt=(
                    "You're an orchestrator agent that coordinates various document processing tasks "
                    "using specialized tools. You decide which tool to use based on the input document "
                    "and the desired output. Output of can be considered as input to the next tool in "
                    "the pipeline. Send whatsapp notification when the processing starts and ends."
                ),
                tools=[
                    textract_extraction_agent,
                    validate_invoice_data,
                    perform_invoice_posting_to_sap,
                    send_whatsapp_notification,
                ],
            )

            result = orchestrator(
                "Run the invoice processing pipeline. Key inputs are s3 bucket and key. "
                f"S3 Bucket name is {bucket_name} and object key is {object_key}."
            )

            logger.info("Orchestration pipeline completed successfully", extra={"result": str(result)})
            metrics.add_metric(name="InvoicesProcessed", unit=MetricUnit.Count, value=1)

        except Exception as exc:
            logger.exception(
                "Orchestration pipeline failed",
                extra={"bucket": bucket_name, "key": object_key, "error": str(exc)},
            )
            metrics.add_metric(name="InvoiceProcessingErrors", unit=MetricUnit.Count, value=1)
            raise

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "S3 event processed successfully.",
                    "bucket": bucket_name,
                    "key": object_key,
                }
            ),
        }

    # ── API Gateway trigger ──────────────────────────────────────────────────
    elif "httpMethod" in event:
        logger.info("HTTP trigger detected", extra={"method": event.get("httpMethod"), "path": event.get("path")})
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/plain"},
            "body": (
                "Thank you for connecting me. However, I am expected to process a "
                "document when a document is uploaded to the S3 bucket."
            ),
        }

    # ── Unknown trigger ──────────────────────────────────────────────────────
    else:
        logger.warning("Unknown invocation source", extra={"event_keys": list(event.keys())})
        return {
            "statusCode": 400,
            "body": json.dumps("Unknown invocation source."),
        }
