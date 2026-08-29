import os
import sys

import subprocess
import importlib.util
import re
import time
import json
import concurrent.futures
import threading
import uuid
import shutil
from datetime import datetime
from apps.gradio.api_client import ControlPlaneClient, PersonaRuntimeClient, normalize_personas
from apps.gradio.auth import request_identity, workspaces_from_profile
from apps.gradio.github_backup import GitHubAuthError, push_session_to_github, validate_and_list_repos

import gradio as gr
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import requests
from openai import OpenAI
import logging

# Configuration from environment variables
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_API_TOKEN") or os.environ.get("GITHUB_API_KEY")
# Primary provider is the self-hosted freellmapi router (Tailscale Funnel; see
# spaces/aux-live/start-live.sh). We no longer use Helmholtz Blablador -- the
# OPENAI_* names take priority here; BLABLADOR_* names are read only as a
# legacy fallback (start-live.sh still mirrors them for anything else that
# might read them), never preferred over the current OPENAI_* configuration.
LLM_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("BLABLADOR_API_KEY")
LLM_BASE_URL = (
    os.environ.get("OPENAI_COMPATIBLE_ENDPOINT")
    or os.environ.get("OPENAI_BASE_URL")
    or os.environ.get("BLABLADOR_BASE_URL")
    or "https://debian-devil.tail3f341b.ts.net/v1"
)
# The freellmapi router requires the literal model id "auto" (its router picks the
# best available model); any other id 400s with model_not_found. GET /v1/models on
# the router lists other catalog ids (fusion, kimi-k2.6, ...) if a specific model is
# ever wanted instead of the router's own selection.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "auto")
# Operator break-glass credential. When ADMIN_API_TOKEN is configured (Hugging Face
# Space secret), maintainers can use the app and API before Hugging Face OAuth login
# by presenting `Authorization: Admin <token>`. Requests fall back to this identity
# only when no Hugging Face OAuth session is present.
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN") or None
ADMIN_WORKSPACE_ID = os.environ.get("ADMIN_WORKSPACE_ID", "admin")
# Bound the OpenAI-compatible completion budget for the Gradio task/UI helpers.
# Blablador's proxy returns "502 Proxy Error" when a large alias is asked to stream
# the SDK default (thousands of tokens); an explicit ceiling keeps calls inside the
# gateway read-timeout. Overridable via OPENAI_MAX_COMPLETION_TOKENS.
try:
    OPENAI_MAX_COMPLETION_TOKENS = int(os.environ.get("OPENAI_MAX_COMPLETION_TOKENS", "8192"))
    if OPENAI_MAX_COMPLETION_TOKENS <= 0:
        OPENAI_MAX_COMPLETION_TOKENS = None
except (TypeError, ValueError):
    OPENAI_MAX_COMPLETION_TOKENS = 8192
# Wait between retry attempts in generate_tasks. Was a hardcoded 35s tuned for
# Blablador's proxy errors/rate limiting; against the fast self-hosted router that
# mostly just wastes time when a retry is actually needed. Overridable via
# OPENAI_TASK_RETRY_WAIT_SECONDS.
try:
    TASK_RETRY_WAIT_SECONDS = float(os.environ.get("OPENAI_TASK_RETRY_WAIT_SECONDS", "3"))
    if TASK_RETRY_WAIT_SECONDS < 0:
        TASK_RETRY_WAIT_SECONDS = 3.0
except (TypeError, ValueError):
    TASK_RETRY_WAIT_SECONDS = 3.0
# Live TinyTroupe generation is a real, model-backed call per persona and can take
# up to ~10 minutes even after the speed tuning in services/persona_service --
# capped here to keep a single on-Space run within a reasonable, honestly-labeled
# wait. Overridable via TINYTROUPE_MAX_PERSONAS; not a limit on other generation
# methods (Example Persona, PersonaPool), which don't hit the slow live path.
try:
    TINYTROUPE_MAX_PERSONAS = int(os.environ.get("TINYTROUPE_MAX_PERSONAS", "3"))
    if TINYTROUPE_MAX_PERSONAS <= 0:
        TINYTROUPE_MAX_PERSONAS = 3
except (TypeError, ValueError):
    TINYTROUPE_MAX_PERSONAS = 3
# Rough ceiling used only to pace the progress bar during live TinyTroupe
# generation (see handle_generate); not an enforced timeout.
TINYTROUPE_ESTIMATED_SECONDS = 600
control_plane = ControlPlaneClient()
persona_runtime = PersonaRuntimeClient()


def admin_clients(workspace_id):
    """Build control-plane and persona clients authenticated with the admin token."""
    workspace = workspace_id or ADMIN_WORKSPACE_ID
    authorization = f"Admin {ADMIN_API_TOKEN}"
    return (
        ControlPlaneClient(workspace_id=workspace, user_id="admin", authorization=authorization),
        PersonaRuntimeClient(workspace_id=workspace, user_id="admin", authorization=authorization),
    )


def authenticated_clients(workspace_id, oauth_profile, oauth_token):
    # Fall back to the administrator credential only when Hugging Face OAuth is
    # absent; a signed-in user always authenticates as themselves.
    if (oauth_profile is None or oauth_token is None) and ADMIN_API_TOKEN:
        return admin_clients(workspace_id)
    identity = request_identity(oauth_profile, oauth_token, workspace_id)
    return (
        ControlPlaneClient(workspace_id=identity.workspace_id, user_id=identity.user_id, authorization=identity.authorization),
        PersonaRuntimeClient(workspace_id=identity.workspace_id, user_id=identity.user_id, authorization=identity.authorization),
    )

# Better summaries for example personas
BETTER_SUMMARIES = {
    "Friedrich_Wolf.agent.json": "A meticulous German architect at Awesome Inc. He focuses on standardizing apartment designs, favoring quality over cost, and can be confrontational when challenged.",
    "Lila.agent.json": "A freelance linguist from Paris specializing in NLP. She is highly analytical, creative, and excels at anticipating user behavior from ambiguous data.",
    "Oscar.agent.json": "A German architect at Awesome Inc. who balances professional excellence with a witty sense of humor. He is detail-oriented and dedicated to sustainable design.",
    "Sophie_Lefevre.agent.json": "A creative professional likely focused on the aesthetic and emotional aspects of design and user experience.",
    "Marcos.agent.json": "A technically-minded individual who prioritizes efficiency and robust, logical solutions in the products he uses.",
    "Lisa.agent.json": "A standard user persona interested in efficiency and clear communication.",
    "Jane_Smith.md": "Standard, versatile persona representing a broad range of consumer behaviors and expectations.",
    "John_Doe.md": "Standard, versatile persona representing a broad range of consumer behaviors and expectations."
}

# In-app activity log (rendered in Live Monitoring / status messages)
github_logs = []

# Slide rendering configuration
SLIDES_OUTPUT_ROOT = os.path.join(os.getcwd(), "rendered_slides_output")
os.makedirs(SLIDES_OUTPUT_ROOT, exist_ok=True)

def add_log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    github_logs.append(log_entry)
    print(log_entry)
    return "\n".join(github_logs[-20:])

# Helper for parallel LLM calls
def call_llm_parallel(client, model_names, messages, **kwargs):
    def make_call(model_name):
        try:
            print(f"Parallel call attempting: {model_name}")
            if OPENAI_MAX_COMPLETION_TOKENS and "max_tokens" not in kwargs:
                kwargs.setdefault("max_tokens", OPENAI_MAX_COMPLETION_TOKENS)
            return client.chat.completions.create(
                model=model_name,
                messages=messages,
                **kwargs
            )
        except Exception as e:
            print(f"Parallel call error from {model_name}: {e}")
            return e

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(model_names)) as executor:
        futures = {executor.submit(make_call, m): m for m in model_names}
        # Wait for the first success that isn't a 502/Proxy Error
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if not isinstance(res, Exception):
                print(f"Parallel call success from: {futures[future]}")
                # Try to cancel others (not always possible but good practice)
                return res
            else:
                # If it's an error, check if we should keep waiting or if all failed
                pass

    return Exception("All parallel calls failed")

# OpenAI-compatible client for the self-hosted freellmapi router, used for
# task generation and the UI-adaptation chat.
def get_llm_client():
    if not LLM_API_KEY:
        return None
    return OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL
    )

def _example_persona_dirs():
    """Candidate directories that hold bundled TinyTroupe example agents.

    The offline demo clones the repo to ``external/TinyTroupe``; the live Space
    installs TinyTroupe as a wheel, so also probe the installed package's
    ``examples/agents`` directory. Missing candidates are skipped silently.
    """
    candidates = [
        "external/TinyTroupe/examples/agents/",
        os.path.join(os.getcwd(), "external/TinyTroupe/examples/agents/"),
    ]
    try:
        spec = importlib.util.find_spec("tinytroupe")
        if spec and spec.origin:
            package_root = os.path.dirname(os.path.dirname(spec.origin))
            candidates.append(os.path.join(package_root, "examples", "agents") + os.sep)
            candidates.append(os.path.join(os.path.dirname(spec.origin), "examples", "agents") + os.sep)
    except (ImportError, ValueError):
        pass
    return [path for path in candidates if os.path.isdir(path)]


def _resolve_example_persona(example_file):
    """Return the absolute path of an example agent file, or None if absent."""
    for directory in _example_persona_dirs():
        candidate = os.path.join(directory, example_file)
        if os.path.isfile(candidate):
            return candidate
    return None


def get_example_personas():
    for directory in _example_persona_dirs():
        try:
            files = [f for f in os.listdir(directory) if f.endswith(".json") or f.endswith(".md")]
            if files:
                return sorted(files)
        except OSError as e:
            print(f"Error listing example personas in {directory}: {e}")
    return []

def _read_example_persona_file(example_file):
    """Pure file read of a bundled example persona -- no network call. Returns
    (name, minibio, raw_persona). Safe to call with no authenticated client (e.g.
    at Gradio module-import time for the dropdown preview default)."""
    path = _resolve_example_persona(example_file)
    if not path:
        raise FileNotFoundError(f"Example persona '{example_file}' is not bundled in this deployment.")
    if example_file.endswith(".json"):
        with open(path, "r") as f:
            data = json.load(f)
        name = data.get("name") or data.get("persona", {}).get("name") or "Unknown"
        bio = BETTER_SUMMARIES.get(example_file)
        if not bio:
            bio = data.get("mental_faculties", [{}])[0].get("context") if "mental_faculties" in data else "An example persona."
        # Match the shape TinyTroupeGenerator._serialize_tiny_person produces for
        # live-generated personas ({"name": ..., **TinyPerson.to_dict()}), since the
        # raw example file only has "name" nested under "persona".
        raw_persona = {"name": name, **data}
    else:  # .md
        with open(path, "r") as f:
            content = f.read()
        name = example_file.replace(".md", "").replace("_", " ")
        bio = BETTER_SUMMARIES.get(example_file) or content
        raw_persona = {"name": name, "background": content}
    return name, bio, raw_persona


def load_example_persona(example_file, persona_client=None, compile_behavior=True, seed=1):
    """Load a bundled example persona (e.g. Friedrich_Wolf.agent.json).

    When compile_behavior is True (the default, needed for journey testing --
    profile.behavior is required), compiles a real BehaviorProfile/AbilityProfile
    for it through the same PersonaCompiler live generation uses, instead of a bare
    {name, minibio, persona} dict. This keeps example-persona testing free of live
    TinyTroupe generation latency/cost: recommended default for backend/API testing
    (see docs/aux-space-status-overview.md).

    When compile_behavior is False, returns the bare {name, minibio, persona} dict
    with no network call -- for display-only previews (e.g. the dropdown preview,
    which may run before an authenticated persona_client exists).

    Returns the persona dict, or raises if the example file isn't bundled or fails
    to load.
    """
    name, bio, raw_persona = _read_example_persona_file(example_file)
    if not compile_behavior:
        return {"name": name, "minibio": bio, "persona": raw_persona}
    compiled = (persona_client or persona_runtime).compile(
        raw_persona, scenario=f"Example persona preview: {name}", seed=seed)
    compiled["name"] = name
    compiled["minibio"] = bio
    return compiled


def select_or_create_personas(theme, customer_profile, num_personas, force_method=None, example_file=None, persona_client=None, compile_behavior=True):
    if force_method == "Example Persona" and example_file:
        add_log(f"Loading example persona from {example_file}...")
        try:
            if not compile_behavior:
                # Preview-only: no network call, no distinct identity needed.
                compiled = load_example_persona(example_file, persona_client, compile_behavior=False)
                return [compiled] * int(num_personas)
            # Compile once per requested persona with a distinct seed, so each
            # gets its own id and its own seed-varied behavior/ability sample --
            # requesting N personas from one fixed example must not silently
            # collapse into N references to the exact same persona (breaks
            # cross-persona synthesis, which groups findings by persona id).
            return [load_example_persona(example_file, persona_client, compile_behavior=True, seed=seed)
                    for seed in range(1, int(num_personas) + 1)]
        except Exception as e:
            add_log(f"Failed to load example persona: {e}")

    if force_method == "PersonaPool":
        # Real GitHub-backed pool lookup (docs/persona-pool-plan.md components A/C):
        # a ranged-match query against a pre-generated pool repo (ARTIFACT_ROOT
        # index.json + persona files, read via a read-only "always-connected"
        # PERSONA_POOL_GITHUB_TOKEN service credential -- see services/
        # persona_service/github_pool.py), instead of a live per-request call to
        # an external stand-in Space. Falls back to live TinyTroupe generation for
        # any shortfall (pool unconfigured, empty, or too few close matches),
        # exactly as section 4 point 4 of that plan specifies.
        add_log("Looking up personas from the GitHub-backed persona pool...")
        try:
            result = (persona_client or persona_runtime).pool_lookup(theme, customer_profile, int(num_personas))
        except requests.exceptions.RequestException as e:
            add_log(f"Persona pool lookup failed: {e}")
            result = {"poolConfigured": False, "personas": []}
        personas = result.get("personas", [])
        if not result.get("poolConfigured"):
            add_log("Persona pool is not configured (PERSONA_POOL_GITHUB_REPO unset); generating instead.")
        elif personas:
            add_log(f"Matched {len(personas)} persona(s) from the GitHub pool.")
        if result.get("skipped"):
            add_log(f"Skipped {len(result['skipped'])} pool entr{'y' if len(result['skipped']) == 1 else 'ies'} that failed to fetch/validate.")
        shortfall = int(num_personas) - len(personas)
        if shortfall > 0:
            if personas:
                add_log(f"Pool covered {len(personas)}/{num_personas} requested personas; generating {shortfall} more.")
            personas.extend(generate_personas(theme, customer_profile, shortfall, persona_client))
        return personas[:int(num_personas)]
    elif force_method == "TinyTroupe":
        add_log("Forcing TinyTroupe generation...")
        return (persona_client or persona_runtime).generate(theme, customer_profile, num_personas, scenario=theme)

    client = get_llm_client()
    if not client:
        return generate_personas(theme, customer_profile, num_personas, persona_client)

    # Real local persona pool: every persona this workspace has ever generated
    # or compiled (live TinyTroupe, Example Persona, PersonaPool/DeepPersona) is
    # already durably saved in the persona-runtime's own store (persona_service's
    # generate/compile endpoints call profiles.save(...) themselves) -- no
    # separate "upload to pool" step needed, and no external repo either.
    pool = (persona_client or persona_runtime).list(limit=50)
    if not pool:
        add_log("Local persona pool is empty; generating new personas.")
        return generate_personas(theme, customer_profile, num_personas, persona_client)

    # Ask LLM to judge
    def _pool_summary(p):
        identity = p.get("persona", {})
        name = identity.get("name") or p.get("id", "Persona")
        minibio = (identity.get("occupation") or {}).get("title") if isinstance(identity.get("occupation"), dict) else identity.get("occupation")
        return {"name": name, "minibio": minibio or ""}
    pool_summaries = [{"index": i, **_pool_summary(p)} for i, p in enumerate(pool)]

    prompt = f"""
    You are an expert in user experience research and persona management.
    We need {num_personas} persona(s) for a UX analysis task with the following theme: {theme}
    And target customer profile: {customer_profile}

    Here is a pool of existing personas:
    {json.dumps(pool_summaries, indent=2)}

    For each of the {num_personas} required personas, decide if one from the pool is an appropriate match or if we should create a new one.
    An appropriate match is a persona whose background, interests, and characteristics align well with the target customer profile and theme.

    Return your decision as a JSON object with the following format:
    {{
        "decisions": [
            {{ "action": "use_pool", "pool_index": 0 }},
            {{ "action": "create_new" }},
            ... (up to {num_personas})
        ]
    }}
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=OPENAI_MAX_COMPLETION_TOKENS,
        )
        content = response.choices[0].message.content
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            decisions_json = json.loads(json_match.group())
            decisions = decisions_json.get("decisions", [])
        else:
            print("Could not parse LLM decision, creating new personas.")
            decisions = [{"action": "create_new"}] * num_personas
    except Exception as e:
        print(f"Error getting LLM decision: {e}, creating new personas.")
        decisions = [{"action": "create_new"}] * num_personas

    final_personas = []
    to_create_count = 0
    for d in decisions:
        if d["action"] == "use_pool" and 0 <= d["pool_index"] < len(pool):
            add_log(f"Using persona from local pool: {pool_summaries[d['pool_index']]['name']}")
            final_personas.append(pool[d['pool_index']])
        else:
            to_create_count += 1

    if to_create_count > 0:
        add_log(f"Creating {to_create_count} new personas.")
        # generate_personas() -> persona_client.generate() already durably saves
        # each generated profile server-side; no separate pool-upload step.
        final_personas.extend(generate_personas(theme, customer_profile, to_create_count, persona_client))

    return final_personas

def generate_personas_from_tiny_factory(theme, customer_profile, num_personas):
    """Compatibility wrapper; persona generation belongs to persona-runtime."""
    return persona_runtime.generate(theme, customer_profile, num_personas, scenario=theme)

def generate_personas(theme, customer_profile, num_personas, persona_client=None):
    """Compatibility wrapper for legacy callbacks during tab migration."""
    return (persona_client or persona_runtime).generate(theme, customer_profile, num_personas, scenario=theme)

def generate_tasks(theme, customer_profile, url):
    client = get_llm_client()
    if not client:
        return [f"Task {i+1} for {theme} (OPENAI_API_KEY not set)" for i in range(10)]

    prompt = f"""
    Generate EXACTLY 10 sequential tasks for a user to perform on the website: {url}
    The theme of the analysis is: {theme}.
    The user persona profile is: {customer_profile}.

    The tasks should cover:
    1. Communication
    2. Purchase decisions
    3. Custom Search / Information gathering
    4. Emotional connection to the persona and content/styling

    The tasks must be in sequential order and specific to the website {url}.

    CRITICAL: Skip all internal monologue or thinking process. Return ONLY a JSON object with a "tasks" key containing a list of exactly 10 strings.
    Example: {{"tasks": ["task 1", "task 2", ..., "task 10"]}}
    Do not include any other text in your response.
    """

    models_to_try = [OPENAI_MODEL]

    for attempt in range(5):
        try:
            print(f"Attempt {attempt+1} for task generation...")
            if attempt > 0:
                print(f"Retrying in parallel with {models_to_try}")
                time.sleep(TASK_RETRY_WAIT_SECONDS)
                response = call_llm_parallel(client, models_to_try, [{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            else:
                response = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    max_tokens=OPENAI_MAX_COMPLETION_TOKENS,
                )

            if response and not isinstance(response, Exception):
                content = response.choices[0].message.content
                # Robust extraction
                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    try:
                        tasks_json = json.loads(json_match.group())
                        tasks = tasks_json.get("tasks", [])
                        if tasks and isinstance(tasks, list) and len(tasks) >= 5:
                            return tasks[:10]
                    except:
                        pass

                # Fallback: try to extract lines that look like tasks
                lines = [re.sub(r'^\d+[\.\)]\s*', '', l).strip() for l in content.split('\n') if l.strip()]
                tasks = [l for l in lines if len(l) > 20 and not l.startswith('{') and not l.startswith('`')]
                if len(tasks) >= 5:
                    return tasks[:10]

            print(f"Attempt {attempt+1} failed to yield valid tasks.")
        except Exception as e:
            print(f"Error in attempt {attempt+1}: {e}")

    return [f"Task {i+1} for {theme} (Manual fallback)" for i in range(10)]

def handle_generate(theme, customer_profile, num_personas, method, example_file, url, workspace_id,
                     oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None,
                     progress=gr.Progress()):
    try:
        _, personas_client = authenticated_clients(workspace_id, oauth_profile, oauth_token)
        current_profile = customer_profile
        if method == "Example Persona" and example_file:
            # Fetch example persona info to use as profile context for task generation.
            # Only .minibio is read below, so skip the compile network call here (it
            # still happens once, authenticated, at line ~680 when the persona is
            # actually used for journey testing).
            ex_personas = select_or_create_personas("", "", 1, "Example Persona", example_file, compile_behavior=False)
            if ex_personas:
                current_profile = ex_personas[0].get('minibio', customer_profile)

        progress(0.02, desc="Thinking...")
        yield "Thinking...", None, None, None
        tasks = generate_tasks(theme, current_profile, url)
        tasks_text = "\n".join(tasks) if isinstance(tasks, list) else str(tasks)

        requested = int(num_personas)
        warning = ""
        if method == "TinyTroupe" and requested > TINYTROUPE_MAX_PERSONAS:
            warning = (f" (capped at {TINYTROUPE_MAX_PERSONAS} personas for live generation; "
                       "can take up to ~10 minutes)")
            requested = TINYTROUPE_MAX_PERSONAS
        elif method == "TinyTroupe":
            warning = " (live generation can take up to ~10 minutes)"

        progress(0.15, desc=f"Selecting or creating personas...{warning}")
        yield f"Selecting or creating personas...{warning}", tasks_text, None, tasks

        if method == "TinyTroupe":
            # personas_client.generate() is a single blocking HTTP call with no
            # intermediate progress signal from the persona runtime. Run it in a
            # background thread and poll from here so the progress bar and status
            # text keep moving (paced against TINYTROUPE_ESTIMATED_SECONDS, an
            # estimate only -- not an enforced timeout) instead of sitting frozen
            # for up to ~10 minutes.
            outcome = {}

            def _run_generation():
                try:
                    outcome["personas"] = personas_client.generate(
                        theme, customer_profile, requested, scenario=f"Test {url}")
                except Exception as error:
                    outcome["error"] = error

            worker = threading.Thread(target=_run_generation, daemon=True)
            worker.start()
            started = time.monotonic()
            while worker.is_alive():
                worker.join(timeout=3)
                elapsed = time.monotonic() - started
                fraction = min(0.95, 0.15 + 0.80 * (elapsed / TINYTROUPE_ESTIMATED_SECONDS))
                status = f"Generating personas... ({int(elapsed)}s elapsed){warning}"
                progress(fraction, desc=status)
                yield status, tasks_text, None, tasks
            if "error" in outcome:
                raise outcome["error"]
            personas = outcome["personas"]
        else:
            personas = select_or_create_personas(theme, customer_profile, requested, force_method=method, example_file=example_file, persona_client=personas_client)

        progress(1.0, desc="Generation complete!")
        yield "Generation complete!", tasks_text, personas, tasks
    except Exception as e:
        yield f"Error during generation: {str(e)}", None, None, None


def start_and_monitor_sessions(personas, tasks, url, allow_irreversible_actions, session_id, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
    if not personas or not tasks:
        yield "Error: Personas or Tasks missing. Please generate them first.", "", "", ""
        return
    try:
        session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
        session = session_client.create_session({"name": session_id or "UX analysis",
                                                 "target_url": url, "source": "gradio"})
        persona_artifacts = []
        for profile in personas:
            profile = dict(profile)
            profile.setdefault("id", f"legacy_persona_{uuid.uuid4().hex}")
            artifact = session_client.create_artifact(
                session["session_id"], "persona.profile", profile,
                metadata={"schema_version": "1.0", "persona_id": profile["id"], "immutable_run_snapshot": True},
            )
            persona_artifacts.append(artifact["artifact_id"])
        # journey-worker's safety.js blocks any task whose text matches a
        # destructive-action pattern (purchase, delete account, deploy
        # production, ...) unless browserSafety.allowIrreversibleActions is
        # explicitly set (spec.md section 36: "require explicit configuration
        # for purchases, submissions or irreversible operations"). Off by
        # default; this is the opt-in the UI exposes for it.
        job = session_client.create_job({"session_id": session["session_id"], "type": "combined_test", "input_artifacts": persona_artifacts,
            "metadata": {"persona_artifacts": persona_artifacts, "tasks": tasks, "url": url,
                        "browserSafety": {"allowIrreversibleActions": bool(allow_irreversible_actions)}}})
        yield f"Analysis queued: {job['job_id']}", "", session["session_id"], job["job_id"]
        job = session_client.wait_for_job(job["job_id"])
        if job["status"] != "succeeded":
            yield f"Analysis failed: {job.get('error')}", "", session["session_id"], job["job_id"]
            return
        report = json.loads(session_client.get_artifact_content(job["output_artifacts"][0]))
        # screenshotCrop is a base64 data URI (can be tens of KB per finding) --
        # unreadable and not renderable in a Markdown code block. Show it as a
        # placeholder here and point to the Presentations tab, which renders the
        # actual cropped images inline in the generated ux.presentation HTML.
        for finding in report.get("critical_pain_points", []):
            if finding.get("screenshotCrop"):
                finding["screenshotCrop"] = "(cropped screenshot -- see the Presentations tab for the image)"
        summary = ("Analysis complete. See the **Presentations** tab for a rendered view with screenshots.\n\n"
                   f"```json\n{json.dumps(report, indent=2)}\n```")
        yield "Analysis complete.", summary, session["session_id"], job["job_id"]
    except Exception as exc:
        yield f"Control-plane error: {exc}", "", "", ""

def generate_agents_prompt(selected_solutions_json):
    if not selected_solutions_json:
        return "No solutions selected."
    try:
        selected_solutions = json.loads(selected_solutions_json)
    except:
        return f"Error parsing solutions: {selected_solutions_json}"

    prompt = """# Coding Agent Prompt: Implement UX Solutions

You are an expert Frontend Developer. Your task is to implement the following "Liked" UX solutions into the project.

## Selected Solutions to Implement:
"""
    for sol in selected_solutions:
        prompt += f"\n### {sol['name']}\n{sol['content']}\n"
        
    prompt += """
## Instructions:
1. Review the existing UI components.
2. Replace or enhance them using the provided code snippets.
3. Ensure the implementation is responsive and adheres to the project's design system.
4. Verify accessibility and performance after implementation.
"""
    return prompt

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
# Bookkeeping browser events whose summaries are plumbing rather than something a
# reader would recognise as the persona acting. Mirrors apps/api/executor.py's
# _QUIET_BROWSER_EVENTS (this module must not import the control-plane package).
_QUIET_BROWSER_EVENT_TYPES = {"browser.snapshot", "browser.screenshot", "browser.get_url", "browser.get_title",
                              "browser.console_evidence", "browser.network_evidence",
                              "browser.network_har.start", "browser.network_har.stop"}


def generate_design_agent_brief(session_id, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
    """Design-agent instructions built from this session's SYNTHESIZED findings
    (apps/api/executor.py's cross-persona root-cause aggregation), not
    individually-selected solutions or per-persona citations -- every finding
    here already reflects how many personas hit it and the combined,
    grounded alternatives (see apps/api/executor.py's _synthesize_pain_points)."""
    if not session_id:
        return "Enter a session ID above, then click Generate."
    try:
        session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
        artifacts = [item for item in session_client.list_artifacts(session_id) if item["kind"] == "ux.report"]
        if not artifacts:
            return f"No UX report found for session `{session_id}`. Run an analysis first."
        report = json.loads(session_client.get_artifact_content(artifacts[-1]["artifact_id"]))
    except Exception as e:
        return f"Error loading session report: {e}"

    findings = sorted(report.get("critical_pain_points", []),
                       key=lambda item: _SEVERITY_ORDER.get(item.get("severity"), 4))
    if not findings or findings[0].get("title") == "No pain points detected":
        return (f"# Design agent brief for {report.get('url', 'the tested site')}\n\n"
                "No synthesized UX findings were reported for this session -- nothing to change.")

    lines = [f"# Design agent brief: {report.get('url', 'target site')}",
              "", report.get("executive_summary", ""), "",
              "You are a design agent. The findings below are synthesized across every synthetic "
              "user persona that tested this site (not one person's opinion) and grounded against "
              "real UX/accessibility references where available. For each finding: understand what is "
              "wrong and why, then change the layout/design to address it. Do not invent unrelated "
              "changes.", ""]
    for index, finding in enumerate(findings, start=1):
        severity, affected = finding.get("severity", "medium"), finding.get("affectedPersonas")
        lines.append(f"## {index}. [{severity.upper()}] {finding.get('title', 'Finding')}")
        if affected:
            lines.append(f"_Observed across {affected} tested persona(s)._")
        if finding.get("summary"):
            lines.append(f"\n**What's wrong:** {finding['summary']}")
        alternatives = finding.get("alternatives") or ([{"proposedChange": finding["recommendation"]}]
                                                         if finding.get("recommendation") else [])
        if alternatives:
            lines.append("\n**What to change:**")
            for alternative in alternatives:
                change = alternative.get("proposedChange", "")
                rationale = f" ({alternative['rationale']})" if alternative.get("rationale") else ""
                effort = f" [{alternative['effort']} effort]" if alternative.get("effort") else ""
                lines.append(f"- {change}{rationale}{effort}")
        lines.append("")
    return "\n".join(lines)


def generate_full_ui_call(session_id, selected_solutions_json, url, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
    if not session_id:
        return "Error: Job ID missing. Start an analysis first."
    try:
        session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
        parent = session_client.get_job(session_id)
        job = session_client.run_job("ui_adaptation", {"title": "UX solution prototype", "request": generate_agents_prompt(selected_solutions_json), "url": url}, session_id=parent["session_id"])
        if job["status"] != "succeeded":
            return f"❌ Prototype generation failed: {job.get('error')}"
        html = session_client.get_artifact_content(job["output_artifacts"][0])
        return f'<iframe srcdoc="{html.replace(chr(34), "&quot;")}" width="100%" height="800" frameborder="0"></iframe>'
    except Exception as exc:
        add_log(f"Control-plane error: {exc}")
        return f"❌ Error: {exc}"

def poll_for_generated_ui(session_id, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
    if not session_id:
        return "Start an analysis or adaptation job first."
    try:
        session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
        job = session_client.get_job(session_id)
        artifacts = session_client.list_artifacts(job["session_id"])
        candidates = [item for item in artifacts if item["kind"] == "ui.prototype"]
        if not candidates:
            return "No generated UI artifact is stored for this session yet."
        html = session_client.get_artifact_content(candidates[-1]["artifact_id"])
        return f'<iframe srcdoc="{html.replace(chr(34), "&quot;")}" width="100%" height="800px" frameborder="0"></iframe>'
    except Exception as error:
        return f"Unable to load the saved UI artifact: {error}"

def llm_chat_adaptation(message, history, jules_uuid, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
    if not jules_uuid:
        return history + [("System", "Error: Analysis job ID missing.")], ""
    try:
        session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
        parent = session_client.get_job(jules_uuid)
        # Revise the most recently generated prototype rather than regenerating
        # from scratch each turn, so the chat is actually iterative.
        prototypes = [a for a in session_client.list_artifacts(parent["session_id"]) if a["kind"] == "ui.prototype"]
        previous_html = session_client.get_artifact_content(prototypes[-1]["artifact_id"]) if prototypes else None
        job = session_client.run_job("ui_adaptation",
            {"title": "Interactive UI adaptation", "request": message, "previous_html": previous_html},
            session_id=parent["session_id"])
        if job["status"] != "succeeded":
            raise RuntimeError(job.get("error"))
        agent_msg = f"Adaptation completed as job {job['job_id']}. The responsive prototype is stored as artifact {job['output_artifacts'][0]}."

        history.append((message, agent_msg))
        return history, ""
    except Exception as e:
        history.append((message, f"Error: {str(e)}"))
        return history, ""

# Gradio UI
with gr.Blocks(title="UX Analysis Orchestrator") as demo:
    gr.Markdown("# UX Analysis Orchestrator")
    with gr.Row():
        login_button = gr.LoginButton()
        # allow_custom_value: Gradio's Dropdown validates a submitted value against
        # this component's *server-side* choices list, which is a single shared
        # object across every concurrent session on this deployment (not
        # per-browser-session state) -- another user's or an earlier event's most
        # recent gr.update(choices=...) can leave it stale/empty for everyone else,
        # producing "Value: hf:user:... is not in the list of choices: []" even for
        # a real signed-in user with a real workspace. The real authorization check
        # happens downstream in authenticated_clients()/request_identity() against
        # the actual OAuth token, so this dropdown only needs to offer choices, not
        # gate them.
        workspace_selector = gr.Dropdown(label="Workspace", choices=[], interactive=True, allow_custom_value=True)
    login_status = gr.Markdown("Sign in with Hugging Face to load your personal and organization workspaces.")

    def load_hf_workspaces(profile: gr.OAuthProfile | None):
        workspaces = workspaces_from_profile(dict(profile) if profile else None)
        if not workspaces:
            return gr.update(choices=[], value=None), "🔒 Sign in with Hugging Face to continue."
        choices = [(f"{item['name']} ({item['role']})", item["id"]) for item in workspaces]
        return gr.update(choices=choices, value=choices[0][1]), f"Signed in as **{profile.username}**. Workspace access is revalidated by the control plane on every request."

    demo.load(fn=load_hf_workspaces, outputs=[workspace_selector, login_status])

    def validate_workspace(workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
        if (not oauth_profile or not oauth_token) and not ADMIN_API_TOKEN:
            return "🔒 Sign in with Hugging Face and select a workspace to continue."
        try:
            session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
            identity = session_client.me()
        except requests.HTTPError as error:
            status = getattr(error.response, "status_code", None)
            if status in (401, 403):
                return "🔒 Sign in with Hugging Face to validate workspace access."
            return f"⚠️ Workspace validation failed ({status or 'error'})."
        except requests.RequestException as error:
            return f"⚠️ Workspace validation is temporarily unavailable: {error}."
        selected = next(item for item in identity["workspaces"] if item["id"] == identity["selected_workspace_id"])
        return f"Signed in as **{identity['user'].get('username') or identity['user']['id']}** · workspace **{selected['name']}** · role `{selected['role']}`."

    workspace_selector.change(fn=validate_workspace, inputs=[workspace_selector], outputs=[login_status])

    active_session_state = gr.State("")
    active_jules_uuid_state = gr.State("")
    last_generated_tasks_state = gr.State([])
    session_id_sync_list = []
    all_solutions_state = gr.State([])
    selected_solutions_json_state = gr.State("[]")

    with gr.Tabs():
        with gr.Tab("Analysis Orchestrator"):
            gr.Markdown("### Start New Analysis Sessions")
            with gr.Row():
                with gr.Column():
                    theme_input = gr.Textbox(label="Theme", placeholder="e.g., Communication, Purchase decisions, Information gathering")
                    profile_input = gr.Textbox(label="Customer Profile Description", placeholder="Describe the target customer...")
                    num_personas_input = gr.Number(label="Number of Personas", value=1, precision=0, minimum=1, maximum=TINYTROUPE_MAX_PERSONAS)
                    url_input = gr.Textbox(label="Target URL", value="https://example.com")
                    allow_irreversible_actions_input = gr.Checkbox(
                        label="Allow potentially irreversible actions (purchases, submissions, deletions, deploys)",
                        value=False,
                        info="Off by default (spec.md section 36): the journey worker blocks any task whose text "
                             "mentions a destructive action (e.g. \"place order\", \"delete account\", \"deploy "
                             "production\") against the real target URL unless explicitly allowed here.")
                    persona_method = gr.Radio(["Example Persona", "TinyTroupe", "PersonaPool"], label="Persona Generation Method", value="TinyTroupe")
                    tinytroupe_warning = gr.Markdown(
                        f"⏳ **Live TinyTroupe generation is capped at {TINYTROUPE_MAX_PERSONAS} personas per run "
                        "and can take up to ~10 minutes** (each persona is a real model-generated profile). "
                        "For more personas, try **PersonaPool** first -- it matches against a pre-generated "
                        "GitHub-backed pool and only falls back to live generation for any shortfall.",
                        visible=True,
                    )

                    with gr.Column(visible=False) as example_persona_col:
                        gr.Markdown("#### Pre-configured Personas")
                        
                        def update_persona_preview(file):
                            if not file: return ""
                            # Preview only needs name/minibio/persona for display, not a
                            # compiled BehaviorProfile -- skip the persona-runtime network
                            # call so this works with no authenticated client (this can run
                            # at Gradio module-import time, before any request identity
                            # exists) and doesn't cost a compile call just to render text.
                            personas = select_or_create_personas("", "", 1, "Example Persona", file, compile_behavior=False)
                            if personas:
                                p = personas[0]
                                name = p.get('name', 'Unknown')
                                bio = p.get('minibio', '')
                                
                                # Better summary logic
                                summary = f"### Persona: {name}\n"
                                
                                if isinstance(p.get('persona'), dict):
                                    pd = p['persona']
                                    age = pd.get('age', pd.get('persona', {}).get('age', 'N/A'))
                                    occ = pd.get('occupation', {}).get('title', pd.get('persona', {}).get('occupation', {}).get('title', 'N/A'))
                                    summary += f"**Age**: {age} | **Occupation**: {occ}\n\n"
                                
                                summary += f"**Summary**: {bio}"
                                return summary
                            return "_Example persona is not bundled in this deployment._"
                        
                        example_personas = get_example_personas()
                        initial_persona = example_personas[0] if example_personas else None
                        example_persona_select = gr.Dropdown(
                            label="Select Example Persona", 
                            choices=example_personas,
                            value=initial_persona
                        )
                        example_persona_preview = gr.Markdown(
                            label="Persona Preview", 
                            value=update_persona_preview(initial_persona) if initial_persona else ""
                        )
                        
                        example_persona_select.change(fn=update_persona_preview, inputs=[example_persona_select], outputs=[example_persona_preview])

                    def update_method_visibility(method, current_count):
                        is_tinytroupe = method == "TinyTroupe"
                        capped_count = min(int(current_count or 1), TINYTROUPE_MAX_PERSONAS) if is_tinytroupe else current_count
                        return (
                            gr.update(visible=(method == "Example Persona")),
                            gr.update(visible=is_tinytroupe),
                            gr.update(maximum=TINYTROUPE_MAX_PERSONAS if is_tinytroupe else None, value=capped_count),
                        )

                    persona_method.change(
                        fn=update_method_visibility,
                        inputs=[persona_method, num_personas_input],
                        outputs=[example_persona_col, tinytroupe_warning, num_personas_input],
                    )

                    generate_btn = gr.Button("Generate Personas & Tasks")

                with gr.Column():
                    status_output = gr.Textbox(label="Status", interactive=False)
                    with gr.Row():
                        task_list_display = gr.TextArea(label="Tasks", lines=10, interactive=True, scale=4)
                        with gr.Column(min_width=40, scale=1):
                            save_tasks_btn = gr.Button("✅")
                            cancel_tasks_btn = gr.Button("❌")
                    
                    persona_display = gr.JSON(label="Personas")

                    def save_tasks(tasks_text):
                        tasks = [t.strip() for t in tasks_text.split("\n") if t.strip()]
                        return tasks, "Tasks saved."

                    def cancel_tasks(last_tasks):
                        return "\n".join(last_tasks), "Changes reverted."

                    save_tasks_btn.click(fn=save_tasks, inputs=[task_list_display], outputs=[last_generated_tasks_state, status_output])
                    cancel_tasks_btn.click(fn=cancel_tasks, inputs=[last_generated_tasks_state], outputs=[task_list_display, status_output])

            start_session_btn = gr.Button("Start Analysis Session", variant="primary")
            session_id_orch = gr.Textbox(label="Session name", interactive=True, placeholder="Optional label for this workspace session...")
            session_id_sync_list.append(session_id_orch)
            report_output = gr.Markdown(label="Active Session Reports")

        with gr.Tab("Persona Studio"):
            gr.Markdown("## Persona Studio\nInspect identity, functional restrictions, behavioral characteristics, and generation provenance. Changes are explicit and persisted through the persona runtime.")
            with gr.Row():
                persona_index = gr.Dropdown(label="Persona", choices=[], interactive=True, allow_custom_value=True)
                refresh_personas_btn = gr.Button("Refresh generated personas")
            with gr.Row():
                studio_example_persona_select = gr.Dropdown(
                    label="Bundled example persona", choices=get_example_personas(),
                    value=(get_example_personas()[0] if get_example_personas() else None),
                    interactive=True)
                load_example_into_studio_btn = gr.Button("Load into Studio", variant="secondary")
            persona_view = gr.JSON(label="Complete synthetic-user profile")
            persona_editor = gr.Code(label="Manual JSON editor", language="json", interactive=True, lines=24)
            with gr.Accordion("Behavior characteristics (0–1)", open=True):
                behavior_sliders = {}
                for trait in ["patience", "persistence", "irritability", "angerReactivity", "angerRecovery", "impulsivity", "ambiguityTolerance", "failureTolerance", "repeatFailureTolerance", "selfEfficacy", "digitalConfidence", "helpSeeking", "exploration", "verificationTendency", "riskTolerance"]:
                    behavior_sliders[trait] = gr.Slider(0, 1, value=.5, step=.01, label=trait)
            with gr.Accordion("Functional restrictions and abilities", open=False):
                color_vision = gr.Dropdown(["typical", "protanopia", "deuteranopia", "tritanopia", "custom"], value="typical", label="Color vision")
                visual_acuity = gr.Slider(0, 1, value=1, step=.01, label="Visual acuity")
                contrast_sensitivity = gr.Slider(0, 1, value=1, step=.01, label="Contrast sensitivity")
                pointer_precision = gr.Slider(0, 1, value=.9, step=.01, label="Pointer precision")
                processing_speed = gr.Slider(0, 1, value=.8, step=.01, label="Processing speed")
                working_memory = gr.Slider(1, 12, value=5, step=1, label="Working-memory items")
                reading_speed = gr.Slider(60, 500, value=220, step=5, label="Reading speed (words/minute)")
            with gr.Row():
                apply_tweaks_btn = gr.Button("Apply tweak controls", variant="secondary")
                save_persona_btn = gr.Button("Save manual profile", variant="primary")
            persona_studio_status = gr.Markdown()

        def format_ux_report(content_json: str) -> str:
            """Render a ux.report as the usability review it is, rather than the raw
            JSON dump this tab previously showed: findings stated as issue -> root
            cause -> recommendation, each with the persona reasoning that produced
            it, then what to fix first and what to preserve."""
            try:
                report = json.loads(content_json)
            except (json.JSONDecodeError, TypeError):
                return "_Could not parse this artifact as JSON._"
            if not isinstance(report, dict) or "critical_pain_points" not in report:
                return f"```json\n{content_json[:4000]}\n```"
            observed = (report.get("evidence_language") or "") == "observed"
            lines = [f"# Usability review — {report.get('url', 'target site')}",
                     f"_{report.get('executive_summary') or ''}_", ""]
            impact = report.get("impact_analysis") or {}
            if impact.get("priorityOrder"):
                lines.append("## What to fix first")
                for position, entry in enumerate(impact["priorityOrder"], start=1):
                    reach = f" · {entry['affectedPersonas']} persona(s)" if entry.get("affectedPersonas") else ""
                    lines.append(f"{position}. **{entry.get('title', '')}** — {entry.get('severity', '')}{reach}")
                lines.append("")
            findings = [item for item in report.get("critical_pain_points", [])
                        if item.get("title") != "No pain points detected"]
            if findings:
                lines.append(f"## {'Observed' if observed else 'Predicted'} user issues")
                for index, item in enumerate(findings, start=1):
                    severity = str(item.get("severity", "")).upper()
                    lines.append(f"\n### 02.{index} {item.get('title', 'Finding')}  \n"
                                 f"`{severity}` · {item.get('category', 'usability')}"
                                 + (f" · reproduced by {item['affectedPersonas']} persona(s)"
                                    if item.get("affectedPersonas") else ""))
                    lines.append(f"\n**{'Observed' if observed else 'Predicted'} user issue** — "
                                 f"{item.get('summary') or item.get('evidence') or ''}")
                    root_cause = item.get("rootCause") or item.get("mechanism")
                    if root_cause:
                        lines.append(f"\n**Root cause analysis** — {root_cause}")
                    alternatives = item.get("alternatives") or ([{"proposedChange": item["recommendation"]}]
                                                                 if item.get("recommendation") else [])
                    changes = [alt.get("proposedChange") for alt in alternatives if alt.get("proposedChange")]
                    if changes:
                        lines.append("\n**Recommendations: design solutions**")
                        lines.extend(f"- {change}" for change in changes)
                    for evidence in (item.get("personaEvidence") or [])[:2]:
                        lines.append(f"\n> 💭 {str(evidence.get('quote', ''))[:400]}\n>\n"
                                     f"> — _{evidence.get('personaName') or 'Synthetic user'}_")
                    references = (item.get("grounding") or {}).get("references") or []
                    if references:
                        grounded = "; ".join(f"{ref.get('source', '')} — {ref.get('principle') or ref.get('title') or ''}"
                                             for ref in references)
                        lines.append(f"\n_Grounded in: {grounded}_")
            preserve = report.get("elements_to_preserve") or []
            if preserve:
                lines.append("\n## Elements to preserve")
                lines.append("_Design decisions that are working and should survive a redesign._\n")
                for item in preserve:
                    seen = (f" _(noted by {item['observedByPersonas']} persona(s))_"
                            if item.get("observedByPersonas") else "")
                    lines.append(f"- **{item.get('title', '')}**{seen} — {item.get('description', '')}")
            if report.get("limitations"):
                lines.append("\n## Limitations")
                lines.extend(f"- {limitation}" for limitation in report["limitations"])
            return "\n".join(lines)

        def format_persona_thought_log(content_json: str) -> str:
            """Render a journey.log or persona.profile artifact as readable
            Markdown instead of a wall of raw JSON -- persona identity, the
            verdict, and the real per-action timeline the director recorded
            (services/journey-worker's timelineToEvents), not just field dumps."""
            try:
                data = json.loads(content_json)
            except (json.JSONDecodeError, TypeError):
                return "_Could not parse this artifact as JSON._"
            if isinstance(data, dict) and isinstance(data.get("runs"), list):
                sections = []
                for run in data["runs"]:
                    persona = (run.get("simulationProfile") or {}).get("persona", {})
                    name = persona.get("name") or run.get("profileId") or run.get("testerProfileId") or "Persona"
                    verdict = run.get("verdict") or {}
                    status_emoji = {"passed": "✅", "failed": "❌", "blocked": "🚫", "inconclusive": "❓"}.get(verdict.get("status"), "•")
                    lines = [f"## {status_emoji} {name} — run `{run.get('runId', '?')}`",
                              f"**Verdict:** {verdict.get('status', 'unknown')} ({verdict.get('confidence', 'n/a')} confidence)",
                              f"\n{verdict.get('summary', '_No summary recorded._')}\n"]
                    timeline = run.get("timeline") or []
                    if timeline:
                        lines.append("**What happened, in the persona's own words:**\n")
                        for event in timeline:
                            event_type, event_data = event.get("type", ""), event.get("data") or {}
                            elapsed = event.get("elapsedMs")
                            when = f" _(+{elapsed / 1000:.1f}s)_" if isinstance(elapsed, (int, float)) else ""
                            # journeytest-core records each assistant turn as
                            # agent.message.end, whose `summary` is the fixed literal
                            # "Assistant message ended" -- the model's actual reasoning
                            # lives in data.text. Rendering `summary` alone (as this
                            # did) showed none of the thinking the tab exists for.
                            if event_type == "agent.message.end" and str(event_data.get("text") or "").strip():
                                thought = str(event_data["text"]).strip()
                                lines.append(f"> 💭 {thought}\n>\n> — _thinking{when}_\n")
                            elif event_type == "agent.message.error" and event_data.get("errorMessage"):
                                lines.append(f"- ⚠️ **Model error:** {event_data['errorMessage']}{when}")
                            elif event_type.startswith("browser.") and event_type not in _QUIET_BROWSER_EVENT_TYPES:
                                summary = event.get("summary") or event_type
                                lines.append(f"- 🖱️ {summary}{when}")
                            elif event_type in {"journey.started", "journey.completed", "journey.verdict"}:
                                lines.append(f"- **{event.get('summary') or event_type}**{when}")
                    for bucket, label in (("blockers", "🚫 Blockers"), ("uxFindings", "⚠️ UX findings")):
                        items = verdict.get(bucket) or []
                        if items:
                            lines.append(f"\n**{label}:**")
                            lines.extend(f"- **{item.get('title', 'Finding')}**: {item.get('description', '')}" for item in items)
                    sections.append("\n".join(lines))
                return "\n\n---\n\n".join(sections) if sections else "_No runs recorded in this log._"
            if isinstance(data, dict) and ("behavior" in data or "abilities" in data):
                persona = data.get("persona", {})
                name = persona.get("name") or data.get("id", "Persona")
                behavior, abilities = data.get("behavior") or {}, data.get("abilities") or {}
                lines = [f"## {name}", f"**Source:** {data.get('source', 'unknown')}  ·  **ID:** `{data.get('id', '?')}`"]
                if behavior:
                    top_traits = sorted(behavior.items(), key=lambda item: -item[1] if isinstance(item[1], (int, float)) else 0)[:5]
                    lines.append("\n**Notable behavior traits:** " + ", ".join(
                        f"{trait} {value:.2f}" for trait, value in top_traits if isinstance(value, (int, float))))
                vision = (abilities.get("vision") or {})
                if vision:
                    lines.append(f"**Vision:** {vision.get('colorVision', 'typical')}, acuity {vision.get('acuity', 1):.2f}")
                return "\n".join(lines)
            return f"```json\n{json.dumps(data, indent=2)[:4000]}\n```"

        def workspace_session_choices(workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
            session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
            sessions = session_client.list_sessions()
            choices = []
            for session in sessions:
                metadata = session.get("metadata") or {}
                label = metadata.get("name") or metadata.get("target_url") or session["session_id"]
                choices.append((f"{label} · {session['session_id']}", session["session_id"]))
            return gr.update(choices=choices, value=choices[0][1] if choices else None), f"Loaded {len(choices)} workspace sessions."

        def workspace_artifact_choices(session_id, kinds, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
            if not session_id:
                return gr.update(choices=[], value=None)
            session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
            artifacts = [item for item in session_client.list_artifacts(session_id) if item["kind"] in kinds]
            choices = [(item.get("metadata", {}).get("download_name") or f"{item['kind']} · {item['artifact_id']}", item["artifact_id"]) for item in artifacts]
            return gr.update(choices=choices, value=choices[0][1] if choices else None)

        def load_workspace_artifact(session_id, artifact_id, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
            if not session_id or not artifact_id:
                return "Select a saved artifact.", None
            session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
            artifact = next(item for item in session_client.list_artifacts(session_id) if item["artifact_id"] == artifact_id)
            return session_client.get_artifact_content(artifact_id), session_client.download_artifact(artifact)

        def presentation_choices(session_id, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
            return workspace_artifact_choices(session_id, {"ux.presentation"}, workspace_id, oauth_profile, oauth_token)

        def slides_choices(session_id, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
            return workspace_artifact_choices(session_id, {"ux.slides"}, workspace_id, oauth_profile, oauth_token)

        def report_choices(session_id, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
            return workspace_artifact_choices(session_id, {"ux.report"}, workspace_id, oauth_profile, oauth_token)

        def log_choices(session_id, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
            return workspace_artifact_choices(session_id, {"journey.log", "persona.profile"}, workspace_id, oauth_profile, oauth_token)

        def evidence_choices(session_id, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
            return workspace_artifact_choices(session_id, {"browser.screenshot", "browser.snapshot", "browser.video", "ux.evidence", "ui.prototype"}, workspace_id, oauth_profile, oauth_token)

        with gr.Tab("Presentations"):
            gr.Markdown("### Saved workspace presentations\nPresentations are generated from completed jobs and stored in the selected user workspace.")
            with gr.Row():
                presentation_session = gr.Dropdown(label="Workspace session", choices=[], interactive=True, allow_custom_value=True)
                presentation_refresh = gr.Button("Refresh sessions")
            presentation_status = gr.Markdown()
            with gr.Row():
                presentation_artifact = gr.Dropdown(label="Presentation", choices=[], interactive=True, allow_custom_value=True)
                presentation_load = gr.Button("Load presentation", variant="primary")
                presentation_download = gr.DownloadButton("Download presentation")
            presentation_view = gr.HTML(label="Presentation")
            presentation_refresh.click(workspace_session_choices, [workspace_selector], [presentation_session, presentation_status], api_name="list_presentation_sessions")
            presentation_session.change(presentation_choices, [presentation_session, workspace_selector], [presentation_artifact], api_name="list_session_presentations")
            presentation_load.click(load_workspace_artifact, [presentation_session, presentation_artifact, workspace_selector], [presentation_view, presentation_download], api_name="load_session_presentation")

            gr.Markdown("### Slide deck\nA navigable slide per synthesized finding (arrow keys or click to advance) -- "
                        "generated locally alongside the presentation, no external tool or repository involved.")
            with gr.Row():
                slides_session = gr.Dropdown(label="Workspace session", choices=[], interactive=True, allow_custom_value=True)
                slides_refresh = gr.Button("Refresh sessions")
            slides_status = gr.Markdown()
            with gr.Row():
                slides_artifact = gr.Dropdown(label="Slide deck", choices=[], interactive=True, allow_custom_value=True)
                slides_load = gr.Button("Load slides", variant="primary")
                slides_download = gr.DownloadButton("Download slides")
            slides_view = gr.HTML(label="Slides")

            def load_and_frame_slides(session_id, artifact_id, workspace_id,
                                       oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
                content, download = load_workspace_artifact(session_id, artifact_id, workspace_id, oauth_profile, oauth_token)
                if not artifact_id:
                    return content, download
                # gr.HTML injects its value via innerHTML, which silently does not
                # execute <script> tags -- the slide deck's own keyboard/click
                # navigation needs a real document context to run in, so embed it
                # in an iframe (the same srcdoc pattern already used for the
                # generated UI prototype elsewhere in this file) instead of
                # rendering the raw HTML directly.
                framed = f'<iframe srcdoc="{content.replace(chr(34), "&quot;")}" width="100%" height="600" frameborder="0"></iframe>'
                return framed, download

            slides_refresh.click(workspace_session_choices, [workspace_selector], [slides_session, slides_status], api_name="list_slides_sessions")
            slides_session.change(slides_choices, [slides_session, workspace_selector], [slides_artifact], api_name="list_session_slides")
            slides_load.click(load_and_frame_slides, [slides_session, slides_artifact, workspace_selector], [slides_view, slides_download], api_name="load_session_slides")

        with gr.Tab("Report Viewer"):
            gr.Markdown("### Saved UX reports\nReports are tenant-owned control-plane artifacts; no GitHub branch or token is used.")
            with gr.Row():
                report_session = gr.Dropdown(label="Workspace session", choices=[], interactive=True, allow_custom_value=True)
                report_refresh = gr.Button("Refresh sessions")
            report_status = gr.Markdown()
            with gr.Row():
                report_artifact = gr.Dropdown(label="Report", choices=[], interactive=True, allow_custom_value=True)
                report_load = gr.Button("Load report", variant="primary")
                report_download = gr.DownloadButton("Download report")
            report_summary = gr.Markdown(label="Report")
            with gr.Accordion("Raw JSON", open=False):
                rv_report_viewer = gr.Code(label="Report content", language="json", lines=28)

            def load_and_format_report(session_id, artifact_id, workspace_id,
                                        oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
                content, download = load_workspace_artifact(session_id, artifact_id, workspace_id, oauth_profile, oauth_token)
                if not artifact_id:
                    return content, "", download
                return format_ux_report(content), content, download

            report_refresh.click(workspace_session_choices, [workspace_selector], [report_session, report_status], api_name="list_report_sessions")
            report_session.change(report_choices, [report_session, workspace_selector], [report_artifact], api_name="list_session_reports")
            report_load.click(load_and_format_report, [report_session, report_artifact, workspace_selector],
                              [report_summary, rv_report_viewer, report_download], api_name="load_session_report")

        with gr.Tab("Persona Thought Logs"):
            gr.Markdown("### Persisted journey and persona logs")
            with gr.Row():
                log_session = gr.Dropdown(label="Workspace session", choices=[], interactive=True, allow_custom_value=True)
                log_refresh = gr.Button("Refresh sessions")
            log_status = gr.Markdown()
            with gr.Row():
                log_artifact = gr.Dropdown(label="Journey log", choices=[], interactive=True, allow_custom_value=True)
                log_load = gr.Button("Load log", variant="primary")
                log_download = gr.DownloadButton("Download log")
            log_summary = gr.Markdown(label="Persona thoughts")
            with gr.Accordion("Raw JSON", open=False):
                log_viewer = gr.Code(label="Journey events and persona snapshots", language="json", lines=28)

            def load_and_format_log(session_id, artifact_id, workspace_id,
                                     oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
                content, download = load_workspace_artifact(session_id, artifact_id, workspace_id, oauth_profile, oauth_token)
                if not artifact_id:
                    return content, "", download
                return format_persona_thought_log(content), content, download

            log_refresh.click(workspace_session_choices, [workspace_selector], [log_session, log_status], api_name="list_log_sessions")
            log_session.change(log_choices, [log_session, workspace_selector], [log_artifact], api_name="list_session_logs")
            log_load.click(load_and_format_log, [log_session, log_artifact, workspace_selector], [log_summary, log_viewer, log_download], api_name="load_session_log")

        with gr.Tab("Evidence Artifacts"):
            gr.Markdown("### Saved browser and UX evidence\nSelect any evidence artifact persisted for this workspace session.")
            with gr.Row():
                evidence_session = gr.Dropdown(label="Workspace session", choices=[], interactive=True, allow_custom_value=True)
                evidence_refresh = gr.Button("Refresh sessions")
            evidence_status = gr.Markdown()
            with gr.Row():
                evidence_artifact = gr.Dropdown(label="Evidence artifact", choices=[], interactive=True, allow_custom_value=True)
                evidence_load = gr.Button("Load evidence", variant="primary")
                evidence_download = gr.DownloadButton("Download evidence")
            evidence_viewer = gr.Code(label="Evidence content", lines=24)
            evidence_refresh.click(workspace_session_choices, [workspace_selector], [evidence_session, evidence_status], api_name="list_evidence_sessions")
            evidence_session.change(evidence_choices, [evidence_session, workspace_selector], [evidence_artifact], api_name="list_session_evidence")
            evidence_load.click(load_workspace_artifact, [evidence_session, evidence_artifact, workspace_selector], [evidence_viewer, evidence_download], api_name="load_session_evidence")

        with gr.Tab("GitHub Backup"):
            gr.Markdown("### Back up workspace session artifacts to your own GitHub repo\n"
                       "Bring your own [fine-grained personal access token](https://github.com/settings/tokens?type=beta) "
                       "with **Contents: Read and write** on the repo you choose. Your token is used live for each "
                       "sync only -- it is **never stored** on the server, so you'll need to re-enter it after a page reload.")
            with gr.Row():
                github_pat_input = gr.Textbox(label="GitHub Personal Access Token", type="password", placeholder="github_pat_... or ghp_...")
                github_connect_btn = gr.Button("Connect", variant="primary")
            github_connect_status = gr.Markdown()
            github_repo_select = gr.Dropdown(label="Repository", choices=[], interactive=True)
            github_pat_state = gr.State("")
            with gr.Row():
                github_backup_session = gr.Dropdown(label="Workspace session", choices=[], interactive=True, allow_custom_value=True)
                github_backup_refresh = gr.Button("Refresh sessions")
            github_sync_btn = gr.Button("Sync session to GitHub", variant="primary")
            github_sync_status = gr.Markdown()

            def connect_github(pat):
                try:
                    username, repos = validate_and_list_repos(pat)
                except GitHubAuthError as e:
                    return gr.update(choices=[], value=None), f"Connection failed: {e}", ""
                except requests.exceptions.RequestException as e:
                    return gr.update(choices=[], value=None), f"GitHub request failed: {e}", ""
                if not repos:
                    return gr.update(choices=[], value=None), f"Connected as **{username}**, but no repos with push access were found.", pat
                return gr.update(choices=repos, value=repos[0]), f"Connected as **{username}** -- {len(repos)} repo(s) with push access.", pat

            github_connect_btn.click(connect_github, [github_pat_input], [github_repo_select, github_connect_status, github_pat_state])
            github_backup_refresh.click(workspace_session_choices, [workspace_selector], [github_backup_session, github_connect_status], api_name="list_github_backup_sessions")

            def sync_session_to_github(pat, repo, session_id, workspace_id,
                                       oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
                if not pat:
                    return "Connect to GitHub first."
                if not repo:
                    return "Choose a repository first."
                if not session_id:
                    return "Choose a workspace session first."
                session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
                result = push_session_to_github(pat, repo, session_id, session_client)
                lines = [f"Pushed {len(result['pushed'])} file(s) to `{repo}`."]
                lines.extend(f"- `{path}`" for path in result["pushed"])
                if result["errors"]:
                    lines.append("**Errors:**")
                    lines.extend(f"- {error}" for error in result["errors"])
                if not result["pushed"] and not result["errors"]:
                    lines.append("No backupable artifacts (ux.report/ux.presentation/ux.slides/journey.log/persona.profile) found on this session yet.")
                return "\n".join(lines)

            github_sync_btn.click(sync_session_to_github,
                                  [github_pat_state, github_repo_select, github_backup_session, workspace_selector],
                                  [github_sync_status], api_name="sync_session_to_github")

        with gr.Tab("Agents.txt"):
            gr.Markdown("### Agent instructions")
            with gr.Row():
                session_id_at = gr.Textbox(label="Session ID", placeholder="Enter Session ID...")
                session_id_sync_list.append(session_id_at)

            gr.Markdown("#### Design agent brief")
            gr.Markdown("Layout/visual-design instructions built from this session's *synthesized* "
                        "UX findings (cross-persona root-cause aggregation, not one persona's opinion) "
                        "-- what's wrong, how many personas hit it, and the grounded, concrete change to make.")
            design_brief_btn = gr.Button("Generate design agent brief", variant="primary")
            design_brief_display = gr.Code(label="agents.txt (design)", language="markdown", lines=24)
            design_brief_btn.click(fn=generate_design_agent_brief, inputs=[session_id_at, workspace_selector],
                                    outputs=[design_brief_display])

            gr.Markdown("#### Coding agent prompt")
            gr.Markdown("Implementation prompt built from solutions selected/liked elsewhere in this session.")
            refresh_agent_prompt_btn = gr.Button("Generate prompt for coding agent")
            agent_prompt_display = gr.Code(label="Prompt for Coding Agent", language="markdown")

            refresh_agent_prompt_btn.click(fn=generate_agents_prompt, inputs=[selected_solutions_json_state], outputs=[agent_prompt_display])

        with gr.Tab("Full New UI"):
            with gr.Row():
                session_id_ui = gr.Textbox(label="Session ID", placeholder="Enter Session name...")
                session_id_sync_list.append(session_id_ui)
                jules_uuid_ui = gr.Textbox(label="System UUID", placeholder="Automatically filled after analysis...")
            with gr.Row():
                with gr.Column(scale=3):
                    gr.Markdown("### Generated Landing Page")
                    generate_full_ui_btn = gr.Button("Generate Full New UI from Selected Solutions", variant="primary")
                    refresh_ui_btn = gr.Button("Refresh UI Display")
                    full_ui_iframe = gr.HTML(label="Generated UI", value="Click Generate to start.")
                
                with gr.Column(scale=1):
                    gr.Markdown("### Real-time Adaptation")
                    ui_chatbot = gr.Chatbot(label="Design Chat")
                    ui_chat_msg = gr.Textbox(label="Request Modification", placeholder="e.g. Change primary color to emerald...")
                    ui_chat_send = gr.Button("Send Request")

            generate_full_ui_btn.click(fn=generate_full_ui_call, inputs=[jules_uuid_ui, selected_solutions_json_state, url_input, workspace_selector], outputs=[full_ui_iframe])
            refresh_ui_btn.click(fn=poll_for_generated_ui, inputs=[jules_uuid_ui, workspace_selector], outputs=[full_ui_iframe])
            ui_chat_send.click(fn=llm_chat_adaptation, inputs=[ui_chat_msg, ui_chatbot, jules_uuid_ui, workspace_selector], outputs=[ui_chatbot, ui_chat_msg])


        with gr.Tab("System"):
            gr.Markdown("### Workspace storage and service diagnostics")
            local_system_refresh = gr.Button("Check local services and workspace storage", variant="primary")
            local_system_status = gr.JSON(label="Diagnostics")

            def local_system_test(workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
                session_client, personas_client = authenticated_clients(workspace_id, oauth_profile, oauth_token)
                return {
                    "identity": session_client.me(),
                    "sessions": len(session_client.list_sessions()),
                    "personas": len(personas_client.list()),
                    "storage": "workspace-scoped control-plane artifacts",
                    "github_runtime_dependency": False,
                }

            local_system_refresh.click(local_system_test, [workspace_selector], [local_system_status], api_name="workspace_storage_diagnostics")

        with gr.Tab("Live Monitoring"):
            gr.Markdown("### Live workspace jobs and artifacts")
            with gr.Row():
                session_id_live = gr.Textbox(label="Session ID", placeholder="Enter Session ID...")
                session_id_sync_list.append(session_id_live)
            live_log = gr.Textbox(label="Workspace activity log", lines=5, interactive=False)
            refresh_feed_btn = gr.Button("Refresh Feed Now")
            global_feed = gr.Markdown(value="Waiting for new reports...")
            
            def monitor_and_log(workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
                # This fires on a 60s background timer for every open tab, signed
                # in or not, so an expired HF OAuth token (a long-idle browser tab)
                # or an anonymous visitor without ADMIN_API_TOKEN configured must
                # not raise an unhandled exception here -- that would spam the
                # server log every minute per stale tab. Show a clear status
                # instead of crashing.
                try:
                    session_client, _ = authenticated_clients(workspace_id, oauth_profile, oauth_token)
                    sessions = session_client.list_sessions()
                except PermissionError as error:
                    return f"_{error}_", ""
                except requests.exceptions.HTTPError as error:
                    status = error.response.status_code if error.response is not None else "?"
                    return f"_Could not refresh (HTTP {status}) -- sign in again if this persists._", ""
                except requests.exceptions.RequestException as error:
                    return f"_Could not reach the control plane: {error}_", ""
                rows, logs, snapshots = [], [], []
                for session in sessions[:20]:
                    jobs = session_client.list_jobs(session["session_id"])
                    rows.extend(f"- `{job['job_id']}` — **{job['status']}** ({job['type']})" for job in jobs)
                    for artifact in session_client.list_artifacts(session["session_id"]):
                        if artifact["kind"] == "persona.profile":
                            profile = json.loads(session_client.get_artifact_content(artifact["artifact_id"]))
                            snapshots.append(f"### {profile.get('persona', {}).get('name', profile['id'])}\n```json\n{json.dumps(profile, indent=2)}\n```")
                    logs.append(f"{session['session_id']}: {len(jobs)} persisted jobs")
                feed = "## Jobs\n" + ("\n".join(rows) or "No persisted jobs yet.")
                if snapshots: feed += "\n\n## Immutable persona snapshots\n" + "\n\n".join(snapshots)
                return feed, "\n".join(logs)

            # Use a Timer to poll every 60 seconds
            timer = gr.Timer(value=60)
            timer.tick(fn=monitor_and_log, inputs=[workspace_selector], outputs=[global_feed, live_log])
            refresh_feed_btn.click(fn=monitor_and_log, inputs=[workspace_selector], outputs=[global_feed, live_log])


        with gr.Tab("Alternative Styling"):
            gr.Markdown("### Design Automation & Iteration")
            gr.Markdown("Design alternatives are stored as workspace artifacts and can be downloaded or iterated without a source-control integration.")
            
            gr.Markdown("---")
            gr.Markdown("### 🚀 Recommendations for Customer-Facing Application")
            gr.Markdown("""
            To transform this prototype into a production-ready customer application, we recommend the following enhancements:
            
            1. **Multi-Tenant Authentication**: Implement Clerk or NextAuth for secure user logins and project isolation, ensuring customers only see their own analysis branches.
            2. **Real-Time Step Visualization**: Extend the persisted event stream with a "Live View" tab showing JourneyTest browser interactions as they happen.
            3. **Figma/Design Integration**: Develop a plugin to export the "Identified UI Improvements" directly into Figma as annotated design layers.
            4. **Guided Onboarding Flow**: Add a "Wizard" mode for first-time users to help them define their Theme and Customer Profile through guided questions.
            5. **Result Comparison (A/B Testing)**: Add a feature to view the original landing page side-by-side with the Generated UI, including a "Scorecard" of UX metrics (Accessibility, Conversion, Clarity).
            6. **Automated Deployment Previews**: Integrate with Vercel/Netlify APIs to automatically deploy the 'Full New UI' to a shareable preview URL upon generation.
            """)


    # Persona Preview Handler (moved to a safe place if not already there)
    # Actually it's inside the Tab block in previous edit.

    # Event handlers
    studio_outputs = [persona_view, persona_editor, *behavior_sliders.values(), color_vision, visual_acuity, contrast_sensitivity, pointer_precision, processing_speed, working_memory, reading_speed]

    def persona_choices(personas):
        personas = normalize_personas(personas)
        choices = [(item.get("persona", {}).get("name", item.get("name", item.get("id", "Persona"))), str(index)) for index, item in enumerate(personas)]
        return gr.update(choices=choices, value=choices[0][1] if choices else None)

    def load_persona(personas, index):
        normalized = normalize_personas(personas)
        try:
            position = int(index or 0)
            profile = normalized[position] if 0 <= position < len(normalized) else normalized[0]
        except (IndexError, ValueError):
            # Nothing to load (empty list, or a stale index left over from a
            # previous persona_display that no longer matches) -- return the
            # same defaults load_persona would derive from an empty profile,
            # instead of crashing the event handler.
            return [None, "", *[.5 for _ in behavior_sliders], "typical", 1, 1, .9, .8, 5, 220]
        behavior, abilities = profile.get("behavior", {}), profile.get("abilities", {})
        vision, motor = abilities.get("vision", {}), abilities.get("motor", {})
        cognition, reading = abilities.get("cognition", {}), abilities.get("reading", {})
        return [profile, json.dumps(profile, indent=2), *[behavior.get(trait, .5) for trait in behavior_sliders], vision.get("colorVision", "typical"), vision.get("acuity", 1), vision.get("contrastSensitivity", 1), motor.get("pointerPrecision", .9), cognition.get("processingSpeed", .8), cognition.get("workingMemoryItems", 5), reading.get("wordsPerMinute", 220)]

    def load_example_persona_into_studio(example_file, personas, workspace_id,
                                         oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
        # Direct path into the Studio for the bundled example personas
        # (Friedrich_Wolf, Lila, Lisa, Marcos, Oscar, Sophie_Lefevre), instead of
        # only reaching them through the Analysis Orchestrator's Generate flow.
        # Compiled through the same PersonaCompiler as every other persona
        # source (real behavior/abilities, not a bare display-only stub) and
        # appended to whatever's already loaded, so it doesn't clobber personas
        # from an earlier Generate run.
        if not example_file:
            return personas, gr.update(), "Choose a bundled example persona first."
        try:
            _, personas_client = authenticated_clients(workspace_id, oauth_profile, oauth_token)
            compiled = load_example_persona(example_file, personas_client, compile_behavior=True, seed=1)
        except requests.exceptions.RequestException as error:
            return personas, gr.update(), f"Failed to load {example_file}: {error}"
        updated = normalize_personas(personas) + [compiled]
        choices = [(item.get("persona", {}).get("name", item.get("name", item.get("id", "Persona"))), str(index))
                   for index, item in enumerate(updated)]
        new_index = str(len(updated) - 1)
        return updated, gr.update(choices=choices, value=new_index), f"Loaded **{compiled.get('name', example_file)}** into the Studio."

    def apply_persona_tweaks(profile_json, *values):
        profile = json.loads(profile_json)
        trait_values, ability_values = values[:len(behavior_sliders)], values[len(behavior_sliders):]
        profile.setdefault("behavior", {}).update(dict(zip(behavior_sliders, trait_values)))
        color, acuity, contrast, pointer, processing, memory, reading = ability_values
        abilities = profile.setdefault("abilities", {})
        abilities.setdefault("vision", {}).update(colorVision=color, acuity=acuity, contrastSensitivity=contrast)
        abilities.setdefault("motor", {})["pointerPrecision"] = pointer
        abilities.setdefault("cognition", {}).update(processingSpeed=processing, workingMemoryItems=int(memory))
        abilities.setdefault("reading", {})["wordsPerMinute"] = int(reading)
        return profile, json.dumps(profile, indent=2), "Tweaks applied locally. Save to persist them."

    def save_manual_persona(profile_json, personas, index, workspace_id, oauth_profile: gr.OAuthProfile | None, oauth_token: gr.OAuthToken | None):
        profile = json.loads(profile_json)
        _, personas_client = authenticated_clients(workspace_id, oauth_profile, oauth_token)
        saved = personas_client.update(profile)
        updated = normalize_personas(personas)
        updated[int(index or 0)] = saved
        return saved, json.dumps(saved, indent=2), updated, f"Saved `{saved['id']}` as a manually edited profile."

    generate_btn.click(
        fn=handle_generate,
        inputs=[theme_input, profile_input, num_personas_input, persona_method, example_persona_select, url_input, workspace_selector],
        outputs=[status_output, task_list_display, persona_display, last_generated_tasks_state],
        api_name="generate_personas",
    ).then(fn=persona_choices, inputs=[persona_display], outputs=[persona_index])

    load_example_into_studio_btn.click(
        fn=load_example_persona_into_studio,
        inputs=[studio_example_persona_select, persona_display, workspace_selector],
        outputs=[persona_display, persona_index, persona_studio_status],
        api_name="load_example_persona_into_studio",
    ).then(fn=load_persona, inputs=[persona_display, persona_index], outputs=studio_outputs)

    refresh_personas_btn.click(fn=persona_choices, inputs=[persona_display], outputs=[persona_index])
    persona_index.change(fn=load_persona, inputs=[persona_display, persona_index], outputs=studio_outputs)
    apply_tweaks_btn.click(fn=apply_persona_tweaks, inputs=[persona_editor, *behavior_sliders.values(), color_vision, visual_acuity, contrast_sensitivity, pointer_precision, processing_speed, working_memory, reading_speed], outputs=[persona_view, persona_editor, persona_studio_status])
    save_persona_btn.click(fn=save_manual_persona, inputs=[persona_editor, persona_display, persona_index, workspace_selector], outputs=[persona_view, persona_editor, persona_display, persona_studio_status])

    start_session_btn.click(
        fn=start_and_monitor_sessions,
        inputs=[persona_display, last_generated_tasks_state, url_input, allow_irreversible_actions_input, session_id_orch, workspace_selector],
        outputs=[status_output, report_output, active_session_state, active_jules_uuid_state]
    ).then(
        fn=lambda x: [x] * len(session_id_sync_list),
        inputs=[active_session_state],
        outputs=session_id_sync_list
    ).then(
        fn=lambda x: x,
        inputs=[active_jules_uuid_state],
        outputs=[jules_uuid_ui]
    )

    # Session ID Sync
    def sync_session_ids(val):
        return [val] * len(session_id_sync_list)
    
    for sid in session_id_sync_list:
        if sid.interactive:
            sid.change(fn=sync_session_ids, inputs=[sid], outputs=session_id_sync_list)
            sid.change(fn=lambda x: x, inputs=[sid], outputs=[active_session_state])

if __name__ == "__main__":
    print("Starting workspace-scoped UX analysis application")

    # Wrap with FastAPI for health check and API endpoints
    fastapi_app = FastAPI()

    @fastapi_app.get("/health")
    def health():
        return {"status": "ok"}

    @fastapi_app.get("/api/info")
    def info():
        return {"app": "UX Analysis Orchestrator", "version": "1.0.0"}

    def api_clients(authorization, workspace_id):
        # Accept a Hugging Face bearer token or the operator break-glass credential
        # (`Authorization: Admin <token>`). The control plane and persona runtime
        # revalidate whichever credential is presented.
        if not authorization or not (authorization.startswith("Bearer ") or authorization.startswith("Admin ")):
            raise HTTPException(401, "Hugging Face bearer token or admin credential required")
        return (
            ControlPlaneClient(workspace_id=workspace_id, authorization=authorization),
            PersonaRuntimeClient(workspace_id=workspace_id, authorization=authorization),
        )

    @fastapi_app.get("/api/v1/sessions")
    def api_sessions(authorization: str | None = Header(None),
                     workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        session_client, _ = api_clients(authorization, workspace_id)
        return {"items": session_client.list_sessions()}

    @fastapi_app.get("/api/v1/sessions/{session_id}/artifacts")
    def api_session_artifacts(session_id: str, authorization: str | None = Header(None),
                              workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        session_client, _ = api_clients(authorization, workspace_id)
        return {"items": session_client.list_artifacts(session_id)}

    @fastapi_app.get("/api/v1/artifacts/{artifact_id}/download")
    def api_artifact_download(artifact_id: str, authorization: str | None = Header(None),
                              workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        session_client, _ = api_clients(authorization, workspace_id)
        response = requests.get(f"{session_client.base_url}/v1/artifacts/{artifact_id}/content",
                                headers=session_client.headers, timeout=120)
        if response.status_code >= 400:
            raise HTTPException(response.status_code, "artifact download failed")
        disposition = response.headers.get("content-disposition", f'attachment; filename="{artifact_id}"')
        return Response(response.content, media_type=response.headers.get("content-type"),
                        headers={"content-disposition": disposition})

    @fastapi_app.get("/api/v1/jobs/{job_id}")
    def api_job(job_id: str, authorization: str | None = Header(None),
                workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        session_client, _ = api_clients(authorization, workspace_id)
        return session_client.get_job(job_id)

    @fastapi_app.post("/api/v1/personas/generate")
    def api_generate_personas(payload: dict, authorization: str | None = Header(None),
                              workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        # Persona generation without a full usability-workflow session/job --
        # useful standalone (e.g. building a persona to inspect or reuse later)
        # and used to seed the GitHub-backed persona pool with real, live-generated
        # profiles rather than placeholder data.
        _, personas_client = api_clients(authorization, workspace_id)
        try:
            personas = personas_client.generate(payload["theme"], payload["customer_profile"],
                                                 int(payload.get("persona_count", 1)),
                                                 scenario=payload.get("scenario") or payload["theme"],
                                                 seed=int(payload.get("seed", 1)),
                                                 allow_offline_fallback=bool(payload.get("allow_offline_fallback", False)))
        except requests.exceptions.RequestException as error:
            raise HTTPException(502, f"persona generation failed: {error}")
        return {"personas": personas}

    @fastapi_app.post("/api/v1/personas/compile-example")
    def api_compile_example_persona(payload: dict, authorization: str | None = Header(None),
                                    workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        # Compile a bundled example persona's behavior/abilities without spinning
        # up a full usability-workflow session/job -- same use as above.
        _, personas_client = api_clients(authorization, workspace_id)
        example_persona = payload.get("example_persona")
        if not example_persona:
            raise HTTPException(400, "example_persona is required")
        try:
            compiled = load_example_persona(example_persona, personas_client, compile_behavior=True,
                                            seed=int(payload.get("seed", 1)))
        except FileNotFoundError as error:
            raise HTTPException(404, str(error))
        except requests.exceptions.RequestException as error:
            raise HTTPException(502, f"persona compilation failed: {error}")
        return {"persona": compiled}

    @fastapi_app.post("/api/v1/personas/pool-lookup")
    def api_pool_lookup_personas(payload: dict, authorization: str | None = Header(None),
                                 workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        # Ranged-match lookup against the GitHub-backed persona pool (docs/
        # persona-pool-plan.md), exposed directly for inspection/tooling --
        # select_or_create_personas' "PersonaPool" method calls the same
        # persona-runtime route internally as part of a full generation flow.
        _, personas_client = api_clients(authorization, workspace_id)
        try:
            result = personas_client.pool_lookup(payload["theme"], payload["customer_profile"],
                                                  int(payload.get("count", 1)), payload.get("behavior_targets"))
        except requests.exceptions.RequestException as error:
            raise HTTPException(502, f"persona pool lookup failed: {error}")
        return result

    @fastapi_app.post("/api/v1/workflows/usability")
    def api_usability_workflow(payload: dict, authorization: str | None = Header(None),
                               workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        session_client, personas_client = api_clients(authorization, workspace_id)
        example_persona = payload.get("example_persona")
        try:
            if example_persona:
                # Skip live TinyTroupe generation and use a bundled example persona
                # (e.g. "Friedrich_Wolf.agent.json") instead -- the recommended
                # default for exercising the rest of the pipeline (journey run,
                # report) without paying live generation latency/cost each time.
                persona_count = int(payload.get("persona_count", 1))
                personas = [load_example_persona(example_persona, personas_client, compile_behavior=True, seed=seed)
                            for seed in range(1, persona_count + 1)]
            else:
                personas = personas_client.generate(payload["theme"], payload["customer_profile"],
                                                    int(payload.get("persona_count", 5)),
                                                    scenario=payload.get("scenario") or f"Test {payload['url']}",
                                                    seed=int(payload.get("seed", 1)),
                                                    allow_offline_fallback=bool(payload.get("allow_offline_fallback", False)))
        except FileNotFoundError as error:
            raise HTTPException(404, str(error))
        except requests.exceptions.RequestException as error:
            # Surface the real upstream failure (e.g. the model router itself
            # rate-limiting or erroring, propagated as an HTTPError from
            # personas_client.compile()/generate()) instead of a bare "Internal
            # Server Error" with no detail.
            raise HTTPException(502, f"persona generation/compilation failed: {error}")
        session = session_client.create_session({"name": payload.get("name") or payload.get("theme") or example_persona,
                                                 "target_url": payload["url"], "source": "api"})
        persona_artifacts = [session_client.create_artifact(
            session["session_id"], "persona.profile", profile,
            metadata={"schema_version": "1.0", "persona_id": profile["id"], "immutable_run_snapshot": True})
            ["artifact_id"] for profile in personas]
        tasks = payload.get("tasks") or [
            "Understand the product and its primary value proposition",
            "Find how to start using the product",
            "Inspect examples or documentation",
            "Identify pricing or usage constraints",
            "Locate support or contact information",
        ]
        # journey-worker's safety.js blocks any task whose text matches a
        # destructive-action pattern (purchase, delete account, deploy
        # production, ...) unless browserSafety.allowIrreversibleActions is
        # explicitly set (spec.md section 36). Off by default; callers opt in
        # explicitly the same way the Gradio UI does.
        job = session_client.create_job({"session_id": session["session_id"], "type": "combined_test",
            "input_artifacts": persona_artifacts,
            "metadata": {"persona_artifacts": persona_artifacts, "tasks": tasks, "url": payload["url"],
                        "browserSafety": {"allowIrreversibleActions": bool(payload.get("allow_irreversible_actions", False))}}})
        completed = (session_client.wait_for_job(job["job_id"], timeout=int(payload.get("timeout", 900)))
                     if payload.get("wait") else job)
        return {"session": session, "personas": personas, "job": completed,
                "artifacts": session_client.list_artifacts(session["session_id"])}

    @fastapi_app.get("/api/readiness")
    def readiness():
        services = {}
        for name, url in {
            "controlPlane": f"{control_plane.base_url}/healthz",
            "personaRuntime": f"{persona_runtime.base_url}/healthz",
            "journeyWorker": f"{os.getenv('JOURNEY_WORKER_URL', 'http://127.0.0.1:8080').rstrip('/')}/healthz",
            "eyesonWorker": f"{os.getenv('EYESON_WORKER_URL', 'http://127.0.0.1:8081').rstrip('/')}/healthz",
        }.items():
            try:
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                services[name] = response.json()
            except requests.RequestException as error:
                services[name] = {"status": "unavailable", "error": str(error)}
        model_configured = bool(os.getenv("OPENAI_API_KEY") or os.getenv("BLABLADOR_API_KEY"))
        return {
            "status": "ready" if all(item.get("status") in {"ok", "ready"} for item in services.values()) else "degraded",
            "services": services,
            "modelCredentialsConfigured": model_configured,
            "liveExecutionReady": model_configured and services.get("personaRuntime", {}).get("tinytroupeAvailable", False)
                and services.get("journeyWorker", {}).get("engine") == "journeytest",
        }

    @fastapi_app.get("/api-docs")
    def api_docs():
        return {
            "endpoints": [
                {
                    "path": "/health",
                    "method": "GET",
                    "purpose": "Health check"
                },
                {
                    "path": "/api/info",
                    "method": "GET",
                    "purpose": "App information"
                },
                {
                    "path": "/api/readiness",
                    "method": "GET",
                    "purpose": "Aggregate control-plane, TinyTroupe, JourneyTest, and model readiness"
                },
                {
                    "path": "/api/v1/workflows/usability",
                    "method": "POST",
                    "purpose": "Generate personas, run a saved usability job, and return workspace artifacts"
                },
                {
                    "path": "/api/v1/sessions/{session_id}/artifacts",
                    "method": "GET",
                    "purpose": "List artifacts saved in the authenticated workspace session"
                },
                {
                    "path": "/api/v1/artifacts/{artifact_id}/download",
                    "method": "GET",
                    "purpose": "Download an authenticated report, presentation, log, or evidence artifact"
                },
                {
                    "path": "/api-docs",
                    "method": "GET",
                    "purpose": "API documentation"
                },
                {
                    "path": "/",
                    "method": "GET",
                    "purpose": "Gradio UI"
                },
                {
                    "path": "/static_slides/{path}",
                    "method": "GET",
                    "purpose": "Static slide deck files"
                }
            ]
        }

    # Mount static files for slides
    fastapi_app.mount("/static_slides", StaticFiles(directory=SLIDES_OUTPUT_ROOT), name="static_slides")

    # Mount Gradio
    # Restrict allowed_paths for better security
    demo_app = gr.mount_gradio_app(fastapi_app, demo, path="/", allowed_paths=["/app"])

    # Run uvicorn
    uvicorn.run(demo_app, host="0.0.0.0", port=7860)
