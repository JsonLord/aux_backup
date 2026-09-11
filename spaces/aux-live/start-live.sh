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
# What the persona sees of a page is decided from the capture rather than from
# the accessibility tree. Unset, the worker keeps the tree-based observation it
# has always used, so this turns perception on rather than being load-bearing.
export PERCEPTION_SERVICE_URL="${PERCEPTION_SERVICE_URL:-http://127.0.0.1:8092}"

# Who drives the browser. The persona director browses as the person the run is
# supposed to be -- through their eyes, stating an expectation before each action,
# held to sounding like them -- and it is the worker's default, so this line
# changes nothing. It is here because its absence is what broke: selection used to
# be `JOURNEY_DIRECTOR === "persona"` against a variable no deployment script set,
# no test asserted and no document mentioned, so every live run silently browsed
# as the competent agent instead and the whole persona path never executed. Set it
# to "pi" to get that agent back deliberately.
export JOURNEY_DIRECTOR="${JOURNEY_DIRECTOR:-persona}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-${BLABLADOR_API_KEY:-}}"
# Deliberately not defaulted to OPENAI_API_KEY any more. The two endpoints are
# now genuinely different services, and sending the primary router's token to
# Blablador is a 401 on every reflection -- which the gate swallows silently,
# so the run looks fine and the persona is simply never held to itself.
export BLABLADOR_API_KEY="${BLABLADOR_API_KEY:-}"
# Its own endpoint now rather than an alias for the primary one: the reflect and
# adherence calls are served here by name, which is the whole reason to name a
# specific small model instead of asking a router to pick.
export BLABLADOR_BASE_URL="${BLABLADOR_BASE_URL:-https://api.helmholtz-blablador.fz-juelich.de/v1}"

# The persona director asks a second, smaller model two things every step:
# whether what happened matched what the persona expected, and whether the action
# it is about to take sounds like this person at all. Both are small, frequent
# jobs, and the router that is best at deciding what a person does next is not
# the one you want doing them -- so they run on Blablador's alias-fast, on its
# own endpoint with its own key, rather than on whatever "auto" resolves to.
# A model, an endpoint and a key are one setting, not three. Naming alias-fast
# without a Blablador token is a 401 on every reflection and every adherence
# check -- which the gate is designed to swallow, so the run would look healthy
# while nothing held the persona to itself. Without the token the second model
# simply follows the acting one, which is where it ran before and is known to
# work.
if [ -n "${JOURNEY_REFLECT_API_KEY:-${BLABLADOR_API_KEY:-}}" ]; then
  export JOURNEY_REFLECT_MODEL="${JOURNEY_REFLECT_MODEL:-alias-fast}"
  export JOURNEY_REFLECT_BASE_URL="${JOURNEY_REFLECT_BASE_URL:-${BLABLADOR_BASE_URL}}"
  export JOURNEY_REFLECT_API_KEY="${JOURNEY_REFLECT_API_KEY:-${BLABLADOR_API_KEY}}"
else
  echo "[start-live] No Blablador token configured; reflection and persona-adherence" \
       "will run on ${OPENAI_MODEL} against the primary endpoint. Set BLABLADOR_API_KEY" \
       "as a Space secret to run them on alias-fast instead."
  export JOURNEY_REFLECT_MODEL="${JOURNEY_REFLECT_MODEL:-${OPENAI_MODEL}}"
  unset JOURNEY_REFLECT_BASE_URL JOURNEY_REFLECT_API_KEY
fi
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
  export AUX_MEMORY_ROOT="/data/control-plane/persona-memory"
  echo "[start-live] Using persistent storage at /data for the control-plane DB and artifacts."
else
  export AUX_MEMORY_ROOT="${AUX_MEMORY_ROOT:-${ARTIFACT_ROOT}/persona-memory}"
  echo "[start-live] No writable /data mount found; using ephemeral in-container storage ($ARTIFACT_ROOT) -- reports will not survive a Space restart."
fi
# Where each persona's bank of what it has learned about itself lives. Unset, the
# bank is in-memory for one run and thrown away -- which is every run starting from
# nothing, so the lessons a run earns never reach the next one and the bank cannot
# do the one thing it is for. A live run confirmed it: `episodes: 0, lessons: [],
# persisted: false` at the start of a run that went on to be judged eight times.
mkdir -p "$AUX_MEMORY_ROOT" 2>/dev/null || true

uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 & pids+=("$!")
uvicorn services.persona_service.main:app --host 127.0.0.1 --port 8090 & pids+=("$!")
uvicorn services.perception_service.main:app --host 127.0.0.1 --port 8092 & pids+=("$!")
node services/journey-worker/node/src/index.js & pids+=("$!")
PORT=8081 node services/eyeson-worker/node/src/index.js & pids+=("$!")

for endpoint in http://127.0.0.1:8000/healthz http://127.0.0.1:8090/healthz http://127.0.0.1:8092/healthz http://127.0.0.1:8080/healthz http://127.0.0.1:8081/healthz; do
  for _ in $(seq 1 60); do
    curl -fsS "$endpoint" >/dev/null && break
    sleep 1
  done
  curl -fsS "$endpoint" >/dev/null
done

python app.py & pids+=("$!")
wait -n "${pids[@]}"
