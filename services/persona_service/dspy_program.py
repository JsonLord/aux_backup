"""DSPy semantic program definitions, imported only when DSPy is installed/configured."""
import os

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


class CompileAbilityProfile(dspy.Signature):
    """Compile functional/perceptual ability priors (vision, motor, cognition, reading) for a
    synthetic web user, representing realistic population-wide statistical diversity. Sample as if
    drawing independently from general population statistics. Never infer, correlate, or condition
    any value on the persona's age, gender, occupation, or any other demographic or biographical
    detail -- that would encode harmful stereotypes (e.g. assuming an older persona has worse
    vision). Most people are within typical ranges; only a realistic minority should deviate
    meaningfully."""

    tiny_person: dict = dspy.InputField()
    scenario: str = dspy.InputField()

    color_vision: str = dspy.OutputField(desc='one of "typical", "protanopia", "deuteranopia", "tritanopia"')
    acuity: float = dspy.OutputField(desc="0 to 1, 1 is normal visual acuity")
    contrast_sensitivity: float = dspy.OutputField(desc="0 to 1, 1 is normal contrast sensitivity")
    glare_sensitivity: float = dspy.OutputField(desc="0 to 1, higher is more sensitive to glare/brightness")
    pointer_precision: float = dspy.OutputField(desc="0 to 1, 1 is precise mouse/touch pointing")
    movement_speed: float = dspy.OutputField(desc="0 to 1, 1 is fast pointer movement")
    drag_reliability: float = dspy.OutputField(desc="0 to 1, 1 is reliable drag-and-drop")
    processing_speed: float = dspy.OutputField(desc="0 to 1, 1 is fast cognitive processing of new UI")
    working_memory_items: int = dspy.OutputField(desc="1 to 12, typical adult is 5 to 9")
    distraction_susceptibility: float = dspy.OutputField(desc="0 to 1, higher is more easily distracted")
    words_per_minute: int = dspy.OutputField(desc="60 to 500, typical adult reading speed is 200 to 260")
    compensatory_strategies: list[str] = dspy.OutputField(
        desc="short list of coping strategies implied by the other values (e.g. relying on icons over "
             "color); empty list if none apply")


def build_compiler():
    return dspy.Predict(CompileBehaviorProfile)


def build_ability_compiler():
    return dspy.Predict(CompileAbilityProfile)


_lm_configured = False


def _max_completion_tokens():
    raw = os.getenv("OPENAI_MAX_COMPLETION_TOKENS")
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def configure_lm(force: bool = False):
    """Idempotently configure DSPy's global LM from the same OPENAI_* settings used
    elsewhere in this service (services/persona_service/generator.py), so DSPy
    targets the same OpenAI-compatible endpoint (self-hosted router; BLABLADOR_*
    names remain supported as legacy aliases) rather than a public OpenAI account.

    Uses litellm's ``openai/<model>`` provider prefix (DSPy 3.x resolves LMs
    through litellm), which routes the call as a plain OpenAI-compatible chat
    completion against the given ``api_base`` instead of assuming api.openai.com.
    """
    global _lm_configured
    if _lm_configured and not force:
        return
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("BLABLADOR_API_KEY")
    base_url = (os.getenv("OPENAI_COMPATIBLE_ENDPOINT") or os.getenv("OPENAI_BASE_URL")
                or os.getenv("BLABLADOR_BASE_URL") or "https://debian-devil.tail3f341b.ts.net/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "auto")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY or BLABLADOR_API_KEY is required to configure DSPy")
    lm_kwargs = {"api_base": base_url, "api_key": api_key, "temperature": 0}
    max_completion_tokens = _max_completion_tokens()
    if max_completion_tokens is not None:
        lm_kwargs["max_tokens"] = max_completion_tokens
    lm = dspy.LM(f"openai/{model}", **lm_kwargs)
    dspy.configure(lm=lm)
    _lm_configured = True
