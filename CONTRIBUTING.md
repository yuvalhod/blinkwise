# Contributing

Thanks for helping people's eyes.

## Dev setup

```bash
python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -e ".[dev]"
```

```bash
pytest -q && ruff check src tests scripts
```

`blinkwise demo --speed 30 --open` exercises the whole app without a camera.

## Most valuable contributions

1. **Labelled blink data.** Record yourself (with consent) in varied conditions: glasses, low light, backlight, different skin tones, children with a parent's consent. Run `python scripts/extract_features.py video.mp4 features.json` (only numbers, no images) and label blink frames in the format of `tests/data/intel_head_pose_labels.json`. Share the features and labels; you never need to share the video.
2. **Packaging**: signed installers for macOS and Windows, and a tray icon.
3. **Translations** of coaching messages.

## Ground rules

* Pixels never leave `vision/tracker.py`. Nothing may store or transmit images.
* Any new advice needs a reference in `research.py` and an honest statement of evidence strength in `docs/SCIENCE.md`.
* Respect attention: new notifications go through the coach's cooldown and anti-nag gate.
* Keep `core/` free of I/O and wall-clock time, so it stays testable with the simulator.
