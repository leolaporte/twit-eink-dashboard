# AGENTS.md — TWiT E-Ink Dashboard

800x480 dashboard for Inky Impression 7.3" e-ink display. Shows TWiT network stats: episodes, Club members, YouTube subs.

## Build & Run

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run
python3 dashboard.py              # Normal: render + push to Pi + Discord
python3 dashboard.py --preview    # Preview only: save to preview.png
```

## Architecture

Single Python script (`dashboard.py`, ~720 lines) + Pi display script (`display.py`, ~15 lines).

### Data Sources

| Source | Data | API |
|--------|------|-----|
| TWiT API | Episodes, thumbnails | `twit.tv/api/v1.0/episodes` |
| Memberful | Club paid member count | GraphQL API |
| YouTube | Subscriber counts | YouTube Data API v3 |

### Rendering Pipeline

1. Fetch episodes (TWiT API) → download album art
2. Fetch member count (Memberful, cached 4h)
3. Fetch YouTube subs (YouTube API, cached 4h)
4. Render 800x480 PIL Image with:
   - Header bar: Club member count
   - Episode tiles: 3 recent episodes with art
   - Footer: YouTube subscriber grid
5. Save locally → push via scp to Pi → post to Discord

### Key Functions

| Function | Purpose |
|----------|---------|
| `fetch_episodes()` | TWiT API → episode list |
| `fetch_memberful_count()` | Memberful GraphQL → active paid count |
| `fetch_youtube_subs()` | YouTube API → subscriber counts |
| `render_dashboard()` | PIL Image composition |
| `push_to_pi()` | scp + ssh trigger display |
| `push_to_discord()` | Webhook POST |

## Secrets

Environment variables (from `~/.secrets.env`):
- `TWIT_APP_ID`, `TWIT_APP_KEY`
- `MEMBERFUL_API_KEY`, `MEMBERFUL_API_USER_ID`
- `YOUTUBE_API_KEY`
- `DISCORD_WEBHOOK_URL` (optional)

## Systemd

```bash
systemctl --user status twit-dashboard.timer    # Next trigger
systemctl --user status twit-dashboard.service  # Last run
journalctl --user -u twit-dashboard.service -n 50  # Logs
```

## TDD Workflow

Use RED-GREEN-BLUE cycle:
1. 🔴 Write failing test
2. 🟢 Minimal code to pass
3. 🔵 Refactor

Note: No test suite currently. When adding features, add tests first.

## Notes

- Pi side only needs `display.py` + inky library
- Images cached in `cache/art/` to avoid re-downloading
- Memberful and YouTube data cached for 4 hours by default
- Show codes extracted from `cleanPath` via slug mapping
