"use strict";

function loadJourneyTest() {
  // The exact dependency is pinned. Keeping the import in this adapter prevents
  // package-specific shapes from leaking into HTTP/domain contracts.
  const core = require("@baguette-studios/journeytest-core");
  const runner = core.runJourney || core.default?.runJourney;
  if (typeof runner !== "function") {
    throw new Error("journeytest-core@0.1.2 does not expose runJourney; verify the installed package API before forking");
  }
  return runner;
}

async function runWithJourneyTest(input) {
  const runJourney = loadJourneyTest();
  const result = await runJourney({
    journey: { url: input.url, tasks: input.tasks },
    profile: { ...input.profile, simulation: input.profile },
    runId: input.runId,
    artifactDirectory: input.artifactDirectory,
  });
  return { ...result, profileId: input.profile.id, simulationProfile: input.profile };
}

module.exports = { loadJourneyTest, runWithJourneyTest };
