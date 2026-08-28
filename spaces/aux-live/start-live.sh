#!/usr/bin/env bash
set -euo pipefail

pids=()
stop_services() {
  trap - TERM INT EXIT
  if ((${#pids[@]})); then
    kill "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}
trap stop_services TERM INT EXIT

# Normalize the Hugging Face Space variable names into the internal service
# contracts. Explicit OPENAI_* Space settings take precedence over legacy
# Blablador aliases without printing any secret value. Primary provider is the
# self-hosted freellmapi router (Tailscale Funnel); Helmholtz Blablador was the
# prior provider and BLABLADOR_* names remain supported as legacy aliases only.
export OPENAI_BASE_URL="${OPENAI_COMPATIBLE_ENDPOINT:-${OPENAI_BASE_URL:-https://debian-devil.tail3f341b.ts.net/v1}}"
# The freellmapi router requires the literal model id "auto" (its router picks the
# best available model); any other id 400s with model_not_found.
export OPENAI_MODEL="${OPENAI_MODEL:-auto}"
export JOURNEY_MODEL="${OPENAI_MODEL:-${JOURNEY_MODEL:-auto}}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-${BLABLADOR_API_KEY:-}}"
export BLABLADOR_API_KEY="${BLABLADOR_API_KEY:-${OPENAI_API_KEY:-}}"
export BLABLADOR_BASE_URL="${BLABLADOR_BASE_URL:-${OPENAI_BASE_URL}}"
# Bound the OpenAI-compatible completion budget. TinyTroupe 0.7 otherwise requests
# 128000 completion tokens by default; an explicit ceiling keeps completions
# bounded and predictable. The router's ~1,048,576 token context window leaves
# ample room to raise this if longer completions are ever needed.
export OPENAI_MAX_COMPLETION_TOKENS="${OPENAI_MAX_COMPLETION_TOKENS:-8192}"
export AGENT_BROWSER_COMMAND="${AGENT_BROWSER_COMMAND:-/home/user/app/spaces/aux-live/agent-browser-container.sh}"

# Prefer Hugging Face Spaces' persistent storage volume (mounted at /data when a
# Space has the Persistent Storage add-on attached) for the control-plane DB,
# persona pool DB, and artifact tree, so sessions/reports/artifacts survive Space
# restarts and redeploys instead of resetting to empty container filesystem every
# time. Falls back to the Dockerfile's ephemeral /home/user paths when /data isn't
# a writable mount (no persistent storage attached).
if [ -d /data ] && ( : > /data/.aux-write-test ) 2>/dev/null; then
  rm -f /data/.aux-write-test
  mkdir -p /data/control-plane /data/artifacts
  export DATABASE_URL="sqlite:////data/control-plane/control-plane.sqlite3"
  export PERSONA_DATABASE_PATH="/data/control-plane/personas.sqlite3"
  export ARTIFACT_ROOT="/data/artifacts"
  export JOURNEY_ARTIFACT_ROOT="/data/artifacts/journeys"
  echo "[start-live] Using persistent storage at /data for the control-plane DB and artifacts."
else
  echo "[start-live] No writable /data mount found; using ephemeral in-container storage ($ARTIFACT_ROOT) -- reports will not survive a Space restart."
fi

uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 & pids+=("$!")
uvicorn services.persona_service.main:app --host 127.0.0.1 --port 8090 & pids+=("$!")
node services/journey-worker/node/src/index.js & pids+=("$!")
PORT=8081 node services/eyeson-worker/node/src/index.js & pids+=("$!")

for endpoint in http://127.0.0.1:8000/healthz http://127.0.0.1:8090/healthz http://127.0.0.1:8080/healthz http://127.0.0.1:8081/healthz; do
  for _ in $(seq 1 60); do
    curl -fsS "$endpoint" >/dev/null && break
    sleep 1
  done
  curl -fsS "$endpoint" >/dev/null
done

python app.py & pids+=("$!")
wait -n "${pids[@]}"
