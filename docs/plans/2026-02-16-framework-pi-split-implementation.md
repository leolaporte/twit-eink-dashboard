# Framework/Pi Split Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split the dashboard so the Framework laptop does all rendering and the Pi is a dumb display that receives a PNG over SSH.

**Architecture:** `dashboard.py` on the Framework fetches APIs, renders the image, saves it locally, then delivers it to the Pi via scp/ssh and to Discord via webhook. A new `display.py` on the Pi loads the PNG and pushes it to the Inky. Both deliveries are fire-and-forget with graceful error handling.

**Tech Stack:** Python 3, Pillow, requests, subprocess (scp/ssh), Discord webhook API

---

### Task 1: Create display.py for the Pi

**Files:**
- Create: `display.py`

**Step 1: Write the Pi display script**

```python
#!/usr/bin/env python3
"""Load a dashboard PNG and display it on the Inky Impression."""

import sys
from pathlib import Path

from inky.auto import auto
from PIL import Image

IMAGE_PATH = Path.home() / "dashboard.png"


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else IMAGE_PATH
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    img = Image.open(path)
    display = auto()
    display.set_image(img)
    display.show()
    print(f"Display updated from {path}")


if __name__ == "__main__":
    main()
```

**Step 2: Verify it's syntactically valid**

Run: `python3 -c "import ast; ast.parse(open('display.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add display.py
git commit -m "feat: add Pi-side display script"
```

---

### Task 2: Add push_to_pi() function

**Files:**
- Modify: `dashboard.py` — add `push_to_pi()` function after `render_dashboard()`

**Step 1: Add the function**

Add after `render_dashboard()`, before `main()`:

```python
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
             f"python3 {display_script}"],
            check=True,
            capture_output=True,
            text=True,
        )
        log.info("Pi display update triggered")
        return True
    except subprocess.CalledProcessError as e:
        log.warning("ssh display trigger failed: %s", e.stderr.strip())
        return False
```

**Step 2: Test syntax**

Run: `python3 -c "import dashboard; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add dashboard.py
git commit -m "feat: add push_to_pi() for scp/ssh delivery"
```

---

### Task 3: Add push_to_discord() function

**Files:**
- Modify: `dashboard.py` — add `push_to_discord()` function after `push_to_pi()`

**Step 1: Add the function**

```python
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
```

**Step 2: Test syntax**

Run: `python3 -c "import dashboard; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add dashboard.py
git commit -m "feat: add push_to_discord() webhook delivery"
```

---

### Task 4: Update main() to use new delivery functions

**Files:**
- Modify: `dashboard.py:576-615` — rewrite `main()` function

**Step 1: Replace main()**

Replace the current `main()` with:

```python
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
```

**Step 2: Test preview mode still works**

Run: `python3 dashboard.py --preview`
Expected: renders preview.png, logs "Preview mode — skipping Pi and Discord delivery"

**Step 3: Commit**

```bash
git add dashboard.py
git commit -m "refactor: replace Inky display code with Pi/Discord delivery"
```

---

### Task 5: Update config files

**Files:**
- Modify: `config.toml.example`
- Modify: `config.toml`

**Step 1: Update config.toml.example**

Replace full contents with:

```toml
[twit]
app_id = "your_app_id"
app_key = "your_app_key"

[memberful]
api_url = "https://twit.memberful.com/api/graphql"
api_user_id = "55380"
api_key = "your_api_key"

[youtube]
api_key = "your_youtube_api_key"

[pi]
host = "raspberrypi.local"
user = "pi"
image_path = "/home/pi/dashboard.png"
display_script = "/home/pi/display.py"

[discord]
webhook_url = ""

[display]
refresh_minutes = 60
memberful_refresh_hours = 4
```

**Step 2: Update config.toml**

Add `[pi]` and `[discord]` sections (preserving existing API keys). Change `refresh_minutes` to `60`.

**Step 3: Commit**

```bash
git add config.toml.example
git commit -m "feat: add pi and discord config sections"
```

Note: `config.toml` is gitignored, so it won't be committed.

---

### Task 6: Update systemd timer to 1 hour

**Files:**
- Modify: `twit-dashboard.timer`
- Modify: `twit-dashboard.service`

**Step 1: Update timer interval**

In `twit-dashboard.timer`, change:
- `Description` to mention "every hour"
- `OnUnitActiveSec` from `30min` to `1h`

**Step 2: Update service description**

In `twit-dashboard.service`, update `Description` to reflect Framework rendering.

**Step 3: Test timer syntax**

Run: `systemd-analyze verify twit-dashboard.timer 2>&1 || true`
(May warn about missing unit file path — that's OK on the Framework)

**Step 4: Commit**

```bash
git add twit-dashboard.timer twit-dashboard.service
git commit -m "chore: update systemd timer to 1-hour interval"
```

---

### Task 7: End-to-end test

**Step 1: Run preview mode**

Run: `python3 dashboard.py --preview`
Expected: Image saved, no Pi/Discord delivery attempted

**Step 2: Run normal mode (will fail gracefully for Pi)**

Run: `python3 dashboard.py`
Expected: Image saved, Pi push logs warning (Pi not reachable), Discord skipped (no webhook URL)

**Step 3: Verify preview.png looks correct**

Open `preview.png` and confirm the layout is intact.

**Step 4: Final commit with any fixups**

```bash
git add -A
git commit -m "fix: any fixups from e2e testing"
```
