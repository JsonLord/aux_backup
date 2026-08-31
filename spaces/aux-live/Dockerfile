FROM python:3.12-slim

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl ffmpeg git gnupg tini \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 \
    libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-6 libx11-xcb1 \
    libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 \
    libxrandr2 fonts-noto-color-emoji \
    && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 user
WORKDIR /home/user/app

COPY requirements-live.txt ./requirements-live.txt
COPY services/persona_service/requirements.lock ./persona-requirements.lock
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r requirements-live.txt \
    && grep -m1 '^tinytroupe ' persona-requirements.lock > tinytroupe-requirement.txt \
    && pip install --no-cache-dir --retries 10 --timeout 120 --no-deps -r tinytroupe-requirement.txt \
    && python -c "from tinytroupe.factory.tiny_person_factory import TinyPersonFactory; print(TinyPersonFactory)"
RUN python -c "import gradio.components.base as b; p=b.__file__; c=open(p).read(); open(p,'w').write(c.replace('if callable(getattr(self, value))','if value != \"__provides__\" and callable(getattr(self, value))').replace('getattr(self, value)','(getattr(self, value) if value != \"__provides__\" else None)'))" \
    && python -c "import gradio_client.utils as u; p=u.__file__; c=open(p).read(); open(p,'w').write(c.replace('if \"const\" in schema:','if isinstance(schema, dict) and \"const\" in schema:').replace('if \"enum\" in schema:','if isinstance(schema, dict) and \"enum\" in schema:').replace('def _json_schema_to_python_type(schema: Any, defs) -> str:','def _json_schema_to_python_type(schema: Any, defs) -> str:\n    if not isinstance(schema, dict): return \"Any\"'))"

COPY services/journey-worker/node/package.json services/journey-worker/node/package-lock.json \
    ./services/journey-worker/node/
RUN npm ci --omit=dev --prefix services/journey-worker/node \
    && HOME=/home/user npx --prefix services/journey-worker/node agent-browser install \
    && chown -R user:user /home/user

COPY --chown=user:user . .
RUN mkdir -p /home/user/data /home/user/artifacts /home/user/app/rendered_slides_output \
    && chmod +x /home/user/app/spaces/aux-live/agent-browser-container.sh \
    && chown -R user:user /home/user/data /home/user/artifacts /home/user/app

USER user
ENV PATH="/home/user/app/services/journey-worker/node/node_modules/.bin:${PATH}" \
    PYTHONPATH="/home/user/app" \
    GRADIO_SERVER_NAME="0.0.0.0" \
    GRADIO_SERVER_PORT="7860" \
    SYSTEM="spaces" \
    SPACE_ID="Leon4gr45/aux-synthetic-ux-demo" \
    CONTROL_PLANE_URL="http://127.0.0.1:8000" \
    PERSONA_RUNTIME_URL="http://127.0.0.1:8090" \
    JOURNEY_WORKER_URL="http://127.0.0.1:8080" \
    EYESON_WORKER_URL="http://127.0.0.1:8081" \
    PERSONA_GENERATOR="tinytroupe" \
    JOURNEY_ENGINE="journeytest" \
    JOURNEY_PROVIDER="openai" \
    DATABASE_URL="sqlite:////home/user/data/control-plane.sqlite3" \
    PERSONA_DATABASE_PATH="/home/user/data/personas.sqlite3" \
    ARTIFACT_ROOT="/home/user/artifacts" \
    AUTH_MODE="hf_token" \
    PORT="8080" \
    JOURNEY_ARTIFACT_ROOT="/home/user/artifacts/journeys" \
    EYESON_REDESIGN_LIMIT="3" \
    PERSONA_POOL_GITHUB_REPO="JsonLord/PersonaPool"
# PERSONA_POOL_GITHUB_TOKEN (read-only, contents:read on the pool repo above) is
# deliberately not set here -- add it as an HF Space secret so it never lands in
# this Dockerfile or any image layer. Without it, GitHubPersonaPoolClient still
# works unauthenticated against the pool repo's public contents, just subject to
# GitHub's lower unauthenticated rate limit.

EXPOSE 7860
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "./start-live.sh"]
