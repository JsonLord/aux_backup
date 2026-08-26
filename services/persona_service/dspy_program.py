"""DSPy semantic program definitions, imported only when DSPy is installed/configured."""
import dspy


class CompileBehaviorProfile(dspy.Signature):
    """Convert a persona into web interaction priors; never infer impairments from demographics."""

    tiny_person: dict = dspy.InputField()
    scenario: str = dspy.InputField()
    patience: float = dspy.OutputField()
    persistence: float = dspy.OutputField()
    irritability: float = dspy.OutputField()
    anger_reactivity: float = dspy.OutputField()
    anger_recovery: float = dspy.OutputField()
    impulsivity: float = dspy.OutputField()
    ambiguity_tolerance: float = dspy.OutputField()
    failure_tolerance: float = dspy.OutputField()
    repeat_failure_tolerance: float = dspy.OutputField()
    self_efficacy: float = dspy.OutputField()
    digital_confidence: float = dspy.OutputField()
    help_seeking: float = dspy.OutputField()
    exploration: float = dspy.OutputField()
    verification_tendency: float = dspy.OutputField()
    risk_tolerance: float = dspy.OutputField()


def build_compiler():
    return dspy.Predict(CompileBehaviorProfile)
