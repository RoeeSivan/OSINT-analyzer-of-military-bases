"""
Web Automation Module for OSINT GEOINT Analyzer.

Handles all Selenium WebDriver interactions:
- Chrome driver setup with proper resource management
- Google Earth navigation and URL construction
- Screenshot capture with smart synchronization
- DOM waiting and overlay cleanup
"""

import time
import math
from contextlib import contextmanager
from typing import Generator

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from PIL import Image

from config import (
    GOOGLE_EARTH_SEARCH_URL_TEMPLATE,
    BROWSER_WAIT_TIMEOUT,
    CANVAS_RENDER_BUFFER,
    RENDER_CLEANUP_WAIT,
    OUTPUT_DIR,
)
import moondream_client


@contextmanager
def create_chrome_driver() -> Generator[webdriver.Chrome, None, None]:
    """
    Context manager for Selenium WebDriver.
    
    Sets up Chrome with non-headless mode (required for Google Earth WebGL rendering)
    and ensures proper cleanup via try/finally.
    
    Yields:
        A configured WebDriver instance.
        
    Example:
        with create_chrome_driver() as driver:
            driver.get("https://earth.google.com/web/")
            # ... use driver ...
            # Automatically quit on exit
    """
    chrome_options = Options()
    # Disable headless mode — Google Earth WebGL doesn't render reliably in headless
    # chrome_options.add_argument("--headless")  # Intentionally NOT used
    
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Set reasonable timeouts
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(10)
    
    try:
        yield driver
    finally:
        driver.quit()


def create_google_earth_url(
    latitude: float,
    longitude: float,
    zoom_range: float,
) -> str:
    """
    Build a Google Earth Web URL pinning camera at given coordinates with zoom.
    
    Uses the /search/ URL format for reliable rendering.
    
    Args:
        latitude: Target latitude in decimal degrees.
        longitude: Target longitude in decimal degrees.
        zoom_range: Camera-to-target distance in meters (smaller = more zoomed).
        
    Returns:
        Full Google Earth URL string.
    """
    # URL-encode the coordinates for the search path
    encoded_lat = str(latitude).replace(".", "%2e")
    encoded_lon = str(longitude).replace(".", "%2e")
    
    # Small altitude above ground level for better rendering
    alt = 100  # meters above sea level
    
    return GOOGLE_EARTH_SEARCH_URL_TEMPLATE.format(
        encoded_lat=encoded_lat,
        encoded_lon=encoded_lon,
        lat=latitude,
        lon=longitude,
        alt=alt,
        range=int(round(zoom_range)),
    )


def navigate_to_coordinates(
    driver: webdriver.Chrome,
    latitude: float,
    longitude: float,
    zoom_range: float,
) -> None:
    """
    Navigate to specific coordinates in Google Earth Web.
    
    Falls back to search bar if URL navigation fails.
    
    Args:
        driver: Selenium WebDriver instance.
        latitude: Target latitude.
        longitude: Target longitude.
        zoom_range: Camera distance in meters.
    """
    url = create_google_earth_url(latitude, longitude, zoom_range)
    
    try:
        print(f"  Navigating via URL (zoom={int(zoom_range)}m)...")
        driver.get(url)
    except Exception as e:
        print(f"  ⚠ URL navigation failed: {e} — falling back to search bar")
        _search_bar_navigation(driver, latitude, longitude, zoom_range)


def _search_bar_navigation(
    driver: webdriver.Chrome,
    latitude: float,
    longitude: float,
    zoom_range: float,
) -> None:
    """
    Fallback navigation: type coordinates into Google Earth search box.
    
    Note: This path lets Google Earth pick its own altitude, so the requested
    zoom_range may not be exactly honored — only used when URL navigation fails.
    
    Args:
        driver: Selenium WebDriver instance.
        latitude: Target latitude.
        longitude: Target longitude.
        zoom_range: Requested camera distance (best effort).
    """
    print(f"  Opening Google Earth (search-bar fallback)...")
    driver.get("https://earth.google.com/web/")
    time.sleep(3)
    
    search_box = None
    search_selectors = [
        (By.XPATH, "//input[@placeholder='Search Google Earth']"),
        (By.XPATH, "//input[contains(@placeholder, 'Search')]"),
        (By.CLASS_NAME, "search-input"),
        (By.XPATH, "//input[@aria-label='Search']"),
    ]
    
    for selector_type, selector_value in search_selectors:
        try:
            search_box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((selector_type, selector_value))
            )
            print(f"  ✓ Found search box")
            break
        except Exception:
            continue
    
    if not search_box:
        print(f"  ⚠ Could not find search box, using URL fallback")
        url = create_google_earth_url(latitude, longitude, zoom_range)
        driver.get(url)
        return
    
    try:
        search_box.click()
        time.sleep(0.5)
        search_box.clear()
        
        search_query = f"{latitude},{longitude}"
        print(f"  Entering coordinates: {search_query}")
        search_box.send_keys(search_query)
        time.sleep(1)
        search_box.send_keys(Keys.RETURN)
        print(f"  ✓ Searching for coordinates...")
        time.sleep(3)
    except Exception as e:
        print(f"  ⚠ Search failed: {e}")


def capture_screenshot(
    driver: webdriver.Chrome,
    base_id: str,
    country: str,
    view_idx: int,
) -> str:
    """
    Capture a screenshot of the current Google Earth view.
    
    Uses smart synchronization:
    1. Wait for canvas elements (WebGL context ready)
    2. Static render buffer (tiles streaming)
    3. Dismiss overlays
    4. Capture screenshot
    
    Args:
        driver: Selenium WebDriver instance.
        base_id: Military base ID.
        country: Country name.
        view_idx: Sequential view number for this base.
        
    Returns:
        Path to saved raw PNG screenshot.
    """
    print(f"  Waiting for Google Earth to load and render...")
    
    # PHASE 1: Wait for canvas elements
    try:
        WebDriverWait(driver, BROWSER_WAIT_TIMEOUT).until(
            EC.presence_of_all_elements_located((By.TAG_NAME, "canvas"))
        )
        print(f"  ✓ Canvas element detected in DOM")
    except Exception as e:
        print(f"  ⚠ Warning: Canvas elements not found after {BROWSER_WAIT_TIMEOUT}s: {e}")
        print(f"  Continuing with static wait fallback...")
    
    # PHASE 2: Render buffer — load-bearing 12s wait for WebGL tiles
    print(f"  Render buffer: waiting {CANVAS_RENDER_BUFFER}s for tiles to stream and render...")
    time.sleep(CANVAS_RENDER_BUFFER)
    
    # PHASE 3: Cleanup overlays
    try:
        close_selectors = [
            (By.CLASS_NAME, "goog-buttonset-action"),
            (By.CLASS_NAME, "close-button"),
            (By.XPATH, "//button[@aria-label='Close']"),
        ]
        
        for selector_type, selector_value in close_selectors:
            try:
                close_buttons = driver.find_elements(selector_type, selector_value)
                for btn in close_buttons:
                    try:
                        btn.click()
                        print(f"  Dismissed overlay")
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass
    
    # Final stabilization
    time.sleep(RENDER_CLEANUP_WAIT)
    
    # PHASE 4: Capture
    print(f"  Capturing screenshot...")
    screenshot_path = f"{OUTPUT_DIR}/base_{base_id}_{country}_v{view_idx}_raw.png"
    driver.save_screenshot(screenshot_path)
    print(f"  ✓ Raw screenshot saved")
    
    return screenshot_path


def crop_image_margins(
    img: Image.Image,
    margin_percent: int = 8,
) -> Image.Image:
    """
    Crop UI chrome from image edges.
    
    Removes `margin_percent` from all four edges to eliminate Google Earth
    UI sidebar and overlays that cause false detections.
    
    Args:
        img: PIL Image instance.
        margin_percent: Percentage of width/height to crop (default 8%).
        
    Returns:
        Cropped PIL Image.
    """
    width, height = img.size
    left_margin = int(width * margin_percent / 100)
    right_margin = int(width * (100 - margin_percent) / 100)
    top_margin = int(height * margin_percent / 100)
    bottom_margin = int(height * (100 - margin_percent) / 100)
    
    return img.crop((left_margin, top_margin, right_margin, bottom_margin))


def recenter_state_on_moondream_point(
    state: dict,
    point: dict,
    image_path: str,
) -> None:
    """
    Adjust the camera state (lat/lon) based on a normalized point in the image.
    
    Converts image pixel coordinates to geographic displacement using the camera's
    current zoom and field of view. Used for smart zoom-in redirection.
    
    Args:
        state: Dict with keys 'lat', 'lon', 'zoom' (mutated in-place).
        point: Dict with 'x', 'y' normalized [0, 1] in image coordinates.
        image_path: Path to the image for aspect ratio calculation.
    """
    with Image.open(image_path) as img:
        aspect = img.size[0] / img.size[1]
    
    # Google Earth 35° vertical FOV: visible height = 2R * tan(17.5°)
    visible_h_m = 2 * state["zoom"] * math.tan(math.radians(35 / 2))
    visible_w_m = visible_h_m * aspect
    
    # Convert normalized image coords to view offset
    dx = point["x"] - 0.5
    dy = point["y"] - 0.5
    east_m = dx * visible_w_m
    south_m = dy * visible_h_m
    
    # Apply displacement in geographic coordinates
    state["lat"] += -south_m / 111320.0
    meters_per_degree_lon = max(1.0, 111320.0 * math.cos(math.radians(state["lat"])))
    state["lon"] += east_m / meters_per_degree_lon
