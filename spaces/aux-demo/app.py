"""Self-contained HF Docker Space preview for the local AUX repository."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlparse

import gradio as gr
from fastapi import FastAPI
import uvicorn


def _bounded_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise gr.Error("Enter an absolute HTTP(S) URL.")
    return value.strip()


def run_contract_demo(url: str, task: str, user_count: int, seed: int):
    """Produce transparent deterministic fixture data; never imply browser execution."""
    url = _bounded_url(url)
    if not task.strip():
        raise gr.Error("Enter a task for the synthetic-user fixture.")
    user_count = max(1, min(8, int(user_count)))
    run_key = hashlib.sha256(f"{url}|{task}|{user_count}|{seed}".encode()).hexdigest()[:12]
    users = []
    events = []
    for index in range(user_count):
        fingerprint = hashlib.sha256(f"{run_key}|{index}".encode()).digest()
        patience = round(0.2 + fingerprint[0] / 255 * 0.7, 3)
        frustration = round(0.1 + (1 - patience) * 0.45, 3)
        user_id = f"fixture_user_{index + 1}"
        users.append({"id": user_id, "behavior": {"seed": seed + index, "patience": patience},
                      "state": {"frustration": frustration, "confusion": 0.25, "trust": 0.72}})
        events.extend([
            {"sequence": len(events) + 1, "type": "journey.step.started", "userId": user_id, "stepId": "step_1"},
            {"sequence": len(events) + 2, "type": "behavior.state.changed", "userId": user_id,
             "stepId": "step_1", "frustration": frustration},
        ])
    run = {
        "schemaVersion": "1.0", "runId": f"demo_{run_key}", "mode": "offline_contract_demo",
        "verdict": "not_executed", "url": url, "task": task.strip(), "syntheticUsers": users,
        "events": events, "grounding": {"status": "not_configured", "references": []},
        "limitations": [
            "No browser was launched.", "No screenshot, video, or observed usability evidence was collected.",
            "Connect the external versioned services for a real synthetic-user run.",
        ],
    }
    timeline = "\n".join(
        f"`{event['sequence']:02d}` **{event['type']}** · {event['userId']} · {event['stepId']}"
        for event in events
    )
    report = f"""## Contract preview

**Run:** `{run['runId']}`  
**Outcome:** Not executed — fixture preview only  
**Evidence language:** simulated/inferred

### Inferred pain point
Task clarity should be validated against observed browser evidence before making a recommendation.

### Proposed next step
Deploy the control plane, Journey worker, persona runtime, and Eyeson worker, then rerun the exact URL/task.

### Grounding
`not_configured`
"""
    readiness = {
        "demo": "ready", "live_browser": "not_configured", "deep_eyeson": "not_configured",
        "persona_provider": "offline_fixture", "production_stack": "external",
    }
    return json.dumps(run, indent=2), timeline, report, json.dumps(readiness, indent=2)


with gr.Blocks(title="AUX Synthetic UX Demo", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🧭 AUX Synthetic UX Demo\nA transparent preview of the local folder's versioned contracts.")
    with gr.Tab("Configure"):
        gr.Markdown("This Space runs a deterministic **offline contract demo**, not a live browser study.")
        url = gr.Textbox(label="Website URL", value="https://example.com")
        task = gr.Textbox(label="Task", value="Find support information")
        with gr.Row():
            user_count = gr.Slider(1, 8, value=2, step=1, label="Synthetic users")
            seed = gr.Number(value=42, precision=0, label="Seed")
        start = gr.Button("Run contract preview", variant="primary")
    with gr.Tab("Live trace"):
        timeline = gr.Markdown("Run the contract preview to populate deterministic events.")
    with gr.Tab("Report"):
        report = gr.Markdown("No fixture has been generated yet.")
        run_json = gr.Code(label="run.json preview", language="json")
    with gr.Tab("Readiness"):
        readiness = gr.Code(label="Deployment readiness", language="json")
    start.click(run_contract_demo, [url, task, user_count, seed], [run_json, timeline, report, readiness])


app = FastAPI(title="AUX Space Demo", version="1.0.0")


@app.get("/healthz")
def healthz():
    return {"status": "ready", "mode": "offline_contract_demo"}


app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
