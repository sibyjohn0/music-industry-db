#!/usr/bin/env python3
"""
Music Industry Database Pipeline
=================================
Fetches artist-label/agency data from MusicBrainz, Discogs, and Spotify,
merges all sources, applies cleaning, and writes music_database_clean.csv.

Usage:
    python3 pipeline.py

Credentials (set in .env or as environment variables):
    DISCOGS_CONSUMER_KEY
    DISCOGS_CONSUMER_SECRET
    SPOTIFY_CLIENT_ID       (default provided)
    SPOTIFY_CLIENT_SECRET
"""

import os, sys, csv, time, base64, warnings, pathlib
from collections import defaultdict

warnings.filterwarnings("ignore")

# ── Load .env if present ───────────────────────────────────────────────────────
ENV_FILE = pathlib.Path(__file__).parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

try:
    import requests
except ImportError:
    sys.exit("ERROR: run `pip3 install requests` first.")

# ── Credentials ────────────────────────────────────────────────────────────────
DISCOGS_KEY    = os.environ.get("DISCOGS_CONSUMER_KEY", "")
DISCOGS_SECRET = os.environ.get("DISCOGS_CONSUMER_SECRET", "")
SPOTIFY_ID     = os.environ.get("SPOTIFY_CLIENT_ID", "d87d3a52622d4b19bb16e9ca0dddaf8d")
SPOTIFY_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

OUT_DIR = pathlib.Path(__file__).parent
FIELDS  = ["Agency/Label Name", "Entity Type", "Country", "Artist Name",
           "Genre", "Contact/A&R Email", "Website", "Source", "Notes"]

# ══════════════════════════════════════════════════════════════════════════════
# CLEANING RULES  (all fixes discovered during manual review)
# ══════════════════════════════════════════════════════════════════════════════

# Canonical name map — normalises duplicate/variant agency names
NAME_MAP = {
    "Mixtape":                       "Mixtape Live",
    "Music Gets Me High (MGMH)":     "MGMH (Music Gets Me High)",
    "Only Much Louder (OML)":        "OML (Only Much Louder)",
    "Speed Records (14)":            "Speed Records",
    "Speed Records Entertainment":   "Speed Records",
}

# Booking/management companies mistakenly tagged as labels
FORCE_AGENCY = {
    "OML (Only Much Louder)",
    "MGMH (Music Gets Me High)",
    "Collective Artists Network",
    "Krunk Live",
    "Mixtape Live",
    "AMG India",
    "Big Bang Music (BGBNG)",
    "REPRESENT",
}

# Non-music talent to exclude
REMOVE_ARTISTS = {
    "Tanmay Bhatt",
    "Zakir Khan",
}

# Entities to drop entirely (comedy/events companies, not music labels)
REMOVE_AGENCIES = {
    "OML (Only Much Louder)",
}

# Historical label flags: (agency_lower, artist_lower) → note
HISTORICAL = {
    ("speed records", "karan aujla"): "Historical — now on Warner Music India (91 North)",
    ("speed records", "naezy"):       "Historical — now on Azadi Records",
}

# Column alias map for normalising headers across sources
COL_ALIAS = {
    "agency name":          "Agency/Label Name",
    "label name":           "Agency/Label Name",
    "agency/label name":    "Agency/Label Name",
    "entity type":          "Entity Type",
    "agency country":       "Country",
    "country":              "Country",
    "artist name":          "Artist Name",
    "artist / act name":    "Artist Name",
    "genre":                "Genre",
    "genre / style":        "Genre",
    "booking email":        "Contact/A&R Email",
    "contact/a&r email":    "Contact/A&R Email",
    "agency website":       "Website",
    "website":              "Website",
    "source":               "Source",
    "notes":                "Notes",
}

# ══════════════════════════════════════════════════════════════════════════════
# MUSICBRAINZ SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

MB_BASE    = "https://musicbrainz.org/ws/2"
MB_HEADERS = {"User-Agent": "MusicIndustryDB/1.0 (sibyjohn0@gmail.com)"}
MB_DELAY   = 1.1   # strict 1 req/sec rate limit

def mb_get(path, params=None):
    params = {**(params or {}), "fmt": "json"}
    r = requests.get(f"{MB_BASE}{path}", headers=MB_HEADERS, params=params, timeout=30)
    time.sleep(MB_DELAY)
    if r.status_code == 503:
        print("  MusicBrainz 503 — sleeping 15s"); time.sleep(15)
        return mb_get(path, params)
    return r.json() if r.status_code == 200 else {}

MB_COUNTRIES = [
    ("IN","India"), ("US","United States"), ("GB","United Kingdom"),
    ("AU","Australia"), ("DE","Germany"), ("SE","Sweden"),
    ("CA","Canada"), ("FR","France"), ("JP","Japan"),
    ("NG","Nigeria"), ("ZA","South Africa"), ("BR","Brazil"),
]

def run_musicbrainz():
    print("\n[MusicBrainz] Starting...")
    rows, seen = [], set()
    for code, country_name in MB_COUNTRIES:
        print(f"  {country_name}")
        for offset in range(0, 200, 100):        # 2 pages max per country
            data = mb_get("/label", {"query": f"country:{code}", "limit": 100, "offset": offset})
            labels = data.get("labels", [])
            if not labels:
                break
            for label in labels:
                lid   = label.get("id", "")
                lname = label.get("name", "")
                lcountry = label.get("country", country_name)
                if not lid or not lname:
                    continue
                releases = mb_get("/release", {
                    "label": lid, "limit": 25, "inc": "artist-credits+genres+tags"
                }).get("releases", [])
                for rel in releases:
                    tags = sorted(
                        (rel.get("tags") or []) + (rel.get("genres") or []),
                        key=lambda t: t.get("count", 0), reverse=True
                    )
                    genre = ", ".join(t["name"] for t in tags[:3])
                    for credit in rel.get("artist-credit", []):
                        if isinstance(credit, str):
                            continue
                        artist = credit.get("artist", {}).get("name", "")
                        if not artist or artist.lower() in ("various artists", "unknown"):
                            continue
                        key = (lname.lower(), artist.lower())
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append({
                            "Agency/Label Name": lname,
                            "Entity Type": "Label",
                            "Country": lcountry,
                            "Artist Name": artist,
                            "Genre": genre,
                            "Contact/A&R Email": "",
                            "Website": f"https://musicbrainz.org/label/{lid}",
                            "Source": "MusicBrainz",
                            "Notes": "",
                        })
        print(f"    running total: {len(rows)}")
    print(f"[MusicBrainz] Done — {len(rows)} rows")
    return rows

# ══════════════════════════════════════════════════════════════════════════════
# DISCOGS SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

DG_BASE    = "https://api.discogs.com"
DG_DELAY   = 1.1   # 25 req/min on consumer key auth

def dg_get(url, params=None):
    if not DISCOGS_KEY or not DISCOGS_SECRET:
        return {}
    r = requests.get(url,
        headers={
            "User-Agent": "MusicIndustryDB/1.0 sibyjohn0@gmail.com",
            "Authorization": f"Discogs key={DISCOGS_KEY}, secret={DISCOGS_SECRET}",
        },
        params=params or {}, timeout=30)
    time.sleep(DG_DELAY)
    if r.status_code == 429:
        print("  Discogs 429 — sleeping 60s"); time.sleep(60)
        return dg_get(url, params)
    return r.json() if r.status_code == 200 else {}

DG_SEARCHES = [
    ("", "India"), ("indie", "India"), ("electronic", "India"),
    ("hip hop", "India"), ("", "US"), ("indie", "US"),
    ("electronic", "US"), ("", "UK"), ("indie", "UK"),
    ("", "Australia"), ("", "Germany"), ("", "Sweden"),
    ("", "Canada"), ("", "Nigeria"), ("", "Brazil"),
    ("", "Japan"), ("Bollywood", ""), ("Tamil music", ""),
    ("Punjabi music", ""), ("Haryanvi", ""),
]

def run_discogs():
    if not DISCOGS_KEY:
        print("[Discogs] Skipped — no credentials")
        return []
    print("\n[Discogs] Starting...")
    rows, seen, seen_ids = [], set(), set()
    for query, country in DG_SEARCHES:
        for page in range(1, 4):
            data = dg_get(f"{DG_BASE}/database/search", {
                "type": "label", "q": query, "country": country,
                "per_page": 50, "page": page,
            })
            results = data.get("results", [])
            if not results:
                break
            for info in results:
                lid   = info.get("id")
                lname = info.get("title", "")
                if not lid or lid in seen_ids:
                    continue
                seen_ids.add(lid)
                releases = dg_get(
                    f"{DG_BASE}/labels/{lid}/releases",
                    {"per_page": 50, "page": 1, "sort": "year", "sort_order": "desc"}
                ).get("releases", [])
                for rel in releases:
                    artist = rel.get("artist", "")
                    if not artist or artist.lower() in ("various", "various artists"):
                        continue
                    genre = ", ".join((rel.get("genres") or []) + (rel.get("styles") or []))[:100]
                    key = (lname.lower(), artist.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "Agency/Label Name": lname,
                        "Entity Type": "Label",
                        "Country": country or "Unknown",
                        "Artist Name": artist,
                        "Genre": genre,
                        "Contact/A&R Email": "",
                        "Website": f"https://www.discogs.com/label/{lid}",
                        "Source": "Discogs",
                        "Notes": "",
                    })
    print(f"[Discogs] Done — {len(rows)} rows")
    return rows

# ══════════════════════════════════════════════════════════════════════════════
# SPOTIFY ARTIST ENRICHMENT
# NOTE: Spotify's label field returns null under Client Credentials (2024+ API
# change). This collects artist name + Spotify URL only, as a reference file.
# EDGE CASE: market=IN caps at limit=10 (undocumented, >10 returns HTTP 400).
# ══════════════════════════════════════════════════════════════════════════════

SP_BASE   = "https://api.spotify.com/v1"
SP_DELAY  = 0.2
_sp_token = None

def sp_token():
    global _sp_token
    if not SPOTIFY_SECRET:
        return None
    creds = base64.b64encode(f"{SPOTIFY_ID}:{SPOTIFY_SECRET}".encode()).decode()
    r = requests.post("https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {creds}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"}, timeout=30)
    r.raise_for_status()
    _sp_token = r.json()["access_token"]
    return _sp_token

def sp_get(path, params=None):
    global _sp_token
    if not _sp_token:
        sp_token()
    if not _sp_token:
        return None
    r = requests.get(f"{SP_BASE}{path}",
        headers={"Authorization": f"Bearer {_sp_token}"}, params=params or {}, timeout=30)
    time.sleep(SP_DELAY)
    if r.status_code == 401:
        sp_token(); return sp_get(path, params)
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", 10)); time.sleep(wait)
        return sp_get(path, params)
    # 400 on search usually means invalid limit for this market — caller handles
    return r.json() if r.status_code == 200 else None

SP_INDIA_QUERIES = [
    "hindi", "bollywood", "filmi", "punjabi", "tamil", "telugu",
    "malayalam", "kannada", "marathi", "bhojpuri",
    "indian indie", "indian hip hop", "desi pop", "indian electronic",
    "indian classical", "carnatic", "hindustani", "ghazal", "qawwali",
    "azadi records", "gully gang", "divine rapper", "raftaar", "badshah",
    "ap dhillon", "arijit singh", "pritam", "ar rahman",
    "prateek kuhad", "ritviz", "when chai met toast", "the local train",
    "seedhe maut", "prabh deep", "nucleya",
]
SP_GLOBAL_QUERIES = [
    ("sub pop", "US"), ("matador", "US"), ("merge records", "US"),
    ("warp", "GB"), ("ninja tune", "GB"), ("domino", "GB"),
    ("indie rock", "US"), ("indie pop", "US"), ("shoegaze", "GB"),
    ("afrobeats", "NG"), ("amapiano", "ZA"), ("k-indie", "KR"),
    ("latin indie", "MX"), ("bossa nova", "BR"),
]

def run_spotify():
    if not SPOTIFY_SECRET:
        print("[Spotify] Skipped — no SPOTIFY_CLIENT_SECRET")
        return []
    sp_token()
    if not _sp_token:
        print("[Spotify] Skipped — token fetch failed")
        return []
    print("\n[Spotify] Starting artist enrichment...")
    rows, seen = [], set()

    def add(a, market):
        aid  = a.get("id")
        name = (a.get("name") or "").strip()
        if not aid or not name or aid in seen:
            return
        seen.add(aid)
        rows.append({
            "Artist Name": name,
            "Spotify ID": aid,
            "Spotify URL": f"https://open.spotify.com/artist/{aid}",
            "Market": market,
        })

    # India: use limit=10 — market IN rejects limit>10 (HTTP 400, undocumented)
    for q in SP_INDIA_QUERIES:
        for offset in range(0, 100, 10):
            data = sp_get("/search", {"q": q, "type": "artist",
                                      "market": "IN", "limit": 10, "offset": offset})
            if not data:
                break
            items = data.get("artists", {}).get("items", [])
            if not items:
                break
            for a in items:
                add(a, "IN")

    # Global: limit=50 works fine outside IN
    for q, market in SP_GLOBAL_QUERIES:
        for offset in range(0, 50, 50):
            data = sp_get("/search", {"q": q, "type": "artist",
                                      "market": market, "limit": 50, "offset": offset})
            if not data:
                break
            for a in (data.get("artists", {}).get("items", []) or []):
                add(a, market)

    print(f"[Spotify] Done — {len(rows)} artists")
    return rows

# ══════════════════════════════════════════════════════════════════════════════
# LOAD EXISTING AGENT CSVS  (web-scraped, kept as supplementary source)
# ══════════════════════════════════════════════════════════════════════════════

def load_agent_csvs():
    agent_files = [
        OUT_DIR / "agent_output.csv",
        OUT_DIR / "labels_agencies_roster.csv",
    ]
    rows = []
    for fpath in agent_files:
        if not fpath.exists():
            continue
        with open(fpath, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                norm = {}
                for k, v in row.items():
                    std = COL_ALIAS.get(k.strip().lower())
                    if std:
                        norm[std] = (v or "").strip()
                if not norm.get("Agency/Label Name") or not norm.get("Artist Name"):
                    continue
                norm.setdefault("Entity Type", "")
                norm.setdefault("Source", fpath.stem)
                norm.setdefault("Notes", "")
                rows.append(norm)
    print(f"[Agent CSVs] Loaded {len(rows)} rows from {[f.name for f in agent_files if f.exists()]}")
    return rows

# ══════════════════════════════════════════════════════════════════════════════
# MERGE + CLEAN
# ══════════════════════════════════════════════════════════════════════════════

def clean_and_merge(all_rows):
    print("\n[Clean] Applying normalization and cleaning rules...")
    out, seen = [], set()
    removed_artists = 0
    removed_agencies = 0

    for r in all_rows:
        artist = r.get("Artist Name", "").strip()
        name   = r.get("Agency/Label Name", "").strip()

        # Remove non-music talent
        if artist in REMOVE_ARTISTS:
            removed_artists += 1
            continue

        # Normalise agency name
        name = NAME_MAP.get(name, name)
        r["Agency/Label Name"] = name

        # Remove entire agencies
        if name in REMOVE_AGENCIES:
            removed_agencies += 1
            continue

        # Fix entity type for known agencies
        if name in FORCE_AGENCY:
            r["Entity Type"] = "Agency"

        # Infer missing entity type
        if not r.get("Entity Type"):
            r["Entity Type"] = "Label"

        # Add historical note
        r["Notes"] = HISTORICAL.get((name.lower(), artist.lower()), r.get("Notes", ""))

        # Deduplicate
        key = (name.lower(), artist.lower())
        if key in seen or not name or not artist:
            continue
        seen.add(key)

        out.append({f: r.get(f, "") for f in FIELDS})

    print(f"  Removed artists: {removed_artists}")
    print(f"  Removed agencies: {removed_agencies}")
    print(f"  Unique rows kept: {len(out)}")

    # Sort: India first, labels before agencies, then name
    def sort_key(r):
        c = r["Country"].lower()
        return (
            0 if c in ("in", "india") else (2 if c == "unknown" else 1),
            0 if r["Entity Type"] == "Label" else 1,
            r["Agency/Label Name"].lower()
        )
    out.sort(key=sort_key)
    return out

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Music Industry Database Pipeline")
    print("=" * 60)

    if not DISCOGS_KEY:
        print("WARNING: DISCOGS_CONSUMER_KEY not set — Discogs will be skipped.")
    if not SPOTIFY_SECRET:
        print("WARNING: SPOTIFY_CLIENT_SECRET not set — Spotify will be skipped.")

    def safe(fn, label):
        try:
            return fn()
        except Exception as e:
            print(f"  [WARN] {label} failed, continuing with partial data: {e}")
            return []
    all_rows = []
    all_rows += safe(load_agent_csvs, "agent CSVs")
    all_rows += safe(run_musicbrainz, "MusicBrainz")
    all_rows += safe(run_discogs, "Discogs")

    # Merge and clean label/agency database
    clean = clean_and_merge(all_rows)
    db_path = OUT_DIR / "music_database_clean.csv"
    with open(db_path, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writeheader()
        csv.DictWriter(f, fieldnames=FIELDS).writerows(clean)
    print(f"\n[Output] {db_path}  ({len(clean)} rows)")

    # Spotify enrichment — separate reference file (no label data available)
    sp_rows = safe(run_spotify, "Spotify")
    if sp_rows:
        sp_path = OUT_DIR / "spotify_artists.csv"
        sp_fields = ["Artist Name", "Spotify ID", "Spotify URL", "Market"]
        with open(sp_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=sp_fields)
            w.writeheader(); w.writerows(sp_rows)
        print(f"[Output] {sp_path}  ({len(sp_rows)} artists)")

    print("\nDone.")

if __name__ == "__main__":
    main()
