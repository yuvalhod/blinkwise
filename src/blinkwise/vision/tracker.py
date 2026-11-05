"""MediaPipe Face Landmarker wrapper: BGR frame in, FrameFeatures out."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
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


def _import_mediapipe():
    """Import MediaPipe Tasks without dragging in matplotlib.

    mediapipe.tasks.python.vision eagerly imports its drawing utilities, which import
    matplotlib.pyplot: ~0.5 s per start, a font-cache build (minutes) on a fresh
    machine, and tens of MB in a packaged app, for code Blinkwise never calls. The
    drawing module only uses pyplot inside functions, so a placeholder is enough while
    importing; it's removed afterwards so real matplotlib still works if anything
    else needs it.
    """
    import types

    stubbed = []
    if "matplotlib" not in sys.modules:
        for name in ("matplotlib", "matplotlib.pyplot"):
            sys.modules[name] = types.ModuleType(name)
            stubbed.append(name)
    try:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
    finally:
        for name in stubbed:
            sys.modules.pop(name, None)
    return mp, BaseOptions, vision


def _ssl_context():
    """certifi's CA bundle when available: some Python builds (python.org, uv) can't see
    the macOS keychain, so the default context fails certificate checks."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def bundled_model() -> Optional[Path]:
    """The model shipped inside a packaged app (PyInstaller), if any: no download needed."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    p = Path(base) / "blinkwise" / "models" / "face_landmarker.task"
    return p if p.exists() and _sha256(p) == MODEL_SHA256 else None


def ensure_model(data_dir: Path, url: str = MODEL_URL) -> Path:
    """Return a verified local copy of the face landmarker model, downloading once.

    The model is the only network access Blinkwise ever makes, and you can skip
    it entirely by placing the file yourself (or setting BLINKWISE_MODEL).
    """
    override = os.environ.get("BLINKWISE_MODEL")
    if override:
        return Path(override)
    bundled = bundled_model()
    if bundled is not None:
        return bundled
    path = data_dir / "face_landmarker.task"
    if path.exists() and _sha256(path) == MODEL_SHA256:
        return path
    data_dir.mkdir(parents=True, exist_ok=True)
    log.info("Downloading face model (3.7 MB, one time) from %s", url)
    with tempfile.NamedTemporaryFile(dir=data_dir, delete=False) as tmp:
        with urllib.request.urlopen(url, timeout=60, context=_ssl_context()) as resp:  # noqa: S310
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


SCAN_EVERY_S = 5.0         # routine look for other people
RESCAN_S = 0.5             # ...and at most this often while the user is not found


class FaceTracker:
    """Runs MediaPipe in VIDEO mode (temporal smoothing + tracking between frames).

    Power: a landmarker asked for N faces runs its face *detector* on every frame
    while it tracks fewer than N, looking for more. So the per-frame model tracks
    one face, and a second, multi-face model looks at the scene every 5 s (and up
    to twice a second while the tracked face isn't the user) to count people and keep the user
    lock honest. That's ~15% less CPU per frame with the same bystander protection.
    """

    def __init__(self, model_path: Path, horizontal_fov_deg: float = 60.0,
                 focal_px_override: Optional[float] = None, max_faces: int = 3,
                 focal_px_width: int = 1280,
                 low_light: bool = True, zoom: bool = True):
        os.environ.setdefault("GLOG_minloglevel", "2")      # silence MediaPipe's C++ logging
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        mp, BaseOptions, vision = _import_mediapipe()

        self._mp = mp

        def make(n: int):
            return vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=n,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                output_face_blendshapes=False,          # not used; skipping saves a model run
                output_facial_transformation_matrixes=True,
            ))
        self._make = make
        self._landmarker = make(1)
        self._scanner = make(max_faces) if max_faces > 1 else None
        self._last_scan = -1e9
        self._scan_ts_ms = -1
        self.people = 0
        self.hfov = horizontal_fov_deg
        self.focal_override = focal_px_override
        self.focal_width = focal_px_width          # image width the calibration was made at
        self._last_ts_ms = -1
        self.last_iris_px: Optional[float] = None
        self.lock = UserLock()
        self.zoom = FaceZoom(enabled=zoom)
        self._frame_size = None
        self.low_light = low_light

    def process(self, frame_bgr: np.ndarray, t: float) -> FrameFeatures:
        import cv2

        h, w = frame_bgr.shape[:2]
        if (w, h) != self._frame_size:
            # New frame size (e.g. switched camera resolution): positions remembered in the
            # old pixel coordinates (zoom crop, where the user was) no longer apply.
            if self._frame_size is not None:
                self.zoom = FaceZoom(enabled=self.zoom.enabled)
                self.lock = UserLock()
            self._frame_size = (w, h)
        ts_ms = int(t * 1000)
        if ts_ms <= self._last_ts_ms:          # MediaPipe requires strictly increasing timestamps
            ts_ms = self._last_ts_ms + 1
        self._last_ts_ms = ts_ms

        raw_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        if self.low_light and is_dark(frame_bgr):
            frame_bgr = enhance_low_light(frame_bgr)
        # Digital zoom: when the face is small, feed MediaPipe a crop around it (its face
        # detector downsizes the whole frame, so small faces otherwise vanish).
        roi = self.zoom.window
        if roi is not None:
            x0, y0, x1, y1 = roi
            feed = frame_bgr[y0:y1, x0:x1]
        else:
            x0, y0, x1, y1 = 0, 0, w, h
            feed = frame_bgr
        rgb = cv2.cvtColor(feed, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        cw, ch = x1 - x0, y1 - y0

        def points(r):
            return [np.array([[x0 + p.x * cw, y0 + p.y * ch, p.z * cw] for p in fl], dtype=np.float32)
                    for fl in r.face_landmarks]

        res = self._landmarker.detect_for_video(image, ts_ms)
        faces = points(res)
        # Trust the 1-face model only while it follows the locked-in user; acquiring the
        # user (largest face) goes through the scan.
        main_ok = bool(faces) and self.lock.active(t) and self.lock.would_accept(_box(faces[0]), t)
        since = t - self._last_scan
        if self._scanner is not None and (since >= SCAN_EVERY_S or (not main_ok and since >= RESCAN_S)):
            self._scan_ts_ms = max(ts_ms, self._scan_ts_ms + 1)
            sres = self._scanner.detect_for_video(image, self._scan_ts_ms)
            self._last_scan = t
            sfaces = points(sres)
            self.people = len(sfaces)
            main_faces = faces
            if not main_ok:
                res, faces = sres, sfaces            # the scan decides who the user is
            idx = self.lock.select([_box(f) for f in faces], t, w)
            if idx is not None and not main_ok and main_faces and \
                    not _same_face(_box(main_faces[0]), _box(faces[idx])):
                # The 1-face model is following someone else: restart it so it re-acquires
                # (its detector prefers the biggest face, which is what the lock picks).
                self._restart_main()
        else:
            if faces:
                self.people = max(self.people, 1)
            idx = self.lock.select([_box(f) for f in faces], t, w)
        self.zoom.update(_box(faces[idx]) if idx is not None else None, w, h)
        if idx is None:
            self.last_iris_px = None
            return FrameFeatures(t=t, face=False, faces=self.people if self._scanner else len(faces))

        pts = faces[idx]
        er, el, wr, wl = geo.both_eyes(pts)
        yaw = pitch = roll = 0.0
        if len(res.facial_transformation_matrixes) > idx:
            yaw, pitch, roll = geo.euler_from_matrix(np.asarray(res.facial_transformation_matrixes[idx]))
        iris = geo.iris_diameter_px(pts)
        self.last_iris_px = iris
        focal = (self.focal_override * w / self.focal_width if self.focal_override
                 else geo.focal_length_px(w, self.hfov))
        blink_score = None
        gray = raw_gray      # report the *real* lighting, not the enhanced image
        vis_r, vis_l = geo.eye_visibility(gray, pts)
        x0, y0, x1, y1 = _box(pts)
        return FrameFeatures(
            t=t, face=True, ear_right=er, ear_left=el, width_right=wr, width_left=wl,
            yaw=yaw, pitch=pitch, roll=roll,
            distance_cm=geo.distance_cm_from_iris(iris, focal),
            luminance=geo.face_luminance(gray, pts),
            blink_score=blink_score,
            faces=max(self.people, 1) if self._scanner else len(faces),
            face_px=float(x1 - x0),
            eye_yaw=geo.eye_in_head_yaw(pts),
            vis_right=vis_r, vis_left=vis_l,
        )

    def _restart_main(self) -> None:
        if self._restarted_at is not None and self._last_ts_ms - self._restarted_at < 3000:
            return                                   # at most every 3 s
        self._restarted_at = self._last_ts_ms
        try:
            self._landmarker.close()
        except Exception:  # pragma: no cover
            pass
        self._landmarker = self._make(1)

    _restarted_at: Optional[int] = None

    def close(self) -> None:
        for lm in (self._landmarker, self._scanner):
            try:
                if lm is not None:
                    lm.close()
            except Exception:  # pragma: no cover - best effort on shutdown
                pass


def _same_face(a, b) -> bool:
    ca, cb = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    return float(np.hypot(ca[0] - cb[0], ca[1] - cb[1])) < 0.5 * max(a[2] - a[0], b[2] - b[0])


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

    def active(self, t: float) -> bool:
        return self.last_center is not None and t - self.last_seen <= self.memory_s

    def would_accept(self, box, t: float) -> bool:
        """Would `box` count as the user (without committing)? True when nobody is locked."""
        if self.last_center is None or t - self.last_seen > self.memory_s:
            return True
        c = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        d = np.hypot(c[0] - self.last_center[0], c[1] - self.last_center[1])
        return d <= self.max_jump * max(self.last_width, box[2] - box[0])

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


class FaceZoom:
    """A smoothed crop window that follows a small face.

    Measured on real video: with the face at 60% of its normal size (~69 px wide)
    MediaPipe found it in 70% of frames, at 40% (~46 px) in none. Cropping around
    the face makes it large again in the image MediaPipe sees.
    """

    def __init__(self, enabled: bool = True, below_px: float = 150.0, factor: float = 4.0,
                 min_crop: float = 240.0, misses_to_reset: int = 3, smooth: float = 0.35):
        self.enabled = enabled
        self.below_px = below_px      # zoom when the face is narrower than this
        self.factor = factor          # crop width = factor x face width
        self.min_crop = min_crop
        self.misses_to_reset = misses_to_reset
        self.smooth = smooth
        self.window = None            # (x0, y0, x1, y1) ints, or None = full frame
        self._f = None                # float window for smoothing
        self._misses = 0
        self.searching = False
        self._scan = 0

    # Half-size tiles (50% overlap) tried when nothing is found in the full frame,
    # so a face too small to be detected at full size can still be acquired.
    _TILES = [(0.25, 0.25), (0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5),
              (0.25, 0.0), (0.25, 0.5), (0.0, 0.25), (0.5, 0.25)]

    def update(self, box, w: int, h: int) -> None:
        if not self.enabled:
            return
        if box is None:
            self._misses += 1
            if self._misses >= self.misses_to_reset:
                self._f = None
                # Alternate: full frame, tile, full frame, next tile, ...
                if self.window is None and self._misses >= 2 * self.misses_to_reset:
                    fx, fy = self._TILES[self._scan % len(self._TILES)]
                    self._scan += 1
                    self.window = (int(fx * w), int(fy * h), int(fx * w + w / 2), int(fy * h + h / 2))
                    self.searching = True
                else:
                    self.window = None
            return
        self._misses = 0
        self.searching = False
        fw = box[2] - box[0]
        if fw >= self.below_px:
            self.window, self._f = None, None
            return
        cw = min(float(w), max(self.min_crop, self.factor * fw))
        chh = min(float(h), cw * h / w)
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        target = [cx - cw / 2, cy - chh / 2, cx + cw / 2, cy + chh / 2]
        if self._f is None:
            self._f = target
        else:
            self._f = [a + self.smooth * (b - a) for a, b in zip(self._f, target, strict=True)]
        x0, y0, x1, y1 = self._f
        # Keep the window inside the frame without changing its size.
        dx = max(0.0, -x0) - max(0.0, x1 - w)
        dy = max(0.0, -y0) - max(0.0, y1 - h)
        x0, x1, y0, y1 = x0 + dx, x1 + dx, y0 + dy, y1 + dy
        self.window = (int(max(0, x0)), int(max(0, y0)), int(min(w, x1)), int(min(h, y1)))
