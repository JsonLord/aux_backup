"""The settings dialog for model providers, and its API surface.

Every run spends a model call, and until now every run spent *this deployment's*
model call, whoever asked for it. That is fine for somebody trying a bundled
example and wrong for a stranger's hundred-step journey against their own site,
so the built-in credentials are reserved (apps/api/model_settings.py) and
everybody else configures a provider here.

It takes one the same two ways the browser-credential dialog takes a session,
and in the same order, because the safety ordering is the same:

  1. A Hugging Face Space secret -- the value never leaves the environment and
     only its name is stored. Offered first and preselected.
  2. A pasted API key -- encrypted at rest, and refused outright when no
     encryption key is configured.

A provider is an endpoint, a model and a key together. That is not tidiness: a
fallback that carried the endpoint and not the model sent the router's "auto" to
Blablador and answered 404 on every persona compile, and a chain whose second
entry has no key looks like a fallback while being a 401 on every call. The form
takes all three or refuses the row.

Providers are listed per role, and the order is the fallback order: the first
that answers serves the run, and a request that never reached a server moves to
the next. Nothing here ever renders a stored key -- the table shows metadata
only, and the paste box is cleared on save.
"""
from __future__ import annotations

import gradio as gr

from apps.api.credentials import CredentialError, encryption_available
from apps.api.model_settings import (
    KIND_REFERENCE, KIND_SECRET, ROLE_ACTING, ROLE_GENERATION, ROLE_REFLECTION, ROLE_VISION,
    ModelSettingsError, may_use_built_in_providers, space_owner, why_not_built_in,
)

SOURCE_REFERENCE = "Hugging Face Space secret (recommended)"
SOURCE_SECRET = "Paste an API key"
SOURCES = [SOURCE_REFERENCE, SOURCE_SECRET]
_KIND_BY_SOURCE = {SOURCE_REFERENCE: KIND_REFERENCE, SOURCE_SECRET: KIND_SECRET}

# Named for what each one does in a run, not for its size. Which model suits
# which job is the decision this dialog exists to let somebody make.
ROLE_LABELS = {
    "Writing personas": ROLE_GENERATION,
    "Browsing as the persona": ROLE_ACTING,
    "Reflecting and scoring": ROLE_REFLECTION,
    "Looking at screenshots": ROLE_VISION,
}
ROLE_HELP = {
    ROLE_GENERATION: "Big and infrequent. A large model earns its cost here.",
    ROLE_ACTING: "Every step of every run. This is where most of the budget goes.",
    ROLE_REFLECTION: "Small, factual, constant. A fast model is the right tool.",
    ROLE_VISION: "Needs to accept images. Once per capture.",
}


def _access_banner(auth: dict | None) -> str:
    """Whether this visitor may run on the Space's own credentials, said up front.

    Finding out after starting a run, from a 502, is the version of this that
    wastes somebody's afternoon.
    """
    owner = space_owner() or "the Space owner"
    if may_use_built_in_providers(auth):
        return ('<p class="aux-cred-banner ok">You can run on this Space\'s built-in models. '
                "Anything you add here is used instead of them.</p>")
    return (f'<p class="aux-cred-banner warn">This Space\'s own model credentials are reserved '
            f"for its example personas, for {owner}, and for the admin API token. Add a provider "
            "below to run your own sites &mdash; a Space secret name is enough, and the value "
            "never leaves the environment.</p>")


def _encryption_banner() -> str:
    if encryption_available():
        return ('<p class="aux-cred-banner ok">A pasted key will be encrypted at rest.</p>')
    return ('<p class="aux-cred-banner warn">No encryption key is configured, so a pasted key '
            "cannot be stored. Name a Space secret instead &mdash; the value stays in the "
            "environment and only the name is written down.</p>")


def _rows(store, workspace_id: str) -> list[list[str]]:
    """Metadata only. A stored key is never rendered."""
    label_by_role = {value: key for key, value in ROLE_LABELS.items()}
    rows = []
    for item in store.list(workspace_id or "local"):
        source = ("secret: " + item["secret_ref"]) if item["kind"] == KIND_REFERENCE else "pasted key"
        rows.append([label_by_role.get(item["role"], item["role"]), item["label"],
                     item["model"], item["base_url"], source, str(item["position"]),
                     item["provider_id"]])
    return rows


def render(store, workspace_selector, auth_state=None):
    """Draw the dialog and wire it. Returns the open button so a caller can place it."""
    open_button = gr.Button("🧠 Models", size="sm")
    backdrop = gr.HTML('<div class="aux-cred-backdrop"></div>', visible=False)

    with gr.Group(visible=False, elem_classes="aux-cred-dialog") as dialog:
        with gr.Group(elem_classes="aux-cred-head"):
            gr.Markdown("### Model providers")
            close_x = gr.Button("✕", elem_classes="aux-cred-x", size="sm")
        gr.HTML('<p class="aux-cred-note">Choose which model runs each part of a review, and on '
                "whose account. Add more than one for a role and they are tried in order, so a "
                "provider that stops answering does not end the run.</p>")
        access = gr.HTML(_access_banner(None))
        banner = gr.HTML(_encryption_banner())

        role = gr.Radio(list(ROLE_LABELS), value="Writing personas", label="What this model does")
        role_note = gr.HTML(f'<p class="aux-cred-note">{ROLE_HELP[ROLE_GENERATION]}</p>')

        label = gr.Textbox(label="Name", placeholder="Blablador – alias-large",
                           info="How you will recognise this row.")
        with gr.Row():
            base_url = gr.Textbox(label="Endpoint", scale=3,
                                  placeholder="https://api.helmholtz-blablador.fz-juelich.de/v1",
                                  info="An OpenAI-compatible base URL, ending in /v1.")
            model = gr.Textbox(label="Model id", scale=2, placeholder="alias-large",
                               info="Exactly as the provider names it.")
        source = gr.Radio(SOURCES, value=SOURCE_REFERENCE, label="Where the key comes from")
        with gr.Group(visible=True) as reference_fields:
            secret_ref = gr.Textbox(
                label="Space secret name", placeholder="BLABLADOR_API_KEY",
                info="The variable holding the key. Only this name is stored; the value is read "
                     "at run time and never written down.")
        with gr.Group(visible=False) as secret_fields:
            api_key = gr.Textbox(label="API key", type="password",
                                 info="Encrypted at rest, and never shown again.")
        position = gr.Number(label="Order", value=0, precision=0,
                             info="0 is tried first. The next is used only when one cannot be reached.")

        with gr.Row():
            save = gr.Button("Save provider", variant="primary")
            close = gr.Button("Close")
        status = gr.Markdown("")

        gr.Markdown("#### Configured")
        table = gr.Dataframe(
            headers=["Does", "Name", "Model", "Endpoint", "Key", "Order", "id"],
            datatype=["str"] * 7, interactive=False, wrap=True, row_count=(0, "dynamic"))
        with gr.Row():
            delete_id = gr.Textbox(label="Delete by id", placeholder="llm_…", scale=3)
            delete = gr.Button("Delete", variant="stop", scale=1)

        with gr.Accordion("Which model should I use?", open=False):
            gr.Markdown(
                "**Writing personas** happens once per run and produces a whole person, so a "
                "large model is worth it — `alias-large`, falling back to `alias-huge`.\n\n"
                "**Browsing as the persona** happens on every step and is where the budget "
                "actually goes.\n\n"
                "**Reflecting and scoring** is small, factual and constant: `alias-fast` is "
                "chosen here precisely because it is cheap and frequent.\n\n"
                "**Looking at screenshots** needs a model that accepts images.\n\n"
                "A provider is an endpoint, a model and a key *together*. Mixing them is a real "
                "failure mode: sending a router's `auto` to a provider that serves named models "
                "answers 404 on every call.")

    def _toggle_fields(chosen):
        return (gr.update(visible=chosen == SOURCE_REFERENCE),
                gr.update(visible=chosen == SOURCE_SECRET))

    def _role_note(chosen):
        return f'<p class="aux-cred-note">{ROLE_HELP[ROLE_LABELS[chosen]]}</p>'

    source.change(_toggle_fields, [source], [reference_fields, secret_fields])
    role.change(_role_note, [role], [role_note])

    def _open(workspace_id, auth=None):
        return (gr.update(visible=True), gr.update(visible=True), _access_banner(auth),
                _encryption_banner(), _rows(store, workspace_id), "")

    def _close():
        return gr.update(visible=False), gr.update(visible=False)

    def _save(workspace_id, chosen_role, chosen_source, name, endpoint, model_id, ref, key, order):
        """Store one provider. Returns cleared inputs -- the key is write-only."""
        kind = _KIND_BY_SOURCE.get(chosen_source, KIND_REFERENCE)
        try:
            store.save(workspace_id=workspace_id or "local", owner_user_id=workspace_id or "local",
                       label=name or "", role=ROLE_LABELS.get(chosen_role, ROLE_GENERATION),
                       base_url=endpoint or "", model=model_id or "", kind=kind,
                       secret=key or "", secret_ref=ref or "", position=int(order or 0))
        except (ModelSettingsError, CredentialError) as error:
            # Written for a reader, and never carrying the key.
            return f"⚠️ {error}", _rows(store, workspace_id), gr.update()
        return (f"✅ Saved **{name}** for {chosen_role.lower()}.",
                _rows(store, workspace_id), gr.update(value=""))

    def _delete(workspace_id, provider_id):
        removed = store.delete((provider_id or "").strip(), workspace_id or "local")
        said = "🗑️ Removed." if removed else "⚠️ No provider with that id in this workspace."
        return said, _rows(store, workspace_id), ""

    opens = [dialog, backdrop, access, banner, table, status]
    open_button.click(_open, [workspace_selector], opens, api_name="model_settings_open")
    for control in (close, close_x):
        control.click(_close, None, [dialog, backdrop])
    save.click(_save,
               [workspace_selector, role, source, label, base_url, model, secret_ref, api_key, position],
               [status, table, api_key], api_name="model_settings_save")
    delete.click(_delete, [workspace_selector, delete_id], [status, table, delete_id],
                 api_name="model_settings_delete")
    return open_button
