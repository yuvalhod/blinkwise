from blinkwise.core.simulate import Scenario, Simulation
from blinkwise.vision.blink import BlinkDetector, BlinkParams


def run_detector(sc: Scenario, params: BlinkParams = None):
    sim = Simulation(sc)
    det = BlinkDetector(params)
    found = [b for f in sim.frames() if (b := det.update(f)) is not None]
    return sim.truth, found


def match(truth, found):
    """Greedy match by time. Returns (pairs, false_positives, misses)."""
    used, pairs, fps = set(), [], []
    for b in found:
        cands = [i for i in range(len(truth)) if i not in used]
        i = min(cands, key=lambda i: abs(truth[i].t - b.t), default=None)
        tol = 0.4 if i is not None and truth[i].long else 0.15
        if i is not None and abs(truth[i].t - b.t) < tol:
            used.add(i)
            pairs.append((truth[i], b))
        else:
            fps.append(b)
    misses = [t for i, t in enumerate(truth) if i not in used]
    return pairs, fps, misses
