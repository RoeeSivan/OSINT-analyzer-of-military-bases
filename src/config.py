"""
Configuration module for OSINT GEOINT Analyzer.

Centralized constants for the entire application:
- Directories and paths
- LLM configuration
- Processing parameters
- Detection targets
"""

import os
from dotenv import load_dotenv
from typing import Final

# Load environment variables
load_dotenv()

# ========== Directories ==========
OUTPUT_DIR: Final[str] = "screenshots"
DATA_DIR: Final[str] = "data"
DATA_JSON_PATH: Final[str] = os.path.join(DATA_DIR, "data.json")

# ========== CSV Configuration ==========
CSV_PATH: Final[str] = "military_bases.csv"

# ========== Processing Parameters ==========
ROWS_TO_PROCESS: Final[int] = 10
NUM_ANALYSTS: Final[int] = 8
SCREENSHOT_WIDTH: Final[int] = 1024

# ========== View Navigation Parameters ==========
INITIAL_ZOOM_RANGE: Final[float] = 2000  # meters
ZOOM_FACTOR: Final[float] = 2.0
MIN_ZOOM_RANGE: Final[float] = 100  # meters
MAX_ZOOM_RANGE: Final[float] = 50000  # meters
MOVE_FRACTION: Final[float] = 0.6

# ========== Image Processing ==========
UI_MARGIN_CROP_PERCENT: Final[int] = 8  # Remove 8% margins to eliminate UI chrome
IMAGE_QUALITY: Final[int] = 85  # JPEG quality

# ========== Google Earth URLs ==========
GOOGLE_EARTH_URL_TEMPLATE: Final[str] = (
    "https://earth.google.com/web/@{lat},{lon},0a,{range}d,35y,0h,0t,0r"
)
GOOGLE_EARTH_SEARCH_URL_TEMPLATE: Final[str] = (
    "https://earth.google.com/web/search/{encoded_lat},{encoded_lon}/"
    "@{lat},{lon},{alt}a,{range}d,35y,0h,0t,0r"
)

# ========== LLM Provider Configuration ==========
LLM_PROVIDER: Final[str] = "openai"  # "gemini" or "openai"

# Gemini Configuration
GEMINI_API_KEY: Final[str | None] = os.getenv("GEMINI_API_KEY")
GEMINI_ANALYST_MODEL: Final[str] = "gemini-2.5-flash"
GEMINI_COMMANDER_MODEL: Final[str] = "gemini-2.5-pro"

# OpenAI Configuration
OPENAI_API_KEY: Final[str | None] = os.getenv("OPENAI_API_KEY")
OPENAI_ANALYST_MODEL: Final[str] = "gpt-5"
OPENAI_COMMANDER_MODEL: Final[str] = "gpt-5"

# ========== Moondream Configuration ==========
MOONDREAM_BASE_URL: Final[str] = "https://api.moondream.ai/v1"
MOONDREAM_API_KEY: Final[str | None] = os.getenv("MOONDREAM_API_KEY")
MOONDREAM_ENABLED: Final[bool] = bool(MOONDREAM_API_KEY)
MOONDREAM_TIMEOUT: Final[int] = 60  # seconds
MOONDREAM_HEADERS: Final[dict[str, str]] = {"X-Moondream-Auth": MOONDREAM_API_KEY or ""}

DETECTION_TARGETS: Final[list[str]] = [
    "aircraft", "helicopter", "hangar", "runway",
    "naval ship", "armored vehicle", "truck",
    "missile launcher", "radar dish", "satellite dish",
    "watchtower", "fuel tank",
]

# ========== Browser Configuration ==========
BROWSER_WAIT_TIMEOUT: Final[int] = 40  # seconds
CANVAS_RENDER_BUFFER: Final[int] = 12  # seconds — load-bearing for WebGL tiles
RENDER_CLEANUP_WAIT: Final[int] = 2  # seconds

# ========== Streamlit UI Configuration ==========
STREAMLIT_DATA_PATH: Final[str] = "data/data.json"
STREAMLIT_SCREENSHOT_DIR: Final[str] = "screenshots"

CONFIDENCE_COLORS: Final[dict[str, str]] = {
    "high": "#8b1a1a",
    "medium": "#a07a2c",
    "low": "#6b6357"
}

ACTION_COLORS: Final[dict[str, str]] = {
    "zoom-in": "#8b1a1a",
    "zoom-out": "#2c3a4a",
    "move-left": "#a07a2c",
    "move-right": "#a07a2c",
    "finish": "#3d342c",
}

COUNTRY_FLAGS: Final[dict[str, str]] = {
    "Egypt": "🇪🇬", "Korea": "🇰🇷", "Russia": "🇷🇺", "China": "🇨🇳",
    "Iran": "🇮🇷", "Syria": "🇸🇾", "USA": "🇺🇸", "Israel": "🇮🇱",
}
