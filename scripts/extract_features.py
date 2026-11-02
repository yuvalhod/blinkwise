"""Run the face tracker over a video once and cache FrameFeatures as JSON.

Used to build the regression fixture in tests/data so detector tests run in
milliseconds without MediaPipe:  python scripts/extract_features.py VIDEO OUT.json
"""
import dataclasses
import json
import sys
from pathlib import Path

from blinkwise.config import data_dir
from blinkwise.vision.camera import FrameSource
from blinkwise.vision.tracker import FaceTracker, ensure_model

video, out = sys.argv[1], sys.argv[2]
tracker = FaceTracker(ensure_model(data_dir()))
rows = []
for t, frame in FrameSource(video):
    f = tracker.process(frame, t)
    rows.append({k: (round(v, 5) if isinstance(v, float) else v) for k, v in dataclasses.asdict(f).items()})
meta = {"video": Path(video).name, "fps": FrameSource(video).file_fps}
tracker.close()
Path(out).write_text(json.dumps({**meta, "frames": rows}))
print(f"{len(rows)} frames -> {out}")
