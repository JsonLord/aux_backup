"use strict";
const { isIP } = require("node:net");

const secretKey = /(password|passwd|secret|token|authorization|cookie|api[-_]?key|credit[-_]?card)/i;
const destructive = /\b(delete account|delete repository|purchase|place order|send payment|wire transfer|publish|deploy production)\b/i;

function privateHost(hostname) {
  const host = hostname.toLowerCase();
  if (["localhost", "localhost.localdomain"].includes(host) || host.endsWith(".local")) return true;
  if (!isIP(host)) return false;
  if (host === "::1" || host.startsWith("fc") || host.startsWith("fd") || host.startsWith("fe80:")) return true;
  const parts = host.split(".").map(Number);
  return parts[0] === 10 || parts[0] === 127 || parts[0] === 0 || (parts[0] === 169 && parts[1] === 254)
    || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) || (parts[0] === 192 && parts[1] === 168);
}

function validateBrowserSafety(input) {
  let target;
  try { target = new URL(input.url); } catch { throw new Error("url must be an absolute HTTP(S) URL"); }
  if (!['http:', 'https:'].includes(target.protocol)) throw new Error("only HTTP(S) target URLs are allowed");
  const policy = input.browserSafety || {};
  if (privateHost(target.hostname) && !policy.allowPrivateNetworks) throw new Error("local/private target networks are blocked");
  const denied = new Set((policy.deniedOrigins || []).map((origin) => new URL(origin).origin));
  if (denied.has(target.origin)) throw new Error("target origin is denied by browser policy");
  const allowed = (policy.allowedOrigins || [target.origin]).map((origin) => new URL(origin).origin);
  if (!allowed.includes(target.origin)) throw new Error("target origin is outside the configured allowlist");
  if ((input.tasks || []).some((task) => destructive.test(String(task))) && !policy.allowIrreversibleActions) {
    throw new Error("potentially irreversible task requires allowIrreversibleActions=true");
  }
  return { targetOrigin: target.origin, allowedOrigins: allowed, allowDownloads: Boolean(policy.allowDownloads),
    cookiePolicy: policy.cookiePolicy || "ephemeral", isolatedSession: true };
}

// CAP-4: an element marked sensitive is redacted on its `name` as well as its
// `value`/`text`/`inputValue`. This function had exactly one caller before CAP-4
// (evidence.js, redacting a persona's own recorded action) and was never applied
// to the accessibility tree the walk produces -- an account menu's accessible
// name ("Signed in as jane.doe@example.com") is exactly as sensitive as a typed
// password, and `name` is the field a walked element's label actually arrives in
// (perceive.py reads `element.name or element.text`).
const SENSITIVE_FIELDS = ["value", "text", "inputValue", "name"];

function redactSensitive(value, key = "") {
  if (secretKey.test(key)) return "[REDACTED]";
  if (Array.isArray(value)) return value.map((item) => redactSensitive(item));
  if (value && typeof value === "object") {
    const sensitiveValue = value.sensitive === true || /^(password|hidden)$/i.test(value.inputType || value.type || "");
    return Object.fromEntries(Object.entries(value).map(([childKey, child]) =>
      [childKey, sensitiveValue && SENSITIVE_FIELDS.includes(childKey) ? "[REDACTED]" : redactSensitive(child, childKey)]));
  }
  return value;
}

/**
 * Mark elements a run was told to always treat as sensitive, by selector --
 * "a per-credential selector list (an account menu, an invoice table)": nothing
 * in a walked element's own data says an account-menu button or an invoice row
 * is sensitive, because no browser-native signal marks it so. This is the other
 * half of the redaction key alongside `redactSensitive`'s own `sensitive`/
 * `inputType` check, supplied by whoever configured the run rather than read off
 * the page. A selector not present on this page, or an absent list, is a no-op.
 */
function markSelectorsSensitive(elements, selectors) {
  if (!Array.isArray(elements) || !selectors?.length) return elements || [];
  const wanted = new Set(selectors);
  return elements.map((element) => (element && wanted.has(element.selector)
    ? { ...element, sensitive: true } : element));
}

function sanitizeUntrustedText(value, maxLength = 20_000) {
  const text = String(value || "").replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, " ").slice(0, maxLength);
  return `<untrusted_web_content>\n${text}\n</untrusted_web_content>`;
}

module.exports = { validateBrowserSafety, redactSensitive, markSelectorsSensitive, sanitizeUntrustedText, privateHost };
