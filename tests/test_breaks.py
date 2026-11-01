from blinkwise.core.breaks import BreakScheduler
from blinkwise.core.events import BreakDue, BreakEnded


def _run(b, seconds, on_screen=True, low=False, t0=0.0, dt=1.0):
    evs, t = [], t0
    for _ in range(int(seconds / dt)):
        t += dt
        evs += b.tick(t, dt, on_screen, low)
    return evs, t


def test_micro_break_due_after_20_minutes_of_screen_time():
    b = BreakScheduler()
    evs, _ = _run(b, 20 * 60 - 2)
    assert evs == []
    evs, _ = _run(b, 3, t0=20 * 60 - 2)
    assert isinstance(evs[0], BreakDue) and evs[0].kind == "micro"


def test_natural_break_resets_timer():
    b = BreakScheduler()
    _, t = _run(b, 15 * 60)
    _, t = _run(b, 25, on_screen=False, t0=t)
    assert b.since_micro == 0
    evs, _ = _run(b, 10 * 60, t0=t)
    assert evs == []


def test_looking_away_during_break_completes_it():
    b = BreakScheduler()
    _, t = _run(b, 20 * 60 + 1)
    evs, _ = _run(b, 20, on_screen=False, t0=t)
    ended = [e for e in evs if isinstance(e, BreakEnded)]
    assert ended and ended[0].outcome == "rested"
    assert b.completed["micro"] == 1


def test_missed_break_snoozes_instead_of_nagging():
    b = BreakScheduler()
    _, t = _run(b, 20 * 60 + 1)
    evs, t = _run(b, 10 * 60, t0=t)          # ignore it for 10 minutes
    dues = [e for e in evs if isinstance(e, BreakDue)]
    missed = [e for e in evs if isinstance(e, BreakEnded) and e.outcome == "missed"]
    assert len(missed) >= 1
    assert len(dues) <= 2                    # grace 2 min + snooze 5 min


def test_adaptive_brings_break_forward_when_blinking_is_low():
    b = BreakScheduler()
    evs, _ = _run(b, 15 * 60 + 1, low=True)
    assert any(isinstance(e, BreakDue) for e in evs)
    b2 = BreakScheduler(adaptive=False)
    evs, _ = _run(b2, 15 * 60 + 1, low=True)
    assert evs == []


def test_long_break_and_ui_finish():
    b = BreakScheduler(micro_minutes=999)
    evs, _ = _run(b, 60 * 60 + 1)
    assert evs[-1].kind == "long"
    ended = b.finish("timer")
    assert ended.outcome == "timer" and b.since_long == 0
    assert b.finish("skipped") is None
