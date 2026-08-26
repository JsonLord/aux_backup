"use strict";

class BehaviorController {
  constructor(profile) {
    this.profile = profile;
    this.state = { frustration: 0, trust: 1, effort: 0, failures: 0, abandoned: false };
  }

  apply(event) {
    const behavior = this.profile.behavior;
    if (event.outcome === "failure") {
      this.state.failures += 1;
      this.state.effort = Math.min(1, this.state.effort + 0.2);
      this.state.frustration = Number(Math.min(1, this.state.frustration + 0.15 + behavior.irritability * 0.2).toFixed(6));
      this.state.trust = Math.max(0, this.state.trust - 0.1);
    } else {
      this.state.frustration = Number(Math.max(0, this.state.frustration - behavior.angerRecovery * 0.1).toFixed(6));
      this.state.trust = Math.min(1, this.state.trust + 0.04);
    }
    const tolerance = this.state.failures > 1 ? behavior.repeatFailureTolerance : behavior.failureTolerance;
    this.state.abandoned = this.state.failures > 0 && this.state.frustration > tolerance && behavior.persistence < 0.5;
    return { ...this.state };
  }

  copingDecision() {
    if (this.state.abandoned) return "abandon";
    if (this.state.failures && this.profile.behavior.helpSeeking > 0.6) return "seek_help";
    if (this.state.failures) return "retry";
    return "continue";
  }
}

module.exports = { BehaviorController };
