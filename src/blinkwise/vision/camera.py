"""Frame sources: live webcam or a video file (for offline analysis and tests)."""

from __future__ import annotations

import os
import time
from typing import Iterator, Optional, Tuple, Union

import numpy as np


class FrameSource:
    """Iterate (t_seconds, bgr_frame).

    For a camera, t is a monotonic clock; for a file, t is the media timestamp,
    so analysis of a recording is deterministic and independent of CPU speed.
    """

    def __init__(self, source: Union[int, str] = 0, width: int = 640, height: int = 480,
                 max_fps: Optional[float] = None):
        os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")   # our own error message is clearer
        import cv2

        self._cv2 = cv2
        self.is_file = isinstance(source, str) and not source.isdigit()
        src = source if self.is_file else int(source)
        self.cap = cv2.VideoCapture(src)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"Could not open {'video file' if self.is_file else 'camera'} {source!r}. "
                "On macOS, grant camera access to your terminal in System Settings > "
                "Privacy & Security > Camera.")
        if not self.is_file:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.file_fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.max_fps = max_fps
        self._index = 0
        self._last_emit = 0.0

    @property
    def size(self) -> Tuple[int, int]:
        return (int(self.cap.get(self._cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.cap.get(self._cv2.CAP_PROP_FRAME_HEIGHT)))

    def read(self) -> Optional[Tuple[float, np.ndarray]]:
        ok, frame = self.cap.read()
        if not ok:
            return None
        if self.is_file:
            t = self._index / self.file_fps
            self._index += 1
            return t, frame
        now = time.monotonic()
        if self.max_fps:
            wait = (1.0 / self.max_fps) - (now - self._last_emit)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
        self._last_emit = now
        return now, frame

    def __iter__(self) -> Iterator[Tuple[float, np.ndarray]]:
        while True:
            item = self.read()
            if item is None:
                return
            yield item

    def release(self) -> None:
        self.cap.release()
