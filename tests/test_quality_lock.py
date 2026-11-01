import numpy as np
from test_coach import ctx, ws

from blinkwise.config import Settings
from blinkwise.core.coach import Coach
from blinkwise.vision import geometry as geo
from blinkwise.vision.quality import assess
from blinkwise.vision.tracker import UserLock


def test_quality_grades():
    assert assess(30, 150, 120, 0.01).level == "good"
    q = assess(15, 100, 50, 0.02)
    assert q.level == "fair" and len(q.reasons) == 3 and q.tips
    assert assess(30, 50, 120, 0.01).level == "poor"
    assert assess(30, 150, 20, 0.01).level == "poor"
    assert assess(30, 150, 120, 0.09).level == "poor"
    assert assess(30, None, 120, 0.01).level == "unknown"


def test_poor_tracking_suppresses_blink_advice_and_explains_why():
    poor = assess(30, 50, 25, 0.02)
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
