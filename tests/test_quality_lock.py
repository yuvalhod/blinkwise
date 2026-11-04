import numpy as np
from test_coach import ctx, ws

from blinkwise.config import Settings
from blinkwise.core.coach import Coach
from blinkwise.vision import geometry as geo
from blinkwise.vision.quality import assess
from blinkwise.vision.tracker import UserLock


def test_quality_grades():
    assert assess(30, 150, 120, 0.01).level == "good"
    q = assess(15, 80, 50, 0.02)
    assert q.level == "fair" and len(q.reasons) == 3 and q.tips
    assert assess(30, 40, 120, 0.01).level == "poor"
    assert assess(30, 60, 120, 0.01).level == "fair"         # zoom keeps 60 px faces usable
    assert assess(30, 150, 20, 0.01).level == "poor"
    assert assess(30, 150, 120, 0.09).level == "poor"
    assert assess(30, None, 120, 0.01).level == "unknown"


def test_poor_tracking_suppresses_blink_advice_and_explains_why():
    poor = assess(30, 40, 25, 0.02)
    fired = {s.rule: s for s in Coach(Settings()).evaluate(ctx(s5=ws(rate=3), quality=poor))}
    assert "low_blink_rate" not in fired
    assert "tracking_quality" in fired and "light" in fired["tracking_quality"].message
    good = assess(30, 150, 120, 0.01)
    assert "low_blink_rate" in {s.rule for s in Coach(Settings()).evaluate(ctx(s5=ws(rate=3), quality=good))}


def _b(cx, w=100, cy=200):
    return (cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2)


def test_user_lock_acquires_largest_then_follows_continuity():
    lock = UserLock()
    assert lock.select([_b(100, 80), _b(500, 140)], 0.0, 640) == 1       # bigger = closer
    # Order changes and the other face grows a bit: stay with the user.
    assert lock.select([_b(505, 140), _b(110, 150)], 0.1, 640) == 0
    assert lock.select([], 0.2, 640) is None


def test_user_lock_never_adopts_bystander_while_user_briefly_hidden():
    lock = UserLock(memory_s=10)
    lock.select([_b(500)], 0.0, 640)
    # User looks down (not detected); only the bystander on the left is visible.
    assert lock.select([_b(100)], 3.0, 640) is None
    assert lock.select([_b(100), _b(495)], 5.0, 640) == 1
    # After the memory expires, whoever is there becomes the user.
    assert lock.select([_b(100)], 30.0, 640) == 0


def _eye_pts(iris_frac):
    pts = np.zeros((478, 3))
    for (outer, inner), c, x0 in ((geo.RIGHT_EYE_CORNERS, geo.RIGHT_IRIS_CENTER, 100),
                                  (geo.LEFT_EYE_CORNERS, geo.LEFT_IRIS_CENTER, 200)):
        pts[outer], pts[inner] = (x0, 100, 0), (x0 + 30, 100, 0)
        pts[c] = (x0 + 15 + iris_frac * 15, 100, 0)
    return pts


def test_eye_in_head_yaw_geometry():
    assert abs(geo.eye_in_head_yaw(_eye_pts(0.0))) < 1e-6
    right = geo.eye_in_head_yaw(_eye_pts(0.4))
    assert 25 < right < 35                      # asin(0.5) = 30 degrees
    assert geo.eye_in_head_yaw(_eye_pts(-0.4)) == -right
    assert geo.eye_in_head_yaw(np.zeros((468, 3))) is None


def test_face_zoom_follows_small_faces_and_searches_when_lost():
    from blinkwise.vision.tracker import FaceZoom
    z = FaceZoom()
    z.update((600, 300, 660, 360), 1280, 720)          # 60 px face -> zoom in around it
    x0, y0, x1, y1 = z.window
    assert x0 <= 600 and x1 >= 660 and y0 <= 300 and y1 >= 360
    assert abs((x1 - x0) / (y1 - y0) - 1280 / 720) < 0.05  # keeps the frame's aspect ratio
    z.update((500, 200, 800, 500), 1280, 720)          # big face -> full frame
    assert z.window is None
    for _ in range(3):
        z.update(None, 1280, 720)                       # lost: full frame first...
    assert z.window is None
    seen = set()
    for _ in range(20):
        z.update(None, 1280, 720)
        if z.window:
            seen.add(z.window)
    assert len(seen) >= 5 and z.searching                # ...then sweeps zoomed tiles
    z.update((100, 100, 140, 140), 1280, 720)            # found in a tile -> zoom on it
    assert z.window is not None and not z.searching
    off = FaceZoom(enabled=False)
    off.update((600, 300, 660, 360), 1280, 720)
    assert off.window is None


def test_frame_size_change_resets_pixel_state():
    """Switching camera resolution must not leave the zoom crop / user lock in old pixels."""
    from blinkwise.vision import tracker as T

    tr = T.FaceTracker.__new__(T.FaceTracker)       # no MediaPipe needed for this part
    tr.zoom, tr.lock, tr._frame_size = T.FaceZoom(), T.UserLock(), (640, 360)
    tr.zoom.window = (100, 50, 300, 200)
    tr.lock.select([(100, 100, 160, 170)], 1.0, 640)
    import numpy as np

    class Stop(Exception):
        pass

    def boom(*a, **k):
        raise Stop
    tr._last_ts_ms, tr.low_light = -1, False
    tr._mp = type("MP", (), {"Image": staticmethod(boom), "ImageFormat": type("F", (), {"SRGB": 0})})
    try:
        tr.process(np.zeros((720, 1280, 3), np.uint8), 2.0)
    except Stop:
        pass
    assert tr.zoom.window is None and tr.lock.last_center is None and tr._frame_size == (1280, 720)
