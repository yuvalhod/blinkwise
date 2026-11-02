# ruff: noqa: E501  (embedded CSS/HTML)
"""Render a design mock-up of the macOS menu-bar item and its dropdown.

The icon comes from blinkwise.ui.icon and the menu text and structure from
blinkwise.ui.menu.build_menu, the same code the real tray uses, so the
mock-up can't drift from the product. Only the macOS chrome is imitated.

    python scripts/render_menubar_mock.py OUT.html
"""

import base64
import html
import io
import sys

from blinkwise.ui.icon import render
from blinkwise.ui.menu import build_menu, icon_state

SCENES = [
    ("Mid-afternoon, blinking too little", dict(
        running=True, face=True, paused=False, blink_rate_5m=7.2, seconds_since_blink=9,
        next_break_s=440, quality={"level": "good"},
        today={"screen_minutes": 263, "breaks_taken": 5})),
    ("Eye break due (dot on the icon)", dict(
        running=True, face=True, paused=False, blink_rate_5m=11.4, seconds_since_blink=2,
        break_active="micro", quality={"level": "good"},
        today={"screen_minutes": 281, "breaks_taken": 5})),
    ("Paused (camera off)", dict(
        running=True, face=False, paused=True, paused_for_s=1520,
        today={"screen_minutes": 300, "breaks_taken": 6})),
]


def icon_data_uri(state, badge, dark):
    img = render(state, 44, (255, 255, 255, 235) if dark else (0, 0, 0, 220), badge=badge)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def menu_html(items, sub=False):
    out = []
    for it in items:
        if it.separator:
            out.append('<div class="sep"></div>')
            continue
        cls = ["item"]
        if it.info:
            cls.append("info")
        elif not it.enabled:
            cls.append("title" if not sub and not out else "disabled")
        check = "&#10003;" if it.checked else ""
        arrow = '<span class="arrow">&#8250;</span>' if it.submenu else ""
        out.append(f'<div class="{" ".join(cls)}"><span class="check">{check}</span>'
                   f'<span class="label">{html.escape(it.text)}</span>{arrow}</div>')
    return "".join(out)


def scene_html(title, snap, dark):
    state, badge = icon_state(snap)
    items = build_menu(snap, blink_cue="menubar", autostart=True)
    sub = next((i for i in items if i.text == "Blink reminder"), None)
    sub_html = f'<div class="menu submenu">{menu_html(sub.submenu, True)}</div>' if (
        sub and "Paused" not in title and "break" not in title) else ""
    return f"""
<figure class="scene {'dark' if dark else 'light'}">
  <div class="desktop">
    <div class="bar">
      <span class="sys">&#63743;</span>
      <span class="right">
        <span class="other">&#9679;&#9679;</span>
        <span class="mine"><img src="{icon_data_uri(state, badge, dark)}" width="22" height="22" alt=""></span>
        <span class="other">&#9685;</span><span class="clock">3:56 PM</span>
      </span>
    </div>
    <div class="menu main">{menu_html(items)}</div>{sub_html}
  </div>
  <figcaption>{html.escape(title)} &middot; {'dark' if dark else 'light'} menu bar</figcaption>
</figure>"""


CSS = """
:root{--bg:#f4f5f7;--ink:#1d1d1f;--muted:#6e6e73}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#111214;--ink:#f2f2f2;--muted:#9a9aa0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:20px;margin:0 0 4px} p.sub{color:var(--muted);margin:0 0 20px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media (max-width:1100px){.grid{grid-template-columns:1fr}}
figure{overflow-x:auto}
figure{margin:0} figcaption{color:var(--muted);font-size:12px;margin-top:6px}
.desktop{position:relative;height:430px;min-width:600px;border-radius:12px;overflow:hidden;
  background:linear-gradient(160deg,#9fb6d8,#c9b6d9 60%,#e6c7b8)}
.dark .desktop{background:linear-gradient(160deg,#1d2b45,#3a2d4f 60%,#4a3530)}
.bar{height:26px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;
  background:rgba(246,246,246,.72);backdrop-filter:blur(20px);color:#000;font-size:13px}
.dark .bar{background:rgba(30,30,30,.6);color:#fff}
.bar .right{display:flex;align-items:center;gap:14px}
.mine{display:flex;align-items:center;justify-content:center;width:30px;height:22px;border-radius:5px;
  background:rgba(0,0,0,.12)}
.dark .mine{background:rgba(255,255,255,.18)}
.other{opacity:.55;letter-spacing:2px}
.menu{position:absolute;min-width:282px;padding:5px;border-radius:9px;font-size:13px;color:#1d1d1f;
  background:rgba(240,240,240,.86);backdrop-filter:blur(30px);
  box-shadow:0 0 0 .5px rgba(0,0,0,.25),0 10px 30px rgba(0,0,0,.25)}
.dark .menu{background:rgba(40,40,42,.88);color:#f2f2f2;box-shadow:0 0 0 .5px rgba(255,255,255,.18),0 10px 30px rgba(0,0,0,.5)}
.main{top:30px;left:120px}
.submenu{top:226px;left:398px;min-width:200px}
.item{display:flex;align-items:center;height:22px;padding:0 10px 0 4px;border-radius:5px;white-space:nowrap}
.item .check{width:16px;text-align:center;font-size:11px}
.item .label{flex:1}
.item .arrow{opacity:.6;margin-left:12px}
.item.title{font-weight:600}
.item.info{color:#555}
.dark .item.info{color:#b5b5ba}
.item.disabled{opacity:.4}
.item:not(.info):not(.title):not(.disabled):hover{background:#0a64d8;color:#fff}
.sep{height:1px;margin:5px 10px;background:rgba(0,0,0,.12)}
.dark .sep{background:rgba(255,255,255,.14)}
@media (max-width:420px){.main{left:8px}.submenu{display:none}}
"""


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "menubar_mock.html"
    scenes = "".join(scene_html(t, s, dark) for dark in (False, True) for t, s in SCENES)
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Blinkwise Menu Bar</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>Blinkwise in the menu bar</h1>
<p class="sub">Generated from the app's own icon renderer and menu model. macOS draws the real menu natively.</p>
<div class="grid">{scenes}</div></div></body></html>"""
    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
