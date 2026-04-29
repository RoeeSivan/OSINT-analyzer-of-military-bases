"""
LLM Orchestration Module for OSINT GEOINT Analyzer.

Handles all LLM interactions:
- Analyst agents (GEOINT vision analysis with Gemini or OpenAI)
- Commander agent (intelligence synthesis and reporting)
- Robust JSON parsing for malformed LLM responses
"""

import base64
import json
from typing import Any

import google.generativeai as genai
from openai import OpenAI

from config import (
    GEMINI_API_KEY,
    GEMINI_ANALYST_MODEL,
    GEMINI_COMMANDER_MODEL,
    OPENAI_API_KEY,
    OPENAI_ANALYST_MODEL,
    OPENAI_COMMANDER_MODEL,
    LLM_PROVIDER,
)
from prompts import (
    GEOINT_RESPONSE_SCHEMA,
    COMMANDER_RESPONSE_SCHEMA,
    get_analyst_prompt_with_context,
    get_commander_prompt,
)
from json_parser import parse_json_safe


# Validate LLM configuration at module load time
if not GEMINI_API_KEY and LLM_PROVIDER == "gemini":
    raise ValueError("GEMINI_API_KEY not found in .env file")

if LLM_PROVIDER == "gemini":
    genai.configure(api_key=GEMINI_API_KEY)

openai_client = None
if LLM_PROVIDER == "openai":
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not found in .env (required when LLM_PROVIDER='openai')")
    openai_client = OpenAI(api_key=OPENAI_API_KEY)


def analyze_with_gemini(
    image_path: str,
    base_id: str,
    country: str,
    history: str | None = None,
    moondream_context: str | None = None,
) -> dict[str, Any]:
    """
    Analyze a satellite image using Gemini 2.5 Flash with vision capabilities.
    
    Args:
        image_path: Path to the JPEG image to analyze.
        base_id: Military base ID (for logging).
        country: Country name (for prompt context).
        history: Optional transcript of prior analysts' reports.
        moondream_context: Optional formatted string of object detector results.
        
    Returns:
        Dictionary with keys: findings, analysis, things_to_continue_analyzing, action.
        If analysis fails, returns a safe fallback dict with empty findings and
        action='finish'.
    """
    print(f"  Analyzing with {GEMINI_ANALYST_MODEL}...")
    
    try:
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
        
        prompt = get_analyst_prompt_with_context(
            country,
            moondream_context=moondream_context,
            history=history,
        )
        
        model = genai.GenerativeModel(GEMINI_ANALYST_MODEL)
        response = model.generate_content(
            [
                prompt,
                {"mime_type": "image/jpeg", "data": image_data},
            ],
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": GEOINT_RESPONSE_SCHEMA,
            },
        )
        
        analysis = parse_json_safe(
            response.text,
            fallback={
                "findings": [],
                "analysis": "Failed to parse LLM response",
                "things_to_continue_analyzing": [],
                "action": "finish",
            },
            strict_keys=["findings", "analysis", "things_to_continue_analyzing", "action"],
        )
        
        print(
            f"  ✓ Analysis complete — "
            f"action={analysis.get('action')}, "
            f"findings={len(analysis.get('findings', []))}"
        )
        return analysis
    
    except Exception as e:
        print(f"  ✗ Error analyzing with {GEMINI_ANALYST_MODEL}: {e}")
        return {
            "findings": [],
            "analysis": f"Error: {e}",
            "things_to_continue_analyzing": [],
            "action": "finish",
        }


def analyze_with_openai(
    image_path: str,
    base_id: str,
    country: str,
    history: str | None = None,
    moondream_context: str | None = None,
) -> dict[str, Any]:
    """
    Analyze a satellite image using OpenAI's vision API with JSON-schema enforcement.
    
    Args:
        image_path: Path to the JPEG image to analyze.
        base_id: Military base ID (for logging).
        country: Country name (for prompt context).
        history: Optional transcript of prior analysts' reports.
        moondream_context: Optional formatted string of object detector results.
        
    Returns:
        Dictionary with keys: findings, analysis, things_to_continue_analyzing, action.
        If analysis fails, returns a safe fallback dict with empty findings and
        action='finish'.
    """
    print(f"  Analyzing with {OPENAI_ANALYST_MODEL}...")
    
    try:
        with open(image_path, "rb") as image_file:
            image_b64 = base64.b64encode(image_file.read()).decode()
        
        prompt = get_analyst_prompt_with_context(
            country,
            moondream_context=moondream_context,
            history=history,
        )
        
        response = openai_client.chat.completions.create(
            model=OPENAI_ANALYST_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            }],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "geoint_analysis",
                    "strict": True,
                    "schema": GEOINT_RESPONSE_SCHEMA,
                },
            },
        )
        
        analysis = parse_json_safe(
            response.choices[0].message.content,
            fallback={
                "findings": [],
                "analysis": "Failed to parse LLM response",
                "things_to_continue_analyzing": [],
                "action": "finish",
            },
            strict_keys=["findings", "analysis", "things_to_continue_analyzing", "action"],
        )
        
        print(
            f"  ✓ Analysis complete — "
            f"action={analysis.get('action')}, "
            f"findings={len(analysis.get('findings', []))}"
        )
        return analysis
    
    except Exception as e:
        print(f"  ✗ Error analyzing with {OPENAI_ANALYST_MODEL}: {e}")
        return {
            "findings": [],
            "analysis": f"Error: {e}",
            "things_to_continue_analyzing": [],
            "action": "finish",
        }


def analyze_image(
    image_path: str,
    base_id: str,
    country: str,
    history: str | None = None,
    moondream_context: str | None = None,
) -> dict[str, Any]:
    """
    Analyze an image using the configured LLM provider (Gemini or OpenAI).
    
    This is the entry point for analyst logic — it routes to the correct
    provider based on LLM_PROVIDER configuration.
    
    Args:
        image_path: Path to the JPEG image to analyze.
        base_id: Military base ID (for logging).
        country: Country name (for prompt context).
        history: Optional transcript of prior analysts' reports.
        moondream_context: Optional formatted string of object detector results.
        
    Returns:
        Analyst response dictionary.
    """
    if LLM_PROVIDER == "openai":
        return analyze_with_openai(
            image_path, base_id, country,
            history=history, moondream_context=moondream_context,
        )
    else:
        return analyze_with_gemini(
            image_path, base_id, country,
            history=history, moondream_context=moondream_context,
        )


def synthesize_commander_report(
    analysts: list[dict[str, Any]],
    country: str,
    base_id: str,
) -> dict[str, Any]:
    """
    Synthesize 8 analyst reports into a single intelligence product using
    the commander agent (Gemini Pro or OpenAI).
    
    Args:
        analysts: List of analyst result dictionaries from all 8 analysts.
        country: Country name.
        base_id: Military base ID.
        
    Returns:
        Commander report dictionary with keys: executive_summary, 
        facility_classification, confidence, key_findings, threat_assessment,
        recommended_next_steps, disagreements_or_uncertainties.
        If synthesis fails, returns a safe fallback dict.
    """
    if LLM_PROVIDER == "openai":
        return _synthesize_commander_report_openai(analysts, country, base_id)
    else:
        return _synthesize_commander_report_gemini(analysts, country, base_id)


def _synthesize_commander_report_gemini(
    analysts: list[dict[str, Any]],
    country: str,
    base_id: str,
) -> dict[str, Any]:
    """
    Gemini implementation of commander synthesis.
    """
    from data_manager import format_analyst_history
    
    print(f"  Commander synthesizing {len(analysts)} analyst reports with {GEMINI_COMMANDER_MODEL}...")
    
    transcript = format_analyst_history(analysts)
    prompt = get_commander_prompt(country, base_id, transcript)
    
    try:
        model = genai.GenerativeModel(GEMINI_COMMANDER_MODEL)
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": COMMANDER_RESPONSE_SCHEMA,
            },
        )
        
        report = parse_json_safe(
            response.text,
            fallback={
                "executive_summary": "Analysis failed",
                "facility_classification": "Unknown",
                "confidence": "low",
                "key_findings": [],
                "threat_assessment": "Unable to synthesize report",
                "recommended_next_steps": [],
                "disagreements_or_uncertainties": [],
            },
            strict_keys=[
                "executive_summary", "facility_classification", "confidence",
                "key_findings", "threat_assessment", "recommended_next_steps",
                "disagreements_or_uncertainties",
            ],
        )
        
        print(
            f"  ✓ Commander report complete — "
            f"classification={report.get('facility_classification')}, "
            f"confidence={report.get('confidence')}"
        )
        return report
    
    except Exception as e:
        print(f"  ✗ Error generating commander report: {e}")
        return {
            "executive_summary": f"Error: {e}",
            "facility_classification": "Unknown",
            "confidence": "low",
            "key_findings": [],
            "threat_assessment": f"Commander synthesis failed: {e}",
            "recommended_next_steps": [],
            "disagreements_or_uncertainties": [],
        }


def _synthesize_commander_report_openai(
    analysts: list[dict[str, Any]],
    country: str,
    base_id: str,
) -> dict[str, Any]:
    """
    OpenAI implementation of commander synthesis.
    """
    from data_manager import format_analyst_history
    
    print(f"  Commander synthesizing {len(analysts)} analyst reports with {OPENAI_COMMANDER_MODEL}...")
    
    transcript = format_analyst_history(analysts)
    prompt = get_commander_prompt(country, base_id, transcript)
    
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_COMMANDER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "commander_report",
                    "strict": True,
                    "schema": COMMANDER_RESPONSE_SCHEMA,
                },
            },
        )
        
        report = parse_json_safe(
            response.choices[0].message.content,
            fallback={
                "executive_summary": "Analysis failed",
                "facility_classification": "Unknown",
                "confidence": "low",
                "key_findings": [],
                "threat_assessment": "Unable to synthesize report",
                "recommended_next_steps": [],
                "disagreements_or_uncertainties": [],
            },
            strict_keys=[
                "executive_summary", "facility_classification", "confidence",
                "key_findings", "threat_assessment", "recommended_next_steps",
                "disagreements_or_uncertainties",
            ],
        )
        
        print(
            f"  ✓ Commander report complete — "
            f"classification={report.get('facility_classification')}, "
            f"confidence={report.get('confidence')}"
        )
        return report
    
    except Exception as e:
        print(f"  ✗ Error generating commander report: {e}")
        return {
            "executive_summary": f"Error: {e}",
            "facility_classification": "Unknown",
            "confidence": "low",
            "key_findings": [],
            "threat_assessment": f"Commander synthesis failed: {e}",
            "recommended_next_steps": [],
            "disagreements_or_uncertainties": [],
        }
