# Framework/Pi Split — Design Document

**Date:** 2026-02-16
**Status:** Approved

## Overview

Move all data fetching and image rendering from the Raspberry Pi to the Framework laptop. The Pi becomes a dumb display device that receives a pre-rendered PNG and pushes it to the Inky Impression. The rendered image is also posted to a Club TWiT Discord channel via webhook.

## Architecture

**Framework** (renderer): Runs hourly via systemd timer. Fetches TWiT episodes, Memberful member count, and YouTube subscriber counts. Renders an 800x480 PNG dashboard image. Delivers to two destinations:

1. **Pi** — `scp` the image, then `ssh` to run `display.py`
2. **Discord** — POST the image as a multipart form to a webhook URL

**Pi** (display): A ~10-line `display.py` that loads a PNG from disk and pushes it to the Inky via `set_image()` / `show()`. No API keys, no config file, no network calls.

## Config Changes

```toml
[pi]
host = "raspberrypi.local"
user = "pi"
image_path = "/home/pi/dashboard.png"
display_script = "/home/pi/display.py"

[discord]
webhook_url = ""  # leave empty to skip

[display]
refresh_minutes = 60
memberful_refresh_hours = 4
```

## Data Flow

```
Framework (hourly):
  1. Fetch TWiT episodes, Memberful count, YouTube subs
  2. Render dashboard → preview.png
  3. scp preview.png → pi@host:image_path
  4. ssh pi@host "python3 display_script"
  5. POST preview.png to Discord webhook (if configured)

Pi (on demand via SSH):
  display.py loads ~/dashboard.png → set_image → show
```

## File Changes

- `dashboard.py` — Remove Inky display code. Add `push_to_pi()` (scp + ssh) and `push_to_discord()` (webhook POST). Always save preview.png locally.
- `display.py` — NEW. Tiny Pi-side script: load PNG, push to Inky.
- `config.toml` / `config.toml.example` — Add `[pi]` and `[discord]` sections. Change refresh to 60 minutes.
- `twit-dashboard.timer` — Change interval to 1 hour.
- `requirements.txt` — No change (Pillow + requests suffice).

## Error Handling

- Pi offline or SSH fails: log warning, skip push, continue to Discord
- Discord webhook fails: log warning, don't block
- Both deliveries are fire-and-forget — the rendered image is always saved locally

## Pi Setup (one-time)

1. Install `inky[rpi]` and `Pillow` in a venv
2. Copy `display.py` to `~/display.py`
3. Add Framework's SSH public key to `~/.ssh/authorized_keys`

## Discord Webhook Setup

1. Open target Discord channel settings
2. Integrations > Webhooks > New Webhook
3. Copy webhook URL into `config.toml`
