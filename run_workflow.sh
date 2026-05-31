#!/usr/bin/env bash

set -euo pipefail

ENV_NAME="${ENV_NAME:-pes}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Usage: ./run_workflow.sh [--refetch | --lineup-only] [--game-index <N>] [<country> ...]"
  echo
  echo "Examples:"
  echo "  ./run_workflow.sh"
  echo "  ./run_workflow.sh --refetch"
  echo "  ./run_workflow.sh --lineup-only france"
  echo "  ./run_workflow.sh france"
  echo "  ./run_workflow.sh --refetch france"
  echo "  ./run_workflow.sh --refetch --game-index 2 morocco"
  echo "  ./run_workflow.sh belgium france germany"
}

find . -depth -type d -name "__pycache__" -exec rm -rf {} +

REFETCH_FLAG=""
LINEUP_ONLY_FLAG=""
GAME_INDEX_FLAG=""
countries=()
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
    countries+=("$arg")
  fi
  i=$((i + 1))
done

if [ -n "$REFETCH_FLAG" ] && [ -n "$LINEUP_ONLY_FLAG" ]; then
  echo "Error: use either --refetch or --lineup-only, not both." >&2
  exit 1
fi

if [ "${#countries[@]}" -eq 0 ]; then
  countries=()
  for formation_file in "$ROOT_DIR"/*/*_formation.txt; do
    if [ ! -f "$formation_file" ]; then
      continue
    fi
    countries+=("$(basename "$(dirname "$formation_file")")")
  done
  if [ "${#countries[@]}" -eq 0 ]; then
    echo "Error: no country folders with *_formation.txt were found." >&2
    exit 1
  fi
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "Error: conda is not available in PATH." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

cd "$ROOT_DIR"

for country in "${countries[@]}"; do
  echo "==> Running workflow for $country"

  if [ -n "$LINEUP_ONLY_FLAG" ]; then
    python fetch_number.py "$LINEUP_ONLY_FLAG" $GAME_INDEX_FLAG "$country"
  elif [ -n "$REFETCH_FLAG" ]; then
    python fetch_number.py "$REFETCH_FLAG" $GAME_INDEX_FLAG "$country"
  else
    python fetch_number.py $GAME_INDEX_FLAG "$country"
  fi
  python fetch_game_data.py "$country"
  python draft_gameplan.py "$country"

  echo "==> Finished $country"
  echo
done
