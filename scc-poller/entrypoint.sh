#!/bin/bash
set -eo pipefail

echo "-------------------------------------"
echo "Security Incident Processing Started"
echo "-------------------------------------"

echo "Step 1: Fetch SCC findings"
if ! ./fetch_findings.sh; then
    echo "ERROR: Failed to fetch SCC findings" >&2
    exit 1
fi

if [ ! -f findings.yaml ]; then
    echo "ERROR: findings.yaml was not created by fetch_findings.sh" >&2
    exit 1
fi

if [ ! -s findings.yaml ]; then
    echo "No findings found in the polling window. Exiting cleanly."
    exit 0
fi

echo "Step 2: Parse findings and send to agent"
if ! python parser-poller.py; then
    echo "ERROR: Failed to parse findings" >&2
    exit 1
fi

echo "-------------------------------------"
echo "Pipeline Completed"
echo "-------------------------------------"