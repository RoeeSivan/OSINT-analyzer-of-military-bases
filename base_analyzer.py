"""
OSINT Analyzer for Military Bases
Analyzes military base locations using Google Earth imagery
"""

import csv
import os
import time
import json
from pathlib import Path
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import google.generativeai as genai
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env
load_dotenv()

# Constants
ROWS_TO_PROCESS = 1
OUTPUT_DIR = "screenshots"
SCREENSHOT_WIDTH = 1024
DATA_DIR = "data"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# Gemini Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file")

genai.configure(api_key=GEMINI_API_KEY)

# Google Earth URL parameters
# Simple approach: use Google Earth search with coordinates
GOOGLE_EARTH_URL_TEMPLATE = "https://earth.google.com/web/search/{latitude},{longitude}"

# Structured-output schema for the analyst. `action` is a strict enum so the
# next step (Selenium dispatcher) can rely on exactly these five values.
GEOINT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {"type": "array", "items": {"type": "string"}},
        "analysis": {"type": "string"},
        "things_to_continue_analyzing": {"type": "array", "items": {"type": "string"}},
        "action": {
            "type": "string",
            "enum": ["zoom-in", "zoom-out", "move-left", "move-right", "finish"],
        },
    },
    "required": ["findings", "analysis", "things_to_continue_analyzing", "action"],
}


def create_google_earth_url(latitude, longitude):
    """
    Create a Google Earth Web search URL for a specific location.
    Uses simple coordinate search for precise positioning.
    
    Args:
        latitude: Base latitude
        longitude: Base longitude
    
    Returns:
        URL string for Google Earth Web search
    """
    url = GOOGLE_EARTH_URL_TEMPLATE.format(
        latitude=latitude,
        longitude=longitude
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
    print(f"  Waiting for Google Earth to load and render...")
    
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
    print(f"  Render buffer: waiting 12 seconds for tiles to stream and render...")
    time.sleep(12)
    
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


def analyze_with_gemini(image_path, base_id, country):
    """
    Analyze satellite image with Gemini 2.5 Flash model for GEOINT intelligence.
    
    Args:
        image_path: Path to the processed JPEG image
        base_id: Military base ID
        country: Country name
    
    Returns:
        Analysis results from Gemini
    """
    print(f"  Analyzing with Gemini 2.5 Flash...")
    
    try:
        # Read the image file
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
        
        # Create the prompt for GEOINT analysis
        geoint_prompt = f"""You are an expert in understanding satellite imagery and you work for the US army. We got intel that this area is a base/facility of the military of {country}. Analyze this image and respond ONLY with a JSON object containing the following keys:

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

        model = genai.GenerativeModel("gemini-2.5-flash")

        response = model.generate_content(
            [
                geoint_prompt,
                {"mime_type": "image/jpeg", "data": image_data},
            ],
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": GEOINT_RESPONSE_SCHEMA,
            },
        )

        analysis = json.loads(response.text)
        print(f"  ✓ Analysis complete — action={analysis['action']}, findings={len(analysis['findings'])}")

        return analysis

    except Exception as e:
        print(f"  ✗ Error analyzing image with Gemini: {e}")
        return {
            "findings": [],
            "analysis": f"Error: {e}",
            "things_to_continue_analyzing": [],
            "action": "finish",
        }


def save_analysis_to_json(results, filename=None):
    """
    Save analysis results to a JSON file.
    
    Args:
        results: List of analysis result dictionaries
        filename: Optional custom filename
    
    Returns:
        Path to saved JSON file
    """
    if not filename:
        filename = f"analysis_results_{TIMESTAMP}.json"
    
    filepath = os.path.join(DATA_DIR, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"  ✓ JSON results saved: {filepath}")
    return filepath


def save_analysis_to_text(results, filename=None):
    """
    Save analysis results to a readable text file.
    
    Args:
        results: List of analysis result dictionaries
        filename: Optional custom filename
    
    Returns:
        Path to saved text file
    """
    if not filename:
        filename = f"analysis_report_{TIMESTAMP}.txt"
    
    filepath = os.path.join(DATA_DIR, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("GEOINT ANALYSIS REPORT - MILITARY BASE INTELLIGENCE\n")
        f.write("="*80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total Bases Analyzed: {len(results)}\n")
        f.write("="*80 + "\n\n")
        
        for idx, result in enumerate(results, 1):
            f.write(f"\n{'='*80}\n")
            f.write(f"BASE #{idx} - ID: {result['base_id']}\n")
            f.write(f"{'='*80}\n")
            f.write(f"Country: {result['country']}\n")
            f.write(f"Latitude: {result['latitude']}\n")
            f.write(f"Longitude: {result['longitude']}\n")
            f.write(f"Screenshot: {result['screenshot_file']}\n")
            f.write(f"\n{'-'*80}\n")
            f.write("GEOINT ANALYSIS:\n")
            f.write(f"{'-'*80}\n")
            f.write(json.dumps(result['geoint_analysis'], indent=2, ensure_ascii=False) + "\n")
            f.write("\n")
    
    print(f"  ✓ Text report saved: {filepath}")
    return filepath


def analyze_military_bases():
    """
    Main function to analyze military bases.
    Processes the first ROWS_TO_PROCESS bases and saves results.
    """
    # Create output directories
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    csv_path = "military_bases.csv"
    
    # Read bases from CSV
    print(f"Reading first {ROWS_TO_PROCESS} military bases from {csv_path}...")
    bases = read_military_bases_csv(csv_path, ROWS_TO_PROCESS)
    
    print(f"Found {len(bases)} bases to process\n")
    
    # Initialize results collection
    analysis_results = []
    
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
            
            # ========== Step 5: GEOINT Analysis with Gemini ==========
            print(f"\n  Starting GEOINT intelligence analysis...")
            geoint_analysis = analyze_with_gemini(final_path, base_id, country)
            
            # ========== Print Analysis Results ==========
            print(f"\n{'-'*70}")
            print(f"GEOINT ANALYSIS RESULTS - Base {base_id} ({country})")
            print(f"{'-'*70}")
            print(json.dumps(geoint_analysis, indent=2, ensure_ascii=False))
            print(f"{'-'*70}\n")
            
            # ========== Store Results for Saving ==========
            result_entry = {
                "base_id": base_id,
                "country": country,
                "latitude": latitude,
                "longitude": longitude,
                "screenshot_file": os.path.basename(final_path),
                "geoint_analysis": geoint_analysis
            }
            analysis_results.append(result_entry)
            
            print(f"✓ Base {base_id} completed successfully")
    
    finally:
        # Close the browser
        driver.quit()
    
    # ========== Save Analysis Results ==========
    print(f"\n{'='*70}")
    print(f"SAVING ANALYSIS RESULTS")
    print(f"{'='*70}")
    
    # Save as JSON
    json_path = save_analysis_to_json(analysis_results)
    
    # Save as text report
    text_path = save_analysis_to_text(analysis_results)
    
    print(f"\n{'='*70}")
    print(f"✓ Analysis Complete!")
    print(f"{'='*70}")
    print(f"Processed {len(bases)} military bases")
    print(f"\n📁 Output Locations:")
    print(f"   Screenshots: {os.path.abspath(OUTPUT_DIR)}/")
    print(f"   JSON Data:   {os.path.abspath(json_path)}")
    print(f"   Text Report: {os.path.abspath(text_path)}")
    print(f"\n✓ All data saved to {os.path.abspath(DATA_DIR)}/ directory\n")


if __name__ == "__main__":
    analyze_military_bases()

