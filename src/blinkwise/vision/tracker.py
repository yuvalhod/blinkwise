"""MediaPipe Face Landmarker wrapper: BGR frame in, FrameFeatures out."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np

from . import geometry as geo
from .features import FrameFeatures

log = logging.getLogger(__name__)

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


def ensure_model(data_dir: Path, url: str = MODEL_URL) -> Path:
    """Return a verified local copy of the face landmarker model, downloading once.

    The model is the only network access Blinkwise ever makes, and you can skip
    it entirely by placing the file yourself (or setting BLINKWISE_MODEL).
    """
    override = os.environ.get("BLINKWISE_MODEL")
    if override:
        return Path(override)
    path = data_dir / "face_landmarker.task"
    if path.exists() and _sha256(path) == MODEL_SHA256:
        return path
    data_dir.mkdir(parents=True, exist_ok=True)
    log.info("Downloading face model (3.7 MB, one time) from %s", url)
    with tempfile.NamedTemporaryFile(dir=data_dir, delete=False) as tmp:
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (fixed https URL)
            shutil.copyfileobj(resp, tmp)
    digest = _sha256(Path(tmp.name))
    if digest != MODEL_SHA256:
        os.unlink(tmp.name)
        raise RuntimeError(f"Model checksum mismatch ({digest}); refusing to use it.")
    os.replace(tmp.name, path)
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class FaceTracker:
    """Runs MediaPipe in VIDEO mode (temporal smoothing + tracking between frames)."""

    def __init__(self, model_path: Path, horizontal_fov_deg: float = 60.0,
                 focal_px_override: Optional[float] = None):
        os.environ.setdefault("GLOG_minloglevel", "2")      # silence MediaPipe's C++ logging
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        import mediapipe as mp  # imported lazily so the engine is usable without it
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(opts)
        self.hfov = horizontal_fov_deg
        self.focal_override = focal_px_override
        self._last_ts_ms = -1
        self.last_iris_px: Optional[float] = None

    def process(self, frame_bgr: np.ndarray, t: float) -> FrameFeatures:
        import cv2

        h, w = frame_bgr.shape[:2]
        ts_ms = int(t * 1000)
        if ts_ms <= self._last_ts_ms:          # MediaPipe requires strictly increasing timestamps
            ts_ms = self._last_ts_ms + 1
        self._last_ts_ms = ts_ms

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        res = self._landmarker.detect_for_video(image, ts_ms)
        if not res.face_landmarks:
            self.last_iris_px = None
            return FrameFeatures(t=t, face=False)

        pts = np.array([[p.x * w, p.y * h, p.z * w] for p in res.face_landmarks[0]], dtype=np.float32)
        er, el, wr, wl = geo.both_eyes(pts)
        yaw = pitch = roll = 0.0
        if res.facial_transformation_matrixes:
            yaw, pitch, roll = geo.euler_from_matrix(np.asarray(res.facial_transformation_matrixes[0]))
        iris = geo.iris_diameter_px(pts)
        self.last_iris_px = iris
        focal = self.focal_override or geo.focal_length_px(w, self.hfov)
        blink_score = None
        if res.face_blendshapes:
            bs = {c.category_name: c.score for c in res.face_blendshapes[0]}
            blink_score = (bs.get("eyeBlinkLeft", 0.0) + bs.get("eyeBlinkRight", 0.0)) / 2
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        return FrameFeatures(
            t=t, face=True, ear_right=er, ear_left=el, width_right=wr, width_left=wl,
            yaw=yaw, pitch=pitch, roll=roll,
            distance_cm=geo.distance_cm_from_iris(iris, focal),
            luminance=geo.face_luminance(gray, pts),
            blink_score=blink_score,
        )

    def close(self) -> None:
        try:
            self._landmarker.close()
        except Exception:  # pragma: no cover - best effort on shutdown
            pass
