"""Entry point for the packaged app. Double-clicking runs the menu-bar app;
with arguments it behaves like the `blinkwise` command."""
import multiprocessing
import sys

from blinkwise.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main(sys.argv[1:] or ["run", "--app"]))
