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

// How far a hand with no precision at all strays from where it was aimed, in CSS
// pixels. Chosen against WCAG 2.5.5, which asks for targets of 44x44: at this
// scatter a 44px control is hit nearly always, a 24px one often missed, and a
// 16px icon missed more often than not.
const POINTER_SCATTER_PX = 24;

/**
 * Where this person's pointer actually lands when aiming at something.
 *
 * The scatter is a property of the movement, not of the target. Scaling it to
 * the target -- as this did, at half the smaller dimension -- said that a person
 * aims more precisely at a small button, and made every control larger than 8px
 * impossible to miss. That is backwards, and it quietly guaranteed that no
 * pointer-precision simulation could ever surface an undersized-target problem,
 * which is the one thing it exists to find.
 */
function simulatePointer(target, abilities, seed = 1) {
  const precision = Math.max(0, Math.min(1, abilities?.motor?.pointerPrecision ?? 1));
  const random = seededRandom(seed);
  const radius = (1 - precision) * POINTER_SCATTER_PX;
  return { x: Number((target.x + target.width / 2 + (random() * 2 - 1) * radius).toFixed(3)),
    y: Number((target.y + target.height / 2 + (random() * 2 - 1) * radius).toFixed(3)),
    seed, radius: Number(radius.toFixed(3)), simulationVersion: "pointer-simulation-v2" };
}

module.exports = { POINTER_SCATTER_PX, perceivedScreenshot, renderPerceivedSvg,
  materializePerceivedArtifact, readingDurationMs, filterWorkingMemory, simulatePointer,
  colorMatrices };
