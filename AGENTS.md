# AGENTS.md

Engineering rules for any AI agent (Claude, Codex, Cursor, etc.) editing this repo.
Project-specific context lives in [CLAUDE.md](CLAUDE.md). These rules are general.

## Fail fast. No silent fallbacks.

The code has expectations. When an expectation is not met, **raise**. Do not paper over it.

**Don't write code like this:**

```python
# BAD
if not os.path.exists(YOLO_MODEL_PATH):
    print("YOLO model missing, falling back to heuristic detector")
    detections = heuristic_detect(img)
else:
    detections = yolo_detect(img)
```

**Write this instead:**

```python
# GOOD
if not os.path.exists(YOLO_MODEL_PATH):
    raise FileNotFoundError(f"YOLO model not found at {YOLO_MODEL_PATH}")
detections = yolo_detect(img)
```

Rules:

- **No "option B" fallbacks** for missing models, missing files, missing API keys, missing env vars, or unexpected response shapes. If the thing isn't there, the run is broken — stop.
- **No `try/except: pass`.** Catch only the specific exception you actually know how to handle, and only if handling it is meaningful. Bare `except Exception` that logs and continues is forbidden.
- **No defaults that hide misconfiguration.** If `GEMINI_API_KEY` is missing, fail at startup with a clear message — do not run with `key = ""` and discover it 30 seconds in.
- **No "continue to the next item" loops that swallow per-item errors silently.** If processing base #3 fails, either (a) let the whole run fail, or (b) record the failure explicitly in the output and re-raise at the end. Never just `print("skipping")` and move on.
- **Validate at boundaries, trust internally.** Check user input, CSV contents, and external API responses once at the boundary. Don't re-validate the same thing in every helper.

## Code structure

- **One responsibility per function.** If a function loads a CSV, opens a browser, takes a screenshot, calls an LLM, and writes JSON — split it.
- **Constants at the top of the module.** No magic numbers buried in the middle of a function. Sleep durations, widths, URLs, paths → named constants.
- **Pure functions where possible.** Side-effectful code (Selenium, file I/O, network) should be isolated from logic that can be reasoned about and tested.
- **No premature abstraction.** Three similar lines is fine. Don't build a plugin system for one model.
- **No dead code, no commented-out code.** Delete it. Git remembers.

## Comments

- Default to none. Well-named identifiers do the work.
- Only comment the **why** when it's non-obvious (a hidden constraint, a load-bearing sleep, a workaround for a specific bug). Example already in this repo: the 12 s sleep comment at [base_analyzer.py:126](base_analyzer.py#L126).
- Never write comments that restate what the code does.

## Dependencies and configuration

- Don't add a dependency without a clear reason. Prefer the stdlib.
- Don't add a config knob "in case someone wants it later." Add it when the second caller appears.

## When unsure

Ask. A two-line question to the user beats a 200-line speculative implementation.
