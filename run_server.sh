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

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m | tr '[:upper:]' '[:lower:]')"

if [[ -z "${LOCAL_WHISPER_DEVICE:-}" ]]; then
  if [[ "$OS" == "darwin" && "$ARCH" == "arm64" ]]; then
    LOCAL_WHISPER_DEVICE="cpu"
  elif [[ "$OS" == "linux" ]] || [[ "$OS" == mingw* ]] || [[ "$OS" == msys* ]] || [[ "$OS" == cygwin* ]]; then
    if command -v nvidia-smi >/dev/null 2>&1; then
      LOCAL_WHISPER_DEVICE="cuda"
    else
      LOCAL_WHISPER_DEVICE="cpu"
    fi
  else
    LOCAL_WHISPER_DEVICE="cpu"
  fi
fi

if [[ -z "${LOCAL_WHISPER_COMPUTE_TYPE:-}" ]]; then
  if [[ "$LOCAL_WHISPER_DEVICE" == "cuda" ]]; then
    LOCAL_WHISPER_COMPUTE_TYPE="float16"
  elif [[ "$OS" == "darwin" && "$ARCH" == "arm64" ]]; then
    LOCAL_WHISPER_COMPUTE_TYPE="int8"
    export LOCAL_WHISPER_BEAM_SIZE="${LOCAL_WHISPER_BEAM_SIZE:-1}"
  else
    LOCAL_WHISPER_COMPUTE_TYPE="int8_float32"
  fi
fi

export LOCAL_WHISPER_MODEL LOCAL_WHISPER_DEVICE LOCAL_WHISPER_COMPUTE_TYPE

: "${HF_HOME:=$PROJECT_ROOT/.cache}"  # Store Hugging Face caches on the larger disk
export HF_HOME

mkdir -p "$HF_HOME"

echo "Starting whisper server with model=$LOCAL_WHISPER_MODEL device=$LOCAL_WHISPER_DEVICE compute_type=$LOCAL_WHISPER_COMPUTE_TYPE" >&2

# Check if port 9000 is in use and kill the blocking process
PORT=9000
if command -v lsof >/dev/null 2>&1; then
  PID=$(lsof -t -i :$PORT || true)
  if [[ -n "$PID" ]]; then
    echo "Warning: Port $PORT is in use by PID $PID. Killing process..." >&2
    kill -9 $PID 2>/dev/null || true
    sleep 1
  fi
elif command -v fuser >/dev/null 2>&1; then
  if fuser $PORT/tcp >/dev/null 2>&1; then
    echo "Warning: Port $PORT is in use. Killing process..." >&2
    fuser -k -9 $PORT/tcp >/dev/null 2>&1 || true
    sleep 1
  fi
fi

exec uvicorn whisper_server:app --host 0.0.0.0 --port $PORT
