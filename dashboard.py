#!/usr/bin/env python3
"""TWiT E-Ink Dashboard — renders to Inky Impression 7.3" or preview PNG."""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import requests
import tomllib
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.toml"
CACHE_DIR = SCRIPT_DIR / "cache"
ART_CACHE_DIR = CACHE_DIR / "art"
MEMBERFUL_CACHE = CACHE_DIR / "memberful.json"

WIDTH = 800
HEIGHT = 480

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


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


def _extract_show_code(clean_path):
    """Extract show short code from cleanPath like '/shows/this-week-in-tech/episodes/1071'.

    Falls back to uppercased slug initials if show not found in mapping.
    """
    # Show slug → short code mapping (from TWiT API /shows endpoint)
    SHOW_CODES = {
        "this-week-in-tech": "TWiT",
        "security-now": "SN",
        "macbreak-weekly": "MBW",
        "windows-weekly": "WW",
        "intelligent-machines": "IM",
        "tech-news-weekly": "TNW",
        "hands-on-tech": "HOT",
        "ios-today": "iOS",
        "this-week-in-space": "TWiS",
        "home-theater-geeks": "HTG",
        "hands-on-apple": "HOA",
        "hands-on-windows": "HOW",
        "untitled-linux-show": "ULS",
        "ai-inside": "AI",
        "twit-plus": "PLUS",
        "twit-plus-club-shows": "PLUSSHOWS",
        "twit-plus-news": "PLUSNEWS",
        "total-leo": "Total Leo",
        "total-mikah": "MIKAH",
        "ask-the-tech-guys": "ATTG",
        "hands-on-android": "H.O.A.",
        "hands-on-photography": "HOP",
    }
    parts = clean_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "shows":
        slug = parts[1]
        return SHOW_CODES.get(slug, slug.upper()[:6])
    return "???"


def fetch_episodes(config):
    """Fetch 4 most recent episodes from TWiT API."""
    twit = config["twit"]
    url = "https://twit.tv/api/v1.0/episodes"
    headers = {
        "Accept": "application/json",
        "app-id": twit["app_id"],
        "app-key": twit["app_key"],
    }
    params = {
        "sort": "-airingDate",
        "range": 4,
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.error("TWiT API request failed: %s", e)
        return None

    episodes = []
    for item in data.get("episodes", []):
        hero = item.get("heroImage") or {}
        derivatives = hero.get("derivatives") or {}
        # Prefer 600x450 derivative for good quality at 140x140 tile size
        image_url = (
            derivatives.get("twit_slideshow_600x450")
            or derivatives.get("thumbnail")
            or hero.get("url")
        )

        show_code = _extract_show_code(item.get("cleanPath", ""))

        episodes.append({
            "show_code": show_code,
            "show_name": item.get("label", "Unknown"),
            "airing_date": item.get("airingDate"),
            "image_url": image_url,
            "episode_id": item.get("id"),
        })

    return episodes


def fetch_memberful_count(config):
    """Fetch active paid member count from Memberful GraphQL API.

    Paginates through all members, counts those with active subscription
    and a credit card on file. Caches result to avoid frequent re-queries.
    """
    # Check cache first
    if MEMBERFUL_CACHE.exists():
        try:
            with open(MEMBERFUL_CACHE) as f:
                cached = json.load(f)
            hours_since = (time.time() - cached["timestamp"]) / 3600
            refresh_hours = config.get("display", {}).get("memberful_refresh_hours", 4)
            if hours_since < refresh_hours:
                log.info("Using cached member count: %d (%.1fh old)", cached["count"], hours_since)
                return cached["count"]
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("Corrupt memberful cache, refetching: %s", e)

    memberful = config["memberful"]
    url = f"{memberful['api_url']}?api_user_id={memberful['api_user_id']}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {memberful['api_key']}",
        "Cache-Control": "no-cache",
    }

    active_count = 0
    has_next = True
    cursor = None
    page = 0

    while has_next:
        page += 1
        after_clause = f', after: "{cursor}"' if cursor else ""
        query = json.dumps({"query":
            "{ members(first: 100" + after_clause
            + ") { pageInfo { endCursor hasNextPage } "
            + "edges { node { creditCard { brand } subscriptions { active } } } } }"
        })
        try:
            resp = requests.post(url, headers=headers, data=query, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            log.error("Memberful API request failed on page %d: %s", page, e)
            return _load_cached_count()

        members = data.get("data", {}).get("members", {})
        page_info = members.get("pageInfo", {})
        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

        for edge in members.get("edges", []):
            node = edge.get("node", {})
            subs = node.get("subscriptions", [])
            card = node.get("creditCard")
            if subs and subs[0].get("active") and card and card.get("brand"):
                active_count += 1

        log.info("Memberful page %d: running count = %d", page, active_count)

    # Cache the result
    with open(MEMBERFUL_CACHE, "w") as f:
        json.dump({"count": active_count, "timestamp": time.time()}, f)

    log.info("Memberful total active paid members: %d", active_count)
    return active_count


def _load_cached_count():
    """Load last cached member count as fallback."""
    if MEMBERFUL_CACHE.exists():
        try:
            with open(MEMBERFUL_CACHE) as f:
                cached = json.load(f)
            log.info("Falling back to cached count: %d", cached["count"])
            return cached["count"]
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def _load_fonts():
    """Load fonts with fallback to default."""
    font_paths = [
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ]
    font_regular_paths = [
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]

    font_header = None
    font_label = None
    font_date = None

    for path in font_paths:
        try:
            font_header = ImageFont.truetype(path, 28)
            font_label = ImageFont.truetype(path, 18)
            break
        except OSError:
            continue

    for path in font_regular_paths:
        try:
            font_date = ImageFont.truetype(path, 16)
            break
        except OSError:
            continue

    if font_header is None:
        font_header = ImageFont.load_default()
        font_label = font_header
    if font_date is None:
        font_date = font_label

    return font_header, font_label, font_date


def download_art(episode):
    """Download and cache album art for an episode. Returns PIL Image or None."""
    if not episode.get("image_url"):
        return None

    cache_path = ART_CACHE_DIR / f"{episode['episode_id']}.png"
    if cache_path.exists():
        return Image.open(cache_path)

    try:
        resp = requests.get(episode["image_url"], timeout=15)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        # Center-crop to square, then resize
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((140, 140), Image.LANCZOS)
        img.save(cache_path, "PNG")
        return img
    except Exception as e:
        log.error("Failed to download art for %s: %s", episode["show_code"], e)
        return None


def format_airing_date(date_str):
    """Format an ISO date string to compact 'M/DD H:MMa' format."""
    if not date_str:
        return "—"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        dt = dt.astimezone()  # convert to local time
        hour = dt.hour
        ampm = "a" if hour < 12 else "p"
        hour = hour % 12 or 12
        return f"{dt.month}/{dt.day} {hour}:{dt.minute:02d}{ampm}"
    except (ValueError, TypeError):
        return "—"


def render_dashboard(episodes, member_count):
    """Render the dashboard as an 800x480 PIL Image."""
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_header, font_label, font_date = _load_fonts()

    # --- Header bar ---
    header_h = 60
    draw.rectangle([(0, 0), (WIDTH, header_h)], fill=(47, 110, 145))
    count_str = f"{member_count:,}" if member_count is not None else "—"
    header_text = f"CLUB TWiT PAID MEMBERS: {count_str}"
    bbox = draw.textbbox((0, 0), header_text, font=font_header)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text(
        ((WIDTH - text_w) // 2, (header_h - text_h) // 2),
        header_text,
        fill=(255, 255, 255),
        font=font_header,
    )

    # --- Episode tiles ---
    if not episodes and not member_count:
        # Both APIs failed with no cached data
        error_msg = "No data yet — check network & config"
        bbox = draw.textbbox((0, 0), error_msg, font=font_label)
        ew = bbox[2] - bbox[0]
        draw.text(
            ((WIDTH - ew) // 2, HEIGHT // 2),
            error_msg,
            fill=(180, 180, 180),
            font=font_label,
        )
        return img

    if not episodes:
        # TWiT API failed but memberful might have data
        error_msg = "No episode data available"
        bbox = draw.textbbox((0, 0), error_msg, font=font_label)
        ew = bbox[2] - bbox[0]
        draw.text(
            ((WIDTH - ew) // 2, HEIGHT // 2),
            error_msg,
            fill=(180, 180, 180),
            font=font_label,
        )
        return img

    tile_w = 190
    gutter = (WIDTH - tile_w * 4) // 5
    art_size = 140
    # Vertically center the tile block (art + label + date) in the area below header
    tile_block_h = art_size + 10 + 24 + 20  # art + gap + label + date
    available_h = HEIGHT - header_h
    art_y = header_h + (available_h - tile_block_h) // 2
    label_y = art_y + art_size + 10
    date_y = label_y + 24

    for i, ep in enumerate(episodes[:4]):
        tile_x = gutter + i * (tile_w + gutter)
        art_x = tile_x + (tile_w - art_size) // 2

        # Album art
        art = download_art(ep)
        if art:
            img.paste(art, (art_x, art_y))
        else:
            draw.rectangle(
                [(art_x, art_y), (art_x + art_size, art_y + art_size)],
                fill=(60, 60, 60),
            )

        # Show code
        code = ep["show_code"].upper()
        bbox = draw.textbbox((0, 0), code, font=font_label)
        cw = bbox[2] - bbox[0]
        draw.text(
            (tile_x + (tile_w - cw) // 2, label_y),
            code,
            fill=(255, 255, 255),
            font=font_label,
        )

        # Airing date
        date_str = format_airing_date(ep.get("airing_date"))
        bbox = draw.textbbox((0, 0), date_str, font=font_date)
        dw = bbox[2] - bbox[0]
        draw.text(
            (tile_x + (tile_w - dw) // 2, date_y),
            date_str,
            fill=(200, 200, 200),
            font=font_date,
        )

    return img


def main():
    args = parse_args()
    config = load_config()
    CACHE_DIR.mkdir(exist_ok=True)
    ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    episodes = fetch_episodes(config)
    if episodes:
        for ep in episodes:
            log.info("  %s: %s (%s)", ep["show_code"], ep["show_name"], ep["airing_date"])
    else:
        log.warning("Failed to fetch episodes")

    member_count = fetch_memberful_count(config)
    log.info("Club TWiT paid members: %s", member_count)

    img = render_dashboard(episodes or [], member_count)

    if args.preview:
        preview_path = SCRIPT_DIR / "preview.png"
        img.save(preview_path)
        log.info("Preview saved to %s", preview_path)
    else:
        try:
            from inky.auto import auto
            display = auto()
            display.set_image(img)
            display.show()
            log.info("Display updated.")
        except ImportError:
            log.error("inky library not available. Use --preview on non-Pi machines.")
            sys.exit(1)


if __name__ == "__main__":
    main()
