#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "This script must be run with bash (try: 'bash run_server.sh')." >&2
  exit 1
fi

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -d .venv ]]; then
  echo "\nERROR: .venv not found. Run 'python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt' first." >&2
  exit 1
fi

source .venv/bin/activate

MODEL_CHOICE="${1:-}"

case "$MODEL_CHOICE" in
  "" )
    : "${LOCAL_WHISPER_MODEL:=base}"
    ;;
  small )
    LOCAL_WHISPER_MODEL="small"
    ;;
  base )
    LOCAL_WHISPER_MODEL="base"
    ;;
  large )
    LOCAL_WHISPER_MODEL="large-v3-turbo"
    ;;
  * )
    echo "Usage: $0 [small|base|large]" >&2
    exit 1
    ;;
esac

: "${LOCAL_WHISPER_DEVICE:=auto}"
: "${LOCAL_WHISPER_COMPUTE_TYPE:=auto}"
export LOCAL_WHISPER_MODEL LOCAL_WHISPER_DEVICE LOCAL_WHISPER_COMPUTE_TYPE

: "${HF_HOME:=$PROJECT_ROOT/.cache}"  # Store Hugging Face caches on the larger disk
export HF_HOME

mkdir -p "$HF_HOME"

echo "Starting whisper server with model=$LOCAL_WHISPER_MODEL device=$LOCAL_WHISPER_DEVICE compute_type=$LOCAL_WHISPER_COMPUTE_TYPE" >&2

exec uvicorn whisper_server:app --host 0.0.0.0 --port 9000
