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
uv venv --python 3.12 --allow-existing .venv
PY="$REPO_DIR/.venv/bin/python"
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
open "$HOME/Applications/Blinkwise.app"

cat <<EOF

Done. Blinkwise is in your menu bar (the eye icon) and starts at login.
  * The first launch asks for camera access (click Allow) and opens a 2-minute setup guide.
  * Dashboard: click the eye > Open dashboard.
  * 30-second accuracy check:  $REPO_DIR/.venv/bin/blinkwise selftest
  * Logs if something's off:   ~/Library/Logs/Blinkwise.log
EOF
