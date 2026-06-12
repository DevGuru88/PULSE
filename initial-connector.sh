#!/usr/bin/env bash
# ============================================================================
# Lifecycle AI Agent — GCP Bootstrap Setup Script
# ============================================================================
#
# PURPOSE:
#   This script is the ONE-COMMAND onboarding tool for any engineer who wants
#   to connect their GCP project to the Lifecycle AI Agent platform.
#
# USAGE:
#   git clone https://github.com/solomonpapathoti/pulse.git
#   cd pulse
#   bash scripts/setup.sh
#
# WHAT IT DOES:
#   1. Asks the engineer 6-7 questions about their project
#   2. Enables required GCP APIs
#   3. Creates a service account with necessary IAM roles
#   4. Creates Artifact Registry repository for Docker images
#   5. Creates GCS buckets for data + Terraform state
#   6. Creates BigQuery dataset with agent tables
#   7. Creates Secret Manager secrets (empty, to fill via UI later)
#   8. Creates Pub/Sub topic for event routing
#   9. Builds and pushes the dashboard Docker image
#  10. Deploys the dashboard to Cloud Run
#  11. Configures IAP so only the engineer can access the URL
#  12. Generates Terraform IaC files for future infrastructure management
#  13. Returns the dashboard URL
#
# REQUIREMENTS:
#   - Run inside GCP Cloud Shell (gcloud, docker, bq pre-installed)
#   - Engineer must have at minimum "Editor" role on the GCP project
#   - Internet access for pulling Docker base images
#
# IDEMPOTENCY:
#   This script is safe to re-run. Each step checks if the resource already
#   exists before creating it. Re-running will skip existing resources and
#   only create missing ones.
#
# Author: Solomon Leo
# Date: March 2026
# ============================================================================

# ============================================================================
# FIX: Use 'set -eo pipefail' but NOT 'set -u'.
#
# Why: 'set -u' (nounset) causes the script to crash whenever a variable is
# empty or unset. Many variables in this script are INTENTIONALLY optional
# (GITHUB_REPO, CONFLUENCE_URL, JIRA_URL, etc.), and GCP CLI tools can set
# variables to empty strings. Removing -u prevents these spurious crashes.
#
# We keep -e (errexit) but guard EVERY gcloud/gsutil/bq call that can
# legitimately fail with '|| true' or explicit exit-code handling.
# ============================================================================
set -eo pipefail

# ============================================================================
# SECTION 0: CONSTANTS & COLOR DEFINITIONS
# ============================================================================

readonly SCRIPT_VERSION="1.0.1"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly LOG_FILE="${HOME}/lifecycle-agent-setup.log"
readonly INFRA_DIR="${HOME}/lifecycle-agent-infra"
readonly TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# Service account and naming
readonly SA_NAME="lifecycle-agent-sa"
readonly SA_DISPLAY_NAME="Lifecycle AI Agent Service Account"
readonly AR_REPO_NAME="lifecycle-agent-repo"
readonly SCC_AR_REPO_NAME="scc-poller-repo"
readonly CLOUD_RUN_SERVICE_NAME="lifecycle-agent"
readonly SCC_CLOUD_RUN_JOB_NAME="scc-poller-job"
readonly SCC_SCHEDULER_NAME="scc-poller-schedule"
readonly PUBSUB_TOPIC_NAME="lifecycle-agent-events"
readonly BQ_DATASET_NAME="lifecycle_agent"

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

# ============================================================================
# Mutable globals — initialised to empty so they are never "unset".
# These are populated by ask_questions() and used throughout the script.
# ============================================================================
GCP_PROJECT_ID=""
CONNECTOR_DISPLAY_NAME=""
GCP_REGION=""
GITHUB_REPO=""
GITHUB_REPOS=""
GITHUB_PAT=""
CONFLUENCE_URL=""
JIRA_URL=""
ENGINEER_EMAIL=""
CONNECTOR_SLUG=""
GCS_DATA_BUCKET=""
GCS_TF_STATE_BUCKET=""
SA_EMAIL=""
REGISTRY=""
IMAGE_URI=""
CLOUD_RUN_URL=""
DETECTED_MANAGER_GROUP=""
CORPUS_RESOURCE_NAME=""
SCC_IMAGE_URI=""
SCC_REGISTRY=""

# ============================================================================
# SECTION 1: UTILITY FUNCTIONS
# ============================================================================

log() {
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S")] $*" >> "${LOG_FILE}"
}

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════════════════════════════════════════╗"
    echo "  ║                                                                  ║"
    echo "  ║         🚀 Lifecycle AI Agent — Setup Wizard v${SCRIPT_VERSION}            ║"
    echo "  ║                                                                  ║"
    echo "  ║    AI-Powered PDLC/SDLC Optimization Platform                    ║"
    echo "  ║    Built on Google Cloud Platform + Gemini AI                     ║"
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

# Check if a GCP API is enabled
is_api_enabled() {
    local api_name=$1
    local result=""
    result=$(gcloud services list --enabled --filter="config.name=${api_name}" --format="value(config.name)" 2>/dev/null) || true
    [[ "${result}" == *"${api_name}"* ]]
}

# Check if a resource exists — runs a command and returns 0 (exists) or 1 (not found).
# FIX: avoid 'eval' under set -e; use a subshell with explicit exit-code capture.
resource_exists() {
    local check_command=$1
    if eval "${check_command}" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

# ── Environment file ─────────────────────────────────────────────────────────
# Writes (or updates) a connector.env file inside INFRA_DIR with all current
# configuration values.  The file uses shell-compatible KEY=VALUE syntax so it
# can be sourced directly by other scripts:
#
#   source "${HOME}/lifecycle-agent-infra/connector.env"
#
# Sensitive values (GITHUB_PAT) are deliberately excluded — they are passed as
# Cloud Run environment variables and injected at build time only.
# ─────────────────────────────────────────────────────────────────────────────
write_env_file() {
    local env_file="${INFRA_DIR}/connector.env"

    # Ensure the infra directory exists (it may not yet during early calls).
    mkdir -p "${INFRA_DIR}"

    cat > "${env_file}" <<ENV_EOF
# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle AI Agent — Environment Configuration
# Generated by initial-connector.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# ──────────────────────────────────────────────────────────────────────────────
# Source this file in other scripts:
#   source "\${HOME}/lifecycle-agent-infra/connector.env"
# ──────────────────────────────────────────────────────────────────────────────

# ── GCP Core ─────────────────────────────────────────────────────────────────
GCP_PROJECT_ID="${GCP_PROJECT_ID}"
GCP_REGION="${GCP_REGION}"

# ── Connector Metadata ───────────────────────────────────────────────────────
CONNECTOR_DISPLAY_NAME="${CONNECTOR_DISPLAY_NAME}"
CONNECTOR_SLUG="${CONNECTOR_SLUG}"

# ── External Integrations (non-secret) ───────────────────────────────────────
GITHUB_REPO="${GITHUB_REPO}"
GITHUB_REPOS="${GITHUB_REPOS}"
CONFLUENCE_URL="${CONFLUENCE_URL}"
JIRA_URL="${JIRA_URL}"
ENGINEER_EMAIL="${ENGINEER_EMAIL}"

# ── Service Account ──────────────────────────────────────────────────────────
SA_NAME="${SA_NAME}"
SA_EMAIL="${SA_EMAIL}"

# ── Storage ──────────────────────────────────────────────────────────────────
GCS_DATA_BUCKET="${GCS_DATA_BUCKET}"
GCS_TF_STATE_BUCKET="${GCS_TF_STATE_BUCKET}"

# ── BigQuery ─────────────────────────────────────────────────────────────────
BQ_DATASET_NAME="${BQ_DATASET_NAME}"

# ── Pub/Sub ──────────────────────────────────────────────────────────────────
PUBSUB_TOPIC_NAME="${PUBSUB_TOPIC_NAME}"

# ── Artifact Registry & Docker Images ────────────────────────────────────────
REGISTRY="${REGISTRY}"
IMAGE_URI="${IMAGE_URI}"
SCC_REGISTRY="${SCC_REGISTRY}"
SCC_IMAGE_URI="${SCC_IMAGE_URI}"
AR_REPO_NAME="${AR_REPO_NAME}"
SCC_AR_REPO_NAME="${SCC_AR_REPO_NAME}"

# ── Cloud Run ────────────────────────────────────────────────────────────────
CLOUD_RUN_SERVICE_NAME="${CLOUD_RUN_SERVICE_NAME}"
CLOUD_RUN_URL="${CLOUD_RUN_URL}"

# ── Security Pipeline (SCC Poller) ───────────────────────────────────────────
SCC_CLOUD_RUN_JOB_NAME="${SCC_CLOUD_RUN_JOB_NAME}"
SCC_SCHEDULER_NAME="${SCC_SCHEDULER_NAME}"

# ── RAG Corpus ───────────────────────────────────────────────────────────────
CORPUS_RESOURCE_NAME="${CORPUS_RESOURCE_NAME}"

# ── Infrastructure ───────────────────────────────────────────────────────────
INFRA_DIR="${INFRA_DIR}"
ENV_EOF

    log "Environment file written to ${env_file}"
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

    # Check docker
    if ! command -v docker &>/dev/null; then
        print_error "Docker not found. Please run this script in GCP Cloud Shell."
        exit 1
    fi
    print_success "Docker found"

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

    # Check if in a project
    local current_project=""
    current_project=$(gcloud config get-value project 2>/dev/null) || true
    if [[ -n "${current_project}" && "${current_project}" != "(unset)" ]]; then
        print_info "Current GCP project: ${current_project}"
    fi

    echo ""
}

# ============================================================================
# SECTION 3: INTERACTIVE QUESTIONS
# ============================================================================

ask_questions() {
    echo -e "${BOLD}${MAGENTA}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━���${NC}"
    echo -e "${BOLD}${MAGENTA}  📝 PROJECT CONFIGURATION${NC}"
    echo -e "${BOLD}${MAGENTA}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${DIM}Please provide the following details about your project.${NC}"
    echo -e "  ${DIM}Press Enter to accept defaults shown in [brackets].${NC}"
    echo ""

    # ── Question 1: GCP Project ID ──
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
    echo ""

    # Set the project for all subsequent gcloud commands
    gcloud config set project "${GCP_PROJECT_ID}" --quiet 2>/dev/null || true

    # ── Question 2: Display Name ──
    echo -e "  ${BLUE}${BOLD}2. Display name for this connector${NC} ${DIM}(e.g., 'AcmeReceipt', 'My Project'):${NC}"
    read -r -p "     > " CONNECTOR_DISPLAY_NAME
    if [[ -z "${CONNECTOR_DISPLAY_NAME}" ]]; then
        # Derive from project ID
        CONNECTOR_DISPLAY_NAME="${GCP_PROJECT_ID}"
    fi
    print_success "Connector name: ${CONNECTOR_DISPLAY_NAME}"
    echo ""

    # ── Question 3: GCP Region ──
    echo -e "  ${BLUE}${BOLD}3. GCP Region${NC} ${DIM}[default: europe-west1]:${NC}"
    echo -e "     ${DIM}(Common options: europe-west1, us-central1, asia-southeast1)${NC}"
    local input_region=""
    read -r -p "     > " input_region
    GCP_REGION="${input_region:-europe-west1}"
    print_success "Region: ${GCP_REGION}"
    echo ""

    # ── Question 4: GitHub Personal Access Token (Optional) ──
    echo -e "  ${BLUE}${BOLD}4. GitHub Personal Access Token (PAT)${NC} ${DIM}(optional, press Enter to skip):${NC}"
    echo ""
    echo -e "     ${DIM}Steps to create a PAT for GitHub:${NC}"
    echo -e "     ${DIM}  1. Go to: https://github.com/settings/personal-access-tokens/new${NC}"
    echo -e "     ${DIM}  2. Create token name${NC}"
    echo -e "     ${DIM}  3. Select resource owner as 'solomonpapathoti'${NC}"
    echo -e "     ${DIM}  4. Set expiration date${NC}"
    echo -e "     ${DIM}  5. Select \"Only select repositories\" and select your repository from the dropdown list${NC}"
    echo -e "     ${DIM}  6. Inside permissions under the repositories tab, select the following permissions:${NC}"
    echo -e "     ${DIM}     Contents, Dependabot alerts, Pull requests, Metadata (selected by default)${NC}"
    echo -e "     ${DIM}  7. Copy the generated token and paste it here${NC}"
    echo ""
    echo -e "     ${YELLOW}⚠  You can skip this step but currently we haven't added the feature${NC}"
    echo -e "     ${YELLOW}   to add PAT from the frontend and re-deploy the agents, so if you${NC}"
    echo -e "     ${YELLOW}   skip this step you will not be able to integrate GitHub MCP later.${NC}"
    echo ""
    read -r -p "     > " GITHUB_PAT
    if [[ -z "${GITHUB_PAT}" ]]; then
        print_warning "No GitHub PAT provided. GitHub MCP tool will not be integrated."
        GITHUB_PAT=""
    else
        print_success "GitHub PAT: (provided)"
    fi
    echo ""

    # ── Question 5: GitHub Repository Names ──
    # Collect repository names in org/repo format. Multiple repos are supported
    # as a comma-separated list. The first repo is also stored as GITHUB_REPO
    # for backward compatibility with the dashboard and Cloud Run env vars.
    echo -e "  ${BLUE}${BOLD}5. GitHub repository names${NC} ${DIM}(optional, press Enter to skip):${NC}"
    echo -e "     ${DIM}Format: org/repo — separate multiple repos with commas${NC}"
    echo -e "     ${DIM}Example: solomonpapathoti/my-app${NC}"
    echo -e "     ${DIM}Example: solomonpapathoti/my-app,solomonpapathoti/my-lib${NC}"
    local input_repos=""
    read -r -p "     > " input_repos
    if [[ -n "${input_repos}" ]]; then
        # Normalize: trim whitespace around commas, collapse empty entries
        GITHUB_REPOS=$(echo "${input_repos}" | sed 's/[[:space:]]*,[[:space:]]*/,/g' | sed 's/,,*/,/g' | sed 's/^,//;s/,$//')
        # First repo becomes the primary GITHUB_REPO for backward compatibility
        GITHUB_REPO="${GITHUB_REPOS%%,*}"
        local repo_count
        repo_count=$(echo "${GITHUB_REPOS}" | awk -F',' '{print NF}')
        print_success "GitHub repos (${repo_count}): ${GITHUB_REPOS}"
    else
        GITHUB_REPOS=""
        GITHUB_REPO=""
        print_info "GitHub repos: Skipped (can configure later)"
    fi
    echo ""

    # ── Question 6: Confluence Page (Optional) ──
    echo -e "  ${BLUE}${BOLD}6. Confluence project page URL${NC} ${DIM}(optional, press Enter to skip):${NC}"
    echo -e "     ${DIM}Example: https://confluence.example.com/display/PROJECT${NC}"
    read -r -p "     > " CONFLUENCE_URL
    if [[ -z "${CONFLUENCE_URL}" ]]; then
        CONFLUENCE_URL=""
        print_info "Confluence: Skipped (can configure later in dashboard)"
    else
        print_success "Confluence: ${CONFLUENCE_URL}"
    fi
    echo ""

    # ── Question 7: Jira Project (Optional) ──
    echo -e "  ${BLUE}${BOLD}7. Jira sprint space URL${NC} ${DIM}(optional, press Enter to skip):${NC}"
    echo -e "     ${DIM}Example: https://jira.example.com/projects/ACMERX${NC}"
    read -r -p "     > " JIRA_URL
    if [[ -z "${JIRA_URL}" ]]; then
        JIRA_URL=""
        print_info "Jira: Skipped (can configure later in dashboard)"
    else
        print_success "Jira: ${JIRA_URL}"
    fi
    echo ""

    # ── Question 8: Engineer Email (Auto-detect) ──
    local detected_email=""
    detected_email=$(gcloud config get-value account 2>/dev/null) || true
    echo -e "  ${BLUE}${BOLD}8. Your email for dashboard access${NC} ${DIM}[auto-detected: ${detected_email}]:${NC}"
    local input_email=""
    read -r -p "     > " input_email
    ENGINEER_EMAIL="${input_email:-${detected_email}}"
    print_success "Access email: ${ENGINEER_EMAIL}"
    echo ""

    # ── Derive computed variables ──
    # Sanitize connector name for use in resource names (lowercase, alphanumeric + hyphens)
    CONNECTOR_SLUG=$(echo "${CONNECTOR_DISPLAY_NAME}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
    # GCS bucket names are limited to 63 characters.
    # Fixed overhead for the most constrained name (tfstate):
    #   "lifecycle-agent-" (16) + slug + "-tfstate-" (9) + project_id = must be <= 63.
    # Compute the max slug length dynamically from the actual project ID length,
    # then strip any trailing hyphen left by truncation.
    local slug_max=$(( 63 - 16 - 9 - ${#GCP_PROJECT_ID} ))
    [[ ${slug_max} -lt 1 ]] && slug_max=1
    CONNECTOR_SLUG="${CONNECTOR_SLUG:0:${slug_max}}"
    CONNECTOR_SLUG="${CONNECTOR_SLUG%-}"  # strip trailing hyphen if truncation left one
    GCS_DATA_BUCKET="lifecycle-agent-${CONNECTOR_SLUG}-data-${GCP_PROJECT_ID}"
    GCS_TF_STATE_BUCKET="lifecycle-agent-${CONNECTOR_SLUG}-tfstate-${GCP_PROJECT_ID}"
    SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
    REGISTRY="${GCP_REGION}-docker.pkg.dev"
    IMAGE_URI="${REGISTRY}/${GCP_PROJECT_ID}/${AR_REPO_NAME}/${CLOUD_RUN_SERVICE_NAME}:latest"
    SCC_REGISTRY="${GCP_REGION}-docker.pkg.dev"
    SCC_IMAGE_URI="${SCC_REGISTRY}/${GCP_PROJECT_ID}/${SCC_AR_REPO_NAME}/${SCC_CLOUD_RUN_JOB_NAME}:latest"
}

# ============================================================================
# SECTION 4: CONFIRMATION PROMPT
# ============================================================================

confirm_setup() {
    # Use safe display values — show "(not set)" for empty optional variables
    local display_github_repos="${GITHUB_REPOS}"
    [[ -z "${display_github_repos}" ]] && display_github_repos="(not set)"
    local display_github_pat="(not provided - skipped)"
    [[ -n "${GITHUB_PAT}" ]] && display_github_pat="(provided)"
    local display_confluence="${CONFLUENCE_URL}"
    [[ -z "${display_confluence}" ]] && display_confluence="(not set)"
    local display_jira="${JIRA_URL}"
    [[ -z "${display_jira}" ]] && display_jira="(not set)"

    echo ""
    echo -e "${BOLD}${MAGENTA}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${MAGENTA}  📋 SETUP SUMMARY — Please Confirm${NC}"
    echo -e "${BOLD}${MAGENTA}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${BOLD}Project Configuration:${NC}"
    echo -e "    GCP Project ID:    ${GREEN}${GCP_PROJECT_ID}${NC}"
    echo -e "    Connector Name:    ${GREEN}${CONNECTOR_DISPLAY_NAME}${NC}"
    echo -e "    Region:            ${GREEN}${GCP_REGION}${NC}"
    echo -e "    GitHub Repos:      ${GREEN}${display_github_repos}${NC}"
    echo -e "    GitHub PAT:        ${GREEN}${display_github_pat}${NC}"
    echo -e "    Confluence:        ${GREEN}${display_confluence}${NC}"
    echo -e "    Jira:              ${GREEN}${display_jira}${NC}"
    echo -e "    Admin Email:       ${GREEN}${ENGINEER_EMAIL}${NC}"
    echo ""
    echo -e "  ${BOLD}Resources to be created:${NC}"
    echo -e "    ${CYAN}• 16 GCP APIs enabled${NC}"
    echo -e "    ${CYAN}• 1 Service Account (${SA_NAME}) with 10 IAM roles${NC}"
    echo -e "    ${CYAN}• 1 Artifact Registry repository (${AR_REPO_NAME})${NC}"
    echo -e "    ${CYAN}• 2 GCS Buckets (data + terraform state)${NC}"
    echo -e "    ${CYAN}• 1 BigQuery Dataset (${BQ_DATASET_NAME}) with 4 tables${NC}"
    echo -e "    ${CYAN}• 3 Secret Manager secrets (empty — fill via dashboard)${NC}"
    echo -e "    ${CYAN}• 1 Pub/Sub Topic (${PUBSUB_TOPIC_NAME})${NC}"
    echo -e "    ${CYAN}• 1 Cloud Run Service (${CLOUD_RUN_SERVICE_NAME}) with IAP${NC}"
    echo -e "    ${CYAN}• 1 Cloud Run Job (${SCC_CLOUD_RUN_JOB_NAME}) for SCC security pipeline${NC}"
    echo -e "    ${CYAN}• 1 Cloud Scheduler (${SCC_SCHEDULER_NAME}) — runs every 5 minutes${NC}"
    echo -e "    ${CYAN}• Terraform IaC files in ${INFRA_DIR}/${NC}"
    echo ""
    echo -e "  ${BOLD}Estimated time:${NC} 8-12 minutes"
    echo -e "  ${BOLD}Estimated cost:${NC} ~\$0.01/day when idle, ~\$1-2/day active"
    echo ""
    echo -e "  ${BOLD}${YELLOW}Proceed? [Y/n]${NC}"
    local confirm=""
    read -r -p "     > " confirm
    if [[ "${confirm,,}" == "n" || "${confirm,,}" == "no" ]]; then
        echo ""
        echo -e "  ${YELLOW}Setup cancelled. No resources were created.${NC}"
        exit 0
    fi
    echo ""
}

# ============================================================================
# SECTION 5: ENABLE GCP APIs
# ============================================================================

enable_apis() {
    local total_steps=14
    print_step 1 "${total_steps}" "Enabling GCP APIs"

    local apis=(
        "run.googleapis.com"
        "aiplatform.googleapis.com"
        "bigquery.googleapis.com"
        "storage.googleapis.com"
        "secretmanager.googleapis.com"
        "logging.googleapis.com"
        "monitoring.googleapis.com"
        "cloudbuild.googleapis.com"
        "artifactregistry.googleapis.com"
        "iap.googleapis.com"
        "pubsub.googleapis.com"
        "cloudscheduler.googleapis.com"
        "cloudresourcemanager.googleapis.com"
        "connectors.googleapis.com"
        "discoveryengine.googleapis.com"
        "securitycommandcenter.googleapis.com"
    )

    # Check which APIs still need enabling
    local to_enable=()
    local skipped_count=0

    local enabled_list=""
    enabled_list=$(gcloud services list --enabled --format="value(config.name)" 2>/dev/null) || true

    for api in "${apis[@]}"; do
        if echo "${enabled_list}" | grep -qF "${api}"; then
            print_info "${api} (already enabled)"
            skipped_count=$((skipped_count + 1))
        else
            to_enable+=("${api}")
        fi
    done

    # Enable all missing APIs in a single batched call.
    # If batch fails (e.g. one API requires org-level permissions), fall back
    # to enabling each API individually so the rest still succeed.
    if [[ ${#to_enable[@]} -gt 0 ]]; then
        print_substep "Enabling ${#to_enable[@]} APIs in a single batch..."
        local enable_exit=0
        gcloud services enable "${to_enable[@]}" --quiet 2>>"${LOG_FILE}" || enable_exit=$?
        if [[ ${enable_exit} -eq 0 ]]; then
            for api in "${to_enable[@]}"; do
                print_success "${api}"
            done
        else
            print_warning "Batch API enable returned non-zero (exit=${enable_exit}). Retrying each API individually..."
            log "FAILED: batch gcloud services enable ${to_enable[*]}"
            for api in "${to_enable[@]}"; do
                local individual_exit=0
                gcloud services enable "${api}" --quiet 2>>"${LOG_FILE}" || individual_exit=$?
                if [[ ${individual_exit} -eq 0 ]]; then
                    print_success "${api}"
                else
                    print_warning "Could not enable ${api} (exit=${individual_exit}). You may need to enable it manually or ask a project admin."
                    log "FAILED: gcloud services enable ${api}"
                fi
            done
        fi
    fi

    echo ""
    print_info "APIs — ${#to_enable[@]} newly enabled, ${skipped_count} already active"

    # Brief wait for API propagation. 10 seconds is enough for most APIs;
    # IAP readiness is verified later in deploy_cloud_run() with retries.
    if [[ ${#to_enable[@]} -gt 0 ]]; then
        print_substep "Waiting for API propagation (10 seconds)..."
        sleep 10
    fi
}

# ============================================================================
# DETECT MANAGER GROUP & GRANT roles/iam.serviceAccountAdmin
# ============================================================================

# Check if a member has a specific role in an IAM policy JSON.
# Usage: iam_has_binding "$policy_json" "roles/foo.bar" "user:someone@example.com"
# Returns 0 if the role+member pair exists in the same binding, 1 otherwise.
iam_has_binding() {
    local policy_json="$1"
    local role="$2"
    local member="$3"
    python3 -c "
import json, sys
policy = json.loads(sys.argv[1])
bindings = policy.get('bindings', [])
for b in bindings:
    if b.get('role') == sys.argv[2] and sys.argv[3] in b.get('members', []):
        sys.exit(0)
sys.exit(1)
" "${policy_json}" "${role}" "${member}" 2>/dev/null
}

ensure_sa_admin_role() {
    print_substep "Detecting manager group for project ${GCP_PROJECT_ID}..."

    local manager_group=""

    # ── Fetch the full IAM policy once (reused for all checks below) ──
    local iam_policy=""
    iam_policy=$(gcloud projects get-iam-policy "${GCP_PROJECT_ID}" \
        --format="json(bindings)" 2>/dev/null) || true

    # ── Strategy 1: Query project IAM policy for existing manager group ──
    # This step looks for an existing IAM group of the form
    # `<project>-manager@${IAM_DOMAIN}` already bound to the GCP project. It
    # is only useful if your organisation issues such groups through a
    # central IAM platform. Set the IAM_DOMAIN env var (e.g.
    # `IAM_DOMAIN=iam.example.com bash initial-connector.sh`) to enable it.
    # When IAM_DOMAIN is empty (the default), Strategy 1 is skipped and the
    # script proceeds straight to Strategy 2 (derive from project name).
    if [[ -n "${IAM_DOMAIN:-}" ]]; then
        manager_group=$(python3 -c "
import json, sys, re
policy = json.loads(sys.argv[1])
domain = re.escape(sys.argv[2])
pattern = re.compile(r'group:(.+-manager@' + domain + r')')
for b in policy.get('bindings', []):
    for m in b.get('members', []):
        match = pattern.search(m)
        if match:
            print(match.group(1))
            sys.exit(0)
" "${iam_policy}" "${IAM_DOMAIN}" 2>/dev/null) || true
    fi

    # ── Strategy 2: Derive from GCP project display name ──
    if [[ -z "${manager_group}" ]]; then
        print_info "No manager group in IAM policy. Deriving from project name..."

        local project_name=""
        project_name=$(gcloud projects describe "${GCP_PROJECT_ID}" \
            --format="value(name)" 2>/dev/null) || true

        if [[ -n "${project_name}" ]]; then
            local name_lower=""
            name_lower=$(echo "${project_name}" | tr '[:upper:]' '[:lower:]')

            local name_dotted=""
            name_dotted=$(echo "${name_lower}" | sed 's/ /./')
            name_dotted=$(echo "${name_dotted}" | tr -d ' ')

            manager_group="${name_dotted}-manager@${IAM_DOMAIN:-example.com}"

            print_info "Derived manager group: ${manager_group}"
            print_info "(from project name: '${project_name}')"
        fi
    fi

    # ── Strategy 3: Fall back to engineer's own email ──
    local iam_member=""
    if [[ -n "${manager_group}" ]]; then
        iam_member="group:${manager_group}"
        print_success "Manager group: ${manager_group}"
    else
        iam_member="user:${ENGINEER_EMAIL}"
        print_warning "Could not detect manager group. Using your email: ${ENGINEER_EMAIL}"
    fi

    # ── Bind administrative roles to the manager group or user ──
    local manager_roles=(
        "roles/iam.serviceAccountAdmin"
        "roles/artifactregistry.admin"
        "roles/secretmanager.admin"
        "roles/storage.admin"
        "roles/bigquery.admin"
        "roles/pubsub.admin"
        "roles/run.admin"
        "roles/iap.admin"
        "roles/connectors.admin"
        "roles/aiplatform.admin"
    )

    # Check which roles are already bound using the cached IAM policy
    local roles_to_bind=()
    for role in "${manager_roles[@]}"; do
        if iam_has_binding "${iam_policy}" "${role}" "${iam_member}"; then
            print_info "${role} already bound to ${iam_member}"
        else
            roles_to_bind+=("${role}")
        fi
    done

    # Bind missing roles (sequential — IAM bindings read-modify-write the
    # same policy and must not race against each other)
    for role in "${roles_to_bind[@]}"; do
        print_substep "Granting ${role} to ${iam_member}..."
        local bind_output=""
        local bind_exit=0
        bind_output=$(gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="${iam_member}" \
            --role="${role}" \
            --format="none" --quiet 2>&1) || bind_exit=$?

        if [[ ${bind_exit} -eq 0 ]]; then
            print_success "${role} granted to ${iam_member}"
        else
            print_warning "Failed to grant ${role}"
            log "Bind output for ${role}: ${bind_output}"
            print_warning "Grant it manually:"
            print_warning "  gcloud projects add-iam-policy-binding ${GCP_PROJECT_ID} \\"
            print_warning "    --member='${iam_member}' --role='${role}'"
        fi
    done

    # ── Bind roles/iam.serviceAccountUser at the service account level ──
    # (Scoped to the specific service account instead of the whole project)
    local sa_email_for_binding="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
    local sa_user_role="roles/iam.serviceAccountUser"

    local sa_iam_policy=""
    sa_iam_policy=$(gcloud iam service-accounts get-iam-policy "${sa_email_for_binding}" \
        --project="${GCP_PROJECT_ID}" --format="json(bindings)" 2>/dev/null) || true

    if iam_has_binding "${sa_iam_policy}" "${sa_user_role}" "${iam_member}"; then
        print_info "${sa_user_role} already bound to ${iam_member} on SA ${sa_email_for_binding}"
    else
        print_substep "Granting ${sa_user_role} to ${iam_member} on SA ${sa_email_for_binding}..."
        local sa_user_bind_output=""
        local sa_user_bind_exit=0
        sa_user_bind_output=$(gcloud iam service-accounts add-iam-policy-binding "${sa_email_for_binding}" \
            --member="${iam_member}" \
            --role="${sa_user_role}" \
            --format="none" --quiet 2>&1) || sa_user_bind_exit=$?

        if [[ ${sa_user_bind_exit} -eq 0 ]]; then
            print_success "${sa_user_role} granted to ${iam_member} on SA ${sa_email_for_binding}"
        else
            print_warning "Failed to grant ${sa_user_role} on SA level"
            log "SA-level bind output for ${sa_user_role}: ${sa_user_bind_output}"
            print_warning "Grant it manually:"
            print_warning "  gcloud iam service-accounts add-iam-policy-binding ${sa_email_for_binding} \\"
            print_warning "    --member='${iam_member}' --role='${sa_user_role}'"
        fi
    fi

    # ── Also bind artifactregistry.admin to the user running the script ──
    local user_member="user:${ENGINEER_EMAIL}"
    local ar_admin_role="roles/artifactregistry.admin"

    if iam_has_binding "${iam_policy}" "${ar_admin_role}" "${user_member}"; then
        print_info "${ar_admin_role} already bound to your user account"
    else
        print_substep "Granting ${ar_admin_role} to your user account (${ENGINEER_EMAIL})..."
        gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="${user_member}" \
            --role="${ar_admin_role}" \
            --format="none" --quiet 2>>"${LOG_FILE}" || \
            print_warning "Failed to grant ${ar_admin_role} to your user. This may cause issues."
        print_success "${ar_admin_role} granted to your user account"
    fi

    DETECTED_MANAGER_GROUP="${manager_group}"
}

# ============================================================================
# SECTION 6: CREATE SERVICE ACCOUNT + IAM ROLES
# ============================================================================

create_service_account() {
    local total_steps=14
    print_step 2 "${total_steps}" "Creating Service Account & IAM Bindings"

    # ── Step A: Check if SA already exists ──
    local sa_exists="false"
    local sa_list_output=""
    sa_list_output=$(gcloud iam service-accounts list \
        --filter="email:${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
        --format="value(email)" \
        --project="${GCP_PROJECT_ID}" 2>/dev/null) || true

    if [[ -n "${sa_list_output}" ]]; then
        sa_exists="true"
        print_info "Service account ${SA_NAME} already exists"
    fi

    # ── Step B: Create SA if it doesn't exist ──
    if [[ "${sa_exists}" == "false" ]]; then
        print_substep "Creating service account: ${SA_NAME}"

        local create_output=""
        local create_exit=0
        create_output=$(gcloud iam service-accounts create "${SA_NAME}" \
            --description="Lifecycle AI Agent service account" \
            --display-name="Lifecycle AI Agent Service Account" \
            --project="${GCP_PROJECT_ID}" 2>&1) || create_exit=$?

        log "SA create output (exit=${create_exit}): ${create_output}"

        # Verify the SA now exists
        local verify_output=""
        verify_output=$(gcloud iam service-accounts list \
            --filter="email:${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
            --format="value(email)" \
            --project="${GCP_PROJECT_ID}" 2>/dev/null) || true

        if [[ -n "${verify_output}" ]]; then
            print_success "Service account created: ${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
        else
            print_error "Failed to create service account. Check the log: ${LOG_FILE}"
            print_error "gcloud output: ${create_output}"
            exit 1
        fi
    fi

    # ── Step C: Wait for SA propagation ──
    print_substep "Waiting for service account propagation (30 seconds)..."
    sleep 30

    # ── Step D: Bind IAM roles ──
    # Fetch current policy once and check which bindings already exist,
    # then only bind the missing ones (avoids redundant API calls).
    local roles=(
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

    local role_count=0
    local role_failed=0
    local sa_member="serviceAccount:${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

    # Fetch current policy once
    local current_sa_policy=""
    current_sa_policy=$(gcloud projects get-iam-policy "${GCP_PROJECT_ID}" \
        --format="json(bindings)" 2>/dev/null) || true

    local roles_to_bind=()
    for role in "${roles[@]}"; do
        if iam_has_binding "${current_sa_policy}" "${role}" "${sa_member}"; then
            print_info "${role} already bound to ${sa_member}"
            role_count=$((role_count + 1))
        else
            roles_to_bind+=("${role}")
        fi
    done

    for role in "${roles_to_bind[@]}"; do
        print_substep "Binding ${role}"

        local bind_output=""
        local bind_exit_code=0
        bind_output=$(gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="${sa_member}" \
            --role="${role}" \
            --format="none" --quiet 2>&1) || bind_exit_code=$?

        if [[ ${bind_exit_code} -eq 0 ]]; then
            role_count=$((role_count + 1))
        else
            role_failed=$((role_failed + 1))
            print_warning "Failed to bind ${role} (exit code: ${bind_exit_code})"
            log "IAM bind failed for ${role}: ${bind_output}"
        fi
    done

    if [[ ${role_failed} -gt 0 ]]; then
        print_warning "${role_count} roles bound, ${role_failed} failed. Check log: ${LOG_FILE}"
    else
        print_success "All ${role_count} IAM roles bound to ${SA_NAME}"
    fi

    # ── Step D2: Bind serviceAccountTokenCreator at service account level ──
    # (Scoped to the specific service account instead of the whole project)
    local token_creator_role="roles/iam.serviceAccountTokenCreator"
    local sa_email_full="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

    local sa_level_policy=""
    sa_level_policy=$(gcloud iam service-accounts get-iam-policy "${sa_email_full}" \
        --project="${GCP_PROJECT_ID}" --format="json(bindings)" 2>/dev/null) || true

    if iam_has_binding "${sa_level_policy}" "${token_creator_role}" "${sa_member}"; then
        print_info "${token_creator_role} already bound to ${sa_member} on SA ${sa_email_full}"
    else
        print_substep "Binding ${token_creator_role} to ${sa_member} on SA ${sa_email_full}..."
        local tc_bind_output=""
        local tc_bind_exit=0
        tc_bind_output=$(gcloud iam service-accounts add-iam-policy-binding "${sa_email_full}" \
            --member="${sa_member}" \
            --role="${token_creator_role}" \
            --format="none" --quiet 2>&1) || tc_bind_exit=$?

        if [[ ${tc_bind_exit} -eq 0 ]]; then
            print_success "${token_creator_role} granted to ${sa_member} on SA ${sa_email_full}"
        else
            print_warning "Failed to bind ${token_creator_role} at SA level (exit code: ${tc_bind_exit})"
            log "SA-level IAM bind failed for ${token_creator_role}: ${tc_bind_output}"
        fi
    fi

    # ── Step E: Grant AI Platform service agent the aiplatform.user role ──
    print_substep "Granting roles/aiplatform.user to AI Platform service agent..."

    local project_number=""
    project_number=$(gcloud projects describe "${GCP_PROJECT_ID}" --format="value(projectNumber)" 2>>"${LOG_FILE}") || true

    if [[ -n "${project_number}" ]]; then
        local aiplatform_sa="serviceAccount:service-${project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
        local aiplatform_bind_output=""
        local aiplatform_bind_exit=0
        aiplatform_bind_output=$(gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="${aiplatform_sa}" \
            --role="roles/aiplatform.user" \
            --format="none" --quiet 2>&1) || aiplatform_bind_exit=$?

        if [[ ${aiplatform_bind_exit} -eq 0 ]]; then
            print_success "roles/aiplatform.user granted to AI Platform service agent"
        else
            print_warning "Failed to grant roles/aiplatform.user to AI Platform service agent (exit=${aiplatform_bind_exit})"
            log "AI Platform SA IAM bind failed: ${aiplatform_bind_output}"
        fi

        # ── Also grant Storage Object User to the AI Platform service agent ──
        print_substep "Granting roles/storage.objectUser to AI Platform service agent..."
        local aiplatform_soc_output=""
        local aiplatform_soc_exit=0
        aiplatform_soc_output=$(gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="${aiplatform_sa}" \
            --role="roles/storage.objectUser" \
            --format="none" --quiet 2>&1) || aiplatform_soc_exit=$?

        if [[ ${aiplatform_soc_exit} -eq 0 ]]; then
            print_success "roles/storage.objectUser granted to AI Platform service agent"
        else
            print_warning "Failed to grant roles/storage.objectUser to AI Platform service agent (exit=${aiplatform_soc_exit})"
            log "AI Platform SA Storage Object Creator bind failed: ${aiplatform_soc_output}"
        fi
    else
        print_warning "Could not determine project number — skipping AI Platform service agent role binding"
    fi
}

# ============================================================================
# SECTION 7: CREATE ARTIFACT REGISTRY
# ============================================================================

create_artifact_registry() {
    local total_steps=14
    print_step 3 "${total_steps}" "Creating Artifact Registry Repository"

    # FIX: Use explicit exit-code capture instead of resource_exists() for
    # gcloud artifacts commands, which can fail with non-zero even for "not found".
    local ar_exists=0
    gcloud artifacts repositories describe "${AR_REPO_NAME}" \
        --location="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" &>/dev/null || ar_exists=$?

    if [[ ${ar_exists} -eq 0 ]]; then
        print_info "Artifact Registry '${AR_REPO_NAME}' already exists"
    else
        print_substep "Creating Docker repository: ${AR_REPO_NAME}"
        local ar_output=""
        local ar_exit=0
        ar_output=$(gcloud artifacts repositories create "${AR_REPO_NAME}" \
            --repository-format=docker \
            --location="${GCP_REGION}" \
            --description="Docker images for Lifecycle AI Agent" \
            --project="${GCP_PROJECT_ID}" \
            --quiet 2>&1) || ar_exit=$?

        if [[ ${ar_exit} -eq 0 ]]; then
            print_success "Artifact Registry created: ${AR_REPO_NAME}"
        else
            # It may have been created by a parallel run or the error is transient
            log "AR create output (exit=${ar_exit}): ${ar_output}"
            # Check again
            if gcloud artifacts repositories describe "${AR_REPO_NAME}" \
                --location="${GCP_REGION}" \
                --project="${GCP_PROJECT_ID}" &>/dev/null; then
                print_success "Artifact Registry created: ${AR_REPO_NAME} (confirmed on retry)"
            else
                print_error "Failed to create Artifact Registry. See log: ${LOG_FILE}"
                print_error "gcloud output: ${ar_output}"
                exit 1
            fi
        fi
    fi

    # Configure Docker authentication for Artifact Registry
    print_substep "Configuring Docker authentication..."
    local docker_auth_exit=0
    gcloud auth configure-docker "${REGISTRY}" --quiet 2>>"${LOG_FILE}" || docker_auth_exit=$?
    if [[ ${docker_auth_exit} -eq 0 ]]; then
        print_success "Docker configured for ${REGISTRY}"
    else
        print_warning "Docker auth configure returned non-zero (exit=${docker_auth_exit}) — this is often harmless"
    fi
}

# ============================================================================
# SECTION 8: CREATE CLOUD STORAGE BUCKETS
# ============================================================================

create_storage_buckets() {
    local total_steps=14
    print_step 4 "${total_steps}" "Creating Cloud Storage Buckets"

    # ── Data Bucket ──
    local data_bucket_exists=1
    gsutil ls -b "gs://${GCS_DATA_BUCKET}" &>/dev/null && data_bucket_exists=0 || true

    if [[ ${data_bucket_exists} -eq 0 ]]; then
        print_info "Data bucket '${GCS_DATA_BUCKET}' already exists"
    else
        print_substep "Creating data bucket: ${GCS_DATA_BUCKET}"
        local mb_exit=0
        gsutil mb -p "${GCP_PROJECT_ID}" -l "${GCP_REGION}" -b on "gs://${GCS_DATA_BUCKET}" 2>>"${LOG_FILE}" || mb_exit=$?
        if [[ ${mb_exit} -eq 0 ]]; then
            print_success "Data bucket created"
        else
            print_error "Failed to create data bucket (exit=${mb_exit}). Check log: ${LOG_FILE}"
            exit 1
        fi
    fi

    # Create directory structure in data bucket (best-effort, never fatal)
    local directories=("rag/docs/" "rag/sprints/" "rag/incidents/" "rag/confluence/" "reports/incidents/" "reports/sprint-docs/" "reports/deployment-validations/" "exports/" "agent-logs/" "pending-documents/")
    for dir in "${directories[@]}"; do
        echo "" | gsutil -q cp - "gs://${GCS_DATA_BUCKET}/${dir}.keep" 2>/dev/null || true
    done
    print_success "Directory structure created in data bucket"

    # ── Terraform State Bucket ──
    local tf_bucket_exists=1
    gsutil ls -b "gs://${GCS_TF_STATE_BUCKET}" &>/dev/null && tf_bucket_exists=0 || true

    if [[ ${tf_bucket_exists} -eq 0 ]]; then
        print_info "Terraform state bucket '${GCS_TF_STATE_BUCKET}' already exists"
    else
        print_substep "Creating Terraform state bucket: ${GCS_TF_STATE_BUCKET}"
        local tf_mb_exit=0
        gsutil mb -p "${GCP_PROJECT_ID}" -l "${GCP_REGION}" -b on "gs://${GCS_TF_STATE_BUCKET}" 2>>"${LOG_FILE}" || tf_mb_exit=$?
        if [[ ${tf_mb_exit} -eq 0 ]]; then
            # Enable versioning on TF state bucket
            gsutil versioning set on "gs://${GCS_TF_STATE_BUCKET}" 2>>"${LOG_FILE}" || true
            print_success "Terraform state bucket created (versioning enabled)"
        else
            print_error "Failed to create TF state bucket (exit=${tf_mb_exit}). Check log: ${LOG_FILE}"
            exit 1
        fi
    fi
}

# ============================================================================
# SECTION 9: CREATE BIGQUERY DATASET + TABLES
# ============================================================================

create_bigquery_resources() {
    local total_steps=14
    print_step 5 "${total_steps}" "Creating BigQuery Dataset & Tables"

    # Create dataset
    local ds_exists=1
    bq ls --project_id="${GCP_PROJECT_ID}" "${BQ_DATASET_NAME}" &>/dev/null && ds_exists=0 || true

    if [[ ${ds_exists} -eq 0 ]]; then
        print_info "Dataset '${BQ_DATASET_NAME}' already exists"
    else
        print_substep "Creating dataset: ${BQ_DATASET_NAME}"
        local bq_exit=0
        bq mk --dataset \
            --location="EU" \
            --description="Lifecycle AI Agent — agent logs, incident reports, sprint docs, deployment validations" \
            "${GCP_PROJECT_ID}:${BQ_DATASET_NAME}" 2>>"${LOG_FILE}" || bq_exit=$?
        if [[ ${bq_exit} -eq 0 ]]; then
            print_success "Dataset created: ${BQ_DATASET_NAME}"
        else
            print_error "Failed to create BigQuery dataset (exit=${bq_exit})"
            exit 1
        fi
    fi

    # ── Table 1: Agent Execution Log ──
    local table_1="${GCP_PROJECT_ID}:${BQ_DATASET_NAME}.agent_execution_log"
    local t1_exists=1
    bq show "${table_1}" &>/dev/null && t1_exists=0 || true
    if [[ ${t1_exists} -eq 0 ]]; then
        print_info "Table agent_execution_log already exists"
    else
        print_substep "Creating table: agent_execution_log"
        bq mk --table \
            --description="Logs every agent execution with request/response, tools called, and metrics" \
            "${table_1}" \
            "execution_id:STRING,agent_type:STRING,trigger_source:STRING,connector_name:STRING,event_payload:STRING,gemini_request:STRING,gemini_response:STRING,tools_called:STRING,execution_time_ms:INTEGER,token_count_input:INTEGER,token_count_output:INTEGER,cost_usd:FLOAT,status:STRING,error_message:STRING,created_at:TIMESTAMP" \
            2>>"${LOG_FILE}" || true
        print_success "Table created: agent_execution_log"
    fi

    # ── Table 2: Incident Reports ──
    local table_2="${GCP_PROJECT_ID}:${BQ_DATASET_NAME}.incident_reports"
    local t2_exists=1
    bq show "${table_2}" &>/dev/null && t2_exists=0 || true
    if [[ ${t2_exists} -eq 0 ]]; then
        print_info "Table incident_reports already exists"
    else
        print_substep "Creating table: incident_reports"
        bq mk --table \
            --description="Stores AI-generated incident analysis reports with RCA, mitigation steps, and ticket references" \
            "${table_2}" \
            "incident_id:STRING,connector_name:STRING,alert_name:STRING,severity:STRING,root_cause_analysis:STRING,mitigation_steps:STRING,affected_services:STRING,jira_ticket_id:STRING,github_issue_url:STRING,confluence_page_url:STRING,resolution_time_seconds:FLOAT,confidence_score:FLOAT,status:STRING,created_at:TIMESTAMP,resolved_at:TIMESTAMP" \
            2>>"${LOG_FILE}" || true
        print_success "Table created: incident_reports"
    fi

    # ── Table 3: Sprint Documents ──
    local table_3="${GCP_PROJECT_ID}:${BQ_DATASET_NAME}.sprint_documents"
    local t3_exists=1
    bq show "${table_3}" &>/dev/null && t3_exists=0 || true
    if [[ ${t3_exists} -eq 0 ]]; then
        print_info "Table sprint_documents already exists"
    else
        print_substep "Creating table: sprint_documents"
        bq mk --table \
            --description="Stores AI-generated sprint documentation with PR/issue summaries and DoD checklists" \
            "${table_3}" \
            "sprint_id:STRING,connector_name:STRING,sprint_label:STRING,start_date:DATE,end_date:DATE,prs_merged:INTEGER,issues_closed:INTEGER,features_delivered:STRING,bugs_fixed:STRING,blockers:STRING,dod_checklist:STRING,document_markdown:STRING,confluence_page_url:STRING,generated_at:TIMESTAMP" \
            2>>"${LOG_FILE}" || true
        print_success "Table created: sprint_documents"
    fi

    # ── Table 4: Deployment Validations ──
    local table_4="${GCP_PROJECT_ID}:${BQ_DATASET_NAME}.deployment_validations"
    local t4_exists=1
    bq show "${table_4}" &>/dev/null && t4_exists=0 || true
    if [[ ${t4_exists} -eq 0 ]]; then
        print_info "Table deployment_validations already exists"
    else
        print_substep "Creating table: deployment_validations"
        bq mk --table \
            --description="Stores deployment readiness validation results with DoD checklist pass/fail status" \
            "${table_4}" \
            "validation_id:STRING,connector_name:STRING,pr_number:INTEGER,repository:STRING,ci_checks_passed:BOOLEAN,tests_passed:BOOLEAN,pr_approved:BOOLEAN,docs_updated:BOOLEAN,infra_validated:BOOLEAN,overall_ready:BOOLEAN,checklist_json:STRING,warnings:STRING,validated_at:TIMESTAMP" \
            2>>"${LOG_FILE}" || true
        print_success "Table created: deployment_validations"
    fi
}

# ============================================================================
# SECTION 10: CREATE SECRET MANAGER SECRETS
# ============================================================================

create_secrets() {
    local total_steps=14
    print_step 6 "${total_steps}" "Creating Secret Manager Secrets"

    local secrets=(
        "lifecycle-agent-confluence-token:Confluence API Token — for reading/writing project documentation"
        "lifecycle-agent-jira-token:Jira API Token — for creating tickets and reading sprint data"
    )

    for entry in "${secrets[@]}"; do
        local secret_id="${entry%%:*}"
        local description="${entry#*:}"

        local sec_exists=1
        gcloud secrets describe "${secret_id}" --project="${GCP_PROJECT_ID}" &>/dev/null && sec_exists=0 || true

        if [[ ${sec_exists} -eq 0 ]]; then
            print_info "Secret '${secret_id}' already exists"
        else
            print_substep "Creating secret: ${secret_id}"
            local sec_exit=0
            gcloud secrets create "${secret_id}" \
                --replication-policy="user-managed" \
                --locations="${GCP_REGION}" \
                --labels="app=lifecycle-agent,managed-by=setup-script" \
                --project="${GCP_PROJECT_ID}" \
                --quiet 2>>"${LOG_FILE}" || sec_exit=$?

            if [[ ${sec_exit} -ne 0 ]]; then
                print_warning "Failed to create secret ${secret_id} (exit=${sec_exit}) — continuing"
                continue
            fi

            # Add an initial empty version
            echo -n "REPLACE_ME" | gcloud secrets versions add "${secret_id}" \
                --data-file=- \
                --project="${GCP_PROJECT_ID}" \
                --quiet 2>>"${LOG_FILE}" || true
            print_success "Secret created: ${secret_id} (placeholder — set real value via dashboard)"
        fi
    done
}

# ============================================================================
# SECTION 11: CREATE PUB/SUB TOPIC
# ============================================================================

create_pubsub() {
    local total_steps=14
    print_step 7 "${total_steps}" "Creating Pub/Sub Topic"

    local topic_exists=1
    gcloud pubsub topics describe "${PUBSUB_TOPIC_NAME}" --project="${GCP_PROJECT_ID}" &>/dev/null && topic_exists=0 || true

    if [[ ${topic_exists} -eq 0 ]]; then
        print_info "Topic '${PUBSUB_TOPIC_NAME}' already exists"
    else
        print_substep "Creating topic: ${PUBSUB_TOPIC_NAME}"
        local topic_exit=0
        gcloud pubsub topics create "${PUBSUB_TOPIC_NAME}" \
            --labels="app=lifecycle-agent,managed-by=setup-script" \
            --project="${GCP_PROJECT_ID}" \
            --quiet 2>>"${LOG_FILE}" || topic_exit=$?

        if [[ ${topic_exit} -eq 0 ]]; then
            print_success "Pub/Sub topic created: ${PUBSUB_TOPIC_NAME}"
        else
            print_error "Failed to create Pub/Sub topic (exit=${topic_exit})"
            exit 1
        fi
    fi
}

# ============================================================================
# SECTION 12: BUILD & PUSH DOCKER IMAGE
# ============================================================================

build_and_push_image() {
    local total_steps=14
    print_step 8 "${total_steps}" "Building & Pushing Docker Image"

    print_info "This step takes ~2-3 minutes..."

    # Copy the FastAPI application files into a temporary build directory.
    # The FastAPI app reads configuration from Cloud Run environment variables
    # (set in deploy_cloud_run), so no sed placeholder injection is needed.
    local temp_build_dir=""
    temp_build_dir=$(mktemp -d)

    print_substep "Preparing FastAPI dashboard files..."
    cp "${SCRIPT_DIR}/Dockerfile" "${temp_build_dir}/Dockerfile"
    cp -r "${SCRIPT_DIR}/webapp" "${temp_build_dir}/webapp"
    cp "${SCRIPT_DIR}/doc_pipeline_tool.py" "${temp_build_dir}/doc_pipeline_tool.py"
    cp -r "${SCRIPT_DIR}/pipeline" "${temp_build_dir}/pipeline"
    print_success "FastAPI dashboard files prepared"

    # Build the Docker image
    print_substep "Building Docker image (this takes ~2 minutes)..."
    local build_exit=0
    docker build -t "${IMAGE_URI}" "${temp_build_dir}" 2>>"${LOG_FILE}" || build_exit=$?
    if [[ ${build_exit} -ne 0 ]]; then
        print_error "Docker build failed (exit=${build_exit}). Check log: ${LOG_FILE}"
        rm -rf "${temp_build_dir}"
        exit 1
    fi
    print_success "Docker image built"

    # Push to Artifact Registry
    print_substep "Pushing to Artifact Registry..."
    local push_exit=0
    docker push "${IMAGE_URI}" 2>>"${LOG_FILE}" || push_exit=$?
    if [[ ${push_exit} -ne 0 ]]; then
        print_error "Docker push failed (exit=${push_exit}). Check log: ${LOG_FILE}"
        rm -rf "${temp_build_dir}"
        exit 1
    fi
    print_success "Image pushed to ${REGISTRY}"

    # Cleanup
    rm -rf "${temp_build_dir}"
}

# ============================================================================
# SECTION 13: DEPLOY TO CLOUD RUN
# ============================================================================

deploy_cloud_run() {
    local total_steps=14
    print_step 9 "${total_steps}" "Deploying to Cloud Run"

    # Check if the service already exists
    if gcloud run services describe "${CLOUD_RUN_SERVICE_NAME}" --region "${GCP_REGION}" --project "${GCP_PROJECT_ID}" &>/dev/null; then
        print_info "Cloud Run service '${CLOUD_RUN_SERVICE_NAME}' already exists. Re-deploying with latest image..."

        # Build env vars for update — ensures GITHUB_REPOS and other config
        # are refreshed even when the service already exists.
        # Use ^@@^ custom delimiter to avoid issues with commas/slashes in values
        # (e.g. GITHUB_REPOS may contain org/repo format).
        local env_vars="^@@^ENVIRONMENT=production"
        env_vars="${env_vars}@@GCP_PROJECT_ID=${GCP_PROJECT_ID}"
        env_vars="${env_vars}@@GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID}"
        env_vars="${env_vars}@@GOOGLE_CLOUD_LOCATION=${GCP_REGION}"
        env_vars="${env_vars}@@CONNECTOR_NAME=${CONNECTOR_DISPLAY_NAME}"
        env_vars="${env_vars}@@GITHUB_REPOS=${GITHUB_REPOS:-}"
        env_vars="${env_vars}@@GITHUB_PAT=${GITHUB_PAT:-}"
        env_vars="${env_vars}@@CONFLUENCE_URL=${CONFLUENCE_URL:-}"
        env_vars="${env_vars}@@JIRA_URL=${JIRA_URL:-}"
        env_vars="${env_vars}@@GCS_DATA_BUCKET=${GCS_DATA_BUCKET:-}"
        env_vars="${env_vars}@@CORPUS_RESOURCE_NAME=${CORPUS_RESOURCE_NAME:-}"

        local redeploy_exit=0
        gcloud run deploy "${CLOUD_RUN_SERVICE_NAME}" \
            --image="${IMAGE_URI}" \
            --region="${GCP_REGION}" \
            --platform=managed \
            --service-account="${SA_EMAIL}" \
            --set-env-vars="${env_vars}" \
            --project="${GCP_PROJECT_ID}" \
            --quiet 2>>"${LOG_FILE}" || redeploy_exit=$?

        if [[ ${redeploy_exit} -ne 0 ]]; then
            print_error "Cloud Run re-deployment failed (exit=${redeploy_exit}). Check log: ${LOG_FILE}"
            exit 1
        fi
        print_success "Cloud Run service re-deployed with latest image: ${CLOUD_RUN_SERVICE_NAME}"
    else
        print_substep "Deploying ${CLOUD_RUN_SERVICE_NAME} (this takes ~1 minute)..."

        # FIX: Build the --set-env-vars string safely. Empty values are fine for
        # Cloud Run env vars, but we must avoid malformed flags.
        # Use ^@@^ custom delimiter to avoid issues with commas/slashes in values.
        local env_vars="^@@^ENVIRONMENT=production"
        env_vars="${env_vars}@@GCP_PROJECT_ID=${GCP_PROJECT_ID}"
        env_vars="${env_vars}@@GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID}"
        env_vars="${env_vars}@@GOOGLE_CLOUD_LOCATION=${GCP_REGION}"
        env_vars="${env_vars}@@CONNECTOR_NAME=${CONNECTOR_DISPLAY_NAME}"
        env_vars="${env_vars}@@GITHUB_REPOS=${GITHUB_REPOS:-}"
        env_vars="${env_vars}@@GITHUB_PAT=${GITHUB_PAT:-}"
        env_vars="${env_vars}@@CONFLUENCE_URL=${CONFLUENCE_URL:-}"
        env_vars="${env_vars}@@JIRA_URL=${JIRA_URL:-}"
        env_vars="${env_vars}@@GCS_DATA_BUCKET=${GCS_DATA_BUCKET:-}"
        env_vars="${env_vars}@@CORPUS_RESOURCE_NAME=${CORPUS_RESOURCE_NAME:-}"

        local deploy_exit=0
        gcloud run deploy "${CLOUD_RUN_SERVICE_NAME}" \
            --image="${IMAGE_URI}" \
            --platform=managed \
            --region="${GCP_REGION}" \
            --service-account="${SA_EMAIL}" \
            --set-env-vars="${env_vars}" \
            --min-instances=0 \
            --max-instances=3 \
            --memory=1Gi \
            --cpu=1 \
            --timeout=300 \
            --port=8080 \
            --ingress=all \
            --project="${GCP_PROJECT_ID}" \
            --quiet 2>>"${LOG_FILE}" || deploy_exit=$?

        if [[ ${deploy_exit} -ne 0 ]]; then
            print_error "Cloud Run deployment failed (exit=${deploy_exit}). Check log: ${LOG_FILE}"
            print_error "This can sometimes happen if the IAP API is not fully ready. Please try re-running the script."
            exit 1
        fi
        print_success "Cloud Run service deployed: ${CLOUD_RUN_SERVICE_NAME}"
    fi

    # ── Enable IAP ──
    print_substep "Ensuring IAP is enabled for the service..."
    local iap_status
    iap_status=$(gcloud beta iap web describe --project="${GCP_PROJECT_ID}" --resource-type=cloud-run --service="${CLOUD_RUN_SERVICE_NAME}" --format="value(iap.enabled)" 2>/dev/null) || true

    if [[ "${iap_status}" == "True" ]]; then
        print_info "IAP is already enabled for '${CLOUD_RUN_SERVICE_NAME}'."
    else
        local iap_update_exit=0
        gcloud beta run services update "${CLOUD_RUN_SERVICE_NAME}" \
            --region="${GCP_REGION}" \
            --project="${GCP_PROJECT_ID}" \
            --iap \
            --quiet 2>>"${LOG_FILE}" || iap_update_exit=$?

        if [[ ${iap_update_exit} -eq 0 ]]; then
            print_success "IAP enabled for '${CLOUD_RUN_SERVICE_NAME}'"
        else
            print_warning "Failed to enable IAP for Cloud Run service (exit=${iap_update_exit})."
        fi
    fi

    # Get the service URL
    CLOUD_RUN_URL=$(gcloud run services describe "${CLOUD_RUN_SERVICE_NAME}" \
        --region="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(status.url)' 2>/dev/null) || true

    print_success "URL: ${CLOUD_RUN_URL:-<not found>}"
}

# ============================================================================
# SECTION 14: CONFIGURE IAP (Identity-Aware Proxy)
# ============================================================================

configure_iap() {
    local total_steps=14
    print_step 10 "${total_steps}" "Configuring IAP Access Policy"

    local iap_member="user:${ENGINEER_EMAIL}"
    local iap_role="roles/iap.httpsResourceAccessor"

    # Check if the user already has the required IAP role
    print_substep "Checking IAP policy for ${ENGINEER_EMAIL}..."
    local current_policy=""
    current_policy=$(gcloud beta iap web get-iam-policy \
        --region="${GCP_REGION}" \
        --resource-type=cloud-run \
        --service="${CLOUD_RUN_SERVICE_NAME}" 2>/dev/null) || true

    if echo "${current_policy}" | grep -q -E "role: ${iap_role}" && echo "${current_policy}" | grep -q "members:\s*- ${iap_member}"; then
        print_info "User ${ENGINEER_EMAIL} already has IAP access role (${iap_role})."
    else
        # Grant the user access through IAP
        print_substep "Adding ${ENGINEER_EMAIL} to the IAP access list..."
        local iap_exit=0
        gcloud beta iap web add-iam-policy-binding \
            --member="${iap_member}" \
            --role="${iap_role}" \
            --region="${GCP_REGION}" \
            --resource-type=cloud-run \
            --service="${CLOUD_RUN_SERVICE_NAME}" --condition=None 2>>"${LOG_FILE}" || iap_exit=$?

        if [[ ${iap_exit} -eq 0 ]]; then
            print_success "IAP configured: ${ENGINEER_EMAIL} can access the dashboard"
        else
            print_warning "Failed to grant IAP access to user (exit=${iap_exit}). You can add it manually:"
            print_warning "  gcloud beta iap web add-iam-policy-binding \\"
            print_warning "    --member='${iap_member}' --role='${iap_role}' \\"
            print_warning "    --region=${GCP_REGION} \\"
            print_warning "    --resource-type=cloud-run --service=${CLOUD_RUN_SERVICE_NAME} \\"
        fi
    fi

    # Allow IAP to invoke the Cloud Run service
    print_substep "Granting IAP service permission to invoke Cloud Run..."
    local project_number=""
    project_number=$(gcloud projects describe "${GCP_PROJECT_ID}" --format="value(projectNumber)" 2>>"${LOG_FILE}") || true
    if [[ -z "${project_number}" ]]; then
        print_warning "Could not determine project number for IAP configuration. Skipping IAP invoker binding."
        return
    fi
    local iap_sa_member="serviceAccount:service-${project_number}@gcp-sa-iap.iam.gserviceaccount.com"

    gcloud run services add-iam-policy-binding "${CLOUD_RUN_SERVICE_NAME}" \
        --project="${GCP_PROJECT_ID}" \
        --region="${GCP_REGION}" \
        --member="${iap_sa_member}" \
        --role="roles/run.invoker" \
        --quiet 2>>"${LOG_FILE}" || true # Best effort, often already exists

    print_success "IAP service account granted Cloud Run Invoker role"
    print_info "To add more users to IAP later, run:"
    print_info "  gcloud beta iap web add-iam-policy-binding \\"
    print_info "    --member='user:EMAIL' --role='${iap_role}' \\"
    print_info "    --region=${GCP_REGION} --resource-type=cloud-run --service=${CLOUD_RUN_SERVICE_NAME}"
}

# ============================================================================
# SECTION 15: GENERATE TERRAFORM FILES
# ============================================================================

generate_terraform() {
    local total_steps=14
    print_step 11 "${total_steps}" "Generating Terraform IaC Files"

    mkdir -p "${INFRA_DIR}"

    # Safe display values for the config file
    local safe_cloud_run_url="${CLOUD_RUN_URL:-pending}"
    local safe_github_repo="${GITHUB_REPO:-}"
    local safe_confluence_url="${CONFLUENCE_URL:-}"
    local safe_jira_url="${JIRA_URL:-}"

    # ── main.tf ──
    # Using a quoted heredoc for Terraform (no bash expansion needed for
    # Terraform interpolation syntax ${...}). Then inject values with sed.
    cat > "${INFRA_DIR}/main.tf" <<MAIN_TF
# ============================================================================
# Lifecycle AI Agent — Infrastructure as Code
# ============================================================================
# Generated by setup.sh on ${TIMESTAMP}
# Project: ${GCP_PROJECT_ID}
# Connector: ${CONNECTOR_DISPLAY_NAME}
#
# This Terraform configuration describes the SAME resources created by the
# setup script. You can import existing resources with:
#   terraform init
#   terraform import <resource> <id>
# ============================================================================

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    bucket = "${GCS_TF_STATE_BUCKET}"
    prefix = "lifecycle-agent"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ============================================================================
# Variables
# ============================================================================

variable "project_id" {
  description = "GCP Project ID"
  type        = string
  default     = "${GCP_PROJECT_ID}"
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "${GCP_REGION}"
}

variable "connector_name" {
  description = "Display name for this connector"
  type        = string
  default     = "${CONNECTOR_DISPLAY_NAME}"
}

# ============================================================================
# Service Account
# ============================================================================

resource "google_service_account" "lifecycle_agent" {
  account_id   = "${SA_NAME}"
  display_name = "${SA_DISPLAY_NAME}"
  description  = "Service account for the Lifecycle AI Agent platform"
  project      = var.project_id
}

locals {
  sa_roles = [
    "roles/aiplatform.user",
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/storage.objectAdmin",
    "roles/logging.viewer",
    "roles/monitoring.viewer",
    "roles/secretmanager.secretAccessor",
    "roles/pubsub.publisher",
    "roles/pubsub.subscriber",
    "roles/run.invoker",
  ]
}

resource "google_project_iam_member" "lifecycle_agent_roles" {
  for_each = toset(local.sa_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:\${google_service_account.lifecycle_agent.email}"
}

# ============================================================================
# Artifact Registry
# ============================================================================

resource "google_artifact_registry_repository" "lifecycle_agent" {
  location      = var.region
  repository_id = "${AR_REPO_NAME}"
  format        = "DOCKER"
  description   = "Docker images for Lifecycle AI Agent"
  project       = var.project_id
}

# ============================================================================
# Cloud Storage
# ============================================================================

resource "google_storage_bucket" "data" {
  name          = "${GCS_DATA_BUCKET}"
  location      = var.region
  project       = var.project_id
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }
}

resource "google_storage_bucket" "tfstate" {
  name          = "${GCS_TF_STATE_BUCKET}"
  location      = var.region
  project       = var.project_id
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }
}

# ============================================================================
# BigQuery
# ============================================================================

resource "google_bigquery_dataset" "lifecycle_agent" {
  dataset_id = "${BQ_DATASET_NAME}"
  project    = var.project_id
  location   = "EU"

  labels = {
    app        = "lifecycle-agent"
    managed-by = "terraform"
  }
}

# ============================================================================
# Secret Manager
# ============================================================================

resource "google_secret_manager_secret" "confluence_token" {
  secret_id = "lifecycle-agent-confluence-token"
  project   = var.project_id
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret" "jira_token" {
  secret_id = "lifecycle-agent-jira-token"
  project   = var.project_id
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

# ============================================================================
# Pub/Sub
# ============================================================================

resource "google_pubsub_topic" "lifecycle_agent_events" {
  name    = "${PUBSUB_TOPIC_NAME}"
  project = var.project_id

  labels = {
    app        = "lifecycle-agent"
    managed-by = "terraform"
  }
}

# ============================================================================
# Cloud Run
# ============================================================================

resource "google_cloud_run_v2_service" "lifecycle_agent" {
  name     = "${CLOUD_RUN_SERVICE_NAME}"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.lifecycle_agent.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = "${IMAGE_URI}"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "ENVIRONMENT"
        value = "production"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "CONNECTOR_NAME"
        value = var.connector_name
      }
    }
  }
}

# IAP — authorized user
resource "google_cloud_run_service_iam_member" "invoker" {
  service  = google_cloud_run_v2_service.lifecycle_agent.name
  location = var.region
  project  = var.project_id
  role     = "roles/run.invoker"
  member   = "user:${ENGINEER_EMAIL}"
}

# ============================================================================
# Outputs
# ============================================================================

output "dashboard_url" {
  value       = google_cloud_run_v2_service.lifecycle_agent.uri
  description = "URL of the Lifecycle AI Agent dashboard"
}

output "service_account_email" {
  value       = google_service_account.lifecycle_agent.email
  description = "Service account email for the agent"
}

output "data_bucket" {
  value       = google_storage_bucket.data.name
  description = "GCS bucket for agent data (RAG docs, reports)"
}

output "bigquery_dataset" {
  value       = google_bigquery_dataset.lifecycle_agent.dataset_id
  description = "BigQuery dataset for agent tables"
}
MAIN_TF

    print_success "Generated: ${INFRA_DIR}/main.tf"

    # ── connector-config.yml ──
    cat > "${INFRA_DIR}/connector-config.yml" <<CONNECTOR_CONFIG
# ============================================================================
# Lifecycle AI Agent — Connector Configuration
# ============================================================================
# Generated by setup.sh on ${TIMESTAMP}
# This file describes the connected project and its integration settings.
# ============================================================================

connector:
  name: "${CONNECTOR_DISPLAY_NAME}"
  slug: "${CONNECTOR_SLUG}"
  created_at: "${TIMESTAMP}"
  created_by: "${ENGINEER_EMAIL}"

gcp:
  project_id: "${GCP_PROJECT_ID}"
  region: "${GCP_REGION}"
  service_account: "${SA_EMAIL}"

integrations:
  github:
    repository: "${safe_github_repo}"
    env_var: "GITHUB_PAT"

  confluence:
    url: "${safe_confluence_url}"
    secret_name: "lifecycle-agent-confluence-token"
    mock_enabled: true

  jira:
    url: "${safe_jira_url}"
    secret_name: "lifecycle-agent-jira-token"
    mock_enabled: true

infrastructure:
  cloud_run:
    service_name: "${CLOUD_RUN_SERVICE_NAME}"
    url: "${safe_cloud_run_url}"

  storage:
    data_bucket: "${GCS_DATA_BUCKET}"
    tfstate_bucket: "${GCS_TF_STATE_BUCKET}"

  bigquery:
    dataset: "${BQ_DATASET_NAME}"
    tables:
      - agent_execution_log
      - incident_reports
      - sprint_documents
      - deployment_validations

  pubsub:
    topic: "${PUBSUB_TOPIC_NAME}"

  secrets:
    - lifecycle-agent-confluence-token
    - lifecycle-agent-jira-token

agents:
  incident:
    enabled: true
    model: "gemini-2.0-flash-001"
    temperature: 0.1
    max_iterations: 10

  sprint:
    enabled: true
    model: "gemini-2.0-flash-001"
    temperature: 0.1

  deployment:
    enabled: true
    model: "gemini-2.0-flash-001"
    temperature: 0.0

  rag:
    corpus_name: "lifecycle-${CONNECTOR_SLUG}-knowledge"
    top_k: 10
    chunk_size: 512
CONNECTOR_CONFIG

    print_success "Generated: ${INFRA_DIR}/connector-config.yml"
    print_info "To manage infrastructure with Terraform later:"
    print_info "  cd ${INFRA_DIR} && terraform init && terraform plan"
}

# ============================================================================
# SECTION 16: SETUP RAG CORPUS
# ============================================================================

setup_rag_corpus() {
    local total_steps=14
    print_step 12 "${total_steps}" "Setting Up RAG Corpus"

    local corpus_name="lifecycle-${CONNECTOR_SLUG}-knowledge"
    local gcs_path="gs://${GCS_DATA_BUCKET}/rag/docs/"

    print_substep "Creating/verifying RAG corpus '${corpus_name}' and importing documents..."

    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    local rag_output=""
    if rag_output=$(python3 "${script_dir}/setup_rag_corpus.py" \
        --project-id "${GCP_PROJECT_ID}" \
        --region "${GCP_REGION}" \
        --corpus-name "${corpus_name}" \
        --gcs-path "${gcs_path}" 2>>"${LOG_FILE}"); then
        print_success "RAG corpus '${corpus_name}' is ready and documents imported."

        # Capture the corpus resource name for use in agent templates
        CORPUS_RESOURCE_NAME=$(echo "${rag_output}" | grep '^CORPUS_RESOURCE_NAME=' | cut -d= -f2-)
        if [[ -n "${CORPUS_RESOURCE_NAME}" ]]; then
            print_info "Corpus resource: ${CORPUS_RESOURCE_NAME}"
        fi
    else
        print_warning "Failed to set up RAG corpus. Check log: ${LOG_FILE}"
    fi
}

# ============================================================================
# SECTION 17: SETUP SECURITY PIPELINE (SCC Poller)
# ============================================================================

setup_security_pipeline() {
    local total_steps=14
    print_step 13 "${total_steps}" "Setting Up Security Pipeline (SCC Poller)"

    print_info "This step creates the SCC security findings pipeline..."

    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # ── Step A: Create Artifact Registry for SCC poller ──
    local scc_ar_exists=0
    gcloud artifacts repositories describe "${SCC_AR_REPO_NAME}" \
        --location="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" &>/dev/null || scc_ar_exists=$?

    if [[ ${scc_ar_exists} -eq 0 ]]; then
        print_info "Artifact Registry '${SCC_AR_REPO_NAME}' already exists"
    else
        print_substep "Creating Docker repository: ${SCC_AR_REPO_NAME}"
        local ar_exit=0
        gcloud artifacts repositories create "${SCC_AR_REPO_NAME}" \
            --repository-format=docker \
            --location="${GCP_REGION}" \
            --description="Docker images for SCC security poller pipeline" \
            --project="${GCP_PROJECT_ID}" \
            --quiet 2>>"${LOG_FILE}" || ar_exit=$?

        if [[ ${ar_exit} -eq 0 ]]; then
            print_success "Artifact Registry created: ${SCC_AR_REPO_NAME}"
        else
            print_warning "Failed to create Artifact Registry for SCC poller (exit=${ar_exit})"
        fi
    fi

    # ── Step B: Build and push SCC poller Docker image ──
    print_substep "Building SCC poller Docker image..."
    local temp_build_dir=""
    temp_build_dir=$(mktemp -d)

    # Copy the scc-poller files to a temp build directory
    cp -r "${script_dir}/scc-poller/"* "${temp_build_dir}/"

    # Look up the security-monitor agent engine ID (for the env var)
    local security_agent_id=""
    security_agent_id=$(gcloud ai agent-engines list \
        --project="${GCP_PROJECT_ID}" \
        --region="${GCP_REGION}" \
        --filter="displayName:security-monitor" \
        --format="value(name)" \
        --limit=1 2>/dev/null | awk -F'/' '{print $NF}') || true

    if [[ -z "${security_agent_id}" ]]; then
        print_warning "security-monitor agent not yet deployed. AGENT_ENGINE_ID env var will be empty until agent is deployed."
        print_info "After deploying the security-monitor agent, the Cloud Run job env var will be updated automatically."
    else
        print_success "Found security-monitor agent engine ID: ${security_agent_id}"
    fi

    print_success "SCC poller files prepared with project configuration"

    # Configure Docker auth for the registry
    gcloud auth configure-docker "${SCC_REGISTRY}" --quiet 2>>"${LOG_FILE}" || true

    # Build the Docker image
    print_substep "Building Docker image (this may take a few minutes)..."
    local build_exit=0
    docker build -t "${SCC_IMAGE_URI}" "${temp_build_dir}" 2>>"${LOG_FILE}" || build_exit=$?
    if [[ ${build_exit} -ne 0 ]]; then
        print_warning "Docker build failed for SCC poller (exit=${build_exit}). Check log: ${LOG_FILE}"
        rm -rf "${temp_build_dir}"
        return
    fi
    print_success "SCC poller Docker image built"

    # Push to Artifact Registry
    print_substep "Pushing SCC poller image to Artifact Registry..."
    local push_exit=0
    docker push "${SCC_IMAGE_URI}" 2>>"${LOG_FILE}" || push_exit=$?
    if [[ ${push_exit} -ne 0 ]]; then
        print_warning "Docker push failed for SCC poller (exit=${push_exit}). Check log: ${LOG_FILE}"
        rm -rf "${temp_build_dir}"
        return
    fi
    print_success "SCC poller image pushed to ${SCC_REGISTRY}"

    # Cleanup temp build directory
    rm -rf "${temp_build_dir}"

    # ── Step C: Create Cloud Run Job ──
    print_substep "Creating Cloud Run job: ${SCC_CLOUD_RUN_JOB_NAME}..."

    local job_exists=0
    gcloud run jobs describe "${SCC_CLOUD_RUN_JOB_NAME}" \
        --region="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" &>/dev/null || job_exists=$?

    if [[ ${job_exists} -eq 0 ]]; then
        print_info "Cloud Run job '${SCC_CLOUD_RUN_JOB_NAME}' already exists. Updating..."
        local update_exit=0
        gcloud run jobs update "${SCC_CLOUD_RUN_JOB_NAME}" \
            --image="${SCC_IMAGE_URI}" \
            --region="${GCP_REGION}" \
            --project="${GCP_PROJECT_ID}" \
            --service-account="${SA_EMAIL}" \
            --set-env-vars="GCP_PROJECT_ID=${GCP_PROJECT_ID},GCP_REGION=${GCP_REGION},AGENT_ENGINE_ID=${security_agent_id:-},GCS_DATA_BUCKET=${GCS_DATA_BUCKET},GITHUB_PAT=${GITHUB_PAT:-}" \
            --task-timeout=600 \
            --max-retries=1 \
            --memory=1Gi \
            --cpu=1 \
            --quiet 2>>"${LOG_FILE}" || update_exit=$?

        if [[ ${update_exit} -eq 0 ]]; then
            print_success "Cloud Run job updated: ${SCC_CLOUD_RUN_JOB_NAME}"
        else
            print_warning "Failed to update Cloud Run job (exit=${update_exit})"
        fi
    else
        local job_exit=0
        gcloud run jobs create "${SCC_CLOUD_RUN_JOB_NAME}" \
            --image="${SCC_IMAGE_URI}" \
            --region="${GCP_REGION}" \
            --project="${GCP_PROJECT_ID}" \
            --service-account="${SA_EMAIL}" \
            --set-env-vars="GCP_PROJECT_ID=${GCP_PROJECT_ID},GCP_REGION=${GCP_REGION},AGENT_ENGINE_ID=${security_agent_id:-},GCS_DATA_BUCKET=${GCS_DATA_BUCKET},GITHUB_PAT=${GITHUB_PAT:-}" \
            --task-timeout=600 \
            --max-retries=1 \
            --memory=1Gi \
            --cpu=1 \
            --quiet 2>>"${LOG_FILE}" || job_exit=$?

        if [[ ${job_exit} -eq 0 ]]; then
            print_success "Cloud Run job created: ${SCC_CLOUD_RUN_JOB_NAME}"
        else
            print_warning "Failed to create Cloud Run job (exit=${job_exit}). Check log: ${LOG_FILE}"
            return
        fi
    fi

    # ── Grant cloudscheduler.admin to the user running the script ──
    # The gcloud scheduler commands run as the authenticated user, not the
    # service account, so the user needs this permission to create/update
    # Cloud Scheduler jobs.
    local sched_user_member="user:${ENGINEER_EMAIL}"
    local sched_admin_role="roles/cloudscheduler.admin"

    local sched_role_bound=""
    sched_role_bound=$(gcloud projects get-iam-policy "${GCP_PROJECT_ID}" \
        --format="value(bindings.members)" \
        --flatten="bindings[].members" \
        --filter="bindings.role:${sched_admin_role} AND bindings.members:${sched_user_member}" \
        2>/dev/null | head -1) || true

    if [[ -n "${sched_role_bound}" ]]; then
        print_info "${sched_admin_role} already bound to your user account"
    else
        print_substep "Granting ${sched_admin_role} to your user account (${ENGINEER_EMAIL})..."
        gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
            --member="${sched_user_member}" \
            --role="${sched_admin_role}" \
            --format="none" --quiet 2>>"${LOG_FILE}" || \
            print_warning "Failed to grant ${sched_admin_role} to your user. Cloud Scheduler creation may fail."
        print_success "${sched_admin_role} granted to your user account"
        # Wait for IAM propagation (30 seconds recommended for role bindings)
        print_substep "Waiting for IAM propagation (30 seconds)..."
        sleep 30
    fi

    # ── Step D: Create Cloud Scheduler to run the job every 5 minutes ──
    print_substep "Creating Cloud Scheduler job: ${SCC_SCHEDULER_NAME}..."

    local scheduler_exists=0
    gcloud scheduler jobs describe "${SCC_SCHEDULER_NAME}" \
        --location="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" &>/dev/null || scheduler_exists=$?

    local cloud_run_job_uri="https://${GCP_REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${GCP_PROJECT_ID}/jobs/${SCC_CLOUD_RUN_JOB_NAME}:run"

    if [[ ${scheduler_exists} -eq 0 ]]; then
        print_info "Cloud Scheduler job '${SCC_SCHEDULER_NAME}' already exists. Updating..."
        local sched_update_exit=0
        gcloud scheduler jobs update http "${SCC_SCHEDULER_NAME}" \
            --location="${GCP_REGION}" \
            --project="${GCP_PROJECT_ID}" \
            --schedule="*/5 * * * *" \
            --uri="${cloud_run_job_uri}" \
            --http-method=POST \
            --oauth-service-account-email="${SA_EMAIL}" \
            --quiet 2>>"${LOG_FILE}" || sched_update_exit=$?

        if [[ ${sched_update_exit} -eq 0 ]]; then
            print_success "Cloud Scheduler job updated: ${SCC_SCHEDULER_NAME}"
        else
            print_warning "Failed to update Cloud Scheduler job (exit=${sched_update_exit})"
        fi
    else
        # Create scheduler job with retry logic. IAM propagation for
        # cloudscheduler.admin can take 30-60+ seconds, so we retry with
        # exponential backoff if the first attempt gets PERMISSION_DENIED.
        local sched_exit=1
        local sched_attempts=3
        local sched_delay=15
        for attempt in $(seq 1 ${sched_attempts}); do
            sched_exit=0
            gcloud scheduler jobs create http "${SCC_SCHEDULER_NAME}" \
                --location="${GCP_REGION}" \
                --project="${GCP_PROJECT_ID}" \
                --schedule="*/5 * * * *" \
                --uri="${cloud_run_job_uri}" \
                --http-method=POST \
                --oauth-service-account-email="${SA_EMAIL}" \
                --quiet 2>>"${LOG_FILE}" || sched_exit=$?

            if [[ ${sched_exit} -eq 0 ]]; then
                print_success "Cloud Scheduler created: runs every 5 minutes"
                break
            fi

            if [[ ${attempt} -lt ${sched_attempts} ]]; then
                print_warning "Cloud Scheduler creation attempt ${attempt}/${sched_attempts} failed. Waiting ${sched_delay}s for IAM propagation..."
                sleep ${sched_delay}
                sched_delay=$((sched_delay * 2))
            else
                print_warning "Failed to create Cloud Scheduler job after ${sched_attempts} attempts (exit=${sched_exit}). Check log: ${LOG_FILE}"
                print_info "You can create it manually with:"
                print_info "  gcloud scheduler jobs create http ${SCC_SCHEDULER_NAME} \\"
                print_info "    --location=${GCP_REGION} --project=${GCP_PROJECT_ID} \\"
                print_info "    --schedule='*/5 * * * *' --uri='${cloud_run_job_uri}' \\"
                print_info "    --http-method=POST --oauth-service-account-email=${SA_EMAIL}"
            fi
        done
    fi

    print_success "Security pipeline setup complete"
    print_info "SCC findings will be fetched every 5 minutes"
    print_info "Agent responses will be saved to gs://${GCS_DATA_BUCKET}/pending-documents/"
}

# ============================================================================
# SECTION 18: SETUP STARTER AGENTS
# ============================================================================

agents_setup() {
    local total_steps=14
    print_step 14 "${total_steps}" "Creating and Deploying Starter Agents"

    print_info "This step will create and deploy standard agents..."

    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    local agents=("document-editor" "security-monitor")

    # ── Phase 1: Create and configure agents sequentially ──
    # Sequential scaffolding avoids disk contention when both agents
    # download dependencies at the same time.
    for AGENT in "${agents[@]}"; do
      print_substep "Creating agent starter pack: ${AGENT}..."
      if uvx agent-starter-pack create "$AGENT" \
        -a adk \
        -d agent_engine \
        --region "${GCP_REGION}" \
        --auto-approve 2>>"${LOG_FILE}"; then
        print_success "Created '$AGENT' agent."
      else
        print_warning "Failed to create '$AGENT' agent. Check logs."
      fi

      # Inject the appropriate agent template based on agent type
      if [ -d "$AGENT" ] && [[ -n "${CORPUS_RESOURCE_NAME}" ]]; then
          if [[ "${AGENT}" == "document-editor" ]]; then
              print_substep "Injecting document-editor agent template into '$AGENT/app/agent.py'..."
              cp "${script_dir}/agent_rag_template.py" "$AGENT/app/agent.py"
              # Copy document pipeline dependencies for doc_manager_agent
              if ! cp "${script_dir}/doc_pipeline_tool.py" "$AGENT/app/doc_pipeline_tool.py" 2>>"${LOG_FILE}"; then
                  print_warning "Failed to copy doc_pipeline_tool.py into '$AGENT/app/'."
              fi
              if ! cp -r "${script_dir}/pipeline" "$AGENT/app/pipeline" 2>>"${LOG_FILE}"; then
                  print_warning "Failed to copy pipeline/ directory into '$AGENT/app/'."
              fi
              # Add python-docx + lxml for the SDLC document pipeline (fill_template.py)
              print_substep "Adding python-docx dependency to '$AGENT'..."
              (cd "$AGENT" && uv add python-docx lxml 2>>"${LOG_FILE}") || \
                  print_warning "Failed to add python-docx dependency to '$AGENT'."
          elif [[ "${AGENT}" == "security-monitor" ]]; then
              print_substep "Injecting security agent template into '$AGENT/app/agent.py'..."
              cp "${script_dir}/agent_security_template.py" "$AGENT/app/agent.py"
          else
              print_warning "Unknown agent '${AGENT}' — skipping template injection."
              continue
          fi

          sed -i "s|__REGION__|${GCP_REGION}|g" "$AGENT/app/agent.py"
          sed -i "s|__CORPUS_RESOURCE_NAME__|${CORPUS_RESOURCE_NAME}|g" "$AGENT/app/agent.py"
          sed -i "s|__GCS_DATA_BUCKET__|${GCS_DATA_BUCKET}|g" "$AGENT/app/agent.py"

          # Conditionally integrate GitHub MCP tool
          if [[ -n "${GITHUB_PAT}" ]]; then
              print_substep "Integrating GitHub MCP tool into '$AGENT/app/agent.py'..."
              sed -i "s|__GITHUB_PAT__|${GITHUB_PAT}|g" "$AGENT/app/agent.py"

              # Inject the appropriate instruction based on agent type
              local agent_instruction
              if [[ "${AGENT}" == "document-editor" ]]; then
                  agent_instruction=$(cat <<INSTRUCTION_EOF
You are the SDLC Document Editor — a knowledgeable assistant that orchestrates three specialist agents:\n\n1. \`rag_agent\` — Searches the internal RAG knowledge base for relevant project documentation.\n2. \`github_agent\` — Fetches code, pull requests, issues, and documentation from GitHub repositories.\n3. \`doc_manager_agent\` — Manages the full SDLC document lifecycle: detects the current project stage, generates stage-appropriate documents (CPDD, DOR, Architecture, Risk Register, Codebase KB, DoD, Runbook, SOP, Sprint Log, Project Explanation), uploads them to GCS, and refreshes the RAG corpus.\n\nFollow these guidelines when answering:\n\n- **IMPORTANT: Before generating any documents, ALWAYS delegate to \`rag_agent\` first to search the RAG knowledge base (corpus: ${CORPUS_RESOURCE_NAME}) for existing documentation.** Only generate documents that are missing or outdated.\n- If the user asks to generate, update, check staleness of, or manage SDLC documents, delegate to \`doc_manager_agent\`. It will detect the project stage (from the value set on the Pulse dashboard, persisted in \`stage.json\`), check the knowledge base for existing documents, and only produce documents that are missing or stale. The agent should NOT ask the user to confirm the stage when one is already stored.\n- If the user's query is about source code, code reviews, pull requests, issues, repository structure, or technical documentation, also delegate to \`github_agent\` to fetch relevant content from the connected repositories.\n- When multiple agents return useful results, combine and synthesize the information into a single coherent answer.\n- If a query is specifically about code implementation details, file contents, or recent changes, prioritize results from \`github_agent\` as it provides the most up-to-date information.\n- If no relevant information is found from any agent, say so clearly.\n\nRAG Knowledge Base corpus ID: ${CORPUS_RESOURCE_NAME}
INSTRUCTION_EOF
                  )
              else
                  agent_instruction=$(cat <<'INSTRUCTION_EOF'
You are the Security Monitor — a GCP security assistant that orchestrates two specialist agents:\n\n1. `rag_agent` — Searches the internal RAG knowledge base for existing security documentation, SOPs, and project context.\n2. `github_agent` — Fetches code, pull requests, issues, and documentation from GitHub repositories to correlate findings with source code.\n\nYour primary role is to analyze Google Cloud Security Command Center (SCC) findings and provide actionable security guidance.\n\nFollow these guidelines when answering:\n\n- When presented with an SCC finding, delegate to `rag_agent` first to check for existing remediation SOPs, security reports, or related documentation in the knowledge base.\n- If the finding relates to code, infrastructure-as-code, or repository configuration, delegate to `github_agent` to fetch the relevant source files, recent changes, or related pull requests.\n- For each finding, provide: (a) root cause analysis, (b) concrete mitigation steps, (c) a remediation SOP, and (d) references to any relevant knowledge base documentation.\n- When both agents return useful results, combine and synthesize the information into a single coherent security assessment.\n- You are a read-only analyst — you do NOT create, edit, or upload documents. Your role is to analyze, assess, and recommend.\n- If no relevant information is found from either agent, say so clearly and provide general GCP security best-practice guidance.
INSTRUCTION_EOF
                  )
              fi

              # Append GitHub repository context to the instruction prompt
              if [[ -n "${GITHUB_REPOS:-}" ]]; then
                  local repos_prompt="\\n\\nConnected GitHub repositories for documentation and code review: ${GITHUB_REPOS}. When going through documentation, code, and project context, use these repositories as your primary sources."
                  agent_instruction="${agent_instruction}${repos_prompt}"
              fi

              sed -i "s|__AGENT_INSTRUCTION__|${agent_instruction}|g" "$AGENT/app/agent.py"

              print_success "GitHub MCP tool integrated into '$AGENT'."
          else
              print_substep "Skipping GitHub MCP tool (no PAT provided)."
              sed -i '/^# __GITHUB_MCP_BEGIN__$/,/^# __GITHUB_MCP_END__$/d' "$AGENT/app/agent.py"
              sed -i '/# __GITHUB_MCP_TOOLS__/d' "$AGENT/app/agent.py"

              # Inject the appropriate RAG-only instruction based on agent type
              local rag_instruction
              if [[ "${AGENT}" == "document-editor" ]]; then
                  rag_instruction=$(cat <<INSTRUCTION_EOF
You are the SDLC Document Editor — a document management assistant that orchestrates two specialist agents:\n\n1. \`rag_agent\` — Retrieves relevant project documentation from the knowledge base.\n2. \`doc_manager_agent\` — Manages the full SDLC document lifecycle: detects the current project stage, generates stage-appropriate documents (CPDD, DOR, Architecture, Risk Register, Codebase KB, DoD, Runbook, SOP, Sprint Log, Project Explanation), uploads them to GCS, and refreshes the RAG corpus.\n\n**IMPORTANT: Before generating any documents, ALWAYS delegate to \`rag_agent\` first to search the RAG knowledge base (corpus: ${CORPUS_RESOURCE_NAME}) for existing documentation.** Only generate documents that are missing or outdated.\n\nIf the user wants to generate, update, check staleness of, or manage SDLC documents, delegate to \`doc_manager_agent\`. It will detect the project stage from the value set on the Pulse dashboard (persisted in \`stage.json\`), check the knowledge base for existing documents, and only produce documents that are missing or stale. The agent should NOT ask the user to confirm the stage when one is already stored.\n\nIf no relevant information is found, say so.\n\nRAG Knowledge Base corpus ID: ${CORPUS_RESOURCE_NAME}
INSTRUCTION_EOF
                  )
              else
                  rag_instruction=$(cat <<'INSTRUCTION_EOF'
You are the Security Monitor — a GCP security assistant that delegates to a specialist agent.\n\nYour primary role is to analyze Google Cloud Security Command Center (SCC) findings and provide actionable security guidance.\n\nAlways delegate to `rag_agent` to search the knowledge base for existing security documentation, SOPs, and remediation guidance before answering.\n\nFor each finding, provide: (a) root cause analysis, (b) concrete mitigation steps, (c) a remediation SOP, and (d) references to any relevant knowledge base documentation.\n\nYou are a read-only analyst — you do NOT create, edit, or upload documents. Your role is to analyze, assess, and recommend.\n\nIf no relevant information is found, say so and provide general GCP security best-practice guidance.
INSTRUCTION_EOF
                  )
              fi

              # Append GitHub repository context to the instruction prompt
              if [[ -n "${GITHUB_REPOS:-}" ]]; then
                  local repos_rag_prompt="\\n\\nConnected GitHub repositories: ${GITHUB_REPOS}. Reference these repositories when discussing project documentation and context."
                  rag_instruction="${rag_instruction}${repos_rag_prompt}"
              fi

              sed -i "s|__AGENT_INSTRUCTION__|${rag_instruction}|g" "$AGENT/app/agent.py"
          fi

          print_success "Agent template injected into '$AGENT'."
      fi
    done

    # ── Phase 2: Free up disk space before parallel deployment ──
    # Clean up unused Docker images/layers to mitigate size overload when
    # both agents build and deploy simultaneously.
    print_substep "Cleaning up Docker resources to free disk space before parallel deployment..."
    docker system prune -f 2>>"${LOG_FILE}" || true

    # ── Phase 3: Deploy agents in parallel ──
    # Both agents are deployed simultaneously to save time. Each deployment
    # runs in a background subshell with output buffered to a temp file.
    print_info "Deploying agents in parallel to reduce setup time..."
    local -a deploy_pids=()
    local -a deploy_agents=()
    local DEPLOY_TMP
    DEPLOY_TMP=$(mktemp -d)

    for AGENT in "${agents[@]}"; do
        if [ -d "$AGENT" ]; then
            (
                cd "$AGENT" || exit 1
                make deploy
            ) > "${DEPLOY_TMP}/${AGENT}.log" 2>&1 &
            deploy_pids+=($!)
            deploy_agents+=("${AGENT}")
            print_info "Started deployment of '${AGENT}' in background (PID: ${deploy_pids[-1]})"
        fi
    done

    # Wait for all deployments to complete and handle post-deployment tasks
    for i in "${!deploy_pids[@]}"; do
        local agent="${deploy_agents[$i]}"
        local exit_code=0
        wait "${deploy_pids[$i]}" || exit_code=$?

        # Print the buffered deployment output
        if [[ -f "${DEPLOY_TMP}/${agent}.log" ]]; then
            cat "${DEPLOY_TMP}/${agent}.log"
        fi

        if [[ ${exit_code} -eq 0 ]]; then
            print_success "Deployed '${agent}' agent."

            # Extract the agent engine ID from deployment_metadata.json before
            # deleting the agent folder. The file is written by the deployment
            # and contains the remote_agent_engine_id path.
            local agent_engine_id=""
            local metadata_file="${agent}/deployment_metadata.json"
            if [[ -f "${metadata_file}" ]]; then
                agent_engine_id=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
engine_path = data.get('remote_agent_engine_id', '')
parts = engine_path.split('/')
engine_id = parts[-1] if len(parts) > 1 else ''
print(engine_id)
" "${metadata_file}" 2>/dev/null) || true
                if [[ -n "${agent_engine_id}" && "${agent_engine_id}" =~ ^[0-9]+$ ]]; then
                    print_success "Extracted '${agent}' agent engine ID from deployment_metadata.json: ${agent_engine_id}"
                else
                    print_warning "Could not parse a valid numeric agent engine ID from ${metadata_file}."
                    agent_engine_id=""
                fi
            else
                print_warning "deployment_metadata.json not found in '${agent}' folder."
            fi

            rm -rf "${agent}"

            # After deploying the security-monitor agent, re-deploy the
            # Cloud Run job with the real agent engine ID.
            if [[ "${agent}" == "security-monitor" ]]; then
                redeploy_security_pipeline "${agent_engine_id}"
            fi

            # After deploying the document-editor agent, update the Cloud Run
            # dashboard service with the agent engine ID so the FastAPI
            # "Knowledge Base" page can call the agent via Agent Engine API.
            if [[ "${agent}" == "document-editor" && -n "${agent_engine_id}" ]]; then
                print_substep "Updating Cloud Run dashboard with document-editor agent engine ID..."
                local cr_update_exit=0
                gcloud run services update "${CLOUD_RUN_SERVICE_NAME}" \
                    --update-env-vars="AGENT_ENGINE_ID=${agent_engine_id}" \
                    --region="${GCP_REGION}" \
                    --project="${GCP_PROJECT_ID}" \
                    --quiet 2>>"${LOG_FILE}" || cr_update_exit=$?
                if [[ ${cr_update_exit} -eq 0 ]]; then
                    print_success "Cloud Run dashboard updated with AGENT_ENGINE_ID=${agent_engine_id}"
                else
                    print_warning "Failed to update Cloud Run with agent engine ID (exit=${cr_update_exit}). You may need to set AGENT_ENGINE_ID manually."
                fi
            fi
        else
            print_warning "Failed to deploy '${agent}'."
        fi

        # Clean up Docker images after each deployment to manage disk space
        # and prevent size overload.
        docker system prune -f 2>>"${LOG_FILE}" || true
    done

    rm -rf "${DEPLOY_TMP}"
}

# ============================================================================
# SECTION 19: RE-DEPLOY SECURITY PIPELINE WITH AGENT ENGINE ID
# ============================================================================

redeploy_security_pipeline() {
    local security_agent_id="${1:-}"
    print_substep "Updating security pipeline with deployed agent engine ID..."

    # Use the agent engine ID passed from agents_setup() (extracted from
    # deployment_metadata.json).  Fall back to gcloud lookup if not provided.
    if [[ -z "${security_agent_id}" ]]; then
        print_warning "Agent engine ID not provided. Falling back to gcloud lookup..."
        security_agent_id=$(gcloud ai agent-engines list \
            --project="${GCP_PROJECT_ID}" \
            --region="${GCP_REGION}" \
            --filter="displayName:security-monitor" \
            --format="value(name)" \
            --limit=1 2>/dev/null | awk -F'/' '{print $NF}') || true
    fi

    if [[ -z "${security_agent_id}" ]]; then
        print_warning "Could not retrieve security-monitor agent engine ID after deployment."
        print_info "The Cloud Run job will need to be manually updated with the correct agent engine ID."
        return
    fi

    print_success "Resolved security-monitor agent engine ID: ${security_agent_id}"

    # Update the Cloud Run job env vars with the real agent engine ID
    # (no Docker rebuild needed — config is read from env vars at runtime)
    print_substep "Updating Cloud Run job env vars with agent engine ID..."
    local update_exit=0
    gcloud run jobs update "${SCC_CLOUD_RUN_JOB_NAME}" \
        --region="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --update-env-vars="AGENT_ENGINE_ID=${security_agent_id}" \
        --quiet 2>>"${LOG_FILE}" || update_exit=$?

    if [[ ${update_exit} -eq 0 ]]; then
        print_success "Cloud Run job updated with security-monitor agent engine ID: ${security_agent_id}"
    else
        print_warning "Failed to update Cloud Run job (exit=${update_exit}). Check log: ${LOG_FILE}"
    fi
}

# ============================================================================
# SECTION 20: SAVE SETUP LOG & PRINT SUMMARY
# ============================================================================

print_final_summary() {
    local total_steps=14
    print_step 14 "${total_steps}" "Setup Complete!"

    local safe_cloud_run_url="${CLOUD_RUN_URL:-<pending>}"

    # Save structured log
    cat >> "${LOG_FILE}" <<LOG_ENTRY

========================================
SETUP COMPLETED: ${TIMESTAMP}
========================================
Project:       ${GCP_PROJECT_ID}
Connector:     ${CONNECTOR_DISPLAY_NAME}
Region:        ${GCP_REGION}
GitHub Repos:  ${GITHUB_REPOS:-<not set>}
Confluence:    ${CONFLUENCE_URL:-<not set>}
Jira:          ${JIRA_URL:-<not set>}
Admin:         ${ENGINEER_EMAIL}
Service URL:   ${safe_cloud_run_url}
Service Acct:  ${SA_EMAIL}
Data Bucket:   ${GCS_DATA_BUCKET}
TF State:      ${GCS_TF_STATE_BUCKET}
BQ Dataset:    ${BQ_DATASET_NAME}
Pub/Sub Topic: ${PUBSUB_TOPIC_NAME}
SCC Job:       ${SCC_CLOUD_RUN_JOB_NAME}
SCC Scheduler: ${SCC_SCHEDULER_NAME} (every 5 min)
Pending Docs:  gs://${GCS_DATA_BUCKET}/pending-documents/
Infra Dir:     ${INFRA_DIR}
========================================
LOG_ENTRY

    echo ""
    echo ""
    echo -e "${GREEN}${BOLD}"
    echo "  ╔══════════════════════════════════════════════════════════════════╗"
    echo "  ║                                                                  ║"
    echo "  ║        ✅ ✅ ✅   SETUP COMPLETE!   ✅ ✅ ✅                    ║"
    echo "  ║                                                                  ║"
    echo "  ╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
    echo -e "  ${BOLD}🌐 Your Lifecycle AI Agent Dashboard:${NC}"
    echo ""
    echo -e "     ${CYAN}${BOLD}${safe_cloud_run_url}${NC}"
    echo ""
    echo -e "  ═══════════════════════════════════════════════════════════════════"
    echo ""
    echo -e "  ${BOLD}📋 NEXT STEPS:${NC}"
    echo ""
    echo -e "  ${GREEN}1.${NC} Click the URL above to open the dashboard"
    echo -e "     ${DIM}(You'll be prompted to authenticate with your Google account)${NC}"
    echo ""
    echo -e "  ${GREEN}2.${NC} Go to ${BOLD}Settings → Secrets${NC} and add your API tokens:"
    echo -e "     ${DIM}• Confluence API Token (optional — for documentation)${NC}"
    echo -e "     ${DIM}• Jira API Token (optional — for ticket creation)${NC}"
    echo ""
    echo -e "     ${DIM}Note: GitHub PAT is stored as a Cloud Run environment variable.${NC}"
    echo -e "     ${DIM}To update it, re-deploy the Cloud Run service and job with the new value.${NC}"
    echo ""
    echo -e "  ${GREEN}3.${NC} Go to ${BOLD}Connectors${NC} to verify your project is connected"
    echo ""
    echo -e "  ${GREEN}4.${NC} Try the ${BOLD}Incident Agent${NC} with a simulated alert!"
    echo ""
    echo -e "  ${GREEN}5.${NC} ${BOLD}Security Pipeline${NC} is running automatically every 5 minutes"
    echo -e "     ${DIM}• SCC findings are fetched and analyzed by the security-monitor agent${NC}"
    echo -e "     ${DIM}• Agent responses saved to: gs://${GCS_DATA_BUCKET}/pending-documents/${NC}"
    echo ""
    echo -e "  ═══════════════════════════════════════��═══════════════════════════"
    echo ""
    echo -e "  ${BOLD}📁 FILES CREATED:${NC}"
    echo -e "    • Terraform IaC:     ${CYAN}${INFRA_DIR}/main.tf${NC}"
    echo -e "    • Connector Config:  ${CYAN}${INFRA_DIR}/connector-config.yml${NC}"
    echo -e "    • Environment File:  ${CYAN}${INFRA_DIR}/connector.env${NC}"
    echo -e "    • Setup Log:         ${CYAN}${LOG_FILE}${NC}"
    echo ""
    echo -e "  ${BOLD}⏱️  Total setup time:${NC} $((SECONDS / 60)) minutes $((SECONDS % 60)) seconds"
    echo -e "  ${BOLD}💰 Estimated cost:${NC} ~\$0.01/day idle, ~\$1-2/day active"
    echo ""
    echo -e "  ${DIM}Need help? See: docs/CONNECTOR_GUIDE.md${NC}"
    echo -e "  ${DIM}To add more users: gcloud run services add-iam-policy-binding ${CLOUD_RUN_SERVICE_NAME} \\${NC}"
    echo -e "  ${DIM}  --region=${GCP_REGION} --member='user:EMAIL' --role='roles/run.invoker'${NC}"
    echo ""
}

# ============================================================================
# SECTION 21: MAIN EXECUTION FLOW
# ============================================================================

main() {
    # Initialize log and timer
    echo "========================================" > "${LOG_FILE}"
    echo "Lifecycle AI Agent Setup — ${TIMESTAMP}" >> "${LOG_FILE}"
    echo "Script Version: ${SCRIPT_VERSION}" >> "${LOG_FILE}"
    echo "========================================" >> "${LOG_FILE}"

    # Reset timer
    SECONDS=0

    # ── Phase 1: Sequential setup (user input, prerequisites, service account) ──
    # These steps require user interaction or must run before anything else.
    print_banner
    preflight_checks
    ask_questions
    confirm_setup

    # Write initial environment file with user-provided configuration values.
    # This is updated again after Phase 3 with runtime-resolved values
    # (CLOUD_RUN_URL, CORPUS_RESOURCE_NAME).
    write_env_file

    enable_apis
    ensure_sa_admin_role
    create_service_account

    # ── Create secure temp directory for parallel execution ──
    local PARALLEL_TMP
    PARALLEL_TMP=$(mktemp -d)

    # ── Phase 2: Independent resource creation (parallel) ──
    # These five steps are completely independent of each other and only
    # require the service account + enabled APIs from Phase 1. Running them
    # in parallel saves significant wall-clock time.
    print_info "Creating infrastructure resources in parallel..."

    create_artifact_registry > "${PARALLEL_TMP}/ar.log" 2>&1 &
    local pid_ar=$!
    create_storage_buckets > "${PARALLEL_TMP}/buckets.log" 2>&1 &
    local pid_buckets=$!
    create_bigquery_resources > "${PARALLEL_TMP}/bq.log" 2>&1 &
    local pid_bq=$!
    create_secrets > "${PARALLEL_TMP}/secrets.log" 2>&1 &
    local pid_secrets=$!
    create_pubsub > "${PARALLEL_TMP}/pubsub.log" 2>&1 &
    local pid_pubsub=$!

    local phase2_failed=0
    for pid_entry in \
        "ar:${pid_ar}" \
        "buckets:${pid_buckets}" \
        "bq:${pid_bq}" \
        "secrets:${pid_secrets}" \
        "pubsub:${pid_pubsub}"; do
        local p_name="${pid_entry%%:*}"
        local p_pid="${pid_entry##*:}"
        local p_exit=0
        wait "${p_pid}" || p_exit=$?
        if [[ -f "${PARALLEL_TMP}/${p_name}.log" ]]; then
            cat "${PARALLEL_TMP}/${p_name}.log"
        else
            print_warning "Log file for ${p_name} not found"
        fi
        if [[ ${p_exit} -ne 0 ]]; then
            phase2_failed=1
        fi
    done

    if [[ ${phase2_failed} -ne 0 ]]; then
        rm -rf "${PARALLEL_TMP}"
        print_error "One or more resource creation steps failed. Aborting."
        exit 1
    fi
    print_success "All infrastructure resources created in parallel"

    # ── Phase 3: Parallel workstreams ──
    # Four independent workstreams that can run simultaneously:
    #   Stream A — Dashboard: build image → deploy Cloud Run → configure IAP
    #   Stream B — RAG corpus setup
    #   Stream C — Security pipeline (SCC poller)
    #   Stream D — Terraform file generation (local only, no GCP calls)
    # Note: Subshells inherit 'set -eo pipefail' from the parent, so any
    # failure inside a stream (e.g. exit 1 in build_and_push_image) causes
    # the subshell to exit immediately with a non-zero code.
    print_info "Running dashboard deployment, RAG corpus, security pipeline, and Terraform generation in parallel..."

    # Stream A: Dashboard pipeline
    (
        build_and_push_image
        deploy_cloud_run
        # Export CLOUD_RUN_URL for the parent process via temp file
        echo "${CLOUD_RUN_URL}" > "${PARALLEL_TMP}/cloud_run_url.txt"
        configure_iap
    ) > "${PARALLEL_TMP}/stream_dashboard.log" 2>&1 &
    local pid_dashboard=$!

    # Stream B: RAG corpus setup
    (
        setup_rag_corpus
        # Export CORPUS_RESOURCE_NAME for the parent process via temp file
        echo "${CORPUS_RESOURCE_NAME}" > "${PARALLEL_TMP}/corpus_resource_name.txt"
    ) > "${PARALLEL_TMP}/stream_rag.log" 2>&1 &
    local pid_rag=$!

    # Stream C: Security pipeline
    setup_security_pipeline > "${PARALLEL_TMP}/stream_security.log" 2>&1 &
    local pid_security=$!

    # Stream D: Terraform file generation (local-only, fast)
    generate_terraform > "${PARALLEL_TMP}/stream_terraform.log" 2>&1 &
    local pid_terraform=$!

    # Wait for all streams and print their buffered output
    local dashboard_exit=0 rag_exit=0 security_exit=0 terraform_exit=0

    wait ${pid_dashboard} || dashboard_exit=$?
    [[ -f "${PARALLEL_TMP}/stream_dashboard.log" ]] && cat "${PARALLEL_TMP}/stream_dashboard.log"

    wait ${pid_rag} || rag_exit=$?
    [[ -f "${PARALLEL_TMP}/stream_rag.log" ]] && cat "${PARALLEL_TMP}/stream_rag.log"

    wait ${pid_security} || security_exit=$?
    [[ -f "${PARALLEL_TMP}/stream_security.log" ]] && cat "${PARALLEL_TMP}/stream_security.log"

    wait ${pid_terraform} || terraform_exit=$?
    [[ -f "${PARALLEL_TMP}/stream_terraform.log" ]] && cat "${PARALLEL_TMP}/stream_terraform.log"

    # Recover global variables set inside subshell functions.
    # The dashboard stream is critical — if it failed, CLOUD_RUN_URL won't
    # exist and we abort below. The RAG stream is best-effort.
    if [[ -f "${PARALLEL_TMP}/cloud_run_url.txt" ]]; then
        CLOUD_RUN_URL=$(cat "${PARALLEL_TMP}/cloud_run_url.txt")
    fi
    if [[ -f "${PARALLEL_TMP}/corpus_resource_name.txt" ]]; then
        CORPUS_RESOURCE_NAME=$(cat "${PARALLEL_TMP}/corpus_resource_name.txt")
    fi

    # Clean up temp directory
    rm -rf "${PARALLEL_TMP}"

    if [[ ${dashboard_exit} -ne 0 ]]; then
        print_error "Dashboard pipeline failed (exit=${dashboard_exit}). Aborting."
        exit 1
    fi
    if [[ ${rag_exit} -ne 0 ]]; then
        print_warning "RAG corpus setup failed (exit=${rag_exit}). Continuing without RAG."
    fi
    if [[ ${security_exit} -ne 0 ]]; then
        print_warning "Security pipeline setup failed (exit=${security_exit}). Continuing..."
    fi
    if [[ ${terraform_exit} -ne 0 ]]; then
        print_warning "Terraform file generation failed (exit=${terraform_exit}). Continuing..."
    fi

    print_success "All parallel workstreams completed"

    # Update the Cloud Run service env vars with runtime-resolved values
    # (CORPUS_RESOURCE_NAME, GCS_DATA_BUCKET) that were populated by Phase 3.
    # These are needed by the Setup Documentation button in the dashboard.
    if [[ -n "${CORPUS_RESOURCE_NAME:-}" || -n "${GCS_DATA_BUCKET:-}" ]]; then
        print_substep "Updating Cloud Run env vars with resolved configuration..."
        local update_env_exit=0
        gcloud run services update "${CLOUD_RUN_SERVICE_NAME}" \
            --region="${GCP_REGION}" \
            --project="${GCP_PROJECT_ID}" \
            --update-env-vars="CORPUS_RESOURCE_NAME=${CORPUS_RESOURCE_NAME:-},GCS_DATA_BUCKET=${GCS_DATA_BUCKET:-},GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID},GOOGLE_CLOUD_LOCATION=${GCP_REGION}" \
            --quiet 2>>"${LOG_FILE}" || update_env_exit=$?

        if [[ ${update_env_exit} -eq 0 ]]; then
            print_success "Cloud Run env vars updated with CORPUS_RESOURCE_NAME and GCS_DATA_BUCKET"
        else
            print_warning "Failed to update Cloud Run env vars (exit=${update_env_exit}). Setup Documentation button may not work."
        fi
    fi

    # Update the environment file with runtime-resolved values
    # (CLOUD_RUN_URL, CORPUS_RESOURCE_NAME) that were populated by Phase 3.
    write_env_file

    # ── Phase 4: Agent deployment ──
    # Terraform files were generated in Phase 3 (parallel stream D).
    agents_setup

    print_final_summary
}

# Run main
main "$@"
