# TWiT E-Ink Dashboard

An 800x480 dashboard for the [Inky Impression 7.3"](https://shop.pimoroni.com/products/inky-impression-7-3) e-ink display, showing live TWiT network stats: recent episodes, Club TWiT membership count, and YouTube subscriber counts across all channels.

![Dashboard example](docs/example.png)

## What It Shows

- **Header** — Live Club TWiT paid member count (from Memberful API)
- **Episode tiles** — Three most recently posted episodes with thumbnail art, title, show code, and air date
- **YouTube footer** — Subscriber counts for all 8 TWiT YouTube channels

## Architecture

The system is split across two machines:

| Machine | Role |
|---------|------|
| **Desktop/server** | Runs `dashboard.py` — fetches API data, renders the 800x480 PNG, pushes to Pi via `scp`, posts to Discord |
| **Raspberry Pi** | Runs `display.py` — receives the PNG and writes it to the Inky Impression e-ink display |

A systemd timer on the desktop triggers the render daily. The Pi just needs SSH access and the Inky library.

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/leolaporte/twit-eink-dashboard.git
cd twit-eink-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Note:** The `inky[rpi]` dependency is only needed on the Raspberry Pi. On a desktop machine you can install just `Pillow` and `requests` to render previews.

### 2. Get API credentials

You'll need keys for three services:

| Service | What for | Where to get it |
|---------|----------|-----------------|
| **TWiT API** | Episode data + thumbnails | [TWiT Developer Portal](https://twit.tv/about/developers) |
| **Memberful** | Club TWiT member count | Memberful dashboard → Settings → API |
| **YouTube Data API v3** | Subscriber counts | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) |
| **Discord** (optional) | Post dashboard image to a channel | Server Settings → Integrations → Webhooks |

### 3. Configure secrets

Create a `.secrets.env` file in your home directory (or wherever you prefer):

```bash
# ~/.secrets.env
TWIT_APP_ID=your_app_id
TWIT_APP_KEY=your_app_key
MEMBERFUL_API_KEY=your_memberful_key
MEMBERFUL_API_USER_ID=your_user_id
YOUTUBE_API_KEY=your_youtube_key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

For Fish shell users, you can also add them to a sourced secrets file:

```fish
# ~/.secrets (sourced from config.fish)
set -gx TWIT_APP_ID "your_app_id"
set -gx TWIT_APP_KEY "your_app_key"
# ... etc
```

### 4. Edit config.toml

The non-secret configuration lives in `config.toml`. Update the `[pi]` section with your Pi's IP, username, and paths:

```toml
[pi]
host = "192.168.1.100"
user = "pi"
image_path = "/home/pi/dashboard.png"
display_script = "/home/pi/dashboard-venv/bin/python3 /home/pi/display.py"
```

Set `memberful_refresh_hours` to control how often the Memberful member count is re-fetched (0 = every run):

```toml
[display]
memberful_refresh_hours = 4
```

### 5. Test it

```bash
# Load secrets and render a local preview
env $(grep -v '^#' ~/.secrets.env | xargs) python3 dashboard.py --preview
# Open preview.png to check the result
```

## Raspberry Pi Setup

On the Pi, you only need `display.py` and the Inky library:

```bash
python3 -m venv dashboard-venv
source dashboard-venv/bin/activate
pip install "inky[rpi]" Pillow
```

Copy `display.py` to the Pi and make sure SSH key auth works from your desktop:

```bash
scp display.py pi@your-pi-ip:~/display.py
ssh pi@your-pi-ip  # should connect without password prompt
```

The desktop's `dashboard.py` handles pushing the rendered image and triggering the display via SSH.

## Automated Daily Updates (systemd)

A systemd user timer runs the dashboard daily. To install:

```bash
# Symlink the unit files
mkdir -p ~/.config/systemd/user
ln -sf "$(pwd)/twit-dashboard.service" ~/.config/systemd/user/
ln -sf "$(pwd)/twit-dashboard.timer" ~/.config/systemd/user/

# Reload and enable
systemctl --user daemon-reload
systemctl --user enable --now twit-dashboard.timer
```

> **Important:** Edit `twit-dashboard.service` to update the `EnvironmentFile` path and `ExecStart`/`WorkingDirectory` paths to match your system.

Check status:

```bash
systemctl --user status twit-dashboard.timer   # next trigger time
systemctl --user status twit-dashboard.service  # last run result
journalctl --user -u twit-dashboard.service -n 50  # recent logs
```

To run manually via systemd (tests that secrets load correctly):

```bash
systemctl --user start twit-dashboard.service
```

## File Overview

```
├── dashboard.py            # Main script: fetches data, renders PNG, delivers
├── display.py              # Pi-side: loads PNG onto Inky Impression e-ink
├── config.toml             # Non-secret config (Pi host, API URLs, cache settings)
├── requirements.txt        # Python dependencies
├── twit-dashboard.service  # systemd oneshot service
├── twit-dashboard.timer    # systemd daily timer (11am local)
└── docs/
    └── example.png         # Example dashboard output
```

## License

MIT
