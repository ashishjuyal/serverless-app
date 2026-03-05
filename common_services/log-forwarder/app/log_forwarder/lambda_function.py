"""
Log Forwarder Lambda
====================
Subscribes to CloudWatch Logs via a subscription filter.

CloudWatch Logs compresses each batch with gzip and base64-encodes it before
delivering it to the subscription destination. This function:

  1. Decodes + decompresses each incoming Kinesis record.
  2. Parses the CloudWatch Logs JSON envelope.
  3. Attempts to parse each log event message as structured JSON
     (produced by AWS Lambda Powertools Logger in the orchestrator).
  4. Enriches each document with CloudWatch metadata (log group, stream, timestamp).
  5. Bulk-indexes the documents into Amazon OpenSearch Service.


Environment variables
---------------------
OPENSEARCH_ENDPOINT  : OpenSearch domain endpoint (no scheme, no trailing slash)
                       e.g. "search-ai-doc-logs-dev-xxx.ap-southeast-2.es.amazonaws.com"
INDEX_NAME           : OpenSearch index to write into   (default: "lambda-logs")
AWS_REGION           : AWS region                        (default: "ap-southeast-2")
"""

import base64
import gzip
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection, helpers

# ── Configuration ────────────────────────────────────────────────────────────
OPENSEARCH_ENDPOINT = os.environ["OPENSEARCH_ENDPOINT"]
INDEX_NAME = os.environ.get("INDEX_NAME", "lambda-logs")
REGION = os.environ.get("AWS_REGION", "ap-southeast-2")


def _build_client() -> OpenSearch:
    """Create an OpenSearch client signed with the Lambda execution role credentials."""
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
    """Base64-decode and gzip-decompress a single CloudWatch Logs payload."""
    compressed = base64.b64decode(encoded)
    decompressed = gzip.decompress(compressed)
    return json.loads(decompressed)


def _build_documents(cw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert a CloudWatch Logs data envelope into a list of OpenSearch documents.

    Each CloudWatch log event becomes one document.  Structured JSON messages
    (from Lambda Powertools) are unpacked so their fields become top-level
    OpenSearch fields — enabling rich filtering and visualisation in Dashboards.
    """
    log_group = cw_data.get("logGroup", "")
    log_stream = cw_data.get("logStream", "")
    documents = []

    for event in cw_data.get("logEvents", []):
        # Try to parse the message as JSON (Lambda Powertools structured log)
        try:
            doc = json.loads(event["message"])
        except (json.JSONDecodeError, KeyError):
            doc = {"message": event.get("message", "")}

        # Inject CloudWatch envelope metadata
        doc.setdefault("@timestamp", _epoch_ms_to_iso(event.get("timestamp")))
        doc["cw_log_group"] = log_group
        doc["cw_log_stream"] = log_stream
        doc["cw_event_id"] = event.get("id", "")

        documents.append(doc)

    return documents


def _epoch_ms_to_iso(epoch_ms: Any) -> str:
    """Convert epoch milliseconds to ISO-8601 string (UTC)."""
    if not epoch_ms:
        return datetime.now(timezone.utc).isoformat()
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Entry point invoked by the CloudWatch Logs subscription filter.

    The event contains a single key ``awslogs`` with a ``data`` field that
    holds the base64+gzip-compressed CloudWatch Logs batch.
    """
    client = _build_client()

    # CloudWatch Logs subscription filter sends a single record per invocation
    raw_data = event.get("awslogs", {}).get("data", "")
    if not raw_data:
        print("No awslogs.data found in event — skipping.")
        return {"statusCode": 200, "forwarded": 0}

    cw_data = _decode_cw_record(raw_data)

    # Skip control messages (heartbeats sent by CloudWatch Logs)
    if cw_data.get("messageType") == "CONTROL_MESSAGE":
        print("Control message received — skipping.")
        return {"statusCode": 200, "forwarded": 0}

    documents = _build_documents(cw_data)
    if not documents:
        return {"statusCode": 200, "forwarded": 0}

    # Bulk index into OpenSearch
    actions = [{"_index": INDEX_NAME, "_source": doc} for doc in documents]
    success_count, errors = helpers.bulk(client, actions, raise_on_error=False)

    if errors:
        print(f"OpenSearch bulk errors ({len(errors)}): {json.dumps(errors[:3])}")

    print(
        f"Forwarded {success_count}/{len(documents)} log events "
        f"from {cw_data.get('logGroup')} → {INDEX_NAME}"
    )

    return {"statusCode": 200, "forwarded": success_count, "errors": len(errors)}
