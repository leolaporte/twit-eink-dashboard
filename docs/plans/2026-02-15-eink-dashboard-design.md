# TWiT E-Ink Dashboard — Design Document

**Date:** 2026-02-15
**Status:** Approved

## Overview

A Python script that renders a TWiT status dashboard to a Pimoroni Inky Impression 7.3" color e-ink display (800x480, 7-color) attached to a dedicated headless Raspberry Pi.

The dashboard shows:
- Club TWiT paid member count (from Memberful API)
- 4 most recently published episodes with album art, show short code, and publish date/time (from TWiT API)

## Hardware

- **Display:** Pimoroni Inky Impression 7.3" (800x480, 7-color e-ink)
- **Computer:** Raspberry Pi with 40-pin GPIO header
- **Deployment:** Dedicated headless Pi, always on, office desk/shelf

## Layout (800x480)

```
+--------------------------------------------------+
|         CLUB TWiT PAID MEMBERS: 12,345           |  <- header bar (~60px)
+----------+----------+----------+-----------------+
|          |          |          |                  |
|  [art]   |  [art]   |  [art]  |  [art]           |  <- album art (~140x140)
|          |          |          |                  |
|   TWiT   |   IM     |   MBW   |   TNW            |  <- show short code
| 2/15 8p  | 2/14 3p  | 2/13 1p | 2/12 11a         |  <- publish date/time
+----------+----------+----------+-----------------+
```

- **Background:** Black (best e-ink contrast)
- **Text:** White, bold for header and show codes
- **Album art:** 140x140px, dithered to 7-color palette by Inky library
- **Tiles:** 4 across, ~190px wide with ~8px gutters, vertically centered

## Data Sources

### TWiT API — Recent Episodes

- **Endpoint:** `GET https://twit.tv/api/v1.0/episodes?sort=-airingDate&range=4`
- **Auth:** `app-id` and `app-key` headers (register at twit-tv.3scale.net)
- **Rate limit:** 5 requests/minute
- **Fields used:** show shortCode, show label, airingDate, heroImage
- **Refresh:** Every 30 minutes

### Memberful API — Active Paid Members

- **Endpoint:** `POST https://twit.memberful.com/api/graphql?api_user_id=55380`
- **Auth:** Bearer token
- **Protocol:** GraphQL with cursor-based pagination (100 members/page)
- **Counting logic:** Member is "active paid" if `subscriptions[0].active == true` AND `creditCard.brand` is set
- **Refresh:** Every 4 hours (pagination requires many requests for large member counts)

## Caching Strategy

- **TWiT episodes:** Fetched fresh every 30 minutes (1 API call)
- **Memberful count:** Fetched every 4 hours, cached to `cache/memberful.json`
- **Album art:** Cached to `cache/art/` after first download, re-fetched only when episode changes

## Project Structure

```
twit-eink-dashboard/
├── config.toml.example    # Template (no secrets)
├── config.toml            # .gitignored, actual secrets on Pi
├── dashboard.py           # Single script: fetch, render, display
├── cache/                 # .gitignored
│   ├── art/               # Cached album art PNGs
│   └── memberful.json     # Cached member count + timestamp
├── requirements.txt       # inky, Pillow, requests
└── twit-dashboard.service # systemd timer + service
```

## Dependencies

- `inky[rpi]` — Inky display driver
- `Pillow` — Image rendering
- `requests` — HTTP client

## Development & Testing

- `dashboard.py --preview` saves to `preview.png` instead of pushing to Inky
- Allows layout iteration from any machine without e-ink hardware

## Error Handling

- TWiT API failure: display last cached data, log error
- Memberful API failure: show last cached count
- No cached data (first run, no network): display "No data yet" placeholder

## Deployment

1. Clone repo to `~/opt/twit-dashboard/`
2. Create venv, install requirements
3. Copy `config.toml.example` to `config.toml`, fill in API keys
4. Install systemd timer (runs every 30 minutes + once at boot)

## Configuration

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
