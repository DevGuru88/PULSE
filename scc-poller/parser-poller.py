import os
import json
import yaml
import logging
import asyncio
from datetime import datetime, timezone
import vertexai
from vertexai import agent_engines
from google.cloud import storage

logging.basicConfig(level=logging.INFO)

# Read configuration from Cloud Run environment variables
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
LOCATION = os.environ.get("GCP_REGION", "")
AGENT_ENGINE_ID = os.environ.get("AGENT_ENGINE_ID", "")
GCS_DATA_BUCKET = os.environ.get("GCS_DATA_BUCKET", "")

FINDINGS_FILE = "findings.yaml"
PENDING_DOCS_FOLDER = "pending-documents"

# Validate required configuration at startup
_missing = [k for k, v in {
    "GCP_PROJECT_ID": PROJECT_ID,
    "GCP_REGION": LOCATION,
    "AGENT_ENGINE_ID": AGENT_ENGINE_ID,
    "GCS_DATA_BUCKET": GCS_DATA_BUCKET,
}.items() if not v]
if _missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(_missing)}")


# -------------------------------
# Initialize Vertex AI Agent
# -------------------------------
def init_agent():
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    agent = agent_engines.get(AGENT_ENGINE_ID)
    return agent


# -------------------------------
# Parse SCC findings
# -------------------------------
def parse_findings():

    findings_payload = []

    if not os.path.exists(FINDINGS_FILE):
        logging.warning("findings.yaml not found")
        return findings_payload

    try:

        with open(FINDINGS_FILE, "r") as f:

            docs = yaml.safe_load_all(f)

            for doc in docs:

                if not doc:
                    continue

                finding = doc.get("finding", {})
                resource = doc.get("resource", {})

                payload = {
                    "category": finding.get("category"),
                    "severity": finding.get("severity"),
                    "description": finding.get("description"),
                    "recommendation": finding.get("sourceProperties", {}).get("Recommendation"),
                    "event_time": finding.get("eventTime"),
                    "resource": {
                        "name": resource.get("displayName"),
                        "project": resource.get("projectDisplayName"),
                        "service": resource.get("service"),
                        "type": resource.get("type")
                    }
                }

                findings_payload.append(payload)

    except Exception as e:
        logging.error(f"Error parsing findings: {e}")

    return findings_payload


# -------------------------------
# Convert a single finding → agent prompt
# -------------------------------
def build_agent_prompt(finding):

    prompt = f"""
You are a GCP security assistant.

Analyze the following Security Command Center finding.

Provide:

1. Root cause
2. Mitigation steps
3. SOP for remediation
4. Knowledge base documentation

Finding:
{json.dumps(finding, indent=2)}
"""

    return prompt


# -------------------------------
# Call Vertex AI Agent
# -------------------------------
async def call_agent(agent, message):

    response_text = ""

    session = agent.create_session(user_id="security_pipeline")

    if isinstance(session, dict):
        session_id = session.get("id") or session.get("name")
    else:
        session_id = getattr(session, "id", None)

    async for event in agent.async_stream_query(
        message=message,
        user_id="security_pipeline",
        session_id=session_id,
    ):

        if isinstance(event, dict):

            if "content" in event and "parts" in event["content"]:
                for part in event["content"]["parts"]:
                    if "text" in part:
                        response_text += part["text"]

            elif "text" in event:
                response_text += event["text"]

        elif hasattr(event, "text"):
            response_text += event.text

    return response_text


# -------------------------------
# Upload response to GCS
# -------------------------------
def upload_to_gcs(response_text, finding_index, category):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_category = (category or "unknown").replace(" ", "-").replace("/", "-").lower()
    filename = f"scc-finding-{finding_index}-{safe_category}-{timestamp}.txt"
    blob_path = f"{PENDING_DOCS_FOLDER}/{filename}"

    logging.info(f"Uploading response to gs://{GCS_DATA_BUCKET}/{blob_path}")

    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(GCS_DATA_BUCKET)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(response_text, content_type="text/plain")

    logging.info(f"Response uploaded to gs://{GCS_DATA_BUCKET}/{blob_path}")
    return blob_path


# -------------------------------
# Main pipeline
# -------------------------------
def main():

    logging.info("Parsing SCC findings")

    findings = parse_findings()

    logging.info(f"Total findings detected: {len(findings)}")

    if not findings:
        logging.info("No findings detected. Skipping agent call.")
        return

    logging.info("Initializing Vertex AI agent")

    agent = init_agent()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for i, finding in enumerate(findings, start=1):
        category = finding.get("category", "unknown")
        logging.info(f"Processing finding {i}/{len(findings)}: {category}")

        prompt = build_agent_prompt(finding)

        logging.info(f"Sending finding {i} to agent")

        response = loop.run_until_complete(call_agent(agent, prompt))

        logging.info(f"Agent response received for finding {i}")

        print(f"\n======= AGENT RESPONSE (Finding {i}: {category}) =======\n")
        print(response)

        if response:
            upload_to_gcs(response, i, category)

    loop.close()

    logging.info(f"All {len(findings)} findings processed")


if __name__ == "__main__":
    main()