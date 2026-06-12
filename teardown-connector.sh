#!/usr/bin/env bash
# ============================================================================
# Lifecycle AI Agent — GCP Teardown / Uninstall Script
# ============================================================================
#
# PURPOSE:
#   This script is the ONE-COMMAND uninstall tool that completely removes all
#   GCP resources created by the initial-connector.sh setup script.
#
# USAGE:
#   cd pulse
#   bash teardown-connector.sh
#
# WHAT IT DOES (in strategic reverse-dependency order):
#   1.  Reads configuration from connector.env (or asks for project details)
#   2.  Displays a detailed warning of everything that will be deleted
#   3.  Requires the user to type "I Agree" before proceeding
#   4.  Deletes Cloud Scheduler job
#   5.  Deletes Cloud Run Job (SCC poller)
#   6.  Deletes Cloud Run Service (dashboard)
#   7.  Deletes Agent Engines (document-editor, security-monitor)
#   8.  Deletes RAG Corpus (Vertex AI)
#   9.  Deletes Pub/Sub Topic
#  10.  Deletes Secret Manager secrets
#  11.  Deletes BigQuery Dataset (cascade — includes all tables)
#  12.  Deletes GCS Buckets (data + Terraform state)
#  13.  Deletes Artifact Registry repositories (with all images)
#  14.  Removes Service Account IAM role bindings
#  15.  Deletes the Service Account
#  16.  Optionally disables GCP APIs
#  17.  Cleans up local infrastructure files
#
# SAFETY:
#   - Every resource is checked for existence before deletion
#   - A clear warning and "I Agree" prompt protect against accidental runs
#   - The script logs all actions to ~/lifecycle-agent-teardown.log
#
# REQUIREMENTS:
#   - Run inside GCP Cloud Shell (gcloud, bq, gsutil pre-installed)
#   - The user must have at minimum "Editor" role on the GCP project
#
# Author: Solomon Leo
# ============================================================================

set -eo pipefail

# ============================================================================
# SECTION 0: CONSTANTS & COLOR DEFINITIONS
# ============================================================================

readonly SCRIPT_VERSION="1.0.0"
readonly TEARDOWN_LOG_FILE="${HOME}/lifecycle-agent-teardown.log"
readonly ENV_FILE="${HOME}/lifecycle-agent-infra/connector.env"
readonly TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# INFRA_DIR is not readonly because connector.env also defines it and will be
# sourced later. Using 'readonly' would cause bash to error on reassignment.
INFRA_DIR="${HOME}/lifecycle-agent-infra"

# Resource naming defaults (same as initial-connector.sh).
# NOT readonly — connector.env (sourced in load_configuration) may reassign
# them with the same values. Using 'readonly' would cause bash to error out.
SA_NAME="lifecycle-agent-sa"
AR_REPO_NAME="lifecycle-agent-repo"
SCC_AR_REPO_NAME="scc-poller-repo"
CLOUD_RUN_SERVICE_NAME="lifecycle-agent"
SCC_CLOUD_RUN_JOB_NAME="scc-poller-job"
SCC_SCHEDULER_NAME="scc-poller-schedule"
PUBSUB_TOPIC_NAME="lifecycle-agent-events"
BQ_DATASET_NAME="lifecycle_agent"

# Colors
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly MAGENTA='\033[0;35m'
readonly BOLD='\033[1m'
readonly DIM='\033[2m'
readonly NC='\033[0m'  # No Color

# Mutable globals — populated from connector.env or user input
GCP_PROJECT_ID=""
GCP_REGION=""
SA_EMAIL=""
GCS_DATA_BUCKET=""
GCS_TF_STATE_BUCKET=""

# Counters
DELETED_COUNT=0
SKIPPED_COUNT=0
FAILED_COUNT=0

# ============================================================================
# SECTION 1: UTILITY FUNCTIONS
# ============================================================================

log() {
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S")] $*" >> "${TEARDOWN_LOG_FILE}"
}

print_banner() {
    echo ""
    echo -e "${RED}${BOLD}"
    echo "  ╔══════════════════════════════════════════════════════════════════╗"
    echo "  ║                                                                  ║"
    echo "  ║         🗑️  Lifecycle AI Agent — Teardown Script v${SCRIPT_VERSION}          ║"
    echo "  ║                                                                  ║"
    echo "  ║    Complete Uninstall of All GCP Resources                        ║"
    echo "  ║    Created by initial-connector.sh                                ║"
    echo "  ║                                                                  ║"
    echo "  ╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
}

print_step() {
    local step_num=$1
    local total=$2
    local description=$3
    echo ""
    echo -e "${BLUE}${BOLD}  [${step_num}/${total}] ${description}${NC}"
    echo -e "${DIM}  ────────────────────────────────────────────────────${NC}"
    log "STEP ${step_num}/${total}: ${description}"
}

print_success() {
    echo -e "         ${GREEN}✅ $1${NC}"
    log "SUCCESS: $1"
}

print_warning() {
    echo -e "         ${YELLOW}⚠️  $1${NC}"
    log "WARNING: $1"
}

print_error() {
    echo -e "         ${RED}❌ $1${NC}"
    log "ERROR: $1"
}

print_info() {
    echo -e "         ${DIM}ℹ️  $1${NC}"
    log "INFO: $1"
}

print_substep() {
    echo -e "         ${CYAN}→ $1${NC}"
}

print_deleted() {
    echo -e "         ${GREEN}🗑️  $1${NC}"
    log "DELETED: $1"
    DELETED_COUNT=$((DELETED_COUNT + 1))
}

print_skipped() {
    echo -e "         ${DIM}⏭️  $1 (not found — skipping)${NC}"
    log "SKIPPED: $1"
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
}

print_failed() {
    echo -e "         ${RED}⚠️  Failed to delete: $1${NC}"
    log "FAILED: $1"
    FAILED_COUNT=$((FAILED_COUNT + 1))
}

# ============================================================================
# SECTION 2: PRE-FLIGHT CHECKS
# ============================================================================

preflight_checks() {
    echo -e "${BOLD}  Running pre-flight checks...${NC}"
    echo ""

    # Check gcloud
    if ! command -v gcloud &>/dev/null; then
        print_error "gcloud CLI not found. Please run this script in GCP Cloud Shell."
        exit 1
    fi
    print_success "gcloud CLI found"

    # Check bq
    if ! command -v bq &>/dev/null; then
        print_error "BigQuery CLI (bq) not found. Please run this script in GCP Cloud Shell."
        exit 1
    fi
    print_success "BigQuery CLI (bq) found"

    # Check authentication
    local account=""
    account=$(gcloud config get-value account 2>/dev/null) || true
    if [[ -z "${account}" || "${account}" == "(unset)" ]]; then
        print_error "Not authenticated to GCP. Run: gcloud auth login"
        exit 1
    fi
    print_success "Authenticated as: ${account}"

    echo ""
}

# ============================================================================
# SECTION 3: LOAD CONFIGURATION
# ============================================================================

load_configuration() {
    echo -e "${BOLD}${MAGENTA}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${MAGENTA}  📋 LOADING CONFIGURATION${NC}"
    echo -e "${BOLD}${MAGENTA}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Try to load from connector.env first
    if [[ -f "${ENV_FILE}" ]]; then
        print_success "Found environment file: ${ENV_FILE}"
        print_substep "Loading configuration from connector.env..."

        # Source the env file to get all variables
        # shellcheck source=/dev/null
        source "${ENV_FILE}"

        # Validate that required variables were loaded
        if [[ -n "${GCP_PROJECT_ID}" && -n "${GCP_REGION}" ]]; then
            print_success "Configuration loaded from connector.env"
            print_info "Project ID: ${GCP_PROJECT_ID}"
            print_info "Region: ${GCP_REGION}"
            print_info "Service Account: ${SA_EMAIL:-${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com}"
            echo ""
            return
        else
            print_warning "connector.env is incomplete. Falling back to manual input."
        fi
    else
        print_info "No connector.env found at ${ENV_FILE}"
        print_info "Falling back to manual input..."
    fi

    echo ""

    # ── Manual input: GCP Project ID ──
    local detected_project=""
    detected_project=$(gcloud config get-value project 2>/dev/null) || true
    if [[ -n "${detected_project}" && "${detected_project}" != "(unset)" ]]; then
        echo -e "  ${BLUE}${BOLD}1. GCP Project ID${NC} ${DIM}[auto-detected: ${detected_project}]:${NC}"
    else
        detected_project=""
        echo -e "  ${BLUE}${BOLD}1. GCP Project ID${NC} ${DIM}(required):${NC}"
    fi
    local input_project_id=""
    read -r -p "     > " input_project_id
    GCP_PROJECT_ID="${input_project_id:-${detected_project}}"

    if [[ -z "${GCP_PROJECT_ID}" ]]; then
        print_error "GCP Project ID is required. Exiting."
        exit 1
    fi

    # Validate the project exists and we have access
    if ! gcloud projects describe "${GCP_PROJECT_ID}" &>/dev/null; then
        print_error "Cannot access project '${GCP_PROJECT_ID}'. Check the ID and your permissions."
        exit 1
    fi
    print_success "Project validated: ${GCP_PROJECT_ID}"

    # Set the project
    gcloud config set project "${GCP_PROJECT_ID}" --quiet 2>/dev/null || true
    echo ""

    # ── Manual input: GCP Region ──
    echo -e "  ${BLUE}${BOLD}2. GCP Region${NC} ${DIM}[default: europe-west1]:${NC}"
    local input_region=""
    read -r -p "     > " input_region
    GCP_REGION="${input_region:-europe-west1}"
    print_success "Region: ${GCP_REGION}"
    echo ""

    # ── Derive computed variables ──
    SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

    # Try to detect bucket names from existing GCS buckets
    print_substep "Detecting existing bucket names..."
    local buckets_list=""
    buckets_list=$(gsutil ls 2>/dev/null) || true

    GCS_DATA_BUCKET=$(echo "${buckets_list}" | grep -oP "lifecycle-agent-[^/]+-data-${GCP_PROJECT_ID}" | head -1) || true
    GCS_TF_STATE_BUCKET=$(echo "${buckets_list}" | grep -oP "lifecycle-agent-[^/]+-tfstate-${GCP_PROJECT_ID}" | head -1) || true

    if [[ -n "${GCS_DATA_BUCKET}" ]]; then
        print_info "Detected data bucket: ${GCS_DATA_BUCKET}"
    else
        print_info "Data bucket not auto-detected (will attempt pattern-based discovery)"
    fi
    if [[ -n "${GCS_TF_STATE_BUCKET}" ]]; then
        print_info "Detected TF state bucket: ${GCS_TF_STATE_BUCKET}"
    else
        print_info "TF state bucket not auto-detected (will attempt pattern-based discovery)"
    fi
    echo ""
}

# ============================================================================
# SECTION 4: DESTRUCTIVE WARNING & CONFIRMATION
# ============================================================================

confirm_teardown() {
    echo ""
    echo -e "${RED}${BOLD}"
    echo "  ╔══════════════════════════════════════════════════════════════════╗"
    echo "  ║                                                                  ║"
    echo "  ║          ⚠️  ⚠️  ⚠️   DESTRUCTIVE OPERATION   ⚠️  ⚠️  ⚠️           ║"
    echo "  ║                                                                  ║"
    echo "  ╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
    echo -e "  ${RED}${BOLD}WARNING: This script will PERMANENTLY DELETE the following resources${NC}"
    echo -e "  ${RED}${BOLD}from GCP project: ${GCP_PROJECT_ID}${NC}"
    echo ""
    echo -e "  ${RED}${BOLD}This action is IRREVERSIBLE. All data will be LOST.${NC}"
    echo ""
    echo -e "  ${BOLD}Resources that will be deleted:${NC}"
    echo ""
    echo -e "    ${RED}🗑️  Cloud Scheduler:${NC}       ${SCC_SCHEDULER_NAME}"
    echo -e "    ${RED}🗑️  Cloud Run Job:${NC}          ${SCC_CLOUD_RUN_JOB_NAME}"
    echo -e "    ${RED}🗑️  Cloud Run Service:${NC}      ${CLOUD_RUN_SERVICE_NAME} (including IAP config)"
    echo -e "    ${RED}🗑️  Agent Engines:${NC}          document-editor, security-monitor"
    echo -e "    ${RED}🗑️  RAG Corpus:${NC}             All Vertex AI RAG corpora for this project"
    echo -e "    ${RED}🗑️  Pub/Sub Topic:${NC}          ${PUBSUB_TOPIC_NAME}"
    echo -e "    ${RED}🗑️  Secrets:${NC}                lifecycle-agent-confluence-token, lifecycle-agent-jira-token"
    echo -e "    ${RED}🗑️  BigQuery Dataset:${NC}       ${BQ_DATASET_NAME} (ALL tables included)"
    echo -e "    ${RED}🗑️  GCS Buckets:${NC}            Data bucket + Terraform state bucket (ALL contents)"
    echo -e "    ${RED}🗑️  Artifact Registry:${NC}      ${AR_REPO_NAME}, ${SCC_AR_REPO_NAME} (ALL Docker images)"
    echo -e "    ${RED}🗑️  Service Account:${NC}        ${SA_NAME} (ALL IAM bindings removed)"
    echo -e "    ${RED}🗑️  Local Files:${NC}            ${INFRA_DIR}/ (Terraform, config, env files)"
    echo ""
    echo -e "  ${YELLOW}${BOLD}═══════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${YELLOW}${BOLD}  To proceed, type exactly:  I Agree${NC}"
    echo -e "  ${YELLOW}${BOLD}  To cancel, type anything else or press Ctrl+C${NC}"
    echo ""
    echo -e "  ${YELLOW}${BOLD}═══════════════════════════════════════════════════════════════════${NC}"
    echo ""
    local confirmation=""
    read -r -p "     > " confirmation

    if [[ "${confirmation}" != "I Agree" ]]; then
        echo ""
        echo -e "  ${GREEN}Teardown cancelled. No resources were deleted.${NC}"
        echo ""
        exit 0
    fi

    echo ""
    echo -e "  ${RED}${BOLD}Confirmation received. Starting teardown in 5 seconds...${NC}"
    echo -e "  ${DIM}  Press Ctrl+C NOW to abort.${NC}"
    sleep 5
    echo ""
}

# ============================================================================
# SECTION 5: DELETE CLOUD SCHEDULER
# ============================================================================

delete_cloud_scheduler() {
    local total_steps=13
    print_step 1 "${total_steps}" "Deleting Cloud Scheduler Job"

    local scheduler_exists=0
    gcloud scheduler jobs describe "${SCC_SCHEDULER_NAME}" \
        --location="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" &>/dev/null || scheduler_exists=$?

    if [[ ${scheduler_exists} -eq 0 ]]; then
        print_substep "Deleting scheduler: ${SCC_SCHEDULER_NAME}..."
        local delete_exit=0
        gcloud scheduler jobs delete "${SCC_SCHEDULER_NAME}" \
            --location="${GCP_REGION}" \
            --project="${GCP_PROJECT_ID}" \
            --quiet 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

        if [[ ${delete_exit} -eq 0 ]]; then
            print_deleted "Cloud Scheduler job: ${SCC_SCHEDULER_NAME}"
        else
            print_failed "Cloud Scheduler job: ${SCC_SCHEDULER_NAME} (exit=${delete_exit})"
        fi
    else
        print_skipped "Cloud Scheduler job: ${SCC_SCHEDULER_NAME}"
    fi
}

# ============================================================================
# SECTION 6: DELETE CLOUD RUN JOB (SCC Poller)
# ============================================================================

delete_cloud_run_job() {
    local total_steps=13
    print_step 2 "${total_steps}" "Deleting Cloud Run Job (SCC Poller)"

    local job_exists=0
    gcloud run jobs describe "${SCC_CLOUD_RUN_JOB_NAME}" \
        --region="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" &>/dev/null || job_exists=$?

    if [[ ${job_exists} -eq 0 ]]; then
        print_substep "Deleting Cloud Run job: ${SCC_CLOUD_RUN_JOB_NAME}..."
        local delete_exit=0
        gcloud run jobs delete "${SCC_CLOUD_RUN_JOB_NAME}" \
            --region="${GCP_REGION}" \
            --project="${GCP_PROJECT_ID}" \
            --quiet 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

        if [[ ${delete_exit} -eq 0 ]]; then
            print_deleted "Cloud Run job: ${SCC_CLOUD_RUN_JOB_NAME}"
        else
            print_failed "Cloud Run job: ${SCC_CLOUD_RUN_JOB_NAME} (exit=${delete_exit})"
        fi
    else
        print_skipped "Cloud Run job: ${SCC_CLOUD_RUN_JOB_NAME}"
    fi
}

# ============================================================================
# SECTION 7: DELETE CLOUD RUN SERVICE (Dashboard)
# ============================================================================

delete_cloud_run_service() {
    local total_steps=13
    print_step 3 "${total_steps}" "Deleting Cloud Run Service (Dashboard)"

    if gcloud run services describe "${CLOUD_RUN_SERVICE_NAME}" \
        --region="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" &>/dev/null; then

        print_substep "Deleting Cloud Run service: ${CLOUD_RUN_SERVICE_NAME}..."
        local delete_exit=0
        gcloud run services delete "${CLOUD_RUN_SERVICE_NAME}" \
            --region="${GCP_REGION}" \
            --project="${GCP_PROJECT_ID}" \
            --quiet 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

        if [[ ${delete_exit} -eq 0 ]]; then
            print_deleted "Cloud Run service: ${CLOUD_RUN_SERVICE_NAME}"
        else
            print_failed "Cloud Run service: ${CLOUD_RUN_SERVICE_NAME} (exit=${delete_exit})"
        fi
    else
        print_skipped "Cloud Run service: ${CLOUD_RUN_SERVICE_NAME}"
    fi
}

# ============================================================================
# SECTION 8: DELETE AGENT ENGINES
# ============================================================================

delete_agent_engines() {
    local total_steps=13
    print_step 4 "${total_steps}" "Deleting Agent Engines (Vertex AI)"

    local agents=("document-editor" "security-monitor")

    for agent_name in "${agents[@]}"; do
        print_substep "Looking for agent engine: ${agent_name}..."

        local agent_resource=""
        agent_resource=$(gcloud ai agent-engines list \
            --project="${GCP_PROJECT_ID}" \
            --region="${GCP_REGION}" \
            --filter="displayName:${agent_name}" \
            --format="value(name)" \
            --limit=1 2>/dev/null) || true

        if [[ -n "${agent_resource}" ]]; then
            print_substep "Deleting agent engine: ${agent_name} (${agent_resource})..."
            local delete_exit=0
            gcloud ai agent-engines delete "${agent_resource}" \
                --project="${GCP_PROJECT_ID}" \
                --region="${GCP_REGION}" \
                --quiet 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

            if [[ ${delete_exit} -eq 0 ]]; then
                print_deleted "Agent engine: ${agent_name}"
            else
                print_failed "Agent engine: ${agent_name} (exit=${delete_exit})"
            fi
        else
            print_skipped "Agent engine: ${agent_name}"
        fi
    done
}

# ============================================================================
# SECTION 9: DELETE RAG CORPUS (Vertex AI)
# ============================================================================

delete_rag_corpus() {
    local total_steps=13
    print_step 5 "${total_steps}" "Deleting RAG Corpora (Vertex AI)"

    # List all RAG corpora that match our naming pattern
    print_substep "Searching for lifecycle RAG corpora..."

    local corpora_list=""
    corpora_list=$(python3 -c "
import sys
try:
    from vertexai.preview import rag
    import vertexai
    vertexai.init(project='${GCP_PROJECT_ID}', location='${GCP_REGION}')
    corpora = rag.list_corpora()
    for corpus in corpora:
        if 'lifecycle' in corpus.display_name.lower():
            print(corpus.name + '|' + corpus.display_name)
except ImportError as e:
    print('ERROR: Missing Python package — ' + str(e), file=sys.stderr)
except Exception as e:
    print('ERROR: Failed to list RAG corpora — ' + str(e), file=sys.stderr)
" 2>>"${TEARDOWN_LOG_FILE}") || true

    if [[ -z "${corpora_list}" ]]; then
        print_skipped "RAG corpora (no lifecycle corpora found)"
        return
    fi

    while IFS='|' read -r corpus_resource corpus_display; do
        if [[ -n "${corpus_resource}" ]]; then
            print_substep "Deleting RAG corpus: ${corpus_display} (${corpus_resource})..."
            local delete_exit=0
            python3 -c "
import sys
try:
    from vertexai.preview import rag
    import vertexai
    vertexai.init(project='${GCP_PROJECT_ID}', location='${GCP_REGION}')
    rag.delete_corpus(name='${corpus_resource}')
    print('Deleted successfully')
except ImportError as e:
    print('ERROR: Missing Python package — ' + str(e), file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print('ERROR: Failed to delete corpus — ' + str(e), file=sys.stderr)
    sys.exit(1)
" 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

            if [[ ${delete_exit} -eq 0 ]]; then
                print_deleted "RAG corpus: ${corpus_display}"
            else
                print_failed "RAG corpus: ${corpus_display} (exit=${delete_exit})"
            fi
        fi
    done <<< "${corpora_list}"
}

# ============================================================================
# SECTION 10: DELETE PUB/SUB TOPIC
# ============================================================================

delete_pubsub() {
    local total_steps=13
    print_step 6 "${total_steps}" "Deleting Pub/Sub Topic"

    local topic_exists=0
    gcloud pubsub topics describe "${PUBSUB_TOPIC_NAME}" \
        --project="${GCP_PROJECT_ID}" &>/dev/null || topic_exists=$?

    if [[ ${topic_exists} -eq 0 ]]; then
        # First delete any subscriptions on this topic
        print_substep "Checking for subscriptions on topic ${PUBSUB_TOPIC_NAME}..."
        local subscriptions=""
        subscriptions=$(gcloud pubsub subscriptions list \
            --filter="topic:projects/${GCP_PROJECT_ID}/topics/${PUBSUB_TOPIC_NAME}" \
            --format="value(name)" \
            --project="${GCP_PROJECT_ID}" 2>/dev/null) || true

        if [[ -n "${subscriptions}" ]]; then
            while IFS= read -r sub; do
                if [[ -n "${sub}" ]]; then
                    print_substep "Deleting subscription: ${sub}..."
                    local sub_exit=0
                    gcloud pubsub subscriptions delete "${sub}" \
                        --project="${GCP_PROJECT_ID}" \
                        --quiet 2>>"${TEARDOWN_LOG_FILE}" || sub_exit=$?
                    if [[ ${sub_exit} -eq 0 ]]; then
                        print_deleted "Pub/Sub subscription: ${sub}"
                    else
                        print_failed "Pub/Sub subscription: ${sub} (exit=${sub_exit})"
                    fi
                fi
            done <<< "${subscriptions}"
        fi

        print_substep "Deleting topic: ${PUBSUB_TOPIC_NAME}..."
        local delete_exit=0
        gcloud pubsub topics delete "${PUBSUB_TOPIC_NAME}" \
            --project="${GCP_PROJECT_ID}" \
            --quiet 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

        if [[ ${delete_exit} -eq 0 ]]; then
            print_deleted "Pub/Sub topic: ${PUBSUB_TOPIC_NAME}"
        else
            print_failed "Pub/Sub topic: ${PUBSUB_TOPIC_NAME} (exit=${delete_exit})"
        fi
    else
        print_skipped "Pub/Sub topic: ${PUBSUB_TOPIC_NAME}"
    fi
}

# ============================================================================
# SECTION 11: DELETE SECRET MANAGER SECRETS
# ============================================================================

delete_secrets() {
    local total_steps=13
    print_step 7 "${total_steps}" "Deleting Secret Manager Secrets"

    local secrets=(
        "lifecycle-agent-confluence-token"
        "lifecycle-agent-jira-token"
    )

    for secret_id in "${secrets[@]}"; do
        local sec_exists=0
        gcloud secrets describe "${secret_id}" \
            --project="${GCP_PROJECT_ID}" &>/dev/null || sec_exists=$?

        if [[ ${sec_exists} -eq 0 ]]; then
            print_substep "Deleting secret: ${secret_id}..."
            local delete_exit=0
            gcloud secrets delete "${secret_id}" \
                --project="${GCP_PROJECT_ID}" \
                --quiet 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

            if [[ ${delete_exit} -eq 0 ]]; then
                print_deleted "Secret: ${secret_id}"
            else
                print_failed "Secret: ${secret_id} (exit=${delete_exit})"
            fi
        else
            print_skipped "Secret: ${secret_id}"
        fi
    done
}

# ============================================================================
# SECTION 12: DELETE BIGQUERY DATASET & TABLES
# ============================================================================

delete_bigquery_resources() {
    local total_steps=13
    print_step 8 "${total_steps}" "Deleting BigQuery Dataset & Tables"

    local ds_exists=0
    bq ls --project_id="${GCP_PROJECT_ID}" "${BQ_DATASET_NAME}" &>/dev/null || ds_exists=$?

    if [[ ${ds_exists} -eq 0 ]]; then
        print_substep "Deleting dataset: ${BQ_DATASET_NAME} (including all tables)..."
        local delete_exit=0
        bq rm --recursive --force --dataset \
            "${GCP_PROJECT_ID}:${BQ_DATASET_NAME}" 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

        if [[ ${delete_exit} -eq 0 ]]; then
            print_deleted "BigQuery dataset: ${BQ_DATASET_NAME} (with all tables)"
        else
            print_failed "BigQuery dataset: ${BQ_DATASET_NAME} (exit=${delete_exit})"
        fi
    else
        print_skipped "BigQuery dataset: ${BQ_DATASET_NAME}"
    fi
}

# ============================================================================
# SECTION 13: DELETE GCS BUCKETS
# ============================================================================

delete_storage_buckets() {
    local total_steps=13
    print_step 9 "${total_steps}" "Deleting Cloud Storage Buckets"

    local buckets=()

    # Add buckets from configuration if available
    if [[ -n "${GCS_DATA_BUCKET}" ]]; then
        buckets+=("${GCS_DATA_BUCKET}")
    fi
    if [[ -n "${GCS_TF_STATE_BUCKET}" ]]; then
        buckets+=("${GCS_TF_STATE_BUCKET}")
    fi

    # If no buckets were found from config, try pattern-based discovery
    if [[ ${#buckets[@]} -eq 0 ]]; then
        print_substep "Discovering lifecycle-agent buckets by pattern..."
        local discovered=""
        discovered=$(gsutil ls 2>/dev/null | grep -oP "gs://lifecycle-agent-[^/]+-(?:data|tfstate)-${GCP_PROJECT_ID}" | sed 's|gs://||') || true

        if [[ -n "${discovered}" ]]; then
            while IFS= read -r bucket_name; do
                if [[ -n "${bucket_name}" ]]; then
                    buckets+=("${bucket_name}")
                fi
            done <<< "${discovered}"
        fi
    fi

    if [[ ${#buckets[@]} -eq 0 ]]; then
        print_skipped "GCS buckets (none found matching lifecycle-agent pattern)"
        return
    fi

    for bucket in "${buckets[@]}"; do
        local bucket_exists=0
        gsutil ls -b "gs://${bucket}" &>/dev/null || bucket_exists=$?

        if [[ ${bucket_exists} -eq 0 ]]; then
            print_substep "Deleting all objects in bucket: ${bucket}..."
            local rm_exit=0
            gsutil -m rm -r "gs://${bucket}/**" 2>>"${TEARDOWN_LOG_FILE}" || rm_exit=$?
            if [[ ${rm_exit} -ne 0 ]]; then
                print_warning "Some objects in bucket ${bucket} could not be deleted (exit=${rm_exit})"
            fi

            print_substep "Deleting bucket: ${bucket}..."
            local delete_exit=0
            gsutil rb "gs://${bucket}" 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

            if [[ ${delete_exit} -eq 0 ]]; then
                print_deleted "GCS bucket: ${bucket}"
            else
                print_failed "GCS bucket: ${bucket} (exit=${delete_exit})"
            fi
        else
            print_skipped "GCS bucket: ${bucket}"
        fi
    done
}

# ============================================================================
# SECTION 14: DELETE ARTIFACT REGISTRY REPOSITORIES
# ============================================================================

delete_artifact_registries() {
    local total_steps=13
    print_step 10 "${total_steps}" "Deleting Artifact Registry Repositories"

    local repos=("${AR_REPO_NAME}" "${SCC_AR_REPO_NAME}")

    for repo in "${repos[@]}"; do
        local repo_exists=0
        gcloud artifacts repositories describe "${repo}" \
            --location="${GCP_REGION}" \
            --project="${GCP_PROJECT_ID}" &>/dev/null || repo_exists=$?

        if [[ ${repo_exists} -eq 0 ]]; then
            print_substep "Deleting Artifact Registry: ${repo} (including all images)..."
            local delete_exit=0
            gcloud artifacts repositories delete "${repo}" \
                --location="${GCP_REGION}" \
                --project="${GCP_PROJECT_ID}" \
                --quiet 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

            if [[ ${delete_exit} -eq 0 ]]; then
                print_deleted "Artifact Registry: ${repo}"
            else
                print_failed "Artifact Registry: ${repo} (exit=${delete_exit})"
            fi
        else
            print_skipped "Artifact Registry: ${repo}"
        fi
    done
}

# ============================================================================
# SECTION 15: REMOVE IAM BINDINGS & DELETE SERVICE ACCOUNT
# ============================================================================

delete_service_account() {
    local total_steps=13
    print_step 11 "${total_steps}" "Removing IAM Bindings & Deleting Service Account"

    local sa_email="${SA_EMAIL:-${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com}"

    # Check if the service account exists
    local sa_exists=""
    sa_exists=$(gcloud iam service-accounts list \
        --filter="email:${sa_email}" \
        --format="value(email)" \
        --project="${GCP_PROJECT_ID}" 2>/dev/null) || true

    if [[ -z "${sa_exists}" ]]; then
        print_skipped "Service account: ${sa_email}"
        return
    fi

    # ── Remove all IAM role bindings for this service account ──
    # NOTE: This list must be kept in sync with the roles granted in
    # create_service_account() inside initial-connector.sh (Section 6).
    print_substep "Removing IAM role bindings for ${sa_email}..."

    local sa_member="serviceAccount:${sa_email}"
    local sa_roles=(
        "roles/aiplatform.user"
        "roles/bigquery.dataEditor"
        "roles/bigquery.jobUser"
        "roles/storage.objectAdmin"
        "roles/logging.viewer"
        "roles/logging.logWriter"
        "roles/monitoring.viewer"
        "roles/secretmanager.secretAccessor"
        "roles/pubsub.publisher"
        "roles/pubsub.subscriber"
        "roles/run.invoker"
        "roles/run.jobs.invoker"
        "roles/secretmanager.viewer"
        "roles/connectors.admin"
        "roles/securitycenter.findingsViewer"
    )

    local removed_count=0
    for role in "${sa_roles[@]}"; do
        local unbind_exit=0
        gcloud projects remove-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="${sa_member}" \
            --role="${role}" \
            --quiet 2>>"${TEARDOWN_LOG_FILE}" || unbind_exit=$?

        if [[ ${unbind_exit} -eq 0 ]]; then
            removed_count=$((removed_count + 1))
        fi
    done
    print_info "Removed ${removed_count}/${#sa_roles[@]} IAM role bindings"

    # ── Remove serviceAccountTokenCreator at the service account level ──
    gcloud iam service-accounts remove-iam-policy-binding "${sa_email}" \
        --member="${sa_member}" \
        --role="roles/iam.serviceAccountTokenCreator" \
        --quiet 2>>"${TEARDOWN_LOG_FILE}" || true
    print_info "Removed roles/iam.serviceAccountTokenCreator from SA-level policy (best-effort)"

    # ── Also remove the AI Platform service agent binding if present ──
    local project_number=""
    project_number=$(gcloud projects describe "${GCP_PROJECT_ID}" \
        --format="value(projectNumber)" 2>/dev/null) || true

    if [[ -n "${project_number}" ]]; then
        local aiplatform_sa="serviceAccount:service-${project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
        gcloud projects remove-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="${aiplatform_sa}" \
            --role="roles/aiplatform.user" \
            --quiet 2>>"${TEARDOWN_LOG_FILE}" || true
        gcloud projects remove-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="${aiplatform_sa}" \
            --role="roles/storage.objectUser" \
            --quiet 2>>"${TEARDOWN_LOG_FILE}" || true
        print_info "Removed AI Platform service agent bindings (best-effort)"
    fi

    # ── Delete the service account ──
    print_substep "Deleting service account: ${sa_email}..."
    local delete_exit=0
    gcloud iam service-accounts delete "${sa_email}" \
        --project="${GCP_PROJECT_ID}" \
        --quiet 2>>"${TEARDOWN_LOG_FILE}" || delete_exit=$?

    if [[ ${delete_exit} -eq 0 ]]; then
        print_deleted "Service account: ${sa_email}"
    else
        print_failed "Service account: ${sa_email} (exit=${delete_exit})"
    fi
}

# ============================================================================
# SECTION 16: DISABLE GCP APIs (Optional)
# ============================================================================

disable_apis() {
    local total_steps=13
    print_step 12 "${total_steps}" "Disabling GCP APIs (Optional)"

    echo ""
    echo -e "  ${YELLOW}${BOLD}  Disabling APIs can affect OTHER services in this project.${NC}"
    echo -e "  ${YELLOW}${BOLD}  Only disable if you are sure no other workloads use these APIs.${NC}"
    echo ""
    echo -e "  ${BOLD}  Disable lifecycle-agent APIs? [y/N]${NC}"
    local disable_confirm=""
    read -r -p "     > " disable_confirm

    if [[ "${disable_confirm,,}" != "y" && "${disable_confirm,,}" != "yes" ]]; then
        print_info "Skipping API disablement (safe default)"
        return
    fi

    # NOTE: pubsub.googleapis.com is NOT included here because it's a core GCP
    # service commonly used by Cloud Build, Container Registry, and other services.
    # Attempting to disable it often fails with FAILED_PRECONDITION.
    local apis=(
        "cloudscheduler.googleapis.com"
        "discoveryengine.googleapis.com"
        "connectors.googleapis.com"
        "iap.googleapis.com"
    )

    print_warning "Only disabling APIs that are unlikely to be shared. Core APIs (run, storage, bigquery, etc.) are left enabled."

    for api in "${apis[@]}"; do
        local api_enabled=""
        api_enabled=$(gcloud services list --enabled \
            --filter="config.name=${api}" \
            --format="value(config.name)" 2>/dev/null) || true

        if [[ -n "${api_enabled}" ]]; then
            print_substep "Disabling ${api}..."
            local disable_exit=0
            gcloud services disable "${api}" \
                --project="${GCP_PROJECT_ID}" \
                --quiet 2>>"${TEARDOWN_LOG_FILE}" || disable_exit=$?

            if [[ ${disable_exit} -eq 0 ]]; then
                print_deleted "API: ${api}"
            else
                print_failed "API: ${api} (exit=${disable_exit})"
            fi
        else
            print_skipped "API: ${api} (not enabled)"
        fi
    done
}

# ============================================================================
# SECTION 17: CLEAN UP LOCAL FILES
# ============================================================================

cleanup_local_files() {
    local total_steps=13
    print_step 13 "${total_steps}" "Cleaning Up Local Files"

    # Clean up infrastructure directory
    if [[ -d "${INFRA_DIR}" ]]; then
        print_substep "Removing infrastructure directory: ${INFRA_DIR}..."
        rm -rf "${INFRA_DIR}"
        print_deleted "Local directory: ${INFRA_DIR}"
    else
        print_skipped "Local directory: ${INFRA_DIR}"
    fi

    # Clean up setup log file (keep teardown log)
    local setup_log="${HOME}/lifecycle-agent-setup.log"
    if [[ -f "${setup_log}" ]]; then
        print_substep "Removing setup log: ${setup_log}..."
        rm -f "${setup_log}"
        print_deleted "Setup log: ${setup_log}"
    else
        print_skipped "Setup log: ${setup_log}"
    fi
}

# ============================================================================
# SECTION 18: PRINT FINAL SUMMARY
# ============================================================================

print_final_summary() {
    echo ""
    echo ""

    # Save structured log
    cat >> "${TEARDOWN_LOG_FILE}" <<LOG_ENTRY

========================================
TEARDOWN COMPLETED: ${TIMESTAMP}
========================================
Project:       ${GCP_PROJECT_ID}
Region:        ${GCP_REGION}
Deleted:       ${DELETED_COUNT} resources
Skipped:       ${SKIPPED_COUNT} resources (not found)
Failed:        ${FAILED_COUNT} resources
========================================
LOG_ENTRY

    if [[ ${FAILED_COUNT} -eq 0 ]]; then
        echo -e "${GREEN}${BOLD}"
        echo "  ╔══════════════════════════════════════════════════════════════════╗"
        echo "  ║                                                                  ║"
        echo "  ║       ✅ ✅ ✅   TEARDOWN COMPLETE!   ✅ ✅ ✅                   ║"
        echo "  ║                                                                  ║"
        echo "  ╚══════════════════════════════════════════════════════════════════╝"
        echo -e "${NC}"
    else
        echo -e "${YELLOW}${BOLD}"
        echo "  ╔══════════════════════════════════════════════════════════════════╗"
        echo "  ║                                                                  ║"
        echo "  ║     ⚠️  TEARDOWN COMPLETED WITH WARNINGS   ⚠️                    ║"
        echo "  ║                                                                  ║"
        echo "  ╚══════════════════════════════════════════════════════════════════╝"
        echo -e "${NC}"
    fi

    echo ""
    echo -e "  ${BOLD}📊 Teardown Summary:${NC}"
    echo ""
    echo -e "    ${GREEN}🗑️  Deleted:${NC}  ${DELETED_COUNT} resources"
    echo -e "    ${DIM}⏭️  Skipped:${NC}  ${SKIPPED_COUNT} resources (already removed or never created)"
    if [[ ${FAILED_COUNT} -gt 0 ]]; then
        echo -e "    ${RED}❌ Failed:${NC}   ${FAILED_COUNT} resources (check log for details)"
    else
        echo -e "    ${GREEN}❌ Failed:${NC}   0 resources"
    fi
    echo ""
    echo -e "  ${BOLD}📁 Teardown log:${NC} ${CYAN}${TEARDOWN_LOG_FILE}${NC}"
    echo ""

    if [[ ${FAILED_COUNT} -gt 0 ]]; then
        echo -e "  ${YELLOW}${BOLD}⚠️  Some resources could not be deleted automatically.${NC}"
        echo -e "  ${YELLOW}  Please review the teardown log and remove them manually:${NC}"
        echo -e "  ${DIM}  cat ${TEARDOWN_LOG_FILE}${NC}"
        echo ""
    fi

    echo -e "  ${BOLD}⏱️  Total teardown time:${NC} $((SECONDS / 60)) minutes $((SECONDS % 60)) seconds"
    echo ""
    echo -e "  ${DIM}The Lifecycle AI Agent has been completely removed from project ${GCP_PROJECT_ID}.${NC}"
    echo -e "  ${DIM}To set up again, run: bash initial-connector.sh${NC}"
    echo ""
}

# ============================================================================
# SECTION 19: MAIN EXECUTION FLOW
# ============================================================================

main() {
    # Initialize log and timer
    echo "========================================" > "${TEARDOWN_LOG_FILE}"
    echo "Lifecycle AI Agent Teardown — ${TIMESTAMP}" >> "${TEARDOWN_LOG_FILE}"
    echo "Script Version: ${SCRIPT_VERSION}" >> "${TEARDOWN_LOG_FILE}"
    echo "========================================" >> "${TEARDOWN_LOG_FILE}"

    # Reset timer
    SECONDS=0

    # ── Phase 1: Pre-flight, configuration, and confirmation ──
    print_banner
    preflight_checks
    load_configuration
    confirm_teardown

    # Set the project for all subsequent gcloud commands
    gcloud config set project "${GCP_PROJECT_ID}" --quiet 2>/dev/null || true

    # ── Phase 2: Strategic deletion in reverse-dependency order ──
    # Each function checks if the resource exists before attempting deletion.

    # Step 1: Cloud Scheduler (depends on Cloud Run Job)
    delete_cloud_scheduler

    # Step 2: Cloud Run Job (depends on Artifact Registry image)
    delete_cloud_run_job

    # Step 3: Cloud Run Service (depends on Artifact Registry image, IAP)
    delete_cloud_run_service

    # Step 4: Agent Engines (Vertex AI)
    delete_agent_engines

    # Step 5: RAG Corpus (Vertex AI)
    delete_rag_corpus

    # Step 6: Pub/Sub Topic
    delete_pubsub

    # Step 7: Secrets
    delete_secrets

    # Step 8: BigQuery Dataset + Tables
    delete_bigquery_resources

    # Step 9: GCS Buckets
    delete_storage_buckets

    # Step 10: Artifact Registry repos (now safe — no Cloud Run referencing images)
    delete_artifact_registries

    # Step 11: Service Account + IAM bindings
    delete_service_account

    # Step 12: APIs (optional, user-prompted)
    disable_apis

    # Step 13: Local files
    cleanup_local_files

    # ── Phase 3: Summary ──
    print_final_summary
}

# Run main
main "$@"
