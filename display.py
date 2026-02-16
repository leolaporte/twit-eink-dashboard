#!/usr/bin/env python3
"""Load a dashboard PNG and display it on the Inky Impression."""

import sys
from pathlib import Path

from inky.inky_ac073tc1a import Inky
from PIL import Image

IMAGE_PATH = Path.home() / "dashboard.png"


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else IMAGE_PATH
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    img = Image.open(path)
    display = Inky()
    display.set_image(img)
    display.show()
    print(f"Display updated from {path}")


if __name__ == "__main__":
    main()
