#!/usr/bin/env python3
"""
Fetches TripAdvisor reviews for Odessy Travel and updates reviews.json.
Tries JSON-LD structured data first, then falls back to HTML parsing.
"""

import json
import re
import sys
import os
from datetime import datetime

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run: pip install requests beautifulsoup4 lxml")
    sys.exit(1)

TA_URL = (
    "https://www.tripadvisor.com/Attraction_Review-g1500185-d34295367"
    "-Reviews-Odessy_Travel-Katunayake_Negombo_Western_Province.html"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "no-cache",
}

REVIEWS_FILE = os.path.join(os.path.dirname(__file__), "..", "reviews.json")


def load_existing():
    try:
        with open(REVIEWS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"reviews": []}


def parse_date(raw):
    """Normalise a date string to YYYY-MM."""
    if not raw:
        return ""
    # Already YYYY-MM
    if re.match(r"^\d{4}-\d{2}", raw):
        return raw[:7]
    # ISO full date
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        return raw[:7]
    return raw


def fetch_reviews():
    print(f"Fetching: {TA_URL}")
    resp = requests.get(TA_URL, headers=HEADERS, timeout=30)
    print(f"HTTP {resp.status_code} — {len(resp.text)} chars")

    soup = BeautifulSoup(resp.text, "lxml")
    reviews = []

    # ── Method 1: JSON-LD structured data (fastest, cleanest) ──
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                for r in item.get("review", []):
                    rating_obj = r.get("reviewRating", {})
                    rating = int(float(rating_obj.get("ratingValue", 5)))
                    author = r.get("author", {})
                    name = (
                        author.get("name", "Traveler")
                        if isinstance(author, dict)
                        else str(author)
                    )
                    reviews.append(
                        {
                            "name": name,
                            "location": "",
                            "trip_type": "",
                            "rating": rating,
                            "date": parse_date(r.get("datePublished", "")),
                            "text": r.get("reviewBody", "").strip(),
                        }
                    )
        except Exception as e:
            print(f"  JSON-LD parse error: {e}")

    if reviews:
        print(f"  ✓ Found {len(reviews)} reviews via JSON-LD")
        return reviews

    # ── Method 2: Scan inline <script> blocks for reviewBody keys ──
    print("  Trying inline script extraction...")
    seen = set()
    for script in soup.find_all("script"):
        text = script.string or ""
        bodies = re.findall(r'"reviewBody"\s*:\s*"((?:[^"\\]|\\.){20,})"', text)
        ratings = re.findall(r'"ratingValue"\s*:\s*"?(\d)"?', text)
        names = re.findall(r'"name"\s*:\s*"([^"]{2,40})"', text)
        for i, body in enumerate(bodies):
            clean = body.replace("\\n", " ").replace('\\"', '"').strip()
            if clean not in seen:
                seen.add(clean)
                reviews.append(
                    {
                        "name": names[i] if i < len(names) else "Traveler",
                        "location": "",
                        "trip_type": "",
                        "rating": int(ratings[i]) if i < len(ratings) else 5,
                        "date": "",
                        "text": clean,
                    }
                )

    if reviews:
        print(f"  ✓ Found {len(reviews)} reviews via inline scripts")
    else:
        print("  ✗ No reviews extracted — TripAdvisor may have blocked the request")

    return reviews


def main():
    existing_data = load_existing()
    existing_reviews = existing_data.get("reviews", [])
    existing_texts = {r["text"][:60] for r in existing_reviews}

    try:
        fetched = fetch_reviews()
    except Exception as e:
        print(f"Fetch failed: {e}")
        print("Keeping existing reviews.json unchanged.")
        sys.exit(0)

    if not fetched:
        print("No reviews returned — keeping existing reviews.json.")
        sys.exit(0)

    # Merge: keep existing metadata (location, trip_type) for known reviews
    # and add any genuinely new ones
    existing_map = {r["text"][:60]: r for r in existing_reviews}
    merged = []
    for r in fetched:
        key = r["text"][:60]
        if key in existing_map:
            # Preserve richer metadata from existing record
            base = existing_map[key].copy()
            base.update({k: v for k, v in r.items() if v})  # update non-empty fields
            merged.append(base)
        else:
            merged.append(r)

    new_count = sum(1 for r in fetched if r["text"][:60] not in existing_texts)

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(merged),
        "reviews": merged,
    }

    with open(REVIEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    if new_count:
        print(f"✓ reviews.json updated — {new_count} new review(s) added ({len(merged)} total)")
    else:
        print(f"✓ reviews.json refreshed — no new reviews ({len(merged)} total)")


if __name__ == "__main__":
    main()
