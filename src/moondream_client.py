"""
Moondream Cloud API Client for OSINT GEOINT Analyzer.

Handles all interactions with Moondream's vision API:
- Object detection (detect)
- Object pointing (point)
- Free-form questions (query)
- Image-to-dataURL conversion for API calls
"""

import base64
import requests
from typing import Any

from config import MOONDREAM_BASE_URL, MOONDREAM_HEADERS, MOONDREAM_TIMEOUT, MOONDREAM_ENABLED
from prompts import get_moondream_triage_question, get_moondream_point_target


def image_to_data_url(image_path: str) -> str:
    """
    Read a JPEG image file and convert to a base64 data URL.
    
    Args:
        image_path: Path to the JPEG image file.
        
    Returns:
        Data URL string: "data:image/jpeg;base64,..."
        
    Raises:
        FileNotFoundError: If the image file does not exist.
        IOError: If the file cannot be read.
    """
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()
    return f"data:image/jpeg;base64,{image_b64}"


def query(image_path: str, question: str) -> str:
    """
    Ask Moondream a free-form question about an image.
    
    Args:
        image_path: Path to the image file to analyze.
        question: The question to ask about the image.
        
    Returns:
        The text answer from Moondream.
        
    Raises:
        requests.RequestException: If the API call fails.
    """
    if not MOONDREAM_ENABLED:
        return ""
    
    payload = {
        "image_url": image_to_data_url(image_path),
        "question": question,
    }
    
    response = requests.post(
        f"{MOONDREAM_BASE_URL}/query",
        headers={**MOONDREAM_HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=MOONDREAM_TIMEOUT,
    )
    response.raise_for_status()
    
    return response.json().get("answer", "")


def detect(image_path: str, target: str) -> list[dict[str, float]]:
    """
    Detect objects of a specific class in an image.
    
    Returns bounding boxes: [{"x_min": 0.1, "y_min": 0.2, "x_max": 0.8, "y_max": 0.9}, ...]
    
    Args:
        image_path: Path to the image file to analyze.
        target: The object class to detect (e.g. "aircraft", "missile launcher").
        
    Returns:
        List of detected objects with bounding box coordinates [0, 1].
        
    Raises:
        requests.RequestException: If the API call fails.
    """
    if not MOONDREAM_ENABLED:
        return []
    
    payload = {
        "image_url": image_to_data_url(image_path),
        "object": target,
    }
    
    response = requests.post(
        f"{MOONDREAM_BASE_URL}/detect",
        headers={**MOONDREAM_HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=MOONDREAM_TIMEOUT,
    )
    response.raise_for_status()
    
    return response.json().get("objects", [])


def point(image_path: str, target: str) -> list[dict[str, float]]:
    """
    Point at instances of an object class in an image.
    
    Returns points: [{"x": 0.5, "y": 0.3}, ...]  with coordinates normalized [0, 1].
    
    Args:
        image_path: Path to the image file to analyze.
        target: The object to point at (e.g. "the most suspicious military target").
        
    Returns:
        List of pointed objects with normalized coordinates [0, 1].
        
    Raises:
        requests.RequestException: If the API call fails.
    """
    if not MOONDREAM_ENABLED:
        return []
    
    payload = {
        "image_url": image_to_data_url(image_path),
        "object": target,
    }
    
    response = requests.post(
        f"{MOONDREAM_BASE_URL}/point",
        headers={**MOONDREAM_HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=MOONDREAM_TIMEOUT,
    )
    response.raise_for_status()
    
    return response.json().get("points", [])


def triage_image(image_path: str) -> bool:
    """
    Determine if an image contains military targets worth a full LLM analysis.
    
    Returns True (fail-open) if Moondream is disabled or the query fails.
    
    Args:
        image_path: Path to the image to triage.
        
    Returns:
        True if the image likely contains targets, False otherwise.
    """
    if not MOONDREAM_ENABLED:
        return True
    
    try:
        answer = query(image_path, get_moondream_triage_question())
        verdict = "yes" in answer.lower()
        print(
            f"  Moondream triage: "
            f"{'YES (analyzing)' if verdict else 'NO (skipping)'} — "
            f"'{answer.strip()[:60]}'"
        )
        return verdict
    except Exception as e:
        print(f"  ⚠ Triage failed: {e} — proceeding with full analysis")
        return True


def detect_all_targets(
    image_path: str,
    detection_targets: list[str],
) -> list[dict[str, Any]]:
    """
    Run object detection for all target classes and return unified results.
    
    Args:
        image_path: Path to the image to analyze.
        detection_targets: List of object classes to detect.
        
    Returns:
        Flat list of detections: [{"label": "aircraft", "box": [x1, y1, x2, y2]}, ...]
    """
    if not MOONDREAM_ENABLED:
        return []
    
    detections = []
    for target in detection_targets:
        try:
            for obj in detect(image_path, target):
                detections.append({
                    "label": target,
                    "box": [obj["x_min"], obj["y_min"], obj["x_max"], obj["y_max"]],
                })
        except Exception as e:
            print(f"  ⚠ detect '{target}' failed: {e}")
    
    return detections


def format_detections_for_prompt(detections: list[dict[str, Any]]) -> str:
    """
    Format Moondream detections as a readable string for injection into LLM prompts.
    
    Args:
        detections: List of detection dictionaries with 'label' and 'box' fields.
        
    Returns:
        Human-readable formatted string.
    """
    if not detections:
        return "Moondream object detector found no targets in this frame."
    
    by_label = {}
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        by_label.setdefault(det["label"], []).append(((x1 + x2) / 2, (y1 + y2) / 2))
    
    lines = [
        "Moondream object detector flagged the following in this frame "
        "(coords normalized 0-1, origin top-left):"
    ]
    for label, points in sorted(by_label.items()):
        coords = ", ".join(f"({x:.2f},{y:.2f})" for x, y in points)
        lines.append(f"  - {len(points)}x {label}: {coords}")
    
    lines.append(
        "Use these as anchors but verify visually — the detector produces "
        "false positives and may miss subtle features."
    )
    
    return "\n".join(lines)


def point_to_most_suspicious_target(image_path: str) -> dict[str, float] | None:
    """
    Use Moondream's point API to identify the most suspicious target in an image.
    Used for smart zoom-in redirection.
    
    Args:
        image_path: Path to the image to analyze.
        
    Returns:
        A point dict {"x": float, "y": float} or None if pointing fails.
    """
    if not MOONDREAM_ENABLED:
        return None
    
    try:
        points = point(image_path, get_moondream_point_target())
        if points:
            return points[0]
    except Exception:
        pass
    
    return None
