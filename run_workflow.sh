#!/usr/bin/env bash

set -euo pipefail

ENV_NAME="${ENV_NAME:-pes}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Usage: ./run_workflow.sh [--refetch | --lineup-only] [--game-index <N>] [<country> | <group> ...]"
  echo
  echo "Examples:"
  echo "  ./run_workflow.sh"
  echo "  ./run_workflow.sh --refetch"
  echo "  ./run_workflow.sh --lineup-only france"
  echo "  ./run_workflow.sh france"
  echo "  ./run_workflow.sh --refetch france"
  echo "  ./run_workflow.sh --refetch --game-index 2 morocco"
  echo "  ./run_workflow.sh belgium france germany"
  echo "  ./run_workflow.sh backup"
  echo "  ./run_workflow.sh --lineup-only challengers"
}

REFETCH_FLAG=""
LINEUP_ONLY_FLAG=""
GAME_INDEX_FLAG=""
countries=()
groups=()
selection_given=0
args=("$@")
i=0
while [ $i -lt ${#args[@]} ]; do
  arg="${args[$i]}"
  if [ "$arg" = "--refetch" ] || [ "$arg" = "--refresh" ] || [ "$arg" = "--no-cache" ]; then
    REFETCH_FLAG="--refetch"
  elif [ "$arg" = "--lineup-only" ] || [ "$arg" = "--espn-lineup" ]; then
    LINEUP_ONLY_FLAG="--lineup-only"
  elif [ "$arg" = "--game-index" ]; then
    i=$((i + 1))
    if [ $i -ge ${#args[@]} ]; then
      echo "Error: --game-index requires a value." >&2; exit 1
    fi
    GAME_INDEX_FLAG="--game-index ${args[$i]}"
  else
    selection_given=1
    case "$arg" in
      contender|contenders) groups+=("contenders") ;;
      challenger|challengers) groups+=("challengers") ;;
      backup) groups+=("backup") ;;
      reserve) groups+=("reserve") ;;
      *) countries+=("$arg") ;;
    esac
  fi
  i=$((i + 1))
done

if [ -n "$REFETCH_FLAG" ] && [ -n "$LINEUP_ONLY_FLAG" ]; then
  echo "Error: use either --refetch or --lineup-only, not both." >&2
  exit 1
fi

for group in "${groups[@]:-}"; do
  for players_file in "$ROOT_DIR"/nations/"$group"/*/*_players.txt; do
    if [ ! -f "$players_file" ] || ! grep -Eq '^[[:space:]]*[^#[:space:]].*,' "$players_file"; then
      continue
    fi
    country="$(basename "$(dirname "$players_file")")"
    duplicate=0
    for existing in "${countries[@]:-}"; do
      if [ "$existing" = "$country" ]; then
        duplicate=1
        break
      fi
    done
    if [ "$duplicate" -eq 0 ]; then
      countries+=("$country")
    fi
  done
done

if [ "${#countries[@]}" -eq 0 ] && [ "$selection_given" -eq 0 ]; then
  seen=()
  for players_file in "$ROOT_DIR"/nations/*/*/*_players.txt; do
    if [ ! -f "$players_file" ]; then
      continue
    fi
    if ! grep -Eq '^[[:space:]]*[^#[:space:]].*,' "$players_file"; then
      continue
    fi
    country="$(basename "$(dirname "$players_file")")"
    duplicate=0
    for existing in "${seen[@]:-}"; do
      if [ "$existing" = "$country" ]; then
        duplicate=1
        break
      fi
    done
    if [ "$duplicate" -eq 0 ]; then
      seen+=("$country")
      countries+=("$country")
    fi
  done
  if [ "${#countries[@]}" -eq 0 ]; then
    echo "Error: no country folders with *_players.txt were found." >&2
    exit 1
  fi
fi

if [ "${#countries[@]}" -eq 0 ]; then
  echo "Error: no nations with populated *_players.txt files matched the selection." >&2
  exit 1
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "Error: conda is not available in PATH." >&2
  exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

cd "$ROOT_DIR"

for country in "${countries[@]}"; do
  echo "==> Running workflow for $country"

  if [ -n "$LINEUP_ONLY_FLAG" ]; then
    python scripts/fetch_number.py "$LINEUP_ONLY_FLAG" $GAME_INDEX_FLAG "$country"
  elif [ -n "$REFETCH_FLAG" ]; then
    python scripts/fetch_number.py "$REFETCH_FLAG" $GAME_INDEX_FLAG "$country"
  else
    python scripts/fetch_number.py $GAME_INDEX_FLAG "$country"
  fi
  python scripts/fetch_game_data.py "$country"
  python scripts/draft_gameplan.py "$country"

  echo "==> Finished $country"
  echo
done
