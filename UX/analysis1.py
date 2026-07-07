"""
AI-powered analysis pipeline for UI/UX feedback.

This module orchestrates the analysis of screenshots and canvases using OpenAI vision models:

Analysis types:
    1. Primary analysis: Load-stage canvases → UI/UX observations
       - Layout, spacing, alignment, grid adherence
       - Typography, color balance, hierarchy
       - Loading states and perceived performance
       - Accessibility cues
    
    2. Compatibility analysis: Cross-browser comparison
       - Visual differences between reference and candidate browsers
       - Likely engine-specific causes (flexbox, grid, font-metrics, etc.)
       - Minimal fix recommendations

Prompt construction:
    - Loads prompt templates from prompts/ directory
    - Includes code context for developer-oriented suggestions
    - Adds URL-specific additional_considerations if provided
    - Builds multi-message conversation with proper context

Output:
    - Structured JSON matching defined schemas
    - Schema validation with jsonschema
    - Per-URL analysis reports saved to reports/ directory
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema import ValidationError, validate

from .openai_client import analyze_images
from .types import AnalysisResultRef, CanvasMeta
from .utils import now_utc_iso, read_text

log = logging.getLogger("frontend_support")


def _load_schema(name: str) -> Dict[str, Any]:
    """Load JSON schema from schemas directory relative to this file."""
    try:
        # Use __file__ to get path relative to this module
        schemas_dir = Path(__file__).parent / "schemas"
        schema_path = schemas_dir / name
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema not found: {schema_path}")
        with schema_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to load schema {name}: {e}") from e


def _load_prompt(name: str, default_text: Optional[str] = None) -> str:
    """Load prompt from prompts directory relative to this file."""
    try:
        # Use __file__ to get path relative to this module
        prompts_dir = Path(__file__).parent / "prompts"
        prompt_path = prompts_dir / name
        if not prompt_path.exists():
            if default_text is not None:
                log.warning("Prompt %s not found; using default.", name)
                return default_text
            raise FileNotFoundError(f"Prompt not found: {prompt_path}")
        with prompt_path.open("r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        if default_text is not None:
            log.warning("Prompt %s not found; using default.", name)
            return default_text
        raise RuntimeError(f"Failed to load prompt {name}: {e}") from e


def _group_primary_canvases_by_slug(canvases: List[CanvasMeta]) -> Dict[str, List[CanvasMeta]]:
    grouped: Dict[str, List[CanvasMeta]] = defaultdict(list)
    for c in canvases:
        if c.get("kind") != "load":
            continue
        slug = c.get("slug", "")
        grouped[slug].append(c)
    # Sort each group for determinism by resolution label
    for slug in grouped:
        grouped[slug].sort(key=lambda x: x.get("resolution_label", ""))
    return grouped


def run_primary_analysis(
    *,
    project,
    canvases: List[CanvasMeta],
    captures: Optional[Dict[str, Any]] = None,
    code_context_path: Optional[str],
    openai_cfg,
    out_dir: Path,
) -> List[AnalysisResultRef]:
    """
    Analyze load-stage canvases per URL (slug). Send up to max_images_per_request images
    per request; if more, chunk and merge observations.
    Optionally extracts and includes full_screen captures if available in captures data.
    """
    schema = _load_schema("primary.schema.json")
    prompt_template = _load_prompt(
        "primary.md",
        default_text=(
            "You are an expert UI/UX reviewer. Analyze the provided canvases showing page load "
            "progress across device resolutions. Focus ONLY on layout, spacing, alignment, "
            "grid adherence, truncation, typography, color balance/contrast, hierarchy, perceived loading, "
            "and accessibility cues. Ignore content semantics.\n"
            "Return JSON strictly matching the required schema."
        ),
    )

    grouped = _group_primary_canvases_by_slug(canvases)
    ensure_dir = out_dir.mkdir(parents=True, exist_ok=True)

    # Extract full_screen captures by slug if available
    full_screen_by_slug: Dict[str, List[Dict[str, Any]]] = {}
    if captures:
        by_url = captures.get("by_url", {})
        for slug, entry in by_url.items():
            res_groups = entry.get("resolutions", {})
            full_screens = []
            for res_label, shots in res_groups.items():
                for shot in shots:
                    if shot.get("is_full_screen", False):
                        full_screens.append(shot)
            if full_screens:
                full_screen_by_slug[slug] = full_screens

    # Build mapping of URL -> additional_considerations from project config
    url_considerations: Dict[str, str] = {}
    if hasattr(project, 'urls'):
        for url_spec in project.urls:
            if url_spec.additional_considerations:
                url_considerations[url_spec.url] = url_spec.additional_considerations

    results: List[AnalysisResultRef] = []
    for slug, items in grouped.items():
        url = items[0].get("url", "")
        project_name = items[0].get("project", getattr(project, "project", ""))
        res_labels = [i.get("resolution_label", "") for i in items]
        paths = [i.get("path", "") for i in items if i.get("path")]
        paths = [p for p in paths if p]

        # Build prompt with context and expectations
        ctx = ""
        if code_context_path:
            ctx_text = read_text(Path(code_context_path))
            if ctx_text:
                ctx = "\n\nDeveloper context (selected source excerpts):\n" + ctx_text[:20000]

        # Build base prompt
        base_prompt = (
            f"Project: {project_name}\n"
            f"URL: {url}\n"
            f"Resolutions: {', '.join(res_labels)}\n\n"
            f"{prompt_template}\n"
            f"{ctx}"
        )
        
        # Add additional considerations if specified for this URL
        additional_considerations_text = url_considerations.get(url)
        if additional_considerations_text:
            prompt = (
                f"{base_prompt}\n\n"
                f"=== SPECIFIC REQUEST FROM PROJECT OWNER ===\n"
                f"The project owner has requested special attention to the following considerations for this URL:\n\n"
                f"{additional_considerations_text}\n\n"
                f"Please ensure your analysis and recommendations carefully address these specific concerns."
            )
        else:
            prompt = base_prompt

        # For GPT-5: send individual canvases with metadata (max 20 images)
        # Build metadata for each canvas
        image_metadata = []
        for item in items:
            image_metadata.append({
                "browser": item.get("browser", "unknown"),
                "resolution": item.get("resolution_label", "unknown"),
                "label": item.get("resolution_label", f"canvas-{item.get('kind', 'load')}")
            })
        
        # Extract full_screen images for this slug
        full_screen_images = []
        full_screen_metadata = []
        if slug in full_screen_by_slug:
            for fs in full_screen_by_slug[slug]:
                full_screen_images.append(fs.get("path", ""))
                full_screen_metadata.append({
                    "browser": fs.get("browser", "unknown"),
                    "resolution": fs.get("resolution_label", "unknown"),
                    "label": f"Full-page {fs.get('resolution_label', 'unknown')}"
                })
        
        # GPT-5 can handle up to 20 images - use all canvases + full_screen + code context
        data = analyze_images(
            model=getattr(openai_cfg, "model", "gpt-5"),
            prompt_text=prompt,
            images=paths[:20],  # Limit to 20 for GPT-5
            image_metadata=image_metadata[:20],
            canvas_image=None,  # No separate canvas in this case
            full_screen_images=full_screen_images if full_screen_images else None,
            full_screen_metadata=full_screen_metadata if full_screen_metadata else None,
            code_context=ctx if ctx else None,
            response_schema=schema,
            reasoning_effort=getattr(openai_cfg, "reasoning_effort", "medium"),
            verbosity=getattr(openai_cfg, "verbosity", "medium"),
            max_output_tokens=getattr(openai_cfg, "max_output_tokens", 4096),
            timeout_s=getattr(openai_cfg, "request_timeout_s", 120),
        )
        
        # Validate response
        try:
            validate(instance=data, schema=schema)
        except ValidationError as ve:
            log.warning("Primary analysis schema validation failed for slug=%s: %s", slug, ve)
        
        merged = data

        # Save
        out_path = out_dir / f"primary_{slug}.json"
        try:
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            results.append(
                AnalysisResultRef(
                    path=str(out_path),
                    kind="primary",
                    url=url,
                    project=project_name,
                    slug=slug,
                    model=getattr(openai_cfg, "model", "gpt-4o"),
                )
            )
            log.info("Saved primary analysis: %s", out_path)
        except Exception as e:
            log.exception("Failed to save primary analysis for slug=%s: %s", slug, e)

    return results


def _find_reference_for_candidate(canvas: CanvasMeta) -> Optional[str]:
    ref = canvas.get("reference_path")
    if isinstance(ref, str) and ref:
        return ref
    # Fallback search: look in parent dir
    try:
        cpath = Path(canvas["path"])
        for p in cpath.parent.glob("*.png"):
            if "__compat-ref__" in p.name and f"__{canvas.get('slug','')}__" in p.name:
                return str(p)
    except Exception:
        pass
    return None


def run_compatibility_analysis(
    *,
    project,
    candidate_canvases: List[CanvasMeta],
    openai_cfg,
    out_dir: Path,
) -> List[AnalysisResultRef]:
    """
    For each candidate canvas (per URL and browser), compare against the reference canvas
    and produce a structured diff report.
    """
    # Try to load compatibility prompt; fallback if missing
    prompt_template = _load_prompt(
        "compatibility.md",
        default_text=(
            "Compare the two canvases (reference on Chrome/Chromium vs candidate on another browser) "
            "across the same set of resolutions. Identify visible differences that likely stem from "
            "browser/engine behavior. For each diff, provide: resolution label, concise description, "
            "probable cause category (e.g., flexbox, grid, font-metrics, subpixel-rounding, overflow, etc.), "
            "and a minimal recommendation to resolve. Return JSON per the schema."
        ),
    )
    schema = _load_schema("compatibility.schema.json")

    out_dir.mkdir(parents=True, exist_ok=True)
    results: List[AnalysisResultRef] = []
    by_slug_browser: Dict[tuple, List[CanvasMeta]] = {}
    # candidate canvases are already one per browser per slug, but guard anyway
    for c in candidate_canvases:
        key = (c.get("slug", ""), c.get("browser", ""))
        by_slug_browser.setdefault(key, []).append(c)

    for (slug, browser), lst in by_slug_browser.items():
        canvas = lst[0]
        url = canvas.get("url", "")
        project_name = canvas.get("project", getattr(project, "project", ""))
        ref_path = _find_reference_for_candidate(canvas)
        if not ref_path:
            log.warning("No reference canvas found for compatibility analysis slug=%s", slug)
            continue
        cand_path = canvas.get("path", "")
        if not cand_path or not Path(cand_path).exists():
            log.warning("Candidate canvas missing for slug=%s browser=%s", slug, browser)
            continue

        prompt = (
            f"Project: {project_name}\n"
            f"URL: {url}\n"
            f"Reference: Chrome/Chromium (assumed from primary)\n"
            f"Candidate: {browser}\n\n"
            f"{prompt_template}"
        )

        # Build metadata for reference and candidate
        image_metadata = [
            {"browser": "chromium (reference)", "resolution": "multi-resolution", "label": "Reference"},
            {"browser": browser, "resolution": "multi-resolution", "label": "Candidate"}
        ]
        
        data = analyze_images(
            model=getattr(openai_cfg, "model", "gpt-5"),
            prompt_text=prompt,
            images=[ref_path, cand_path],
            image_metadata=image_metadata,
            canvas_image=None,
            code_context=None,
            response_schema=schema,
            reasoning_effort=getattr(openai_cfg, "reasoning_effort", "medium"),
            verbosity=getattr(openai_cfg, "verbosity", "medium"),
            max_output_tokens=getattr(openai_cfg, "max_output_tokens", 4096),
            timeout_s=getattr(openai_cfg, "request_timeout_s", 120),
        )

        try:
            validate(instance=data, schema=schema)
        except ValidationError as ve:
            log.warning("Compatibility analysis schema validation failed for slug=%s browser=%s: %s", slug, browser, ve)

        out_path = out_dir / f"compat_{browser}_{slug}.json"
        try:
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            results.append(
                AnalysisResultRef(
                    path=str(out_path),
                    kind="compat",
                    url=url,
                    project=project_name,
                    slug=slug,
                    browser=browser,
                    model=getattr(openai_cfg, "model", "gpt-4o"),
                )
            )
            log.info("Saved compatibility analysis: %s", out_path)
        except Exception as e:
            log.exception("Failed to save compatibility analysis for slug=%s browser=%s: %s", slug, browser, e)

    return results
