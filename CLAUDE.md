# CLAUDE.md

## Project

OSINT / GEOINT analyzer for military bases. HW2, assignment2-exercise2 of the "From idea to app using AI" course.

Pipeline (single script, [base_analyzer.py](base_analyzer.py)):

1. Read first `ROWS_TO_PROCESS` rows from [military_bases.csv](military_bases.csv) (id, country, latitude, longitude).
2. For each base, open Google Earth Web at the coordinates via Selenium + Chrome (webdriver-manager).
3. Wait for the WebGL canvas, add a 12 s render buffer, dismiss overlays, save a raw PNG.
4. Resize to 1024 px wide, save as JPEG, delete the raw PNG.
5. Send the JPEG to Gemini 1.5 Flash with a GEOINT prompt (infrastructure / vehicles / defensive measures).
6. Write per-base results to [data/](data/) as `analysis_results_<timestamp>.json` and `analysis_report_<timestamp>.txt`.

## Run

```bash
source venv/bin/activate
python base_analyzer.py
```

Requires a valid `GEMINI_API_KEY` in [.env](.env) (see [.env.example](.env.example)). The key must come from https://aistudio.google.com/apikey — keys created in the GCP Console without the Generative Language API enabled fail with `API_KEY_INVALID`.

## Layout

- [base_analyzer.py](base_analyzer.py) — entire pipeline, one file.
- [military_bases.csv](military_bases.csv) — input coordinates.
- [.env](.env) — `GEMINI_API_KEY=...` (gitignored).
- [screenshots/](screenshots/) — generated JPEGs, one per base (gitignored).
- [data/](data/) — JSON + text reports (gitignored).

## Config knobs (top of [base_analyzer.py](base_analyzer.py))

- `ROWS_TO_PROCESS` — how many bases to process (default 5).
- `SCREENSHOT_WIDTH` — resized width in pixels (default 1024).
- `OUTPUT_DIR`, `DATA_DIR` — output folders.
- `GOOGLE_EARTH_URL_TEMPLATE` — URL pattern for search-by-coordinates.

## Constraints and gotchas

- **Chrome must run non-headless.** Google Earth WebGL does not render reliably in headless mode; the `--headless` flag is intentionally commented out at [base_analyzer.py:73](base_analyzer.py#L73).
- **The 12 s sleep is load-bearing.** [base_analyzer.py:126](base_analyzer.py#L126) waits for WebGL tiles to stream after the canvas element appears. Shortening it causes blank or half-loaded screenshots.
- **Raw PNG is deleted** after JPEG conversion at [base_analyzer.py:207](base_analyzer.py#L207) — intentional, saves disk.
- **.env is gitignored**; do not commit the key.
- The script uses the legacy `google-generativeai` SDK (import as `genai`). A newer unified SDK (`google-genai`) exists but migration is out of scope for this assignment.
