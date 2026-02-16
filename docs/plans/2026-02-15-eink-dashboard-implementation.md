# TWiT E-Ink Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python script that renders a TWiT status dashboard (member count + 4 recent episodes) to a Pimoroni Inky Impression 7.3" e-ink display.

**Architecture:** Single Python script (`dashboard.py`) fetches data from TWiT API and Memberful GraphQL API, renders an 800x480 PIL image, and pushes it to the Inky display. A `--preview` flag saves to PNG for development without hardware. Systemd timer runs it every 30 minutes on a headless Pi.

**Tech Stack:** Python 3, Pillow (image rendering), requests (HTTP), tomllib (config), inky (display driver on Pi only)

---

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `config.toml.example`
- Create: `.gitignore`
- Create: `dashboard.py` (empty entry point)

**Step 1: Create requirements.txt**

```
inky[rpi]
Pillow
requests
```

**Step 2: Create config.toml.example**

```toml
[twit]
app_id = "your_app_id"
app_key = "your_app_key"

[memberful]
api_url = "https://twit.memberful.com/api/graphql"
api_user_id = "55380"
api_key = "your_api_key"

[display]
refresh_minutes = 30
memberful_refresh_hours = 4
```

**Step 3: Create .gitignore**

```
config.toml
cache/
*.pyc
__pycache__/
preview.png
.venv/
```

**Step 4: Create empty dashboard.py**

```python
#!/usr/bin/env python3
"""TWiT E-Ink Dashboard — renders to Inky Impression 7.3" or preview PNG."""


def main():
    pass


if __name__ == "__main__":
    main()
```

**Step 5: Commit**

```bash
git add requirements.txt config.toml.example .gitignore dashboard.py
git commit -m "chore: scaffold project with config template and gitignore"
```

---

### Task 2: Config Loading & CLI Args

**Files:**
- Modify: `dashboard.py`
- Test: manual — `python3 dashboard.py --preview` should print config and exit

**Step 1: Write config loading and argument parsing**

```python
#!/usr/bin/env python3
"""TWiT E-Ink Dashboard — renders to Inky Impression 7.3" or preview PNG."""

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.toml"
CACHE_DIR = SCRIPT_DIR / "cache"
ART_CACHE_DIR = CACHE_DIR / "art"
MEMBERFUL_CACHE = CACHE_DIR / "memberful.json"

WIDTH = 800
HEIGHT = 480


def load_config():
    if not CONFIG_PATH.exists():
        print(f"Error: {CONFIG_PATH} not found. Copy config.toml.example and fill in API keys.", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def parse_args():
    parser = argparse.ArgumentParser(description="TWiT E-Ink Dashboard")
    parser.add_argument("--preview", action="store_true", help="Save to preview.png instead of displaying on Inky")
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()
    CACHE_DIR.mkdir(exist_ok=True)
    ART_CACHE_DIR.mkdir(exist_ok=True)
    print(f"Config loaded. Preview mode: {args.preview}")


if __name__ == "__main__":
    main()
```

**Step 2: Create a config.toml for testing**

Copy `config.toml.example` to `config.toml` and fill in real API keys (or placeholders for now).

**Step 3: Run to verify**

Run: `python3 dashboard.py --preview`
Expected: `Config loaded. Preview mode: True`

**Step 4: Commit**

```bash
git add dashboard.py
git commit -m "feat: add config loading and CLI argument parsing"
```

---

### Task 3: TWiT API Client

**Files:**
- Modify: `dashboard.py`
- Test: manual — `python3 dashboard.py --preview` should print 4 episode titles

**Step 1: Add TWiT episode fetching function**

```python
import requests
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


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
    for item in data.get("_embedded", {}).get("episodes", []):
        show_data = item.get("_embedded", {}).get("shows", [{}])[0]
        hero = item.get("heroImage", {})
        # Try to get a usable image URL from heroImage derivatives
        image_url = None
        if hero and hero.get("derivatives"):
            derivatives = hero["derivatives"]
            # Prefer a mid-size derivative
            for deriv in derivatives:
                if deriv.get("width") and 200 <= deriv["width"] <= 600:
                    image_url = deriv["url"]
                    break
            if not image_url and derivatives:
                image_url = derivatives[0].get("url")
        if not image_url and hero:
            image_url = hero.get("url")

        episodes.append({
            "show_code": show_data.get("shortCode", "???"),
            "show_name": show_data.get("label", "Unknown"),
            "airing_date": item.get("airingDate"),
            "image_url": image_url,
            "episode_id": item.get("id"),
        })

    return episodes
```

**Step 2: Wire into main and test**

Add to `main()`:
```python
    episodes = fetch_episodes(config)
    if episodes:
        for ep in episodes:
            print(f"  {ep['show_code']}: {ep['show_name']} ({ep['airing_date']})")
    else:
        print("  Failed to fetch episodes")
```

Run: `python3 dashboard.py --preview`
Expected: 4 lines with show codes and dates

**Step 3: Commit**

```bash
git add dashboard.py
git commit -m "feat: add TWiT API client to fetch recent episodes"
```

**Note:** The TWiT API response structure (especially heroImage nesting) may need adjustment once we see real responses. The plan includes fallback logic for this. Examine the actual JSON from step 2's output and adjust field paths if needed.

---

### Task 4: Memberful API Client

**Files:**
- Modify: `dashboard.py`
- Test: manual — `python3 dashboard.py --preview` should print member count

**Step 1: Add Memberful member counting with pagination and caching**

```python
import json
import time


def fetch_memberful_count(config):
    """Fetch active paid member count from Memberful GraphQL API.

    Paginates through all members, counts those with active subscription
    and a credit card on file. Caches result to avoid frequent re-queries.
    """
    # Check cache first
    if MEMBERFUL_CACHE.exists():
        with open(MEMBERFUL_CACHE) as f:
            cached = json.load(f)
        hours_since = (time.time() - cached["timestamp"]) / 3600
        refresh_hours = config.get("display", {}).get("memberful_refresh_hours", 4)
        if hours_since < refresh_hours:
            log.info("Using cached member count: %d (%.1fh old)", cached["count"], hours_since)
            return cached["count"]

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
        query = (
            '{"query": "query MemberCounting {members (first: 100'
            + after_clause
            + ') { totalCount pageInfo { endCursor hasNextPage } '
            + 'edges { node { creditCard { brand } subscriptions { active } } } } }"}'
        )
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
        with open(MEMBERFUL_CACHE) as f:
            cached = json.load(f)
        log.info("Falling back to cached count: %d", cached["count"])
        return cached["count"]
    return None
```

**Step 2: Wire into main and test**

Add to `main()`:
```python
    member_count = fetch_memberful_count(config)
    print(f"  Club TWiT paid members: {member_count}")
```

Run: `python3 dashboard.py --preview`
Expected: Member count printed (may take a while on first run due to pagination)

**Step 3: Commit**

```bash
git add dashboard.py
git commit -m "feat: add Memberful GraphQL client with pagination and caching"
```

---

### Task 5: Image Rendering

**Files:**
- Modify: `dashboard.py`
- Test: `python3 dashboard.py --preview` generates `preview.png`

This is the core rendering task. The user should make decisions about font choice and exact spacing here.

**Step 1: Add album art downloading with cache**

```python
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont


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
        img = img.resize((140, 140), Image.LANCZOS)
        img.save(cache_path, "PNG")
        return img
    except Exception as e:
        log.error("Failed to download art for %s: %s", episode["show_code"], e)
        return None
```

**Step 2: Add the main render function**

```python
def render_dashboard(episodes, member_count):
    """Render the dashboard as an 800x480 PIL Image."""
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Load fonts — use a built-in default, user can swap later
    try:
        font_header = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 28)
        font_label = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 18)
        font_date = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", 16)
    except OSError:
        font_header = ImageFont.load_default()
        font_label = font_header
        font_date = font_header

    # --- Header bar ---
    header_h = 60
    draw.rectangle([(0, 0), (WIDTH, header_h)], fill=(47, 110, 145))
    count_str = f"{member_count:,}" if member_count else "—"
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
    tile_w = 190
    gutter = (WIDTH - tile_w * 4) // 5
    art_size = 140
    art_y = header_h + 30
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


def format_airing_date(date_str):
    """Format an ISO date string to compact 'M/DD H:MMa' format."""
    if not date_str:
        return "—"
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        dt = dt.astimezone()  # convert to local time
        hour = dt.hour
        ampm = "a" if hour < 12 else "p"
        hour = hour % 12 or 12
        return f"{dt.month}/{dt.day} {hour}:{dt.minute:02d}{ampm}"
    except (ValueError, TypeError):
        return "—"
```

**Step 3: Wire rendering and output into main**

Replace the debug prints in `main()` with:
```python
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
```

**Step 4: Test preview mode**

Run: `python3 dashboard.py --preview`
Expected: `preview.png` appears in project directory. Open it and verify layout.

**Step 5: Commit**

```bash
git add dashboard.py
git commit -m "feat: add image rendering with album art, header, and preview mode"
```

**User review point:** Open `preview.png` and evaluate the layout. This is where we iterate on spacing, font sizes, colors. Adjust constants in `render_dashboard()` as needed.

---

### Task 6: Systemd Timer & Service

**Files:**
- Create: `twit-dashboard.service`
- Create: `twit-dashboard.timer`

**Step 1: Create the service unit**

```ini
[Unit]
Description=TWiT E-Ink Dashboard updater

[Service]
Type=oneshot
ExecStart=/home/leo/opt/twit-dashboard/.venv/bin/python3 /home/leo/opt/twit-dashboard/dashboard.py
WorkingDirectory=/home/leo/opt/twit-dashboard
```

**Step 2: Create the timer unit**

```ini
[Unit]
Description=Refresh TWiT E-Ink Dashboard every 30 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=30min
AccuracySec=1min

[Install]
WantedBy=timers.target
```

**Step 3: Commit**

```bash
git add twit-dashboard.service twit-dashboard.timer
git commit -m "feat: add systemd service and timer for 30-minute refresh"
```

**Note:** These are deployed to the Pi later. On the Pi:
```bash
ln -sf ~/opt/twit-dashboard/twit-dashboard.service ~/.config/systemd/user/
ln -sf ~/opt/twit-dashboard/twit-dashboard.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now twit-dashboard.timer
```

---

### Task 7: Error State Rendering

**Files:**
- Modify: `dashboard.py`

**Step 1: Add fallback rendering for missing data**

If `episodes` is `None` or empty, render a centered message: "No episode data available". If `member_count` is `None`, show "—" in the header (already handled). If both APIs fail on first run with no cache, render "No data yet — check network & config".

**Step 2: Test by temporarily breaking API keys**

Set invalid keys in `config.toml`, run `python3 dashboard.py --preview`, verify the error state renders cleanly.

**Step 3: Commit**

```bash
git add dashboard.py
git commit -m "feat: add graceful error state rendering for API failures"
```

---

## Deployment Checklist (on the Pi)

1. `git clone <repo> ~/opt/twit-dashboard/`
2. `python3 -m venv ~/opt/twit-dashboard/.venv`
3. `~/opt/twit-dashboard/.venv/bin/pip install -r ~/opt/twit-dashboard/requirements.txt`
4. Copy `config.toml.example` → `config.toml`, fill in keys
5. Test: `~/opt/twit-dashboard/.venv/bin/python3 ~/opt/twit-dashboard/dashboard.py`
6. Install timer (see Task 6 note)
7. Verify: `systemctl --user status twit-dashboard.timer`
