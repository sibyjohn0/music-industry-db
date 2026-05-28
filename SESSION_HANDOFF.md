# Music Industry Database — Session Handoff

## What this is
A CSV database of music labels, booking agencies, and management companies — India-first, then global — with their artist rosters. Built from four sources: web-scraped agency/label websites (via AI agents), Discogs API, MusicBrainz API, and Spotify (artist enrichment only).

---

## Files

| File | What it is |
|---|---|
| `~/Downloads/music_db/music_database_clean.csv` | **Main database. Open this.** 1,327 rows, India-sorted. |
| `~/Downloads/music_db/spotify_artists.csv` | 721 Indian + global artists with Spotify URLs. Use to add Spotify links to any artist in the main DB. |
| `~/Downloads/music_db/pipeline.py` | Single script to regenerate the full database from scratch. |
| `~/Downloads/music_db/.env` | All API credentials (Spotify + Discogs). |

---

## GitHub repo
**https://github.com/sibyjohn0/music-industry-db**

- `music_database_clean.csv` and `spotify_artists.csv` are committed and live here
- GitHub Actions auto-refreshes the DB quarterly (1 Jan, 1 Apr, 1 Jul, 1 Oct)
- All four API secrets are already set in repo Settings → Secrets
- To trigger a manual refresh: Actions tab → "Refresh Music Database" → Run workflow

---

## Database schema

| Column | Notes |
|---|---|
| Agency/Label Name | Canonical name (normalised across sources) |
| Entity Type | Label / Agency / Management |
| Country | India rows are sorted first; "Unknown" = Discogs global search rows |
| Artist Name | |
| Genre | From MusicBrainz/Discogs tags; blank for web-scraped rows |
| Contact/A&R Email | Sparse — only what agencies publish publicly |
| Website | Label/agency URL or MusicBrainz/Discogs profile |
| Source | MusicBrainz / Discogs / labels_agencies_roster / agent |
| Notes | "Historical — now on X" for stale label relationships |

---

## To re-run the pipeline

```bash
cd ~/Downloads/music_db
pip3 install -r requirements.txt
python3 pipeline.py
```

Credentials load automatically from `.env`. Runtime: ~25–35 min (MusicBrainz is 1 req/sec).

---

## Known data quality issues (already fixed in clean CSV)

- **Mixtape / Mixtape Live** — were two separate entries, merged into "Mixtape Live"
- **MGMH** — had two name variants, merged into "MGMH (Music Gets Me High)"
- **Speed Records Entertainment** — merged into "Speed Records"
- **OML (Only Much Louder)** — removed entirely; comedy/events company, not music
- **Entity Type** — OML, MGMH, Collective Artists, Krunk Live, AMG India, REPRESENT, Mixtape Live all fixed from "Label" → "Agency"
- **Tanmay Bhatt, Zakir Khan** — comedians, removed
- **Karan Aujla / Speed Records** — marked Historical (now on Warner 91 North)
- **Naezy / Speed Records** — marked Historical (now on Azadi Records)

---

## Still worth manual review

- **MGMH roster**: Farhan Akhtar and Kailash Kher (Kailasa) listed — verify if MGMH still represents them (MGMH primarily books electronic acts)
- **Sandunes**: appears under both Krunk Live and Mixtape Live — could be correct (different agencies for different services) or a duplication
- **Discogs "Unknown" country rows**: 667 rows from Bollywood/Tamil/Punjabi searches have Country = "Unknown" — likely Indian artists but unverified
- **Artist names with asterisk** (e.g. "Hindi\*"): Discogs disambiguation format — real artist, just Discogs-styled
- **Domino Records, Rough Trade**: both missing from global data — can add manually or re-run pipeline which will pick them up via MusicBrainz

---

## API credentials (also in .env and GitHub Secrets)

| Key | Value |
|---|---|
| Spotify Client ID | d87d3a52622d4b19bb16e9ca0dddaf8d |
| Spotify Client Secret | in `.env` |
| Discogs Consumer Key | fQefzebpOPuBtYHVAxDy |
| Discogs Consumer Secret | in `.env` |
| Spotify app name | Spotify-Indie (developer.spotify.com/dashboard) |

**Gotchas discovered during build:**
- Spotify `label` field returns `null` under Client Credentials auth — can't get label data from Spotify this way
- Spotify search with `market=IN` caps at `limit=10` (not documented; anything higher returns HTTP 400)
- MusicBrainz query with `type:Original Production` breaks due to space in Lucene — just use `country:IN`
- Discogs uses Consumer Key/Secret in auth header, not OAuth token
- Spotify browse/new-releases and featured-playlists endpoints were silently deprecated in late 2024

---

## Update cadence
- **Quarterly** for full refresh (automated via GitHub Actions)
- **Monthly** manually if tracking Indian indie labels specifically (Azadi, Gully Gang, Pagal Haina sign new artists frequently)
- Re-run `python3 pipeline.py` anytime for a fresh pull
