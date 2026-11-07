#!/usr/bin/env bash
# One-step Blinkwise install for macOS. Run from anywhere:
#
#   bash scripts/install_mac.sh            (inside a clone of the repo)
#
# What it does, in order (nothing needs sudo):
#   1. installs uv (a small Python manager) into ~/.local/bin if it's missing
#   2. creates ~/blinkwise/.venv with Python 3.12 (uv downloads it; includes Tk for pop-ups)
#   3. installs Blinkwise and its dependencies into that venv
#   4. downloads the face model once (3.7 MB, checked against a pinned SHA-256)
#   5. checks the camera, model and UI (`blinkwise doctor`)
#   6. builds ~/Applications/Blinkwise.app (menu-bar app), adds it to login items, opens it
#
# Undo: `~/blinkwise/.venv/bin/blinkwise uninstall-app` and delete the ~/blinkwise folder.
set -euo pipefail

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mError:\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || fail "This script is for macOS. On Linux/Windows see the README."

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$REPO_DIR/pyproject.toml" ]] || fail "Run this from inside the blinkwise folder (scripts/install_mac.sh)."
cd "$REPO_DIR"

say "1/6  Python manager (uv)"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

say "2/6  Python 3.12 environment in $REPO_DIR/.venv"
# Stop a running copy first (reinstalls replace the environment it runs from).
pkill -f "Blinkwise.app/Contents/MacOS/Blinkwise" 2>/dev/null || true
pkill -f "blinkwise run --app" 2>/dev/null || true
# Use uv's own native Python, never one already on the machine: an Anaconda or Homebrew
# Python can be an Intel build that runs under Rosetta (slower, more battery, and macOS
# is phasing Intel apps out).
if [[ "$(sysctl -n hw.optional.arm64 2>/dev/null)" == "1" ]]; then
  WANT_ARCH=arm64; PYSPEC=cpython-3.12-macos-aarch64-none
else
  WANT_ARCH=x86_64; PYSPEC=cpython-3.12-macos-x86_64-none
fi
uv python install "$PYSPEC"
rm -rf .venv
uv venv --python "$PYSPEC" --python-preference only-managed .venv
PY="$REPO_DIR/.venv/bin/python"
GOT_ARCH="$("$PY" -c 'import platform; print(platform.machine())')"
[[ "$GOT_ARCH" == "$WANT_ARCH" ]] || fail "Got a $GOT_ARCH Python on a $WANT_ARCH Mac. Please report this."
echo "Python $("$PY" -c 'import platform; print(platform.python_version())') ($GOT_ARCH, native)"
"$PY" -c 'import tkinter' 2>/dev/null && echo "Tk available (on-screen blink cue and break cards)." \
  || echo "Tk not available: Blinkwise will use notifications instead of on-screen cards."

say "3/6  Installing Blinkwise"
uv pip install --python "$PY" -e ".[tray]"

say "4/6  Face model (one-time 3.7 MB download)"
"$PY" -c 'from blinkwise.config import data_dir; from blinkwise.vision.tracker import ensure_model; print(ensure_model(data_dir()))'

say "5/6  Checking camera, model and UI"
echo "(macOS may ask whether Terminal can use the camera: click Allow.)"
"$REPO_DIR/.venv/bin/blinkwise" doctor || echo "Some checks failed; see above. Continuing, the app will tell you what to fix."

say "6/6  Menu-bar app"
"$REPO_DIR/.venv/bin/blinkwise" install-app --login
LOG="$HOME/Library/Logs/Blinkwise.log"
before=$(wc -l < "$LOG" 2>/dev/null || echo 0)
open "$HOME/Applications/Blinkwise.app"
echo "Starting Blinkwise (macOS will ask once whether Blinkwise may use the camera: click Allow)..."
ok=""
for _ in $(seq 1 40); do
  sleep 1
  if tail -n +"$((before + 1))" "$LOG" 2>/dev/null | grep -q "menu-bar icon ready"; then ok=1; break; fi
done
if [[ -n "$ok" ]]; then
  echo "The eye icon is in your menu bar."
else
  echo "The menu-bar icon hasn't reported in yet. Last lines of $LOG:"
  tail -n 25 "$LOG" 2>/dev/null || echo "(no log yet)"
  echo "If you have many menu-bar icons, it may be hidden behind the notch: hold Cmd and drag icons to make room."
fi

cat <<EOF

Done. Blinkwise is in your menu bar (the eye icon) and starts at login.
  * The first launch asks for camera access (click Allow) and opens a 2-minute setup guide.
  * Dashboard: click the eye > Open dashboard.
  * 30-second accuracy check:  $REPO_DIR/.venv/bin/blinkwise selftest
  * Logs if something's off:   ~/Library/Logs/Blinkwise.log
EOF
