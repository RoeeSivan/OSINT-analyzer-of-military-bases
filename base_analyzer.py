"""
OSINT Analyzer for Military Bases
Analyzes military base locations using Google Earth imagery
"""

import csv
import os
import time
from pathlib import Path
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# Constants
ROWS_TO_PROCESS = 5
OUTPUT_DIR = "screenshots"
SCREENSHOT_WIDTH = 1024

# Google Earth URL parameters
GOOGLE_EARTH_URL_TEMPLATE = "https://earth.google.com/web/@{latitude},{longitude},{altitude}a,{distance}d,{tilt}y,{heading}h,{time}t,{roll}r"

# Default camera parameters for Google Earth
DEFAULT_ALTITUDE = 1000  # meters above sea level
DEFAULT_DISTANCE = 5000  # camera distance from the point
DEFAULT_TILT = 45  # camera tilt angle (0 = straight down, 90 = horizon)
DEFAULT_HEADING = 0  # compass heading (0 = north)
DEFAULT_TIME = 0  # time parameter
DEFAULT_ROLL = 0  # roll parameter


def create_google_earth_url(latitude, longitude, altitude=DEFAULT_ALTITUDE, 
                           distance=DEFAULT_DISTANCE, tilt=DEFAULT_TILT,
                           heading=DEFAULT_HEADING, time=DEFAULT_TIME, roll=DEFAULT_ROLL):
    """
    Create a Google Earth Web URL for a specific location.
    
    Args:
        latitude: Base latitude
        longitude: Base longitude
        altitude: Altitude above sea level in meters
        distance: Camera distance from the point being looked at
        tilt: Camera tilt angle (0° = straight down, 90° = toward horizon)
        heading: Compass heading in degrees (0 = north, 90 = east)
        time: Time parameter (usually 0)
        roll: Roll parameter (usually 0)
    
    Returns:
        URL string for Google Earth Web
    """
    url = GOOGLE_EARTH_URL_TEMPLATE.format(
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        distance=distance,
        tilt=tilt,
        heading=heading,
        time=time,
        roll=roll
    )
    return url


def setup_chrome_driver():
    """
    Set up Selenium WebDriver for Chrome with non-headless mode.
    
    Returns:
        WebDriver instance
    """
    chrome_options = Options()
    # Disable headless mode so we can see what's happening
    # chrome_options.add_argument("--headless")  # Commented out for debugging
    
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # Use webdriver-manager to automatically handle ChromeDriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Set longer timeouts for page loading
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(10)
    
    return driver


def take_screenshot(driver, base_id, country):
    """
    Take a screenshot of the current page and save it.
    Uses smart synchronization: waits for canvas elements to be present,
    then adds a render buffer to ensure WebGL tiles are streamed and rendered.
    
    Args:
        driver: Selenium WebDriver instance
        base_id: Military base ID
        country: Country name
    
    Returns:
        Path to the saved screenshot file
    """
    print(f"  Waiting for Google Earth 3D canvas to load...")
    
    # ========== PHASE 1: Smart DOM Synchronization ==========
    # Wait for canvas elements to be present in the DOM
    # This ensures the WebGL context is initialized
    try:
        WebDriverWait(driver, 40).until(
            EC.presence_of_all_elements_located((By.TAG_NAME, "canvas"))
        )
        print(f"  ✓ Canvas element detected in DOM")
    except Exception as e:
        print(f"  ⚠ Warning: Canvas elements not found after 40s: {e}")
        print(f"  Continuing with static wait fallback...")
    
    # ========== PHASE 2: Render Buffer (Static Wait) ==========
    # After DOM elements are present, wait for the actual 3D tiles to stream
    # and render on screen. Google Earth's WebGL rendering is asynchronous,
    # so we need this secondary buffer to guarantee the tiles are rendered.
    print(f"  Render buffer: waiting 10 seconds for 3D tiles to stream and render...")
    time.sleep(10)
    
    # ========== PHASE 3: Cleanup Overlays ==========
    # Try to dismiss any UI overlays or loading indicators
    try:
        # Look for common close/dismiss buttons
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
                    except:
                        pass
            except:
                pass
    except:
        pass
    
    # Final stabilization wait
    time.sleep(2)
    
    # ========== PHASE 4: Capture Screenshot ==========
    print(f"  Capturing screenshot...")
    screenshot_path = os.path.join(OUTPUT_DIR, f"base_{base_id}_{country}_raw.png")
    driver.save_screenshot(screenshot_path)
    print(f"  ✓ Raw screenshot saved")
    
    return screenshot_path


def process_image(input_path, base_id, country):
    """
    Process the screenshot: scale to 1024px width and convert to JPEG.
    This reduces file size and makes the image more suitable for LLM analysis.
    
    Args:
        input_path: Path to the raw screenshot (PNG)
        base_id: Military base ID
        country: Country name
    
    Returns:
        Path to the processed image file (JPEG)
    """
    print(f"  Processing image...")
    
    try:
        # Open the raw PNG screenshot
        img = Image.open(input_path)
        original_width, original_height = img.size
        print(f"  Original dimensions: {original_width}x{original_height}")
        
        # ========== Image Scaling ==========
        # Scale width to 1024 pixels, maintaining aspect ratio
        new_width = SCREENSHOT_WIDTH  # 1024 pixels
        new_height = int((SCREENSHOT_WIDTH / original_width) * original_height)
        
        # Resize using high-quality Lanczos filter
        img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        print(f"  Scaled to: {new_width}x{new_height} (aspect ratio preserved)")
        
        # ========== Format Conversion ==========
        # Convert to JPEG for reduced file size
        output_path = os.path.join(OUTPUT_DIR, f"base_{base_id}_{country}.jpg")
        img_resized.save(output_path, "JPEG", quality=85, optimize=True)
        
        # Get file sizes for verification
        original_size = os.path.getsize(input_path) / (1024 * 1024)  # MB
        final_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
        compression_ratio = (1 - final_size / original_size) * 100
        
        print(f"  File size: {original_size:.2f}MB → {final_size:.2f}MB ({compression_ratio:.1f}% reduction)")
        
        # Remove the raw PNG file to save disk space
        os.remove(input_path)
        print(f"  ✓ Image processed and saved: {output_path}")
        
        return output_path
    
    except Exception as e:
        print(f"  ✗ Error processing image: {e}")
        raise


def read_military_bases_csv(csv_path, num_rows=ROWS_TO_PROCESS):
    """
    Read military bases from CSV file.
    
    Args:
        csv_path: Path to the CSV file
        num_rows: Number of rows to read
    
    Returns:
        List of dictionaries with base information
    """
    bases = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= num_rows:
                break
            bases.append(row)
    
    return bases


def analyze_military_bases():
    """
    Main function to analyze military bases.
    Processes the first ROWS_TO_PROCESS bases.
    """
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    csv_path = "military_bases.csv"
    
    # Read bases from CSV
    print(f"Reading first {ROWS_TO_PROCESS} military bases from {csv_path}...")
    bases = read_military_bases_csv(csv_path, ROWS_TO_PROCESS)
    
    print(f"Found {len(bases)} bases to process\n")
    
    # Initialize Chrome driver
    driver = setup_chrome_driver()
    
    try:
        for idx, base in enumerate(bases, 1):
            base_id = base['id']
            country = base['country']
            latitude = float(base['latitude'])
            longitude = float(base['longitude'])
            
            print(f"\n{'='*70}")
            print(f"[{idx}/{len(bases)}] Processing Base {base_id} ({country})")
            print(f"{'='*70}")
            print(f"Location: Latitude {latitude}, Longitude {longitude}")
            
            # ========== Step 1: Create Google Earth URL ==========
            url = create_google_earth_url(latitude, longitude)
            print(f"Opening: {url}")
            
            # ========== Step 2: Navigate to Google Earth ==========
            driver.get(url)
            
            # ========== Step 3: Smart Screenshot with Render Buffer ==========
            screenshot_path = take_screenshot(driver, base_id, country)
            
            # ========== Step 4: Process Image (Scale & Convert) ==========
            final_path = process_image(screenshot_path, base_id, country)
            
            print(f"✓ Base {base_id} completed successfully")
    
    finally:
        # Close the browser
        driver.quit()
    
    print(f"\n{'='*70}")
    print(f"✓ Analysis Complete!")
    print(f"{'='*70}")
    print(f"Processed {len(bases)} military bases")
    print(f"Output location: {os.path.abspath(OUTPUT_DIR)}/")
    print(f"All screenshots scaled to {SCREENSHOT_WIDTH}px width and converted to JPEG\n")


if __name__ == "__main__":
    analyze_military_bases()

