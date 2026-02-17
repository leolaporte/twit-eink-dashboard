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
NUM_TILES = 3
ART_WIDTH = 256

# YouTube channels: (label, channel_id) — ordered by subscriber count, high to low
YOUTUBE_CHANNELS = [
    ("TWiT", "UCwY9B5_8QDGP8niZhBtTh8w"),        # 280K
    ("SN", "UCNbqa_9xihC8yaV2o6dlsUg"),           # 76.1K
    ("TWiT Show", "UCagoIYmo_gO1iVaCeeSikEg"),    # 63.5K
    ("HOT", "UCY96oB1A0TiENISMIy_E2gg"),          # 61.8K
    ("MBW", "UC7DLT1zdSVGvnW11y4kqDng"),          # 30.4K
    ("WW", "UC1WHdBv9P5tYEGfy-btvYfA"),           # 26.5K
    ("iOS", "UCnVDIyVmcIVxb34i0LiD-3w"),          # 22.3K
    ("TWiS", "UCQp83PyFvuolpx529fhih_Q"),         # 4.6K
]
YOUTUBE_CACHE = CACHE_DIR / "youtube.json"

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
        "range": 3,
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
            derivatives.get("twit_thumb_720x405")
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


def fetch_youtube_subs(config):
    """Fetch YouTube subscriber counts for all configured channels.

    Returns list of (label, subscriber_count_str) tuples.
    Caches results alongside memberful data (same refresh interval).
    """
    # Check cache first
    if YOUTUBE_CACHE.exists():
        try:
            with open(YOUTUBE_CACHE) as f:
                cached = json.load(f)
            hours_since = (time.time() - cached["timestamp"]) / 3600
            refresh_hours = config.get("display", {}).get("memberful_refresh_hours", 4)
            if hours_since < refresh_hours:
                log.info("Using cached YouTube subs (%.1fh old)", hours_since)
                return cached["subs"]
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("Corrupt YouTube cache, refetching: %s", e)

    yt = config.get("youtube", {})
    api_key = yt.get("api_key")
    if not api_key:
        log.warning("No YouTube API key configured")
        return _load_cached_youtube()

    # Batch all channel IDs into one API call
    channel_ids = ",".join(cid for _, cid in YOUTUBE_CHANNELS)
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "statistics",
        "id": channel_ids,
        "key": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.error("YouTube API request failed: %s", e)
        return _load_cached_youtube()

    # Build a lookup by channel ID
    stats_by_id = {}
    for item in data.get("items", []):
        count = int(item["statistics"].get("subscriberCount", 0))
        stats_by_id[item["id"]] = count

    subs = []
    for label, cid in YOUTUBE_CHANNELS:
        count = stats_by_id.get(cid, 0)
        subs.append((label, _format_sub_count(count)))

    # Cache
    with open(YOUTUBE_CACHE, "w") as f:
        json.dump({"subs": subs, "timestamp": time.time()}, f)

    log.info("YouTube subs fetched: %s", subs)
    return subs


def _format_sub_count(count):
    """Format subscriber count like '22.8K' or '280K'."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    elif count >= 100_000:
        return f"{count // 1000}K"
    elif count >= 1_000:
        return f"{count / 1000:.1f}K"
    return str(count)


def _load_cached_youtube():
    """Load last cached YouTube subs as fallback."""
    if YOUTUBE_CACHE.exists():
        try:
            with open(YOUTUBE_CACHE) as f:
                cached = json.load(f)
            return cached["subs"]
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
    font_code = None
    font_label = None
    font_title = None
    font_date = None

    for path in font_paths:
        try:
            font_header = ImageFont.truetype(path, 28)
            font_code = ImageFont.truetype(path, 22)
            font_label = ImageFont.truetype(path, 18)
            font_title = ImageFont.truetype(path, 16)
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
    if font_code is None:
        font_code = font_label
    if font_title is None:
        font_title = font_label
    if font_date is None:
        font_date = font_label

    return font_header, font_code, font_label, font_title, font_date


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
        # Resize to fit tile width, preserving aspect ratio
        img.thumbnail((ART_WIDTH, ART_WIDTH), Image.LANCZOS)
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


def render_dashboard(episodes, member_count, youtube_subs=None):
    """Render the dashboard as an 800x480 PIL Image."""
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_header, font_code, font_label, font_title, font_date = _load_fonts()

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

    # --- YouTube footer (calculate height first for vertical centering) ---
    footer_h = 0
    if youtube_subs:
        mid = (len(youtube_subs) + 1) // 2
        footer_lines = [youtube_subs[:mid], youtube_subs[mid:]]
        banner_h = 28       # red banner with title
        line_h = 24         # bigger text lines
        footer_h = banner_h + len(footer_lines) * line_h + 10

    # --- Episode tiles ---
    if not episodes and member_count is None:
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

    tile_w = ART_WIDTH
    gutter = (WIDTH - tile_w * NUM_TILES) // (NUM_TILES + 1)

    # Download art first to know heights for vertical centering
    art_images = [download_art(ep) for ep in episodes[:NUM_TILES]]
    max_art_h = max((a.size[1] if a else 0) for a in art_images) or 140

    # "Just Posted" bar + tiles + title (2 lines) + code + date
    just_posted_h = 28
    title_line_h = 16
    tile_block_h = just_posted_h + 8 + max_art_h + 6 + title_line_h * 2 + 4 + 26 + 6 + 20  # bar+gap+art+gap+title*2+gap+code+gap+date
    available_h = HEIGHT - header_h - footer_h
    block_y = header_h + (available_h - tile_block_h) // 2

    # --- "Just Posted" white bar ---
    draw.rectangle([(0, block_y), (WIDTH, block_y + just_posted_h)], fill=(255, 255, 255))
    jp_text = "Just Posted"
    bbox = draw.textbbox((0, 0), jp_text, font=font_label)
    jp_w = bbox[2] - bbox[0]
    jp_h = bbox[3] - bbox[1]
    draw.text(
        ((WIDTH - jp_w) // 2, block_y + (just_posted_h - jp_h) // 2),
        jp_text,
        fill=(0, 0, 0),
        font=font_label,
    )

    art_y = block_y + just_posted_h + 8

    for i, ep in enumerate(episodes[:NUM_TILES]):
        tile_x = gutter + i * (tile_w + gutter)
        art = art_images[i]

        # Album art
        if art:
            art_x = tile_x + (tile_w - art.size[0]) // 2
            art_y_offset = art_y + (max_art_h - art.size[1])  # bottom-align
            img.paste(art, (art_x, art_y_offset))
        else:
            draw.rectangle(
                [(tile_x, art_y), (tile_x + tile_w, art_y + max_art_h)],
                fill=(60, 60, 60),
            )

        # Episode title in quotes (up to 2 lines)
        title_y = art_y + max_art_h + 6
        raw_title = ep["show_name"]
        # Try to fit on one line first
        title_text = f'"{raw_title}"'
        bbox = draw.textbbox((0, 0), title_text, font=font_title)
        tw = bbox[2] - bbox[0]
        if tw <= tile_w:
            # Fits on one line
            draw.text(
                (tile_x + (tile_w - tw) // 2, title_y),
                title_text,
                fill=(255, 255, 255),
                font=font_title,
            )
        else:
            # Word-wrap into 2 lines
            words = raw_title.split()
            best_split = len(words) // 2 or 1
            line1 = " ".join(words[:best_split])
            line2 = " ".join(words[best_split:])
            for line_idx, line in enumerate([f'"{line1}', f'{line2}"']):
                bbox = draw.textbbox((0, 0), line, font=font_title)
                lw = bbox[2] - bbox[0]
                # Truncate if still too wide
                while lw > tile_w and len(line) > 4:
                    line = line[:-2] + "…"
                    bbox = draw.textbbox((0, 0), line, font=font_title)
                    lw = bbox[2] - bbox[0]
                draw.text(
                    (tile_x + (tile_w - lw) // 2, title_y + line_idx * title_line_h),
                    line,
                    fill=(255, 255, 255),
                    font=font_title,
                )

        # Show code (bigger)
        label_y = title_y + title_line_h * 2 + 4
        code = ep["show_code"].upper()
        bbox = draw.textbbox((0, 0), code, font=font_code)
        cw = bbox[2] - bbox[0]
        draw.text(
            (tile_x + (tile_w - cw) // 2, label_y),
            code,
            fill=(255, 255, 255),
            font=font_code,
        )

        # Airing date
        date_y = label_y + 26 + 6
        date_str = format_airing_date(ep.get("airing_date"))
        bbox = draw.textbbox((0, 0), date_str, font=font_date)
        dw = bbox[2] - bbox[0]
        draw.text(
            (tile_x + (tile_w - dw) // 2, date_y),
            date_str,
            fill=(200, 200, 200),
            font=font_date,
        )

    # --- YouTube subscriber footer ---
    if youtube_subs and footer_h:
        banner_h = 28
        line_h = 24
        y = HEIGHT - footer_h

        # Red banner with title
        draw.rectangle([(0, y), (WIDTH, y + banner_h)], fill=(180, 30, 30))
        banner_text = "YouTube Subscriber Counts"
        bbox = draw.textbbox((0, 0), banner_text, font=font_label)
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        # Account for bbox top offset for true vertical centering
        draw.text(
            ((WIDTH - bw) // 2, y + (banner_h - bh) // 2 - bbox[1]),
            banner_text,
            fill=(255, 255, 255),
            font=font_label,
        )
        y += banner_h + 5

        # Subscriber count lines (bigger font)
        separator = "  ·  "
        for line_subs in footer_lines:
            line_text = separator.join(f"{label} {count}" for label, count in line_subs)
            bbox = draw.textbbox((0, 0), line_text, font=font_label)
            lw = bbox[2] - bbox[0]
            draw.text(
                ((WIDTH - lw) // 2, y),
                line_text,
                fill=(200, 200, 200),
                font=font_label,
            )
            y += line_h

    return img


def push_to_pi(config, image_path):
    """Push rendered image to Pi via scp and trigger display update."""
    pi = config.get("pi", {})
    host = pi.get("host")
    if not host:
        log.info("No [pi] host configured, skipping Pi push")
        return False

    user = pi.get("user", "pi")
    remote_path = pi.get("image_path", "/home/pi/dashboard.png")
    display_script = pi.get("display_script", "/home/pi/display.py")

    import subprocess

    # scp the image
    dest = f"{user}@{host}:{remote_path}"
    try:
        subprocess.run(
            ["scp", "-o", "ConnectTimeout=10", str(image_path), dest],
            check=True,
            capture_output=True,
            text=True,
        )
        log.info("Image pushed to %s", dest)
    except subprocess.CalledProcessError as e:
        log.warning("scp to Pi failed: %s", e.stderr.strip())
        return False

    # ssh to trigger display update
    try:
        subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", f"{user}@{host}",
             display_script],
            check=True,
            capture_output=True,
            text=True,
        )
        log.info("Pi display update triggered")
        return True
    except subprocess.CalledProcessError as e:
        log.warning("ssh display trigger failed: %s", e.stderr.strip())
        return False


def push_to_discord(config, image_path):
    """Post rendered dashboard image to Discord via webhook."""
    discord = config.get("discord", {})
    webhook_url = discord.get("webhook_url")
    if not webhook_url:
        log.info("No [discord] webhook_url configured, skipping Discord push")
        return False

    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                webhook_url,
                files={"file": ("dashboard.png", f, "image/png")},
                timeout=30,
            )
            resp.raise_for_status()
        log.info("Image posted to Discord webhook")
        return True
    except requests.RequestException as e:
        log.warning("Discord webhook failed: %s", e)
        return False


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

    youtube_subs = fetch_youtube_subs(config)
    if youtube_subs:
        log.info("YouTube subs: %s", youtube_subs)

    img = render_dashboard(episodes or [], member_count, youtube_subs)

    # Always save locally
    preview_path = SCRIPT_DIR / "preview.png"
    img.save(preview_path)
    log.info("Image saved to %s", preview_path)

    if args.preview:
        log.info("Preview mode — skipping Pi and Discord delivery")
        return

    # Deliver to Pi and Discord (both fire-and-forget)
    push_to_pi(config, preview_path)
    push_to_discord(config, preview_path)


if __name__ == "__main__":
    main()
