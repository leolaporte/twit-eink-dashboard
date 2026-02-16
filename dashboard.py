#!/usr/bin/env python3
"""TWiT E-Ink Dashboard — renders to Inky Impression 7.3" or preview PNG."""

import argparse
import sys
from pathlib import Path

import tomllib

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.toml"
CACHE_DIR = SCRIPT_DIR / "cache"
ART_CACHE_DIR = CACHE_DIR / "art"
MEMBERFUL_CACHE = CACHE_DIR / "memberful.json"

WIDTH = 800
HEIGHT = 480


def load_config():
    if not CONFIG_PATH.exists():
        print(
            f"Error: {CONFIG_PATH} not found. Copy config.toml.example and fill in API keys.",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def parse_args():
    parser = argparse.ArgumentParser(description="TWiT E-Ink Dashboard")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Save to preview.png instead of displaying on Inky",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()
    CACHE_DIR.mkdir(exist_ok=True)
    ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Config loaded. Preview mode: {args.preview}")


if __name__ == "__main__":
    main()
