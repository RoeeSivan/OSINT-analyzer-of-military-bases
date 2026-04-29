"""
LLM Prompts and Response Schemas for OSINT GEOINT Analyzer.

Centralized repository for all long-form prompts and JSON schemas used by:
- Analyst agents (GEOINT vision analysis)
- Commander agent (intelligence synthesis)
"""

from typing import Final

# ========== Analyst Response Schema ==========
# Structured output for individual analyst reports
GEOINT_RESPONSE_SCHEMA: Final[dict] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "findings": {"type": "array", "items": {"type": "string"}},
        "analysis": {"type": "string"},
        "things_to_continue_analyzing": {"type": "array", "items": {"type": "string"}},
        "action": {
            "type": "string",
            "enum": ["zoom-in", "zoom-out", "move-left", "move-right", "finish"],
        },
    },
    "required": [
        "findings",
        "analysis",
        "things_to_continue_analyzing",
        "action"
    ],
}

# ========== Commander Response Schema ==========
# Structured output for the commander's intelligence synthesis
COMMANDER_RESPONSE_SCHEMA: Final[dict] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "executive_summary": {"type": "string"},
        "facility_classification": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "threat_assessment": {"type": "string"},
        "recommended_next_steps": {"type": "array", "items": {"type": "string"}},
        "disagreements_or_uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "executive_summary",
        "facility_classification",
        "confidence",
        "key_findings",
        "threat_assessment",
        "recommended_next_steps",
        "disagreements_or_uncertainties",
    ],
}


def get_analyst_prompt(country: str) -> str:
    """
    Generate the GEOINT analysis prompt for individual analysts.
    
    Args:
        country: The country where the military facility is located.
        
    Returns:
        The full system prompt for the analyst agent.
    """
    return f"""You are an expert in understanding satellite imagery and you work for the US army. We got intel that this area is a base/facility of the military of {country}. Analyze this image and respond ONLY with a JSON object containing the following keys:

1. 'findings': A list of findings that you think are important for the US army to know, including all man-made structures, military equipment, and infrastructure. We are trying to find which systems, weapons, or equipment are present so focus on that.
2. 'analysis': A detailed analysis of your findings.
3. 'things_to_continue_analyzing': A list of things that you think are important to continue analyzing in further images.
4. 'action': One of ['zoom-in', 'zoom-out', 'move-left', 'move-right', 'finish'] based on what would help you analyze the image or area better.
- Choose 'zoom-in' if you need to zoom in the image
- Choose 'zoom-out' if you need more context of the surrounding area or if you are zoomed in too much
- Choose 'move-left' or 'move-right' if you suspect there are important features just outside the current view
- Choose 'finish' if you have a complete understanding of the location

Return ONLY the JSON object, no markdown fences, no preamble, no trailing commentary.

If imagery is unusable (cloud cover, blank tile, solid color, no visible ground features), set findings=[], put the reason in analysis, and set action='zoom-out'."""


def get_analyst_prompt_with_context(
    country: str,
    moondream_context: str | None = None,
    history: str | None = None,
) -> str:
    """
    Generate the GEOINT analysis prompt with optional context from prior analysts
    and Moondream detections.
    
    Args:
        country: The country where the facility is located.
        moondream_context: Optional formatted string of Moondream object detections.
        history: Optional formatted transcript of prior analysts' findings.
        
    Returns:
        The full analyst prompt with context injected.
    """
    prompt = get_analyst_prompt(country)
    
    if moondream_context:
        prompt += f"\n\nObject detector context:\n{moondream_context}"
    
    if history:
        prompt += (
            "\n\nHere is the analysis of previous analysts about this area and their "
            "recommendations. You can use this data but don't use it as fact, think "
            "for yourself:\n\n"
            f"{history}"
        )
    
    return prompt


def get_commander_prompt(
    country: str,
    base_id: str,
    analyst_transcript: str,
) -> str:
    """
    Generate the intelligence synthesis prompt for the commander agent.
    
    Args:
        country: The country where the facility is located.
        base_id: The unique identifier of the base being analyzed.
        analyst_transcript: Formatted transcript of all 8 analysts' reports.
        
    Returns:
        The full commander synthesis prompt.
    """
    return f"""You are a senior military intelligence commander. Intel suggests the location in {country} (site ID {base_id}) is an enemy military facility. Eight analysts have independently examined satellite imagery from different zoom levels and positions — each saw a different frame, and later analysts were shown earlier analysts' notes but told not to treat them as fact.

Your job: synthesize their observations into a single authoritative intelligence report a field commander can act on. Analysts may disagree, overfit to small details, or miss the bigger picture. Reconcile the evidence, weight findings by how many analysts corroborated them, and produce a clear assessment.

Here is the full transcript of the analysts' findings (each block is one analyst):

{analyst_transcript}

Respond ONLY with a JSON object with these keys:
- executive_summary: 1-3 sentence tl;dr of what this facility is and why it matters to the US army.
- facility_classification: short concrete label for the facility type (e.g. "Air Base", "Surface-to-Air Missile Site", "Naval Port", "Radar Station", "Army Garrison", "Storage Depot", "Unknown"). Pick one.
- confidence: one of ["low", "medium", "high"] — how confident you are in the classification given the evidence.
- key_findings: 3-7 consolidated findings as single sentences, ordered by military significance (most important first). Consolidate duplicates across analysts.
- threat_assessment: one paragraph covering offensive/defensive capability, operational readiness indicators, and the reasoning behind your threat judgment.
- recommended_next_steps: concrete follow-up actions (e.g. "request high-resolution SAR imagery of the eastern perimeter", "monitor hangar activity over 72h for aircraft movement", "cross-reference with SIGINT on frequencies X-Y MHz").
- disagreements_or_uncertainties: points where analysts diverged or where evidence was ambiguous. If the analysts were fully consistent, return [].

Rules:
- Do not invent findings not supported by any analyst.
- A single analyst's isolated claim is weaker evidence than a finding repeated by multiple analysts — weight accordingly.
- Be specific, not generic. "Possible SAM site" is better than "possible military asset".
- Return ONLY the JSON object — no markdown fences, no preamble, no trailing commentary."""


def get_moondream_triage_question() -> str:
    """
    Get the triage question used to pre-filter whether an image has military targets.
    
    Returns:
        The triage question for Moondream.
    """
    return (
        "Are there any man-made structures, vehicles, or military equipment "
        "in this image? Answer with only 'yes' or 'no'."
    )


def get_moondream_point_target() -> str:
    """
    Get the target object description used for Moondream's point-finding feature.
    Used to identify the most suspicious military target for smart zoom-in.
    
    Returns:
        The target description for Moondream.point().
    """
    return "the most suspicious military target or unusual man-made structure"
