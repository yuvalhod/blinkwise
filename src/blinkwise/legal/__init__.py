"""Privacy Policy and Terms of Use, shipped with the app and served as pages.

Bump TERMS_VERSION whenever either document changes materially: the app then asks the
user to review and accept again before the camera turns on.
"""

from __future__ import annotations

import html
import re
from importlib import resources

TERMS_VERSION = "2026-11-07"
DOCS = {"privacy": "privacy.md", "terms": "terms.md"}


def text(name: str) -> str:
    return resources.files("blinkwise.legal").joinpath(DOCS[name]).read_text(encoding="utf-8")


def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def to_html(md: str) -> str:
    """Just enough Markdown for these two documents: headings, paragraphs, bullet lists,
    tables, bold and code. Everything is escaped first; no raw HTML passes through."""
    out, para, items, table = [], [], [], []

    def flush():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
        if table:
            rows = [r for r in table if not re.fullmatch(r"\|[\s|:-]+\|", r)]
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
            head, body = cells[0], cells[1:]
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head)
                       + "</tr></thead><tbody>" + "".join(
                           "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</tbody></table>")
            table.clear()

    for line in md.splitlines():
        if not line.strip():
            flush()
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            flush()
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
        elif line.startswith("|"):
            if para or items:
                flush()
            table.append(line)
        elif re.match(r"^\s*[*-]\s+", line):
            if para or table:
                flush()
            items.append(re.sub(r"^\s*[*-]\s+", "", line))
        elif items and line.startswith("  "):
            items[-1] += " " + line.strip()          # continuation of a bullet
        else:
            if items or table:
                flush()
            para.append(line.strip())
    flush()
    return "\n".join(out)


def page(name: str, back: str = "/") -> str:
    body = to_html(text(name))
    title = "Privacy Policy" if name == "privacy" else "Terms of Use"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Blinkwise · {title}</title>
<link rel="stylesheet" href="/theme.css"><style>
.wrap{{max-width:720px;margin:0 auto;padding:26px 20px 64px}}
.top{{display:flex;align-items:center;gap:14px;padding-bottom:16px;
  border-bottom:1px solid var(--ink);margin-bottom:26px}}
h1{{font-size:40px;line-height:1.1;margin:0 0 14px}} h2{{font-size:24px;margin:30px 0 8px}}
p,li{{font-size:15.5px;line-height:1.6}} li{{margin:6px 0}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0}}
th,td{{text-align:left;padding:8px 10px 8px 0;border-top:1px solid var(--rule);vertical-align:top}}
th{{font:700 11px/1.2 var(--text);letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}}
code{{font-size:13px;background:var(--sheet2);padding:1px 5px}}
nav{{display:flex;gap:16px;font-size:14px}}
</style></head><body><div class="wrap">
<header class="top"><a class="brand" href="{html.escape(back)}">Blinkwise</a><span style="flex:1"></span>
<nav><a href="/privacy">Privacy</a><a href="/terms">Terms</a></nav></header>
{body}
</div></body></html>"""
