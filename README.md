# efootball

Tracks eFootball national-team squads. Each nation has a hand-maintained player pool; a deterministic drafter picks a gameplan (11 starters, 11 substitutes, 1 wildcard) with real jersey numbers scraped from Transfermarkt and ESPN, and a build script turns the results into JSON for a static site in `docs/`, published with GitHub Pages and refreshed daily by GitHub Actions.

## Repo layout

```
nations/<group>/<country>/   per-nation inputs and drafted squads
  <country>_players.txt      player pool (hand-maintained)
  <country>.txt              drafted squad (generated)
nations/ranking.json         FIFA ranking snapshot used for grouping
scripts/                     command-line entry points and site build
jersey_fetch/                ESPN lineup + Transfermarkt jersey scraping
gameplan/                    draft builder (lineup, formation, jersey assignment)
common/                      country slug lookup
reference/                   draft rules (draft_gameplan_rules.txt)
data/                        caches: card_cache.json, photo caches, overrides, card_names.json
docs/                        static site: index.html, squads.json, players.json, history.json
pes.db                       SQLite: players, jersey history, game_data
run_workflow.sh              local workflow wrapper
.github/workflows/           site.yml (daily build), tm-probe.yml (diagnostic)
```

Groups follow the FIFA men's ranking: `contenders` (1-20), `challengers` (21-50), `backup` (51-100), `reserve` (101+). Slugs follow FIFA labels (`cabo-verde`, `korea-republic`); scripts take a bare slug such as `france`.

## File formats

### `<country>_players.txt`

One row per player and main position. `#` lines and blank lines are ignored; a player may have several rows for different positions.

```
Name, MAIN_POS, RATING, RECENT, CARD_TYPE, [PROFICIENT_POSITIONS], [SEMIPROFICIENT_POSITIONS]
Pelé, CF, 99.81, False, Epic, [CF, SS], [AMF]
```

- `MAIN_POS`: `GK, CB, LB, RB, LWB, RWB, DMF, CMF, AMF, LMF, RMF, LWF, RWF, SS, CF`.
- `RECENT`: `True` if the player is in the latest national-team squad (rewritten from ESPN by the workflow).
- `CARD_TYPE`: `Epic`, `BigTime`, `Showtime`, `Highlight`, or `Standard`.

### `<country>.txt`

Drafted by `scripts/draft_gameplan.py`. Contenders get a First and Second Squad (later squads exclude cards already used); challengers get one squad; backup and reserve nations list starters only.

```
Starters:
  SLOT  PLAYER            POS  RATING  NO.
  CF    Adriano           CF    98.68  #9
  LWF   Ronaldinho        LWF   99.95  #10
  CB    VACANT
```

The formation starts from `CF, LWF, RWF, AMF, CMF, DMF, LB, CB, CB, RB, GK` and switches a slot (e.g. LWF to LMF, CF to SS) only for a higher-tier special card. Full selection and numbering rules are in [`reference/draft_gameplan_rules.txt`](./reference/draft_gameplan_rules.txt).

## Daily pipeline

`.github/workflows/site.yml` runs every day (and on demand):

1. Runs `scripts/efootball_build.py`, which reads every nation's player and squad files plus `pes.db`, derives squad history from git, and writes `docs/squads.json`, `docs/players.json` and `docs/history.json`.
2. Resolves player photos (Transfermarkt, then FotMob) and card images, within a per-run request budget, caching results under `data/`.
3. Commits the updated JSON and caches back to `main`, which GitHub Pages serves.

Drafting squads and scraping jersey numbers happen locally with `run_workflow.sh`.

## Card images

Card art comes from efHUB, found through pesdb.net's player search by name and main position, and is cached in `data/card_cache.json`. The site falls back to the player photo, then initials.

- Existing rows follow the as-of-date rule: a special card is the newest matching card as of the date the row's current rating first appeared in git history.
- Rows added or edited after 2026-11-23 take the newest card of that type for that player and position.
- `Standard` matches the card whose OVR equals the whole-number part of `RATING` (nearest card if none is exact, marked approximate).
- `Epic` and `BigTime` are interchangeable; `Showtime` matches Show Time cards.
- `Highlight` covers both Highlight and Trending cards.
- Automatic special-card picks are `likely` until the user confirms them; confirmed picks and all Standard cards are `confirmed`. Each cached card records the rating it was picked for. When a special card's row changes rating, the card is looked up again ahead of other lookups, even if confirmed, using the newest-card rule. Earlier rejections are cleared, and a different card comes back as `likely`. Otherwise confirmed cards are never looked up again. Changing a row's card type or position makes it a new row.

If the name search finds nothing, the lookup searches pesdb by the player's nationality, position and (for Standard) exact OVR, then matches names loosely: a shared surname or given name, transliteration variants (ch/č, zh/j, kh/x), double letters, either name order, or a nickname prefix (Miguelito/Miguel). A Standard card is also tried at any position if the full name matches. Players no rule can match go in `data/card_names.json` (country → name in the players file → name on pesdb).

Try one lookup: `python3 scripts/cardfetch.py "Thierry Henry" CF Epic 100.03` (add a country slug such as `france` as a fifth argument to enable the nationality fallback).

## Running locally

Setup: `conda create -n pes python=3.11 -y && conda activate pes && pip install -r requirements.txt && python -m playwright install chromium` (`run_workflow.sh` activates the `pes` env; override with `ENV_NAME`).

```bash
./run_workflow.sh                       # every nation with player rows
./run_workflow.sh france germany        # specific nations
./run_workflow.sh backup                # a whole group
./run_workflow.sh --lineup-only france  # refresh ESPN recent flags/numbers only
./run_workflow.sh --refetch france      # refresh lineup + reseed numbers; scrape new players
./run_workflow.sh --rescrape france     # full Transfermarkt re-scrape (slow)
python3 scripts/draft_gameplan.py france  # redraft from existing pes.db data
python3 scripts/efootball_build.py        # rebuild the site JSON
```

`--game-index N` uses the Nth most recent match. If Transfermarkt shows a bot check, rerun with `TRANSFERMARKT_INTERACTIVE=1` to verify in a browser window. Shell completion for nation names is in `completions/` (zsh and bash).

## Viewing the site

GitHub Pages serves `docs/` from `main`. To preview locally, run `python3 -m http.server -d docs 8000` and open http://localhost:8000.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `EFOOTBALL_CARD_LIMIT` | `150` | Card lookups per build run |
| `EFOOTBALL_CARD_DELAY` | `6` | Seconds between card requests |
| `EFOOTBALL_CARD_TTL_DAYS` | `7` | Days before a missed card lookup is retried |
| `EFOOTBALL_CARD_TYPES` | `all` | Card types to look up: `all`, `special`, `standard` |
| `EFOOTBALL_CARD_NEWEST_AFTER` | `2026-11-23` | Rows changed after this date take the newest card |
| `EFOOTBALL_TM_LIMIT` | `23` | Transfermarkt photos resolved per build run |
| `TRANSFERMARKT_INTERACTIVE` | unset | `1` opens a browser for Transfermarkt verification |

## Scripts

- `scripts/efootball_build.py`: builds the site JSON, photos, card images, and squad history.
- `scripts/draft_gameplan.py`: drafts a nation's squad(s) into `<country>.txt`.
- `scripts/fetch_number.py`: ESPN lineup flags and Transfermarkt jersey history into `pes.db`.
- `scripts/fetch_game_data.py`: loads `<country>_players.txt` into `pes.db`.
- `scripts/prune_unconsidered_standard.py`: removes Standard rows that can never be selected.
- `scripts/cardfetch.py`: card lookup and matching against pesdb.net.
- `scripts/tmfetch.py`, `scripts/imgcache.py`: Transfermarkt photo fetching and cache.
- `scripts/sort_players.py`, `scripts/prune_db.py`, `scripts/merge_json_conflict.py`: maintenance (sort player files, drop orphaned DB rows, merge JSON conflicts).
