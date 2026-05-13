# efootball

Tooling for drafting an eFootball "gameplan" (11 starters + 11 substitutes + 1 wildcard) for a national team. The pipeline scrapes shirt-number history from Transfermarkt, pulls the most recent ESPN match lineup to flag who is currently in the squad, then runs a deterministic builder that picks players for each formation slot and assigns each picked player a real jersey number they have actually worn.

All persistent state lives in the SQLite file `pes.db` at the repo root. Each national team lives in its own folder (e.g. `belgium/`, `france/`, `argentina/`).

---

## 1. Setup

Requirements:

- Python 3 (anything recent), with [`conda`](https://docs.conda.io/) on `PATH`. `run_workflow.sh` activates an env named `pes` by default (override with `ENV_NAME=...`).
- A Chromium install for Playwright (used as a fallback when Transfermarkt's WAF blocks plain HTTP).

Install:

```bash
conda create -n pes python=3.11 -y
conda activate pes
pip install -r requirements.txt
python -m playwright install chromium
```

`requirements.txt` pins the four runtime dependencies:

- `requests`, `beautifulsoup4` — ESPN/DuckDuckGo/Wikidata HTTP + HTML parsing.
- `playwright` — headless Chromium for Transfermarkt pages and ID search.
- `curl_cffi` — TLS-impersonating HTTP client tried first against Transfermarkt before falling back to Playwright.

---

## 2. Per-country inputs

For each national team you want to draft, create a folder named after the country (e.g. `belgium/`) containing:

### `<country>_players.txt` (required)

One row per player+main-position combination. Comma-separated columns:

```
Name, MAIN_POS, RATING, RECENT, CARD_TYPE, [PROFICIENT_POSITIONS], [SEMIPROFICIENT_POSITIONS]
```

- `MAIN_POS` — one of `GK, CB, LB, RB, LWB, RWB, DMF, CMF, AMF, LMF, RMF, LWF, RWF, SS, CF`.
- `RATING` — float; the builder is rating-driven.
- `RECENT` — `True`/`False`. `True` means the player is in the latest national-team squad and locks their most recently worn jersey number. The workflow rewrites this column from ESPN's latest lineup when `--refetch` or `--lineup-only` is used.
- `CARD_TYPE` — `Epic`, `BigTime`, `Showtime`, `Highlight`, or `Standard`. Anything other than those four "non-Standard" tiers is treated as Standard.
- `[PROFICIENT_POSITIONS]` and `[SEMIPROFICIENT_POSITIONS]` — bracketed, comma-separated position lists (may be empty, e.g. `[]`).

A player can appear on multiple lines if they have separate cards for different main positions (see `belgium/belgium_players.txt` for examples like Charles De Ketelaere as both `SS` and `AMF`). Lines starting with `#` and blank lines are ignored.

### `<country>_formation.txt` (optional)

Either one position per line or a single comma-separated line of 11 positions. If missing, the default formation from `gameplan/formation.py` is used:

```
CF, LWF, RWF, AMF, CMF, DMF, LB, CB, CB, RB, GK
```

### `<country>.txt` (output, generated)

The drafted gameplan written by `draft_gameplan.py`. Lists Starters, Substitutes, and the Wildcard with each player's slot, main position, rating, and assigned jersey number.

---

## 3. Running the workflow

The convenience wrapper:

```bash
./run_workflow.sh                           # run for every country folder that has *_formation.txt
./run_workflow.sh france                    # run for one country
./run_workflow.sh belgium france germany    # run for several countries
./run_workflow.sh --refetch france          # force-refresh ESPN + Transfermarkt cache for france
./run_workflow.sh --lineup-only france      # only refresh ESPN "recent" flags; skip Transfermarkt
```

Flags:

- `--refetch` (aliases: `--refresh`, `--no-cache`) — ignore cached jersey rows for this country and re-scrape Transfermarkt; also re-pulls ESPN.
- `--lineup-only` (alias: `--espn-lineup`) — only update the `recent` flags in `<country>_players.txt` from the latest ESPN match. Skips all Transfermarkt traffic.

`--refetch` and `--lineup-only` are mutually exclusive.

For each country the script runs three stages in order:

1. `python fetch_number.py <country>` — ESPN recent-flag update + Transfermarkt jersey scrape into `pes.db`.
2. `python fetch_game_data.py <country>` — Reads `<country>_players.txt`, resolves names to `player_id`s, and writes a `game_data` row per player+position into `pes.db`.
3. `python draft_gameplan.py <country>` — Builds the gameplan from `pes.db` and writes `<country>/<country>.txt`.

You can also run any of those scripts directly if you only need that one stage.

`fetch_numbers.py` is an alias of `fetch_number.py` (both just call `jersey_fetch.run.main`).

Extra flag honored by `fetch_number.py` directly (not exposed by `run_workflow.sh`):

- `--gameid <espnEventId>` — pin a specific ESPN match instead of auto-resolving the latest one.

---

## 4. Database schema (`pes.db`)

Created and migrated automatically. Three tables:

- `players(player_id TEXT PRIMARY KEY, name TEXT)` — Transfermarkt ID → official Transfermarkt display name.
- `jersey(player_id, idx, season, country, number)` — Per-player jersey history, ordered newest-first by `idx`. `country` is the club or national team Transfermarkt label; the workflow filters to the relevant national team when assigning numbers.
- `game_data(country, player_id, position, rating, recent, card_type, proficient_positions, semiproficient_positions)` — One row per player+position+country combo, populated from `<country>_players.txt`.

`fetch_game_data.py` deletes the existing `game_data` rows for the target country before reinserting, so it is always safe to rerun.

---

## 5. Draft rules

The full, authoritative description of starter/substitute/wildcard selection, jersey-number tiering, recent-flag locks, and vacancy-fill order lives in [`draft_gameplan_rules.txt`](./draft_gameplan_rules.txt). The implementation in `gameplan/` follows that document.

---

## 6. File-by-file reference

### Repo root

- `run_workflow.sh` — Bash entry point. Cleans `__pycache__`, parses `--refetch` / `--lineup-only` / country args, activates the conda env, and runs the three Python stages per country. Auto-discovers countries by looking for any `*/_formation.txt` when no country is passed.
- `fetch_number.py` / `fetch_numbers.py` — Thin wrappers that `asyncio.run(jersey_fetch.run.main())`.
- `fetch_game_data.py` — Reads `<country>_players.txt`, parses each line, fuzzy-matches the name to a `player_id` from the `players` table (with a Levenshtein fallback and a hardcoded `MANUAL_ID_OVERRIDES` map for ambiguous names), and writes the resulting rows into `game_data`. Reports parse warnings and unmatched names at the end.
- `draft_gameplan.py` — Loads the formation, loads `game_data` rows for the country, calls `gameplan.builder.build_gameplan`, and writes the human-readable gameplan to both stdout and `<country>/<country>.txt`.
- `draft_gameplan_rules.txt` — Reference document describing the draft rules implemented in `gameplan/`.
- `requirements.txt` — Python dependencies.
- `pes.db` — SQLite database (committed). Holds `players`, `jersey`, and `game_data`.
- `.gitignore` — Ignores `__pycache__/`.
- `<country>/` folders — Per-country inputs and the generated gameplan output.

### `jersey_fetch/` — ESPN + Transfermarkt scraping

- `run.py` — Orchestrates the scrape. Parses CLI args, reads `<country>_players.txt`, optionally fetches ESPN's latest match to flip `recent` flags and seed the most recent jersey number, then for each player resolves their Transfermarkt ID, fetches their `rueckennummern` page, parses national-team rows, and stores them in `pes.db` (or short-circuits on cached rows).
- `discovery.py` — Finds a player's Transfermarkt numeric ID using Wikidata's P2446 property first, then DuckDuckGo HTML search, then a Playwright-driven Transfermarkt search and DuckDuckGo browser search as fallbacks. `score_transfermarkt_candidate` ranks search hits.
- `transfermarkt.py` — Fetches the jersey-history HTML. Tries `curl_cffi` (Chrome TLS impersonation) first; on failure or AWS WAF challenge falls back to a hardened Playwright Chromium context (German locale, stealth init script, cookie-banner click). `extract_national_numbers_from_html` parses the `#yw2 .grid-view` table, skipping youth/B-team/Olympic rows.
- `espn.py` — Resolves an ESPN team ID from the country label (filtering out women's competitions), finds the most recent completed match for that team, downloads its `summary` payload, and produces an `aliases + jersey + role` roster. `map_recent_players_to_roster` matches each ESPN entry against players in `<country>_players.txt`.
- `matching.py` — Name-token compatibility helpers used by the ESPN matcher (initials, surname Levenshtein tolerance, role compatibility, scoring/tiebreak).
- `players_file.py` — Parses CLI args (`parse_args`), resolves the per-country players file path, rewrites `<country>_players.txt` in place to update names or `recent` flags (`rewrite_players_txt`), and builds the local "profiles" + position search hints used by ESPN matching and Transfermarkt search.
- `storage.py` — All `pes.db` access for this package: schema bootstrap (`init_db`), name→ID map, manual-override lookup, jersey insertion (with optional country-scoped delete), cache load, and warnings when a player's stored jersey rows do not include the expected nation.
- `constants.py` — Shared constants: DB path (re-exported from `gameplan.constants`), HTTP user agents, manual Transfermarkt ID overrides per country, ESPN exclusions and manual role overrides, and the `POSITION_SEARCH_PHRASES` map used to disambiguate player searches.
- `names.py` — `normalize_name`, DuckDuckGo redirect unwrapper, and a heuristic for invalid Transfermarkt page titles (WAF challenges, error pages).
- `text_utils.py` — Levenshtein distance.
- `__init__.py` — Marks the package; empty.

### `gameplan/` — Draft builder

- `builder.py` — `build_gameplan` is the entry point. Picks an initial lineup, runs the jersey-assignment phases, and then iteratively replaces starters whose preferred numbers cannot be assigned, fills vacancies in the documented stage order (`main` non-Std → `main` Std → `proficient` non-Std → `proficient` Std → `semiproficient` …), upgrades subs, and tries swap-based fills. Finally chooses a wildcard from the remaining pool.
- `lineup.py` — `choose_initial_lineup` performs Stages A–D from `draft_gameplan_rules.txt` for starters and the rating-driven first pass for substitutes (with the `LWF`/`RWF` → `SS` fallback for sub wings).
- `jerseys.py` — Jersey number assignment. `load_jersey_stats` and `jersey_prefs_for_player` derive each player's preference list from `jersey` rows (Epic uses most-worn; everyone else uses newest-unique-first). `assign_jerseys` assigns numbers in the documented group order: starter non-Std main → starter non-Std proficient → starter Std main → starter Std proficient → sub non-Std normal → sub non-Std `SS`-on-wing → sub Std → sub non-Std `SS`-on-wing via proficient. Within each group, recent-flag locks run first, then card-tier buckets (Epic/BigTime > Showtime > Highlight > Standard), then a tie-break that won't steal another player's first-choice number.
- `candidates.py` — Helpers for the builder's replacement loop: pick the next-best player for a slot (`next_candidate_for_slot`, `next_candidate_for_sub_wing`), refill empty subs (`refill_empty_subs`), and `try_free_jersey_via_swap` to free a recent player's preferred number by re-numbering a non-recent holder.
- `data.py` — Loads `game_data` rows for a country into `PlayerRole` objects, loads the formation file, and resolves the per-country file paths.
- `formation.py` — `DEFAULT_FORMATION` and the mutable `FORMATION` list that the builder reads. `draft_gameplan.py` overwrites `FORMATION[:]` from the country's formation file before building.
- `models.py` — Plain-data classes: `PlayerRole` (one row of `game_data`) and `Assignment` (slot + player + jersey).
- `constants.py` — `DB_PATH`, the set of non-Standard card types, the wing slot set used for the `SS` fallback, the `MATCH_STAGES` ordering used during sub vacancy fill, and `is_standard()`.
- `__init__.py` — Marks the package; empty.

---

## 7. Typical recipes

- **First-time draft for a new country**: create `<country>/<country>_players.txt` (and optionally `<country>_formation.txt`), then `./run_workflow.sh <country>`. The first run is slow because it has to scrape Transfermarkt for every player.
- **Fastest refresh after a new international match**: `./run_workflow.sh --lineup-only <country>` to pull the latest ESPN squad and update `recent` flags, then `./run_workflow.sh <country>` to redraft using cached jerseys.
- **Forcing a Transfermarkt re-scrape** (e.g. after an in-season jersey change): `./run_workflow.sh --refetch <country>`.
- **Drafting from existing data without scraping**: run only `python draft_gameplan.py <country>`. This requires `game_data` rows to already exist for that country in `pes.db`.
