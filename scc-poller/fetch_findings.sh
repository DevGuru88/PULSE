#!/bin/bash

set -eo pipefail

# Read from Cloud Run environment variable
PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID environment variable must be set}"

END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
START_TIME=$(date -u -d "5 minutes ago" +"%Y-%m-%dT%H:%M:%SZ")

FILTER="state=\"ACTIVE\" AND create_time>=\"$START_TIME\" AND create_time<=\"$END_TIME\" AND (severity=\"HIGH\" OR severity=\"CRITICAL\")"

echo "Fetching findings between $START_TIME and $END_TIME (severity: HIGH, CRITICAL)"

if ! gcloud scc findings list projects/$PROJECT_ID/sources/- \
  --filter="$FILTER" \
  --format=yaml > findings.yaml 2>&1; then
    echo "ERROR: Failed to fetch SCC findings. Ensure the service account has 'roles/securitycenter.findingsViewer'." >&2
    exit 1
fi

echo "Findings written to findings.yaml"