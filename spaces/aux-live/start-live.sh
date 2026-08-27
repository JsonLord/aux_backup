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
# Blablador aliases without printing any secret value.
export OPENAI_BASE_URL="${OPENAI_COMPATIBLE_ENDPOINT:-${OPENAI_BASE_URL:-https://api.helmholtz-blablador.fz-juelich.de/v1}}"
# "alias-huge" is not a valid Blablador alias (live gateway returns 404). The
# documented aliases are alias-fast, alias-large, alias-code, alias-embeddings,
# alias-reasoning; alias-large is the largest general-purpose model.
export OPENAI_MODEL="${OPENAI_MODEL:-alias-large}"
export JOURNEY_MODEL="${OPENAI_MODEL:-${JOURNEY_MODEL:-alias-large}}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-${BLABLADOR_API_KEY:-}}"
export BLABLADOR_API_KEY="${BLABLADOR_API_KEY:-${OPENAI_API_KEY:-}}"
export BLABLADOR_BASE_URL="${BLABLADOR_BASE_URL:-${OPENAI_BASE_URL}}"
# Bound the OpenAI-compatible completion budget. TinyTroupe 0.7 otherwise requests
# 128000 completion tokens, which the Blablador gateway cannot stream for the large
# aliases and rejects with "502 Proxy Error / Error reading from remote server".
export OPENAI_MAX_COMPLETION_TOKENS="${OPENAI_MAX_COMPLETION_TOKENS:-8192}"
export AGENT_BROWSER_COMMAND="${AGENT_BROWSER_COMMAND:-/home/user/app/spaces/aux-live/agent-browser-container.sh}"

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
