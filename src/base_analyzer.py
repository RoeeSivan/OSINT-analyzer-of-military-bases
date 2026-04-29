"""
OSINT GEOINT Analyzer — Main Pipeline.

Orchestrates the complete military base analysis workflow:
1. Read military bases from CSV
2. For each base, open Google Earth Web and capture screenshots
3. Run 8 independent analyst agents on different views (with smart navigation)
4. Synthesize the 8 reports into a single commander intelligence product
5. Persist results incrementally to data/data.json for the Streamlit GUI

All configuration, prompts, and LLM orchestration are modularized for clarity.
"""

import os
import json
import random
from typing import Any

from config import (
    ROWS_TO_PROCESS,
    NUM_ANALYSTS,
    OUTPUT_DIR,
    DATA_DIR,
    DATA_JSON_PATH,
    INITIAL_ZOOM_RANGE,
    ZOOM_FACTOR,
    MIN_ZOOM_RANGE,
    MAX_ZOOM_RANGE,
    MOVE_FRACTION,
    MOONDREAM_ENABLED,
    DETECTION_TARGETS,
    LLM_PROVIDER,
)
from data_manager import (
    read_military_bases_csv,
    load_data_json,
    save_data_json,
    format_analyst_history,
)
from web_automation import (
    create_chrome_driver,
    navigate_to_coordinates,
    capture_screenshot,
    crop_image_margins,
    recenter_state_on_moondream_point,
)
from llm_orchestration import analyze_image, synthesize_commander_report
import moondream_client


# Print startup configuration
def _print_startup_config() -> None:
    """Print LLM and feature configuration at startup."""
    if LLM_PROVIDER == "openai":
        print("✓ Using OpenAI (gpt-5 for both analyst and commander)")
    else:
        print("✓ Using Gemini (2.5-flash for analyst, 2.5-pro for commander)")
    
    if MOONDREAM_ENABLED:
        print("✓ Moondream cloud enabled — triage / detection / smart-zoom on")
    else:
        print(
            "⚠ MOONDREAM_API_KEY not in .env — running without triage / "
            "bounding boxes / smart zoom.\n"
            "   Get a key at https://moondream.ai and add: MOONDREAM_API_KEY=... to .env"
        )


def apply_action(
    state: dict[str, float],
    action: str,
    image_path: str | None = None,
) -> None:
    """
    Apply analyst's action to the per-base view state (mutated in-place).
    
    The state dict has keys: lat (decimal degrees), lon (decimal degrees),
    zoom (camera distance in meters). Actions mutate this state for the
    next analyst's view.
    
    Actions:
    - zoom-in: Use Moondream to find the most suspicious target and recenter,
      then halve zoom. Falls back to plain center-zoom if Moondream disabled/fails.
    - zoom-out: Double zoom, clamped.
    - move-left / move-right: Shift longitude by MOVE_FRACTION * zoom.
    - finish: No-op (next analyst reuses this view).
    
    Args:
        state: Dict with 'lat', 'lon', 'zoom' (mutated in-place).
        action: The action string from the analyst's JSON response.
        image_path: Path to the current screenshot (required for Moondream pointing).
    """
    if action == "zoom-in":
        if MOONDREAM_ENABLED and image_path:
            try:
                target_point = moondream_client.point_to_most_suspicious_target(image_path)
                if target_point:
                    recenter_state_on_moondream_point(state, target_point, image_path)
                    print(
                        f"  Moondream pointed at ({target_point['x']:.2f}, {target_point['y']:.2f}) "
                        f"— recentered before zoom"
                    )
            except Exception as e:
                print(f"  ⚠ Moondream point failed: {e} — center-zoom fallback")
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


def process_image_to_jpeg(
    raw_png_path: str,
    base_id: str,
    country: str,
    view_idx: int,
) -> str:
    """
    Process raw screenshot: crop margins, scale to 1024px width, convert to JPEG.
    
    Reduces file size and prepares for LLM analysis. Removes ~8% UI chrome margins.
    Deletes the raw PNG after conversion to save disk space.
    
    Args:
        raw_png_path: Path to the raw PNG screenshot from Selenium.
        base_id: Military base ID.
        country: Country name.
        view_idx: Sequential view number for this base.
        
    Returns:
        Path to the processed JPEG file.
        
    Raises:
        Exception: If image processing fails.
    """
    from config import SCREENSHOT_WIDTH, IMAGE_QUALITY, UI_MARGIN_CROP_PERCENT
    from PIL import Image as PILImage
    
    print(f"  Processing image...")
    
    try:
        img = PILImage.open(raw_png_path)
        original_width, original_height = img.size
        print(f"  Original dimensions: {original_width}x{original_height}")
        
        # Crop UI chrome
        img_cropped = crop_image_margins(img, margin_percent=UI_MARGIN_CROP_PERCENT)
        cropped_width, cropped_height = img_cropped.size
        print(f"  Cropped margins: {original_width}x{original_height} → {cropped_width}x{cropped_height}")
        
        # Scale width to 1024px
        new_width = SCREENSHOT_WIDTH
        new_height = int((SCREENSHOT_WIDTH / cropped_width) * cropped_height)
        img_resized = img_cropped.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
        print(f"  Scaled to: {new_width}x{new_height} (aspect ratio preserved)")
        
        # Convert to JPEG
        output_path = f"{OUTPUT_DIR}/base_{base_id}_{country}_v{view_idx}.jpg"
        img_resized.save(output_path, "JPEG", quality=IMAGE_QUALITY, optimize=True)
        
        original_size = os.path.getsize(raw_png_path) / (1024 * 1024)
        final_size = os.path.getsize(output_path) / (1024 * 1024)
        compression_ratio = (1 - final_size / original_size) * 100
        
        print(f"  File size: {original_size:.2f}MB → {final_size:.2f}MB ({compression_ratio:.1f}% reduction)")
        
        # Remove raw PNG
        os.remove(raw_png_path)
        print(f"  ✓ Image processed and saved: {output_path}")
        
        return output_path
    
    except Exception as e:
        print(f"  ✗ Error processing image: {e}")
        raise


def annotate_detections_on_image(
    image_path: str,
    detections: list[dict[str, Any]],
    output_path: str,
) -> None:
    """
    Draw red bounding boxes and labels on image copy for visualization.
    
    Args:
        image_path: Path to the original JPEG image.
        detections: List of detection dicts with 'label' and 'box' [x1, y1, x2, y2].
        output_path: Path where the annotated image should be saved.
    """
    from PIL import Image as PILImage, ImageDraw
    
    img = PILImage.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size
    
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        x1, y1, x2, y2 = int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)
        draw.rectangle([x1, y1, x2, y2], outline="red", width=3)
        draw.text((x1 + 2, max(0, y1 - 12)), det["label"], fill="red")
    
    img.save(output_path, "JPEG", quality=85)



def main() -> None:
    """
    Main pipeline orchestrator.
    
    Workflow:
    1. Load military bases from CSV
    2. Check data.json to skip already-processed bases
    3. For each base:
       - Take 8 analyst passes, each on a different view (smart navigation)
       - Synthesize the 8 reports into a commander intelligence product
       - Persist result incrementally to data.json
    4. Report completion
    
    Uses context managers for proper resource cleanup (Selenium WebDriver, file handles).
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    _print_startup_config()
    
    # Read CSV and load existing results
    print(f"\nReading military bases from {DATA_JSON_PATH}...")
    all_bases = read_military_bases_csv()
    print(f"Read {len(all_bases)} bases from CSV")
    
    data_entries = load_data_json()
    existing_ids = {entry["base_id"] for entry in data_entries}
    if existing_ids:
        print(
            f"Found {len(existing_ids)} previously analyzed base(s) in {DATA_JSON_PATH} "
            f"— will skip them"
        )
    
    unprocessed = [b for b in all_bases if b["id"] not in existing_ids]
    if not unprocessed:
        print("Nothing to do — all bases in CSV are already in data.json. Exiting.")
        return
    
    n_to_pick = min(ROWS_TO_PROCESS, len(unprocessed))
    bases_to_process = random.sample(unprocessed, n_to_pick)
    print(
        f"Randomly selected {n_to_pick} base(s) from {len(unprocessed)} unprocessed: "
        f"{[b['id'] for b in bases_to_process]}\n"
    )
    
    # Main processing loop with context manager for WebDriver
    with create_chrome_driver() as driver:
        for idx, base in enumerate(bases_to_process, 1):
            base_id = base['id']
            country = base['country']
            initial_lat = float(base['latitude'])
            initial_lon = float(base['longitude'])
            
            print(f"\n{'='*70}")
            print(f"[{idx}/{len(bases_to_process)}] Processing Base {base_id} ({country})")
            print(f"{'='*70}")
            print(f"Initial view: lat={initial_lat}, lon={initial_lon}, zoom={INITIAL_ZOOM_RANGE}m")
            
            # Per-base mutable state: analysts mutate this between calls
            state = {
                "lat": initial_lat,
                "lon": initial_lon,
                "zoom": INITIAL_ZOOM_RANGE,
            }
            
            analysts = []
            current_screenshot_path = None
            view_idx = 0
            need_new_view = True
            
            # Run 8 analyst passes
            for analyst_num in range(1, NUM_ANALYSTS + 1):
                print(f"\n{'-'*70}")
                print(f"ANALYST {analyst_num}/{NUM_ANALYSTS} — Base {base_id} ({country})")
                print(f"{'-'*70}")
                
                # Generate new screenshot or reuse
                if need_new_view:
                    view_idx += 1
                    print(
                        f"View #{view_idx}: lat={state['lat']}, lon={state['lon']}, "
                        f"zoom={state['zoom']:.0f}m"
                    )
                    navigate_to_coordinates(driver, state["lat"], state["lon"], state["zoom"])
                    raw_path = capture_screenshot(driver, base_id, country, view_idx)
                    current_screenshot_path = process_image_to_jpeg(
                        raw_path, base_id, country, view_idx
                    )
                    need_new_view = False
                else:
                    print(f"Reusing view #{view_idx} (previous analyst returned 'finish')")
                
                # Run Moondream detection
                detections = (
                    moondream_client.detect_all_targets(current_screenshot_path, DETECTION_TARGETS)
                    if MOONDREAM_ENABLED
                    else []
                )
                moondream_context = (
                    moondream_client.format_detections_for_prompt(detections)
                    if detections
                    else None
                )
                if detections:
                    print(
                        f"  Moondream pre-detect: {len(detections)} object(s) across "
                        f"{len({d['label'] for d in detections})} class(es)"
                    )
                
                # Triage logic
                if analyst_num == 1:
                    print(f"  First analyst on this base — bypassing triage to guarantee full analysis")
                    triaged_in = True
                elif detections:
                    print(f"  Detector found targets — bypassing triage")
                    triaged_in = True
                else:
                    triaged_in = moondream_client.triage_image(current_screenshot_path)
                
                # LLM analysis
                if triaged_in:
                    history = format_analyst_history(analysts) if analysts else None
                    if history:
                        print(f"  (injecting history from {len(analysts)} prior analyst(s))")
                    if moondream_context:
                        print(f"  (injecting Moondream detection anchors into prompt)")
                    
                    analysis = analyze_image(
                        current_screenshot_path,
                        base_id,
                        country,
                        history=history,
                        moondream_context=moondream_context,
                    )
                else:
                    analysis = {
                        "findings": [],
                        "analysis": "Skipped — Moondream triage detected no relevant targets.",
                        "things_to_continue_analyzing": [],
                        "action": "zoom-out",
                    }
                
                print(json.dumps(analysis, indent=2, ensure_ascii=False))
                
                # Annotate if detections exist
                annotated_file = None
                if detections:
                    annotated_path = current_screenshot_path.replace(".jpg", "_annotated.jpg")
                    try:
                        annotate_detections_on_image(
                            current_screenshot_path, detections, annotated_path
                        )
                        annotated_file = os.path.basename(annotated_path)
                        print(f"  ✓ {len(detections)} detection(s) drawn → {annotated_file}")
                    except Exception as e:
                        print(f"  ⚠ Annotation failed: {e}")
                
                # Record analyst result
                analysts.append({
                    "analyst_num": analyst_num,
                    "view_idx": view_idx,
                    "screenshot_file": os.path.basename(current_screenshot_path),
                    "annotated_screenshot_file": annotated_file,
                    "moondream_detections": detections,
                    "triaged_in": triaged_in,
                    "state_when_analyzed": dict(state),
                    "analysis": analysis,
                })
                
                # Apply action to state
                action = analysis["action"]
                if action in ("zoom-in", "zoom-out", "move-left", "move-right"):
                    apply_action(state, action, image_path=current_screenshot_path)
                    need_new_view = True
                    print(
                        f"  → applied '{action}' → next view: "
                        f"lat={state['lat']:.6f}, lon={state['lon']:.6f}, zoom={state['zoom']:.0f}m"
                    )
                else:
                    print(f"  → analyst chose 'finish' — next analyst reuses the same view")
            
            # Commander synthesis
            print(f"\n{'-'*70}")
            print(f"COMMANDER — Base {base_id} ({country})")
            print(f"{'-'*70}")
            commander_report = synthesize_commander_report(analysts, country, base_id)
            print(json.dumps(commander_report, indent=2, ensure_ascii=False))
            
            # Persist result
            result_entry = {
                "base_id": base_id,
                "country": country,
                "initial_latitude": initial_lat,
                "initial_longitude": initial_lon,
                "analysts": analysts,
                "commander_report": commander_report,
            }
            
            data_entries.append(result_entry)
            save_data_json(data_entries)
            
            print(
                f"\n✓ Base {base_id} completed — {NUM_ANALYSTS} analysts across "
                f"{view_idx} distinct views + commander"
            )
            print(f"  ✓ Persisted to {DATA_JSON_PATH} (cumulative: {len(data_entries)} bases)")
    
    # Final report
    print(f"\n{'='*70}")
    print(f"✓ Analysis Complete — {len(bases_to_process)} new base(s) added")
    print(f"{'='*70}")
    print(f"  Data:        {os.path.abspath(DATA_JSON_PATH)} (cumulative: {len(data_entries)} bases)")
    print(f"  Screenshots: {os.path.abspath(OUTPUT_DIR)}/\n")


import math


if __name__ == "__main__":
    _print_startup_config()
    main()


