#!/usr/bin/env bash
# Start native Ollama (outside Docker, for Metal GPU) if it is not already serving, then check the
# model is pulled. Called by `make up-detached`; a no-op when Ollama is already up.
set -euo pipefail

URL="${OLLAMA_URL:-http://localhost:11434}"
MODEL="${MODEL_NAME:-qwen3.8:27b}"
LOG="${OLLAMA_LOG:-$HOME/Library/Logs/ollama-local-muse.log}"

up() { curl -sf -m 2 "$URL/api/version" >/dev/null; }

if ! up; then
  command -v ollama >/dev/null || { echo "ollama not installed: brew install ollama" >&2; exit 1; }
  echo "starting ollama serve (log: $LOG)"
  nohup ollama serve >>"$LOG" 2>&1 &
  for _ in $(seq 1 30); do up && break; sleep 1; done
  up || { echo "ollama did not start; see $LOG" >&2; exit 1; }
fi

if ! curl -sf -m 5 "$URL/api/tags" | grep -q "\"name\":\"$MODEL\""; then
  echo "model $MODEL is not pulled; run: ollama pull $MODEL" >&2
  exit 1
fi
echo "ollama up with $MODEL"
