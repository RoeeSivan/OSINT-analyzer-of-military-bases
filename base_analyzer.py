"""
OSINT Analyzer for Military Bases
Analyzes military base locations using Google Earth imagery
"""

import csv
import os
import time
import json
import math
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
ROWS_TO_PROCESS = 8
NUM_ANALYSTS = 8
OUTPUT_DIR = "screenshots"
SCREENSHOT_WIDTH = 1024
DATA_DIR = "data"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# View-navigation parameters. The analyst's `action` mutates a per-base state
# dict with these three fields; `zoom` is the camera-to-target distance in
# meters (smaller = more zoomed in) which maps directly to the `d` param in
# the Google Earth @-URL.
INITIAL_ZOOM_RANGE = 5000   # meters
ZOOM_FACTOR = 2.0           # half / double the range per zoom action
MIN_ZOOM_RANGE = 100        # m — prevent tunneling into the ground
MAX_ZOOM_RANGE = 50000      # m — prevent zooming to orbit
MOVE_FRACTION = 0.6         # shift longitude by 60% of the current range

# Gemini Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file")

genai.configure(api_key=GEMINI_API_KEY)

# Google Earth Web URL format: @lat,lon,{alt}a,{distance}d,{fov}y,{heading}h,{tilt}t,{roll}r
#   lat,lon  — target coordinates
#   alt (a)  — target altitude in meters above sea level (0 = sea level; safe default)
#   dist (d) — camera distance from target in meters (this IS the zoom)
#   fov (y)  — vertical field of view in degrees (35 is Google's default)
#   heading (h) — 0 = north up
#   tilt (t) — 0 = top-down satellite view
#   roll (r) — always 0
GOOGLE_EARTH_URL_TEMPLATE = (
    "https://earth.google.com/web/@{lat},{lon},0a,{range}d,35y,0h,0t,0r"
)

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

# Commander model — a larger, more deliberate Gemini variant (Pro vs Flash) used
# once per base to synthesize the 8 analyst reports into a single intelligence
# product. Different model, same API, same key.
COMMANDER_MODEL = "gemini-2.5-pro"

# Structured-output schema for the commander. Each field is picked to map
# cleanly onto Streamlit widgets in the final GUI step.
COMMANDER_RESPONSE_SCHEMA = {
    "type": "object",
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


def create_google_earth_url(latitude, longitude, zoom_range):
    """
    Build a Google Earth Web @-URL pinning camera at (lat, lon) with the given
    camera-to-target distance. `zoom_range` is meters — smaller = more zoomed in.
    """
    return GOOGLE_EARTH_URL_TEMPLATE.format(
        lat=latitude,
        lon=longitude,
        range=int(round(zoom_range)),
    )


def apply_action(state, action):
    """
    Mutate the per-base view state dict in place based on the analyst's action.

    `state` has keys: lat (deg), lon (deg), zoom (camera distance, meters).
    - zoom-in / zoom-out: halve or double `zoom`, clamped to [MIN, MAX] range.
    - move-left / move-right: shift `lon` by MOVE_FRACTION * zoom, converted
      from meters to degrees of longitude via the cos(lat) correction.
    - finish: no-op.
    """
    if action == "zoom-in":
        state["zoom"] = max(MIN_ZOOM_RANGE, state["zoom"] / ZOOM_FACTOR)
    elif action == "zoom-out":
        state["zoom"] = min(MAX_ZOOM_RANGE, state["zoom"] * ZOOM_FACTOR)
    elif action in ("move-left", "move-right"):
        shift_meters = state["zoom"] * MOVE_FRACTION
        # 1 degree of latitude ≈ 111,320 m; 1 degree of longitude shrinks by cos(lat).
        meters_per_degree_lon = max(1.0, 111320.0 * math.cos(math.radians(state["lat"])))
        delta_lon = shift_meters / meters_per_degree_lon
        if action == "move-left":
            delta_lon = -delta_lon
        new_lon = state["lon"] + delta_lon
        if new_lon > 180:
            new_lon -= 360
        elif new_lon < -180:
            new_lon += 360
        state["lon"] = new_lon


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


def take_screenshot(driver, base_id, country, view_idx):
    """
    Take a screenshot of the current page and save it.
    Uses smart synchronization: waits for canvas elements to be present,
    then adds a render buffer to ensure WebGL tiles are streamed and rendered.

    `view_idx` is the sequential index of the distinct view for this base
    (increments each time the analyst triggers a zoom/move navigation).
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
    screenshot_path = os.path.join(OUTPUT_DIR, f"base_{base_id}_{country}_v{view_idx}_raw.png")
    driver.save_screenshot(screenshot_path)
    print(f"  ✓ Raw screenshot saved")
    
    return screenshot_path


def process_image(input_path, base_id, country, view_idx):
    """
    Process the screenshot: scale to 1024px width and convert to JPEG.
    This reduces file size and makes the image more suitable for LLM analysis.

    `view_idx` matches the one passed to `take_screenshot` so the processed
    JPEG lines up 1:1 with its raw PNG source.
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
        output_path = os.path.join(OUTPUT_DIR, f"base_{base_id}_{country}_v{view_idx}.jpg")
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


def format_history_of_analysts(prior_analysts):
    """
    Render a compact, readable transcript of the prior analysts' outputs so it
    can be injected into the next analyst's prompt. One block per analyst with
    findings / analysis / next-steps / recommended action.
    """
    blocks = []
    for a in prior_analysts:
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


def analyze_with_gemini(image_path, base_id, country, history=None):
    """
    Analyze a satellite image with Gemini 2.5 Flash and return a parsed dict
    with `findings` / `analysis` / `things_to_continue_analyzing` / `action`.

    If `history` is provided (a formatted string from `format_history_of_analysts`),
    it is appended to the prompt so the analyst can build on prior findings.
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

        if history:
            geoint_prompt += (
                "\n\nHere is the analysis of previous analysts about this area and their "
                "recommendations. You can use this data but don't use it as fact, think "
                "for yourself:\n\n"
                f"{history}"
            )

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


def run_commander(analysts, country, base_id):
    """
    Synthesize the 8 analysts' reports into a single intelligence product using
    a larger Gemini model (2.5 Pro). Returns a parsed dict matching
    COMMANDER_RESPONSE_SCHEMA — safe to dump straight into JSON for the GUI.
    """
    print(f"  Commander synthesizing {len(analysts)} analyst reports with {COMMANDER_MODEL}...")

    transcript = format_history_of_analysts(analysts)

    commander_prompt = f"""You are a senior military intelligence commander. Intel suggests the location in {country} (site ID {base_id}) is an enemy military facility. Eight analysts have independently examined satellite imagery from different zoom levels and positions — each saw a different frame, and later analysts were shown earlier analysts' notes but told not to treat them as fact.

Your job: synthesize their observations into a single authoritative intelligence report a field commander can act on. Analysts may disagree, overfit to small details, or miss the bigger picture. Reconcile the evidence, weight findings by how many analysts corroborated them, and produce a clear assessment.

Here is the full transcript of the analysts' findings (each block is one analyst):

{transcript}

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

    try:
        model = genai.GenerativeModel(COMMANDER_MODEL)
        response = model.generate_content(
            commander_prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": COMMANDER_RESPONSE_SCHEMA,
            },
        )
        report = json.loads(response.text)
        print(
            f"  ✓ Commander report complete — "
            f"classification={report['facility_classification']}, "
            f"confidence={report['confidence']}"
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
            f.write(f"Initial Latitude: {result['initial_latitude']}\n")
            f.write(f"Initial Longitude: {result['initial_longitude']}\n")
            f.write(f"Analysts: {len(result['analysts'])}\n")

            for analyst in result['analysts']:
                s = analyst['state_when_analyzed']
                f.write(f"\n{'-'*80}\n")
                f.write(
                    f"ANALYST {analyst['analyst_num']} — view #{analyst['view_idx']} — "
                    f"{analyst['screenshot_file']}\n"
                )
                f.write(
                    f"  state: lat={s['lat']:.6f}, lon={s['lon']:.6f}, zoom={s['zoom']:.0f}m\n"
                )
                f.write(f"{'-'*80}\n")
                f.write(json.dumps(analyst['analysis'], indent=2, ensure_ascii=False) + "\n")

            commander = result.get('commander_report')
            if commander:
                f.write(f"\n{'#'*80}\n")
                f.write(f"COMMANDER REPORT — Base {result['base_id']}\n")
                f.write(f"{'#'*80}\n")
                f.write(json.dumps(commander, indent=2, ensure_ascii=False) + "\n")
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
            initial_lat = float(base['latitude'])
            initial_lon = float(base['longitude'])

            print(f"\n{'='*70}")
            print(f"[{idx}/{len(bases)}] Processing Base {base_id} ({country})")
            print(f"{'='*70}")
            print(f"Initial view: lat={initial_lat}, lon={initial_lon}, zoom={INITIAL_ZOOM_RANGE}m")

            # Per-base mutable view state. Analyst `action` values mutate this
            # between calls so the next analyst sees a different image.
            state = {
                "lat": initial_lat,
                "lon": initial_lon,
                "zoom": INITIAL_ZOOM_RANGE,
            }

            analysts = []
            current_screenshot_path = None
            view_idx = 0
            need_new_view = True  # first analyst always needs the initial view

            for analyst_num in range(1, NUM_ANALYSTS + 1):
                print(f"\n{'-'*70}")
                print(f"ANALYST {analyst_num}/{NUM_ANALYSTS} — Base {base_id} ({country})")
                print(f"{'-'*70}")

                if need_new_view:
                    view_idx += 1
                    url = create_google_earth_url(state["lat"], state["lon"], state["zoom"])
                    print(f"View #{view_idx}: {url}")
                    driver.get(url)
                    raw_path = take_screenshot(driver, base_id, country, view_idx)
                    current_screenshot_path = process_image(raw_path, base_id, country, view_idx)
                    need_new_view = False
                else:
                    print(f"Reusing view #{view_idx} (previous analyst returned 'finish')")

                history = format_history_of_analysts(analysts) if analysts else None
                if history:
                    print(f"  (injecting history from {len(analysts)} prior analyst(s))")
                analysis = analyze_with_gemini(
                    current_screenshot_path, base_id, country, history=history
                )
                print(json.dumps(analysis, indent=2, ensure_ascii=False))

                analysts.append({
                    "analyst_num": analyst_num,
                    "view_idx": view_idx,
                    "screenshot_file": os.path.basename(current_screenshot_path),
                    "state_when_analyzed": dict(state),
                    "analysis": analysis,
                })

                action = analysis["action"]
                if action in ("zoom-in", "zoom-out", "move-left", "move-right"):
                    apply_action(state, action)
                    need_new_view = True
                    print(
                        f"  → applied '{action}' → next view: "
                        f"lat={state['lat']:.6f}, lon={state['lon']:.6f}, zoom={state['zoom']:.0f}m"
                    )
                else:
                    print(f"  → analyst chose 'finish' — next analyst reuses the same view")

            # ========== Commander synthesis ==========
            print(f"\n{'-'*70}")
            print(f"COMMANDER — Base {base_id} ({country})")
            print(f"{'-'*70}")
            commander_report = run_commander(analysts, country, base_id)
            print(json.dumps(commander_report, indent=2, ensure_ascii=False))

            result_entry = {
                "base_id": base_id,
                "country": country,
                "initial_latitude": initial_lat,
                "initial_longitude": initial_lon,
                "analysts": analysts,
                "commander_report": commander_report,
            }
            analysis_results.append(result_entry)

            print(f"\n✓ Base {base_id} completed — {NUM_ANALYSTS} analysts across {view_idx} distinct views + commander")
    
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

