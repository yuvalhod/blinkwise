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
from .enhance import enhance_low_light, is_dark
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
                 focal_px_override: Optional[float] = None, max_faces: int = 3,
                 low_light: bool = True):
        os.environ.setdefault("GLOG_minloglevel", "2")      # silence MediaPipe's C++ logging
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        import mediapipe as mp  # imported lazily so the engine is usable without it
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=max_faces,
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
        self.lock = UserLock()
        self.low_light = low_light

    def process(self, frame_bgr: np.ndarray, t: float) -> FrameFeatures:
        import cv2

        h, w = frame_bgr.shape[:2]
        ts_ms = int(t * 1000)
        if ts_ms <= self._last_ts_ms:          # MediaPipe requires strictly increasing timestamps
            ts_ms = self._last_ts_ms + 1
        self._last_ts_ms = ts_ms

        raw_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        if self.low_light and is_dark(frame_bgr):
            frame_bgr = enhance_low_light(frame_bgr)
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        res = self._landmarker.detect_for_video(image, ts_ms)
        faces = [np.array([[p.x * w, p.y * h, p.z * w] for p in fl], dtype=np.float32)
                 for fl in res.face_landmarks]
        idx = self.lock.select([_box(f) for f in faces], t, w)
        if idx is None:
            self.last_iris_px = None
            return FrameFeatures(t=t, face=False, faces=len(faces))

        pts = faces[idx]
        er, el, wr, wl = geo.both_eyes(pts)
        yaw = pitch = roll = 0.0
        if len(res.facial_transformation_matrixes) > idx:
            yaw, pitch, roll = geo.euler_from_matrix(np.asarray(res.facial_transformation_matrixes[idx]))
        iris = geo.iris_diameter_px(pts)
        self.last_iris_px = iris
        focal = self.focal_override or geo.focal_length_px(w, self.hfov)
        blink_score = None
        if len(res.face_blendshapes) > idx:
            bs = {c.category_name: c.score for c in res.face_blendshapes[idx]}
            blink_score = (bs.get("eyeBlinkLeft", 0.0) + bs.get("eyeBlinkRight", 0.0)) / 2
        gray = raw_gray      # report the *real* lighting, not the enhanced image
        vis_r, vis_l = geo.eye_visibility(gray, pts)
        x0, y0, x1, y1 = _box(pts)
        return FrameFeatures(
            t=t, face=True, ear_right=er, ear_left=el, width_right=wr, width_left=wl,
            yaw=yaw, pitch=pitch, roll=roll,
            distance_cm=geo.distance_cm_from_iris(iris, focal),
            luminance=geo.face_luminance(gray, pts),
            blink_score=blink_score,
            faces=len(faces),
            face_px=float(x1 - x0),
            eye_yaw=geo.eye_in_head_yaw(pts),
            vis_right=vis_r, vis_left=vis_l,
        )

    def close(self) -> None:
        try:
            self._landmarker.close()
        except Exception:  # pragma: no cover - best effort on shutdown
            pass


def _box(pts: np.ndarray):
    x0, y0 = pts[:, :2].min(0)
    x1, y1 = pts[:, :2].max(0)
    return float(x0), float(y0), float(x1), float(y1)


class UserLock:
    """Decide which face is "the user" when several are in view.

    MediaPipe returns faces in no stable order, and after tracking is lost it
    re-acquires whichever face it finds first, so a coworker or family member in
    the background would otherwise get mixed into your statistics.

    * Continuity: within `memory_s` of last seeing the user, take the face
      nearest their last position if it's within `max_jump` face-widths;
      if only other people are visible, report no user rather than adopting them.
    * Acquisition: otherwise take the largest face (closest to the screen),
      breaking near-ties by closeness to the image centre.
    """

    def __init__(self, memory_s: float = 10.0, max_jump: float = 1.5):
        self.memory_s = memory_s
        self.max_jump = max_jump
        self.last_center = None
        self.last_width = 0.0
        self.last_seen = -1e9

    def select(self, boxes, t: float, image_w: float):
        if not boxes:
            return None
        centers = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
        widths = [b[2] - b[0] for b in boxes]
        idx = None
        if self.last_center is not None and t - self.last_seen <= self.memory_s:
            d = [np.hypot(c[0] - self.last_center[0], c[1] - self.last_center[1]) for c in centers]
            j = int(np.argmin(d))
            if d[j] > self.max_jump * max(self.last_width, widths[j]):
                # Someone else is visible but the user isn't (looking down, turned away).
                # Don't adopt them; report "no user" until the memory expires.
                return None
            idx = j
        if idx is None:
            def score(i):
                off = abs(centers[i][0] - image_w / 2) / max(image_w, 1)
                return widths[i] * (1.0 - 0.3 * off)
            idx = max(range(len(boxes)), key=score)
        self.last_center, self.last_width, self.last_seen = centers[idx], widths[idx], t
        return idx
