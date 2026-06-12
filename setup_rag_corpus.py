#!/usr/bin/env python3
"""Create or reuse a Vertex AI RAG corpus and import documents from GCS."""

import argparse
import sys
import time

import vertexai
from vertexai import rag


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create/verify a RAG corpus and import documents from GCS."
    )
    parser.add_argument("--project-id", required=True, help="GCP project ID")
    parser.add_argument("--region", required=True, help="GCP region (e.g. europe-west1)")
    parser.add_argument("--corpus-name", required=True, help="Display name for the RAG corpus")
    parser.add_argument("--gcs-path", required=True, help="GCS path to import documents from")
    args = parser.parse_args()

    vertexai.init(project=args.project_id, location=args.region)

    # ------------------------------------------------------------------
    # Check if a corpus with the given display name already exists
    # ------------------------------------------------------------------
    existing_corpus = None
    try:
        for c in rag.list_corpora():
            if c.display_name == args.corpus_name:
                existing_corpus = c
                break
    except Exception as e:
        print(f"ERROR: Failed to list RAG corpora: {e}", file=sys.stderr)
        print("Ensure the Vertex AI RAG API is enabled and the service account has 'roles/aiplatform.user'.", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Create or reuse the corpus
    # ------------------------------------------------------------------
    if existing_corpus:
        corpus = existing_corpus
        print(f"Using existing corpus: {corpus.name}")
    else:
        try:
            corpus = rag.create_corpus(display_name=args.corpus_name)
            print(f"Created new corpus: {corpus.name}")
        except Exception as e:
            print(f"ERROR: Failed to create RAG corpus: {e}", file=sys.stderr)
            print("Ensure the Vertex AI RAG API is enabled and the service account has 'roles/aiplatform.user'.", file=sys.stderr)
            sys.exit(1)

    # Output the corpus resource name immediately so the shell wrapper can
    # capture it even if the import step below fails.
    print(f"CORPUS_RESOURCE_NAME={corpus.name}")

    # ------------------------------------------------------------------
    # Import files from GCS (with retry logic)
    # ------------------------------------------------------------------
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            rag.import_files(
                corpus_name=corpus.name,
                paths=[args.gcs_path],
            )
            print(f"Files imported into corpus: {corpus.name}")
            break
        except Exception as e:
            print(f"WARNING: Import attempt {attempt}/{max_attempts} failed: {e}", file=sys.stderr)
            if attempt < max_attempts:
                wait_time = 2 ** (attempt - 1)
                print(f"Retrying in {wait_time} seconds...", file=sys.stderr)
                time.sleep(wait_time)
            else:
                print(f"ERROR: All {max_attempts} import attempts failed. Corpus created but empty.", file=sys.stderr)
                print("Ensure the GCS path exists and the service account has 'roles/storage.objectViewer'.", file=sys.stderr)
                sys.exit(1)


if __name__ == "__main__":
    main()
