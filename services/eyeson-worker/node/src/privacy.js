"use strict";

const sensitiveKey = /(password|passwd|secret|token|authorization|cookie|api[-_]?key|card(number)?|cvv|ssn)/i;

function redactArtifact(value, key = "") {
  if (sensitiveKey.test(key)) return "[REDACTED]";
  if (Array.isArray(value)) return value.map((item) => redactArtifact(item));
  if (value && typeof value === "object") {
    const sensitiveValue = value.sensitive === true || /^(password|hidden)$/i.test(value.inputType || value.type || "");
    return Object.fromEntries(Object.entries(value).map(([childKey, child]) =>
      [childKey, sensitiveValue && ["value", "text", "inputValue"].includes(childKey) ? "[REDACTED]" : redactArtifact(child, childKey)]));
  }
  return value;
}

function retentionPolicy(kind, options = {}) {
  if (options.localOnly) return { storage: "local", expiresInDays: null, uploadAllowed: false };
  if (options.pinned) return { storage: "configured", expiresInDays: null, uploadAllowed: true };
  const raw = kind.startsWith("evidence.") || kind.startsWith("video.");
  return { storage: "configured", expiresInDays: raw ? 30 : 180, uploadAllowed: true };
}

module.exports = { redactArtifact, retentionPolicy };
