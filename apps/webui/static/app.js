"use strict";
// The page is a thin view over /webui/api. It never holds a key: a Space-secret
// provider is named by its variable, and a pasted key is sent once on save and
// then cleared from the form. Nothing read back from the server carries one.

const $ = (selector) => document.querySelector(selector);
const state = { roles: [] };

/** Workspace scoping travels the same way it does everywhere else in this app. */
function headers() {
  const workspace = new URLSearchParams(location.search).get("workspace");
  return workspace ? { "X-Workspace-ID": workspace } : {};
}

async function api(path, options = {}) {
  const response = await fetch(`/webui/api${path}`, {
    ...options,
    headers: { "content-type": "application/json", ...headers(), ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || body.message || `HTTP ${response.status}`);
  return body;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderRoles(data) {
  state.roles = data.roles;
  const host = $("#roles");
  host.replaceChildren();

  const access = $("#access");
  if (data.builtInAllowed) {
    access.hidden = true;
  } else {
    access.hidden = false;
    access.textContent = data.whyNotBuiltIn || "Configure a provider to run.";
  }

  for (const role of data.roles) {
    const section = element("section", "role");
    const head = element("header");
    head.append(element("h3", null, role.label), element("p", "note", role.help));
    section.append(head);

    if (!role.providers.length) {
      section.append(element("p", "empty", "Nothing configured — runs use the deployment's own, if this workspace may."));
    } else {
      const list = element("ul", "providers");
      role.providers.forEach((provider, index) => {
        const row = element("li");
        row.append(element("span", "order", `${index + 1}`));
        row.append(element("span", "name", provider.label));
        // Endpoint comes back as scheme and host only; the server never sends a path.
        row.append(element("span", "meta", `${provider.model} · ${provider.endpoint || "—"}`));
        if (provider.secret_ref) row.append(element("span", "meta", `$${provider.secret_ref}`));
        row.append(element("span", "spacer"));

        const models = element("button", null, "List models");
        models.addEventListener("click", () => withStatus(models, "List models", async () => {
          const found = await api(`/models?provider_id=${encodeURIComponent(provider.provider_id)}`);
          show(section, found.models.length
            ? `${found.endpoint} serves ${found.models.length}:\n${found.models.join("\n")}`
            : `${found.endpoint} listed no models.`);
        }));

        const check = element("button", null, "Check");
        check.addEventListener("click", () => withStatus(check, "Check", async () => {
          const answer = await api("/chat/completions", {
            method: "POST",
            body: JSON.stringify({ provider_id: provider.provider_id }),
          });
          show(section, `${answer.endpoint} (${answer.model}) answered:\n${answer.reply}`);
        }));

        const remove = element("button", "danger", "Remove");
        remove.addEventListener("click", async () => {
          if (!confirm(`Remove "${provider.label}"? Runs stop using it immediately.`)) return;
          await withStatus(remove, "Remove", async () => {
            await api(`/settings/${encodeURIComponent(provider.provider_id)}`, { method: "DELETE" });
            await load();
          });
        });

        row.append(models, check, remove);
        list.append(row);
      });
      section.append(list);
    }
    host.append(section);
  }
}

/** One place for "working…", the answer, and the failure. */
async function withStatus(button, label, work) {
  const previous = button.textContent;
  button.disabled = true;
  button.textContent = "…";
  try {
    await work();
  } catch (error) {
    show(button.closest(".role") || document.body, `Failed: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = previous || label;
  }
}

function show(section, text) {
  let panel = section.querySelector(".reply");
  if (!panel) {
    panel = element("pre", "reply");
    section.append(panel);
  }
  panel.textContent = text;
}

function fillRoleSelect(data) {
  const select = $("#role");
  select.replaceChildren();
  for (const role of data.roles) {
    const option = element("option", null, role.label);
    option.value = role.role;
    select.append(option);
  }
  const note = () => {
    const chosen = data.roles.find((role) => role.role === select.value);
    $("#role-help").textContent = chosen ? chosen.help : "";
  };
  select.addEventListener("change", note);
  note();

  const encryption = $("#encryption-note");
  if (!data.encryptionAvailable) {
    encryption.hidden = false;
    encryption.textContent =
      "A pasted key cannot be stored: no encryption key is configured, and storing it "
      + "in the clear would be worse than refusing. Name a Space secret instead.";
  }
}

function wireSourceToggle() {
  const ref = $("#secretRef");
  const key = $("#apiKey");
  for (const radio of document.querySelectorAll('input[name="source"]')) {
    radio.addEventListener("change", () => {
      const usingRef = document.querySelector('input[name="source"]:checked').value === "ref";
      ref.hidden = !usingRef;
      key.hidden = usingRef;
      if (usingRef) key.value = "";
      else ref.value = "";
    });
  }
}

async function load() {
  try {
    const data = await api("/settings");
    renderRoles(data);
    return data;
  } catch (error) {
    $("#roles").replaceChildren(element("p", "empty", `Could not load settings: ${error.message}`));
    return null;
  }
}

async function start() {
  const data = await load();
  if (data) fillRoleSelect(data);
  wireSourceToggle();

  $("#add-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = $("#add-status");
    status.className = "status";
    status.textContent = "Saving…";
    const usingRef = document.querySelector('input[name="source"]:checked').value === "ref";
    try {
      await api("/settings", {
        method: "PUT",
        body: JSON.stringify({
          role: $("#role").value,
          label: $("#label").value,
          baseUrl: $("#baseUrl").value,
          model: $("#model").value,
          secretRef: usingRef ? $("#secretRef").value : "",
          apiKey: usingRef ? "" : $("#apiKey").value,
        }),
      });
      // Cleared on save: the form is not somewhere a key should sit around.
      $("#apiKey").value = "";
      status.className = "status ok";
      status.textContent = "Saved.";
      await load();
    } catch (error) {
      status.className = "status bad";
      status.textContent = error.message;
    }
  });
}

start();
