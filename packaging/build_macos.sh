#!/bin/bash
# Build a self-contained Blinkwise.app and Blinkwise.dmg on macOS.
#   bash packaging/build_macos.sh
# Optional: SIGN_ID="Developer ID Application: ..." for a notarisable signature
# (ad-hoc signing is used otherwise; users then right-click > Open the first time).
set -euo pipefail
cd "$(dirname "$0")/.."
# Clean build environment. MediaPipe declares the full GUI OpenCV and matplotlib, which
# Blinkwise doesn't use (~30 MB of Qt; matplotlib is stubbed at import), so install
# MediaPipe without them and use headless OpenCV. Verified with a frozen build that
# runs the full pipeline offline.
python3 -m venv build/venv
source build/venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q --no-deps mediapipe
python -m pip install -q absl-py flatbuffers certifi numpy opencv-python-headless \
    pillow pystray screeninfo psutil pyinstaller
python -m pip install -q --no-deps -e .
python - <<'PY'
import hashlib, urllib.request, pathlib
from blinkwise.vision.tracker import MODEL_URL, MODEL_SHA256
p = pathlib.Path("packaging/face_landmarker.task")
if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != MODEL_SHA256:
    p.write_bytes(urllib.request.urlopen(MODEL_URL, timeout=60).read())
assert hashlib.sha256(p.read_bytes()).hexdigest() == MODEL_SHA256, "model checksum mismatch"
from blinkwise.macos import write_icns
write_icns(pathlib.Path("packaging/Blinkwise.icns"))
PY
rm -rf build/blinkwise dist
pyinstaller --noconfirm packaging/blinkwise.spec
codesign --force --deep --options runtime --sign "${SIGN_ID:--}" dist/Blinkwise.app
codesign --verify --deep --strict dist/Blinkwise.app
# Smoke test the frozen app before packaging it.
dist/Blinkwise.app/Contents/MacOS/Blinkwise --version
dist/Blinkwise.app/Contents/MacOS/Blinkwise doctor || true      # no camera on CI runners
hdiutil create -volname Blinkwise -srcfolder dist/Blinkwise.app -ov -format UDZO dist/Blinkwise.dmg
echo "Built dist/Blinkwise.app and dist/Blinkwise.dmg"
