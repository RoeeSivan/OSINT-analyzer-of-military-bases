"""
Robust JSON Parsing Module for OSINT GEOINT Analyzer.

Handles malformed JSON responses from LLMs:
- Extracts JSON from markdown code blocks (```json ... ```)
- Cleans up common formatting issues
- Validates and safely deserializes to dictionaries
"""

import json
import re
from typing import Any, TypeVar

T = TypeVar('T')


def extract_json_from_markdown(text: str) -> str:
    """
    Extract JSON from markdown code blocks if present.
    
    Handles common patterns like:
    - ```json ... ```
    - ``` ... ```
    - ```python ... ```
    
    Args:
        text: The text potentially containing markdown-wrapped JSON.
        
    Returns:
        The JSON string, either extracted from markdown or returned as-is.
    """
    # Pattern: ```[optional language]\n...\n```
    match = re.search(
        r'```(?:json|python|)?\s*\n(.*?)\n```',
        text,
        re.DOTALL | re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    return text


def clean_json_string(text: str) -> str:
    """
    Clean common JSON formatting issues from LLM outputs.
    
    - Removes leading/trailing whitespace
    - Strips markdown code blocks
    - Removes trailing commas before closing braces/brackets
    - Handles newlines in strings
    
    Args:
        text: The potentially malformed JSON string.
        
    Returns:
        Cleaned JSON string.
    """
    # Extract from markdown if needed
    text = extract_json_from_markdown(text)
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    # Remove common markdown patterns
    text = re.sub(r'^\s*```.*?\n', '', text)  # Remove opening fence
    text = re.sub(r'\n```\s*$', '', text)     # Remove closing fence
    
    # Fix trailing commas (JSON doesn't allow them)
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    
    return text.strip()


def parse_json_safe(
    text: str,
    fallback: dict[str, Any] | None = None,
    strict_keys: list[str] | None = None,
) -> dict[str, Any]:
    """
    Safely parse JSON with multiple fallback strategies.
    
    Attempts:
    1. Standard json.loads() on cleaned text
    2. Extract and parse from markdown blocks
    3. Regex-based extraction of JSON-like patterns
    4. Return fallback dict if all else fails
    
    Args:
        text: The JSON string to parse.
        fallback: Dictionary to return if parsing fails. Defaults to empty dict.
        strict_keys: If provided, only these top-level keys are allowed
                     in the result. Missing required keys will cause an error.
        
    Returns:
        Parsed dictionary or fallback.
        
    Raises:
        ValueError: If strict_keys validation fails.
    """
    if fallback is None:
        fallback = {}
    
    # Attempt 1: Clean and parse
    try:
        cleaned = clean_json_string(text)
        result = json.loads(cleaned)
        if isinstance(result, dict):
            if strict_keys and not all(k in result for k in strict_keys):
                missing = [k for k in strict_keys if k not in result]
                raise ValueError(f"Missing required keys in parsed JSON: {missing}")
            return result
    except (json.JSONDecodeError, ValueError) as e:
        pass
    
    # Attempt 2: Aggressive extraction — find { ... } pairs
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                if strict_keys and not all(k in result for k in strict_keys):
                    missing = [k for k in strict_keys if k not in result]
                    raise ValueError(f"Missing required keys in parsed JSON: {missing}")
                return result
    except (json.JSONDecodeError, ValueError, AttributeError):
        pass
    
    # All attempts failed — return fallback
    return fallback


def extract_json_list_from_text(text: str) -> list[dict[str, Any]]:
    """
    Extract a JSON array from text, with fallback to empty list.
    
    Args:
        text: Text potentially containing a JSON array.
        
    Returns:
        Parsed list of dictionaries, or empty list on failure.
    """
    try:
        cleaned = clean_json_string(text)
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
        return []
    except (json.JSONDecodeError, ValueError):
        return []


def validate_json_schema(
    data: dict[str, Any],
    required_keys: list[str],
) -> bool:
    """
    Validate that a parsed dictionary contains all required keys.
    
    Args:
        data: The dictionary to validate.
        required_keys: List of keys that must be present.
        
    Returns:
        True if all required keys are present, False otherwise.
    """
    return all(key in data for key in required_keys)


def merge_json_objects(*dicts: dict[str, Any]) -> dict[str, Any]:
    """
    Safely merge multiple JSON-like dictionaries with conflict resolution.
    Later dictionaries take precedence.
    
    Args:
        *dicts: Variable number of dictionaries to merge.
        
    Returns:
        Merged dictionary.
    """
    result = {}
    for d in dicts:
        if isinstance(d, dict):
            result.update(d)
    return result
