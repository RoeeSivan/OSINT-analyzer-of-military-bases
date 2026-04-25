# Random Base Analysis with Moondream

This feature allows you to randomly select a military base from the CSV file and analyze it using Moondream's bounding box detection capabilities.

## Overview

Every time you run the random analysis mode:
1. A random base is selected from `military_bases.csv`
2. Google Earth imagery is captured for the base location
3. Moondream performs bounding box detection on the imagery
4. Detected objects are annotated with red bounding boxes
5. Gemini analyzes the imagery and provides intelligence
6. Results are saved with timestamped filenames

## Usage

```bash
# Run random base analysis
python base_analyzer.py --random

# Run sequential analysis (default)
python base_analyzer.py
```

## Moondream Detection

When analyzing imagery, Moondream detects the following objects:
- aircraft
- vehicle  
- building
- radar dish
- tower
- ship
- fuel tank
- antenna

## Output Files

### Random Analysis Mode
- `data/random_analysis_{base_id}_{timestamp}.json` - Full analysis results in JSON
- `data/random_report_{base_id}_{timestamp}.txt` - Human-readable report
- `screenshots/base_{base_id}_{country}_v{view}_annotated.jpg` - Image with bounding boxes
- `screenshots/base_{base_id}_{country}_v{view}.jpg` - Processed image without boxes

### Sequential Analysis Mode (default)
- `data/data.json` - Persistent cumulative results
- `data/analysis_results_{timestamp}.json` - Per-run results
- `data/analysis_report_{timestamp}.txt` - Per-run report

## Features

### Automatic Duplicate Prevention
The system tracks previously analyzed bases and won't select them again unless all bases have been analyzed.

### Bounding Box Visualization
Moondream's detection results are drawn as red bounding boxes with labels on annotated images.
### Multi-Analyst Intelligence

Each random base analysis uses 8 "analysts" (same as sequential mode) with different perspectives to build comprehensive intelligence.

## Example Workflow

```bash
# Select and analyze a random base
$ python base_analyzer.py --random

Running RANDOM base analysis mode
======================================================================
RANDOM BASE SELECTED: 427 (Korea)
Coordinates: 38.50285779743661, 124.8657191581862
======================================================================

View #1: lat=38.50285779743661, lon=124.8657191581862, zoom=3000m
  ✓ 5 detection(s) drawn → base_427_Korea_v1_annotated.jpg
  - aircraft at [0.15, 0.26, 0.68, 0.95]
  - building at [0.32, 0.41, 0.58, 0.72]
  ...

✓ Random base 427 completed — 8 analysts, 2 views
✓ JSON: /path/to/random_analysis_427_20260425_230000.json
✓ Text: /path/to/random_report_427_20260425_230000.txt

✓ Random analysis complete!
```

## Integration with Sequential Analysis

The random analysis mode complements the existing sequential analysis:
- **Sequential** (`python base_analyzer.py`): Analyzes bases in order, useful for systematic coverage
- **Random** (`python base_analyzer.py --random`): Analyzes random bases, useful for surprise inspections or testing

Both modes use the same Moondream detection and Gemini analysis infrastructure, ensuring consistent results.