"""The settings dialog for browser credentials, and its API surface.

A run browses signed in when it is handed a storage-state file. Somebody has to
supply one, and the three ways they might are not equally safe, so the dialog is
ordered by that rather than by what is quickest to type:

  1. A Hugging Face Space secret -- the value never leaves the environment and
     only its name is stored. Offered first and preselected.
  2. Pasted session JSON -- encrypted at rest, and refused outright when no
     encryption key is configured.
  3. Username and password -- same, and only useful once a login-capture flow
     exchanges it for a session.

Every handler is registered with an `api_name`, so the same three paths are
callable from the Space's API (gradio_client) without going through the UI --
which is how a CI job or a script attaches a session before kicking off a run.

Nothing here ever renders a stored secret. Inputs are write-only: the password
and JSON boxes are cleared on save, and the table shows metadata only.
"""
from __future__ import annotations

import gradio as gr

from apps.api.credentials import (
    KIND_PASSWORD, KIND_REFERENCE, KIND_STATE, CredentialError,
    encryption_available, generate_key,
)

SOURCE_REFERENCE = "Hugging Face Space secret (recommended)"
SOURCE_STATE = "Paste session JSON"
SOURCE_PASSWORD = "Username and password"
SOURCES = [SOURCE_REFERENCE, SOURCE_STATE, SOURCE_PASSWORD]

_KIND_BY_SOURCE = {
    SOURCE_REFERENCE: KIND_REFERENCE,
    SOURCE_STATE: KIND_STATE,
    SOURCE_PASSWORD: KIND_PASSWORD,
}

# Gradio 5 has no modal component, so the dialog is a Group positioned over the
# app with a backdrop behind it. Scoped to .aux-cred-* so it cannot restyle the
# rest of the page.
CSS = """
.aux-cred-backdrop {
  position: fixed; inset: 0; z-index: 900;
  background: rgba(15, 23, 42, .55); backdrop-filter: blur(2px);
}
.aux-cred-dialog {
  position: fixed; z-index: 901;
  top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: min(680px, calc(100vw - 32px));
  max-height: min(86vh, 900px); overflow-y: auto;
  padding: 20px 22px 18px;
  border-radius: 14px;
  background: var(--background-fill-primary, #fff);
  box-shadow: 0 24px 64px rgba(2, 6, 23, .38), 0 0 0 1px rgba(148, 163, 184, .28);
  /* A Group is a flex container. Left as one, a max-height makes its children
     shrink to fit instead of overflowing, which silently compresses the form
     into itself -- clipped headings, collapsed inputs, one visible table row.
     Block flow lets the content take its natural height and the dialog scroll. */
  display: block !important;
}
.aux-cred-dialog > .styler,
.aux-cred-dialog > div { display: block !important; }
/* Restore the vertical rhythm that block flow drops. The form wrappers also
   paint their own fill, which in block flow shows as grey bars between the
   fields rather than as a background behind them. */
.aux-cred-dialog .form, .aux-cred-dialog .block { margin-bottom: 10px; }
.aux-cred-dialog .form { background: transparent; border: 0; }
/* The Group's styler paints its own fill, which shows through the gaps between
   the transparent form wrappers as grey bars between every field. */
.aux-cred-dialog > .styler { background: transparent; }
.aux-cred-dialog h3 { margin: 0 0 2px; font-size: 1.05rem; }
.aux-cred-note {
  font-size: .82rem; line-height: 1.5; opacity: .8; margin: 0 0 10px;
}
.aux-cred-banner {
  font-size: .82rem; line-height: 1.5; padding: 8px 11px;
  border-radius: 8px; margin: 0 0 12px; border-left: 3px solid;
}
.aux-cred-banner.ok   { background: rgba(16, 185, 129, .10); border-color: #10b981; }
.aux-cred-banner.warn { background: rgba(245, 158, 11, .12); border-color: #f59e0b; }
@media (max-width: 640px) {
  .aux-cred-dialog { width: calc(100vw - 16px); padding: 16px 14px 14px; }
}
"""


def _encryption_banner() -> str:
    if encryption_available():
        return ('<div class="aux-cred-banner ok"><strong>Encryption on.</strong> '
                "Pasted sessions and passwords are encrypted before they are written down.</div>")
    return ('<div class="aux-cred-banner warn"><strong>No encryption key set.</strong> '
            "Pasted sessions and passwords cannot be stored until <code>AUX_CREDENTIAL_KEY</code> "
            "is set as a Space secret. A Space-secret reference works without it, because the "
            "value stays in the environment.</div>")


def _rows(store, workspace_id: str) -> list[list[str]]:
    """Table rows. Metadata only -- no secret reaches this function."""
    rows = []
    for item in store.list_credentials(workspace_id or "local"):
        if item["kind"] == KIND_REFERENCE:
            source = f"Space secret ${item['secret_ref']}"
            if not item["resolvable"]:
                source += "  ⚠ not set in this deployment"
        elif item["kind"] == KIND_STATE:
            source = "Pasted session (encrypted)"
        else:
            source = f"Password for {item['username'] or 'user'} (encrypted)"
        rows.append([item["label"], item["origin"] or "any site", source,
                     item["last_used_at"] or "never used", item["credential_id"]])
    return rows


def render(store, workspace_selector):
    """Draw the dialog and wire it. Returns the open button so a caller can place it."""
    open_button = gr.Button("🔐 Credentials", size="sm")
    backdrop = gr.HTML('<div class="aux-cred-backdrop"></div>', visible=False)

    with gr.Group(visible=False, elem_classes="aux-cred-dialog") as dialog:
        gr.Markdown("### Browser credentials")
        gr.HTML('<p class="aux-cred-note">Give a run a signed-in browser session, so it tests '
                "the product your users actually see rather than the logged-out one.</p>")
        banner = gr.HTML(_encryption_banner())

        source = gr.Radio(SOURCES, value=SOURCE_REFERENCE, label="Where the session comes from")
        label = gr.Textbox(label="Name", placeholder="Shop – returning customer",
                           info="How you will pick this when starting a run.")
        origin = gr.Textbox(label="Site (optional)", placeholder="https://shop.example.com",
                            info="Recorded so a session is not reused against the wrong site.")

        with gr.Group(visible=True) as reference_fields:
            secret_ref = gr.Textbox(
                label="Space secret name", placeholder="SHOP_SESSION_STATE",
                info="The variable holding the storage-state JSON. Only this name is stored; "
                     "the value is read at run time and never written down.")
        with gr.Group(visible=False) as state_fields:
            state_json = gr.Textbox(
                label="Storage state JSON", lines=6, max_lines=12,
                placeholder='{"cookies": [...], "origins": [...]}',
                info="From `agent-browser state save`. Encrypted at rest; never shown again.")
        with gr.Group(visible=False) as password_fields:
            username = gr.Textbox(label="Username")
            password = gr.Textbox(label="Password", type="password",
                                  info="Encrypted at rest, and only used to capture a session.")

        with gr.Row():
            save = gr.Button("Save credential", variant="primary")
            close = gr.Button("Close")
        status = gr.Markdown("")

        gr.Markdown("#### Saved")
        table = gr.Dataframe(
            headers=["Name", "Site", "Source", "Last used", "id"],
            datatype=["str"] * 5, interactive=False, wrap=True, row_count=(0, "dynamic"))
        with gr.Row():
            delete_id = gr.Textbox(label="Delete by id", placeholder="cred_…", scale=3)
            delete = gr.Button("Delete", variant="stop", scale=1)

        gr.Markdown("#### Capture a session")
        gr.HTML('<p class="aux-cred-note">Sign a saved password credential in once and keep the '
                "session. If the site asks for a second factor, the capture waits — answer the "
                "challenge in the live view and it carries on by itself.</p>")
        with gr.Row():
            capture_id = gr.Textbox(label="Credential id", placeholder="cred_…", scale=2)
            capture_url = gr.Textbox(label="Sign-in page", placeholder="https://shop.example.com/login", scale=3)
        capture = gr.Button("Sign in and capture session")
        capture_status = gr.Markdown("")

        gr.Markdown("#### No credential for a site yet?")
        gr.HTML('<p class="aux-cred-note">Open its sign-in page and log in yourself in the live '
                "view. Nothing is typed by this service and no password is stored — only the "
                "session that results, which is all a run needs.</p>")
        with gr.Row():
            hand_label = gr.Textbox(label="Name", placeholder="Shop – my account", scale=2)
            hand_url = gr.Textbox(label="Sign-in page", placeholder="https://shop.example.com/login", scale=3)
        hand_capture = gr.Button("Open it and let me sign in")
        hand_status = gr.Markdown("")

        with gr.Accordion("How do I get a session, or a key?", open=False):
            gr.Markdown(
                "**A session file** – sign in once in a real browser, then export it:\n"
                "```bash\n"
                "agent-browser --auto-connect state save ./session.json\n"
                "```\n"
                "Paste the contents above, or put them in a Space secret and reference it by name.\n\n"
                "**An encryption key** – generate one and add it as the Space secret "
                "`AUX_CREDENTIAL_KEY`:\n"
                "```python\n"
                "from apps.api.credentials import generate_key; print(generate_key())\n"
                "```\n\n"
                "A stored session is a bearer credential: anyone holding it is signed in as that "
                "user until it expires. Prefer a throwaway test account over a real one.")

    def _toggle_fields(chosen):
        return (gr.update(visible=chosen == SOURCE_REFERENCE),
                gr.update(visible=chosen == SOURCE_STATE),
                gr.update(visible=chosen == SOURCE_PASSWORD))

    source.change(_toggle_fields, [source], [reference_fields, state_fields, password_fields])

    def _open(workspace_id):
        return (gr.update(visible=True), gr.update(visible=True),
                _encryption_banner(), _rows(store, workspace_id), "")

    def _close():
        return gr.update(visible=False), gr.update(visible=False)

    def _save(workspace_id, chosen, name, site, ref, state, user, secret):
        """Store one credential. Returns cleared inputs -- secrets are write-only."""
        kind = _KIND_BY_SOURCE.get(chosen, KIND_REFERENCE)
        try:
            store.put(workspace_id=workspace_id or "local", label=name, kind=kind, origin=site,
                      secret=state if kind == KIND_STATE else (secret if kind == KIND_PASSWORD else None),
                      secret_ref=ref if kind == KIND_REFERENCE else None,
                      username=user if kind == KIND_PASSWORD else None)
        except CredentialError as error:
            # The message is written for a reader and never carries the secret.
            return f"⚠️ {error}", _rows(store, workspace_id), gr.update(), gr.update()
        return (f"✅ Saved **{name}**.", _rows(store, workspace_id),
                gr.update(value=""), gr.update(value=""))

    def _delete(workspace_id, credential_id):
        if not str(credential_id or "").strip():
            return "Enter the id of the credential to delete.", _rows(store, workspace_id)
        removed = store.delete(credential_id.strip(), workspace_id or "local")
        return ("🗑️ Deleted." if removed else "No credential with that id in this workspace."), \
            _rows(store, workspace_id)

    def _capture(workspace_id, credential_id, login_url):
        """Drive a sign-in and keep the session it produces.

        Can take minutes when a second factor is involved -- that wait is the
        point, not a stall -- so the message says what is being waited on.
        """
        if not str(credential_id or "").strip():
            return "Enter the id of the password credential to sign in with.", gr.update()
        try:
            meta = store.capture_session(credential_id.strip(), login_url or "",
                                         workspace_id=workspace_id or "local")
        except CredentialError as error:
            return f"⚠️ {error}", _rows(store, workspace_id)
        return (f"✅ Signed in and kept the session for **{meta['label']}**. "
                "Runs using it now browse signed in."), _rows(store, workspace_id)

    def _sign_in_by_hand(workspace_id, name, login_url):
        """Hand the browser over so a person can sign in themselves.

        Blocks while they do, which can be minutes -- that wait is the feature.
        """
        try:
            meta = store.sign_in_by_hand(label=name or "", login_url=login_url or "",
                                         workspace_id=workspace_id or "local")
        except CredentialError as error:
            return f"⚠️ {error}", _rows(store, workspace_id)
        return (f"✅ Kept the session for **{meta['label']}**. No password was stored."), \
            _rows(store, workspace_id)

    open_button.click(_open, [workspace_selector],
                      [dialog, backdrop, banner, table, status])
    close.click(_close, None, [dialog, backdrop])
    save.click(_save,
               [workspace_selector, source, label, origin, secret_ref, state_json, username, password],
               [status, table, state_json, password],
               api_name="store_browser_credential")
    delete.click(_delete, [workspace_selector, delete_id], [status, table],
                 api_name="delete_browser_credential")
    capture.click(_capture, [workspace_selector, capture_id, capture_url],
                  [capture_status, table], api_name="capture_browser_session")
    hand_capture.click(_sign_in_by_hand, [workspace_selector, hand_label, hand_url],
                       [hand_status, table], api_name="sign_in_by_hand")

    # Listing is its own endpoint so a script can check what a workspace already
    # has before attaching another one. Metadata only.
    lister = gr.Button("List browser credentials", visible=False)
    lister.click(lambda workspace_id: store.list_credentials(workspace_id or "local"),
                 [workspace_selector], [gr.JSON(visible=False)],
                 api_name="list_browser_credentials")

    return open_button
