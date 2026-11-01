"""Command-line interface: `blinkwise <command>`."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import statistics
import sys
import textwrap
import time
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import Settings, data_dir


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="blinkwise",
        description="Blinkwise: a private, on-device webcam coach for healthier screen habits.")
    p.add_argument("--version", action="version", version=f"blinkwise {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="start monitoring with your webcam (default)")
    r.add_argument("--camera", help="camera index or video file (default from settings)")
    r.add_argument("--no-ui", action="store_true", help="no on-screen overlay; system notifications only")
    r.add_argument("--no-dashboard", action="store_true")
    r.add_argument("--open", action="store_true", help="open the dashboard in your browser")

    d = sub.add_parser("demo", help="try Blinkwise without a camera (simulated user)")
    d.add_argument("--speed", type=float, default=1.0, help="simulation speed multiplier")
    d.add_argument("--no-ui", action="store_true")
    d.add_argument("--open", action="store_true", help="open the dashboard in your browser")

    a = sub.add_parser("analyze", help="analyze a recorded video file offline")
    a.add_argument("video")
    a.add_argument("--labels", help="ground-truth JSON to score blink detection against")
    a.add_argument("--json", dest="json_out", help="write the full report as JSON")

    sub.add_parser("report", help="summary of recent days").add_argument("--days", type=int, default=7)
    sub.add_parser("dashboard", help="open the history dashboard without the camera")

    c = sub.add_parser("calibrate", help="calibrate distance estimation for your camera")
    c.add_argument("--distance-cm", type=float, required=True,
                   help="your actual eye-to-camera distance while calibrating (measure it)")
    c.add_argument("--seconds", type=float, default=4.0)

    cf = sub.add_parser("config", help="show or change settings, e.g. `blinkwise config stare_seconds=8`")
    cf.add_argument("assignments", nargs="*")
    cf.add_argument("--reset", action="store_true")

    sub.add_parser("doctor", help="check that camera, model and UI work on this machine")
    sub.add_parser("science", help="the research behind Blinkwise's advice")
    w = sub.add_parser("wipe", help="delete all locally stored history")
    w.add_argument("--yes", action="store_true")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    cmd = args.cmd or "run"
    if cmd == "run" and not hasattr(args, "camera"):
        args = p.parse_args(["run", *(argv or sys.argv[1:])])
    return {
        "run": cmd_run, "demo": cmd_demo, "analyze": cmd_analyze, "report": cmd_report,
        "dashboard": cmd_dashboard, "calibrate": cmd_calibrate, "config": cmd_config,
        "doctor": cmd_doctor, "science": cmd_science, "wipe": cmd_wipe,
    }[cmd](args)


# ---------------------------------------------------------------------------
def cmd_run(args) -> int:
    from .app import App
    s = Settings.load()
    if args.camera is not None:
        s.camera = args.camera
    _first_run_notice()
    App(s, ui=not args.no_ui, dashboard=not args.no_dashboard, open_browser=args.open).run()
    return 0


def cmd_demo(args) -> int:
    from .app import App
    s = Settings.load()
    print(f"Demo: simulating a two-monitor user who forgets to blink, at {args.speed:g}x speed.")
    App(s, demo=True, demo_speed=args.speed, ui=not args.no_ui, open_browser=args.open,
        monitors=2).run()
    return 0


def cmd_dashboard(args) -> int:
    import webbrowser

    from .core.storage import History
    from .ui.dashboard import DashboardServer
    s = Settings.load()
    srv = DashboardServer(s.dashboard_port, history=History(data_dir() / "history.sqlite"))
    url = srv.start()
    print(f"History dashboard: {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()
    return 0


def cmd_analyze(args) -> int:
    from .core.engine import Engine
    from .core.events import BlinkEvent, Suggestion
    from .vision.camera import FrameSource
    from .vision.tracker import FaceTracker, ensure_model

    s = Settings.load()
    src = FrameSource(args.video)
    tracker = FaceTracker(ensure_model(data_dir()), s.camera_hfov_deg, s.focal_px)
    engine = Engine(s, monitors=None)
    blinks, suggestions, frames, faces = [], [], 0, 0
    t0 = time.time()
    for t, frame in src:
        f = tracker.process(frame, t)
        frames += 1
        faces += int(f.face)
        for ev in engine.step(f):
            if isinstance(ev, BlinkEvent):
                blinks.append(ev.blink)
            elif isinstance(ev, Suggestion):
                suggestions.append(ev)
    tracker.close()
    elapsed = time.time() - t0
    snap = engine.snapshot()
    duration = frames / src.file_fps if src.file_fps else 0
    judged = [b for b in blinks if b.complete is not None]
    report = {
        "video": args.video, "frames": frames, "fps": round(src.file_fps, 2),
        "duration_s": round(duration, 1), "face_found_pct": round(100 * faces / max(frames, 1), 1),
        "observed_s": round(snap["screen_minutes"] * 60, 1),
        "blinks": len(blinks),
        "blink_rate_per_min": round(len(blinks) / (snap["screen_minutes"] or 1e-9), 1)
        if snap["screen_minutes"] > 0 else None,
        "incomplete_pct": round(100 * sum(not b.complete for b in judged) / len(judged), 1)
        if judged else None,
        "mean_blink_ms": round(1000 * statistics.mean(b.duration for b in blinks)) if blinks else None,
        "distance_cm": snap["distance_cm"],
        "zones": snap["zones"],
        "suggestions": [dataclasses.asdict(x) for x in suggestions],
        "blink_times_s": [round(b.t, 3) for b in blinks],
        "processing_fps": round(frames / max(elapsed, 1e-9), 1),
    }
    print(f"Video: {args.video}  ({duration:.1f} s @ {src.file_fps:.1f} fps, face visible "
          f"{report['face_found_pct']}% of frames, processed at {report['processing_fps']} fps)")
    print(f"Blinks: {len(blinks)}   rate: {report['blink_rate_per_min']}/min of observed time")
    if report["incomplete_pct"] is not None:
        print(f"Incomplete blinks: {report['incomplete_pct']}%")
    else:
        print("Incomplete blinks: n/a (needs >= 20 fps video)")
    if report["distance_cm"]:
        print(f"Estimated viewing distance: ~{report['distance_cm']:.0f} cm")
    if args.labels:
        from .vision.evaluate import score
        labels = json.loads(Path(args.labels).read_text())
        sc = score([round(b.t * src.file_fps) for b in blinks], labels)
        report["score"] = dict(precision=sc.precision, recall=sc.recall, f1=sc.f1,
                               tp=sc.tp, fp=sc.fp, fn=sc.fn)
        print(f"Against labels: precision {sc.precision:.2f}, recall {sc.recall:.2f}, "
              f"F1 {sc.f1:.2f} (tp={sc.tp} fp={sc.fp} fn={sc.fn})")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2))
        print(f"Wrote {args.json_out}")
    return 0


def cmd_report(args) -> int:
    from .core.storage import History
    path = data_dir() / "history.sqlite"
    if not path.exists():
        print("No history yet. Run `blinkwise run` first.")
        return 0
    days = History(path).daily(args.days)
    if not days:
        print("No history in that period.")
        return 0
    print(f"{'day':<12}{'screen':>9}{'blinks/min':>12}{'full blinks':>13}{'distance':>10}{'breaks':>9}")
    for d in days:
        full = "--" if d["incomplete_ratio"] is None else f"{100 * (1 - d['incomplete_ratio']):.0f}%"
        rate = "--" if d["blink_rate"] is None else f"{d['blink_rate']:.1f}"
        dist = "--" if d["distance_cm"] is None else f"{d['distance_cm']} cm"
        print(f"{d['day']:<12}{d['screen_minutes'] / 60:>8.1f}h{rate:>12}{full:>13}{dist:>10}"
              f"{d['breaks_taken']:>5}/{d['breaks_missed']}")
    return 0


def cmd_calibrate(args) -> int:
    from .vision.camera import FrameSource
    from .vision.tracker import FaceTracker, ensure_model
    s = Settings.load()
    tracker = FaceTracker(ensure_model(data_dir()), s.camera_hfov_deg)
    src = FrameSource(s.camera)
    print(f"Sit still with your eyes {args.distance_cm:g} cm from the camera and look at it...")
    samples, end = [], time.monotonic() + args.seconds
    while time.monotonic() < end:
        item = src.read()
        if item is None:
            break
        f = tracker.process(item[1], item[0])
        if f.face and abs(f.yaw) < 15 and tracker.last_iris_px:
            samples.append(tracker.last_iris_px)
    src.release()
    tracker.close()
    if len(samples) < 10:
        print("Couldn't see your face clearly enough. Check lighting and try again.")
        return 1
    iris = statistics.median(samples)
    s.focal_px = round(iris * args.distance_cm / 1.17, 1)
    s.save()
    print(f"Calibrated: focal length {s.focal_px} px (from {len(samples)} frames). Saved.")
    return 0


def cmd_config(args) -> int:
    s = Settings() if args.reset else Settings.load()
    if args.assignments or args.reset:
        try:
            s.update(**dict(a.split("=", 1) for a in args.assignments))
        except (KeyError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"Saved {s.save()}")
    for k, v in dataclasses.asdict(s).items():
        print(f"  {k} = {v}")
    return 0


def cmd_doctor(args) -> int:
    ok = True

    def check(name, fn):
        nonlocal ok
        try:
            msg = fn()
            print(f"  [ok]   {name}{': ' + msg if msg else ''}")
        except Exception as e:
            ok = False
            print(f"  [fail] {name}: {e}")

    print(f"Blinkwise {__version__} on Python {sys.version.split()[0]} ({sys.platform})")
    print(f"Data folder: {data_dir()}")

    def mp():
        import mediapipe
        return mediapipe.__version__

    def model():
        from .vision.tracker import ensure_model
        return str(ensure_model(data_dir()))

    def cam():
        from .vision.camera import FrameSource
        s = Settings.load()
        src = FrameSource(s.camera)
        item = src.read()
        size = src.size
        src.release()
        if item is None:
            raise RuntimeError("opened but returned no frames")
        return f"camera {s.camera} gives {size[0]}x{size[1]}"

    def tk():
        from .ui.overlay import TK_AVAILABLE
        from .ui.overlay import tk as _tk
        if not TK_AVAILABLE:
            raise RuntimeError("tkinter missing; overlays disabled (install python3-tk)")
        r = _tk.Tk()
        r.destroy()
        return "on-screen overlays available"

    def monitors():
        from .vision.attention import connected_monitors
        n = connected_monitors()
        if n:
            return f"{n} display(s)"
        return "unknown (no display found; screens in use are still inferred from head pose)"

    check("MediaPipe", mp)
    check("Face model", model)
    check("Camera", cam)
    check("Overlay UI", tk)
    check("Displays", monitors)
    return 0 if ok else 1


def cmd_science(args) -> int:
    from .research import REFERENCES
    for r in REFERENCES.values():
        print(textwrap.fill(r.finding, 88))
        print(textwrap.indent(textwrap.fill(r.citation, 84), "    "))
        print(f"    {r.url}\n")
    return 0


def cmd_wipe(args) -> int:
    path = data_dir() / "history.sqlite"
    if not path.exists():
        print("Nothing to delete.")
        return 0
    if not args.yes and input(f"Delete all history in {path}? [y/N] ").strip().lower() != "y":
        return 1
    path.unlink()
    print("History deleted.")
    return 0


def _first_run_notice() -> None:
    marker = data_dir() / ".welcomed"
    if marker.exists():
        return
    print(textwrap.dedent("""
        Welcome to Blinkwise.
          - Your camera is analysed on this computer only. No images are stored or sent.
          - Only per-minute numbers (blink counts, distance, breaks) are saved locally.
          - Pause any time from the dashboard (the camera turns off), or press Ctrl+C to quit.
          - The face model (3.7 MB) is downloaded once from Google's MediaPipe servers.
        """))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1")


if __name__ == "__main__":
    sys.exit(main())
