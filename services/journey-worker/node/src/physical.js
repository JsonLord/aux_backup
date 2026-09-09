"use strict";
const { seededRandom } = require("./behavior");

const colorMatrices = {
  typical: [1, 0, 0, 0, 1, 0, 0, 0, 1],
  protanopia: [.567, .433, 0, .558, .442, 0, 0, .242, .758],
  deuteranopia: [.625, .375, 0, .7, .3, 0, 0, .3, .7],
  tritanopia: [.95, .05, 0, 0, .433, .567, 0, .475, .525],
};

function perceivedScreenshot(original, abilities, seed = 1) {
  const vision = abilities?.vision || {};
  const colorVision = vision.colorVision || "typical";
  return { artifactId: `${original.artifactId}_perceived_${seed}`, kind: "evidence.perceived_screenshot",
    contentType: original.contentType || "image/png", sourceArtifactId: original.artifactId,
    transform: { version: "perception-transform-v1", seed, colorVision,
      colorMatrix: colorMatrices[colorVision] || colorMatrices.typical,
      contrast: Number((vision.contrastSensitivity ?? 1).toFixed(3)),
      blurPx: Number(((1 - (vision.acuity ?? 1)) * 3).toFixed(3)) } };
}

function renderPerceivedSvg(original, abilities, seed = 1) {
  if (!original.url) throw new Error("original screenshot URL is required to render perceived pixels");
  const manifest = perceivedScreenshot(original, abilities, seed).transform;
  const matrix = manifest.colorMatrix;
  const values = `${matrix[0]} ${matrix[1]} ${matrix[2]} 0 0 ${matrix[3]} ${matrix[4]} ${matrix[5]} 0 0 ${matrix[6]} ${matrix[7]} ${matrix[8]} 0 0 0 0 0 1 0`;
  const safeUrl = String(original.url).replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${Number(original.width) || 1280}" height="${Number(original.height) || 720}"><filter id="perceived"><feColorMatrix type="matrix" values="${values}"/><feComponentTransfer><feFuncR type="linear" slope="${manifest.contrast}"/><feFuncG type="linear" slope="${manifest.contrast}"/><feFuncB type="linear" slope="${manifest.contrast}"/></feComponentTransfer><feGaussianBlur stdDeviation="${manifest.blurPx}"/></filter><image width="100%" height="100%" href="${safeUrl}" filter="url(#perceived)"/></svg>`;
}

async function materializePerceivedArtifact(original, abilities, seed, artifactWriter) {
  if (typeof artifactWriter !== "function") throw new Error("artifactWriter is required");
  return artifactWriter({ kind: "evidence.perceived_screenshot", contentType: "image/svg+xml",
    content: renderPerceivedSvg(original, abilities, seed), metadata: { sourceArtifactId: original.artifactId,
      transform: perceivedScreenshot(original, abilities, seed).transform } });
}

function readingDurationMs(text, abilities) {
  const words = String(text || "").trim().split(/\s+/).filter(Boolean).length;
  const wordsPerMinute = Math.max(30, Number(abilities?.reading?.wordsPerMinute) || 220);
  return Math.round(words / wordsPerMinute * 60000);
}

function filterWorkingMemory(facts, abilities) {
  const limit = Math.max(1, Math.floor(abilities?.cognition?.workingMemoryItems || 5));
  return facts.slice(-limit);
}

function simulatePointer(target, abilities, seed = 1) {
  const precision = Math.max(0, Math.min(1, abilities?.motor?.pointerPrecision ?? 1));
  const random = seededRandom(seed);
  const radius = (1 - precision) * Math.max(4, Math.min(target.width, target.height) / 2);
  return { x: Number((target.x + target.width / 2 + (random() * 2 - 1) * radius).toFixed(3)),
    y: Number((target.y + target.height / 2 + (random() * 2 - 1) * radius).toFixed(3)),
    seed, simulationVersion: "pointer-simulation-v1" };
}

module.exports = { perceivedScreenshot, renderPerceivedSvg, materializePerceivedArtifact,
  readingDurationMs, filterWorkingMemory, simulatePointer, colorMatrices };
