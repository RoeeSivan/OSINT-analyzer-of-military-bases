"""
Data Management Module for OSINT GEOINT Analyzer.

Handles persistent data operations:
- CSV reading for military base coordinates
- JSON persistence for analysis results
- Atomic writes to prevent data loss on crash
"""

import csv
import json
import os
from typing import Any

from config import DATA_JSON_PATH, DATA_DIR, CSV_PATH


def read_military_bases_csv(csv_path: str = CSV_PATH) -> list[dict[str, str]]:
    """
    Read military base coordinates and metadata from CSV file.
    
    Expected columns: id, country, latitude, longitude
    
    Args:
        csv_path: Path to the CSV file (default: military_bases.csv).
        
    Returns:
        List of base dictionaries with keys: id, country, latitude, longitude.
        
    Raises:
        FileNotFoundError: If the CSV file does not exist.
        csv.Error: If the CSV is malformed.
    """
    with open(csv_path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_data_json(json_path: str = DATA_JSON_PATH) -> list[dict[str, Any]]:
    """
    Load the persistent analysis results from JSON file.
    
    Returns empty list if the file does not exist. Raises immediately if
    the JSON is malformed — we fail-fast to avoid silently overwriting
    a user's prior results.
    
    Args:
        json_path: Path to the data JSON file.
        
    Returns:
        List of base analysis result dictionaries.
        
    Raises:
        json.JSONDecodeError: If the JSON file is malformed.
    """
    if not os.path.exists(json_path):
        return []
    
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data_json(
    entries: list[dict[str, Any]],
    json_path: str = DATA_JSON_PATH,
) -> None:
    """
    Atomically persist analysis results to JSON file.
    
    Writes to a temporary .tmp file first, then renames to avoid leaving
    a half-written JSON if the process is killed mid-write.
    
    Args:
        entries: List of base analysis result dictionaries.
        json_path: Path where the data JSON should be saved.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path = json_path + ".tmp"
    
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    
    os.replace(tmp_path, json_path)


def format_analyst_history(analysts: list[dict[str, Any]]) -> str:
    """
    Format prior analysts' reports as a readable transcript for injection
    into the next analyst's prompt.
    
    Args:
        analysts: List of analyst result dictionaries.
        
    Returns:
        Formatted transcript string with one block per analyst.
    """
    blocks = []
    for a in analysts:
        inner = a["analysis"]
        blocks.append(
            f"--- Analyst {a['analyst_num']} (view #{a['view_idx']}) ---\n"
            f"findings: {json.dumps(inner['findings'], ensure_ascii=False)}\n"
            f"analysis: {inner['analysis']}\n"
            f"things_to_continue_analyzing: "
            f"{json.dumps(inner['things_to_continue_analyzing'], ensure_ascii=False)}\n"
            f"recommended_action: {inner['action']}"
        )
    return "\n\n".join(blocks)
