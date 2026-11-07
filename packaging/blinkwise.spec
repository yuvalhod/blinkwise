# PyInstaller spec for a self-contained Blinkwise app.
#   macOS:   packaging/build_macos.sh   -> dist/Blinkwise.app + Blinkwise.dmg
#   others:  pyinstaller packaging/blinkwise.spec  -> dist/Blinkwise/
# Needs the face model next to this file (the build script downloads and verifies it).
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

HERE = os.path.abspath(SPECPATH)  # noqa: F821  (provided by PyInstaller)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
from blinkwise import __version__, macos  # noqa: E402

model = os.path.join(HERE, "face_landmarker.task")
if not os.path.exists(model):
    raise SystemExit(f"Missing {model}: run the build script (it downloads and verifies the model).")

datas = [
    (os.path.join(ROOT, "src/blinkwise/ui/static"), "blinkwise/ui/static"),
    (os.path.join(ROOT, "src/blinkwise/legal"), "blinkwise/legal"),
    (model, "blinkwise/models"),
]
datas += collect_data_files("mediapipe", includes=["**/*.so", "**/*.dylib", "**/*.dll", "**/*.binarypb"])
binaries = collect_dynamic_libs("mediapipe")

a = Analysis(  # noqa: F821
    [os.path.join(HERE, "entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=["blinkwise.ui.tray", "blinkwise.ui.overlay", "pystray._darwin",
                   "pystray._win32", "pystray._xorg", "PIL.ImageTk"],
    # Blinkwise never draws plots; mediapipe's drawing utils import pyplot lazily-stubbed.
    excludes=["matplotlib", "pandas", "scipy", "IPython", "jax", "tensorflow", "torch"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="Blinkwise",
    console=sys.platform.startswith("linux"),   # GUI app on macOS/Windows
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Blinkwise", upx=False)  # noqa: F821

if sys.platform == "darwin":
    icns = os.path.join(HERE, "Blinkwise.icns")
    app = BUNDLE(  # noqa: F821
        coll, name="Blinkwise.app", icon=icns if os.path.exists(icns) else None,
        bundle_identifier=macos.BUNDLE_ID, version=__version__,
        info_plist=macos.info_plist(__version__),
    )
