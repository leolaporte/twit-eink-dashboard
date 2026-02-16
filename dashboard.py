#!/usr/bin/env python3
"""TWiT E-Ink Dashboard — renders to Inky Impression 7.3" or preview PNG."""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import requests
import tomllib

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
        try:
            with open(MEMBERFUL_CACHE) as f:
                cached = json.load(f)
            log.info("Falling back to cached count: %d", cached["count"])
            return cached["count"]
        except (json.JSONDecodeError, KeyError):
            pass
    return None


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
        log.warning("  Failed to fetch episodes")

    member_count = fetch_memberful_count(config)
    log.info("Club TWiT paid members: %s", member_count)


if __name__ == "__main__":
    main()
