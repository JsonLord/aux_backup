"use strict";
const { BehaviorController } = require("./behavior");

function replayFromEvidence(input) {
  if (!input.profile?.behavior || !Array.isArray(input.evidence)) {
    throw new Error("profile.behavior and evidence are required for replay");
  }
  const controller = new BehaviorController(input.profile);
  const transitions = input.evidence.map((item, index) => {
    const event = item.event || item.behavior?.events?.[0];
    if (!event?.type) throw new Error(`evidence[${index}] has no normalized experience event`);
    return controller.apply(event, item.context || {});
  });
  return { schemaVersion: "1.0", replayId: input.replayId, sourceRunId: input.sourceRunId,
    mode: "evidence_without_browser", profileId: input.profile.id, transitions,
    versions: { reducer: transitions[0]?.reducerVersion || "behavior-state-v1",
      coping: transitions[0]?.coping.policyVersion || "coping-policy-v1" } };
}

module.exports = { replayFromEvidence };
