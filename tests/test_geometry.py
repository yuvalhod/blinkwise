import math

import numpy as np
import pytest

from blinkwise.vision import geometry as geo


def _eye_points(open_px: float, width: float = 30.0) -> np.ndarray:
    pts = np.zeros((478, 3), dtype=np.float32)
    for (outer, inner), pairs, x0 in ((geo.RIGHT_EYE_CORNERS, geo.RIGHT_EYE_PAIRS, 100),
                                      (geo.LEFT_EYE_CORNERS, geo.LEFT_EYE_PAIRS, 200)):
        pts[outer] = (x0, 100, 0)
        pts[inner] = (x0 + width, 100, 0)
        for k, (up, lo) in enumerate(pairs):
            x = x0 + width * (k + 1) / 4
            pts[up] = (x, 100 - open_px / 2, 0)
            pts[lo] = (x, 100 + open_px / 2, 0)
    return pts


def test_ear_scales_with_opening_and_is_scale_invariant():
    er, el, wr, wl = geo.both_eyes(_eye_points(9.0))
    assert er == pytest.approx(0.3) and el == pytest.approx(0.3)
    assert wr == pytest.approx(30.0)
    big = _eye_points(18.0, width=60.0)
    assert geo.both_eyes(big)[0] == pytest.approx(0.3)
    assert geo.both_eyes(_eye_points(0.0))[0] == pytest.approx(0.0)


def test_ear_handles_degenerate_eye():
    assert geo.eye_aspect_ratio(np.zeros((478, 3)), (0, 1), ((2, 3),)) == (0.0, 0.0)


def _rot(yaw=0.0, pitch=0.0, roll=0.0):
    y, p, r = map(math.radians, (yaw, pitch, roll))
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = rz @ ry @ rx
    return m


@pytest.mark.parametrize("yaw,pitch,roll", [(0, 0, 0), (25, 0, 0), (-30, 10, 5), (10, -20, -15)])
def test_euler_roundtrip(yaw, pitch, roll):
    # MediaPipe's +x rotation is chin-down, which we report as negative pitch.
    y, p, r = geo.euler_from_matrix(_rot(yaw, -pitch, roll))
    assert (y, p, r) == pytest.approx((yaw, pitch, roll), abs=1e-6)


def test_iris_distance_similar_triangles():
    f = geo.focal_length_px(640, 60.0)
    assert f == pytest.approx(554.26, rel=1e-3)
    # An 11.7 mm iris that is 10.8 px wide is ~60 cm away for this focal length.
    assert geo.distance_cm_from_iris(10.8, f) == pytest.approx(60.0, rel=0.01)
    assert geo.distance_cm_from_iris(None, f) is None


def test_iris_requires_refined_landmarks():
    assert geo.iris_diameter_px(np.zeros((468, 3))) is None
    pts = np.zeros((478, 3))
    pts[469], pts[471] = (0, 0, 0), (12, 0, 0)
    pts[474], pts[476] = (0, 0, 0), (8, 0, 0)
    assert geo.iris_diameter_px(pts) == pytest.approx(12.0)   # the nearer (larger) iris


def test_face_luminance():
    gray = np.full((100, 100), 77, dtype=np.uint8)
    pts = np.array([[10, 10, 0], [60, 70, 0]], dtype=float)
    assert geo.face_luminance(gray, pts) == pytest.approx(77)
