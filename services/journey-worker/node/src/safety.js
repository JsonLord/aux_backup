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

function redactSensitive(value, key = "") {
  if (secretKey.test(key)) return "[REDACTED]";
  if (Array.isArray(value)) return value.map((item) => redactSensitive(item));
  if (value && typeof value === "object") {
    const sensitiveValue = value.sensitive === true || /^(password|hidden)$/i.test(value.inputType || value.type || "");
    return Object.fromEntries(Object.entries(value).map(([childKey, child]) =>
      [childKey, sensitiveValue && ["value", "text", "inputValue"].includes(childKey) ? "[REDACTED]" : redactSensitive(child, childKey)]));
  }
  return value;
}

function sanitizeUntrustedText(value, maxLength = 20_000) {
  const text = String(value || "").replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, " ").slice(0, maxLength);
  return `<untrusted_web_content>\n${text}\n</untrusted_web_content>`;
}

module.exports = { validateBrowserSafety, redactSensitive, sanitizeUntrustedText, privateHost };
