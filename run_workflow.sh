#!/usr/bin/env bash

set -euo pipefail

ENV_NAME="${ENV_NAME:-pes}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Usage: ./run_workflow.sh <country> [<country> ...]"
  echo
  echo "Examples:"
  echo "  ./run_workflow.sh france"
  echo "  ./run_workflow.sh belgium france germany"
}

if [ "$#" -eq 0 ]; then
  usage
  exit 1
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "Error: conda is not available in PATH." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

cd "$ROOT_DIR"

for country in "$@"; do
  echo "==> Running workflow for $country"

  python fetch_number.py "$country"
  python fetch_game_data.py "$country"
  python draft_gameplan.py "$country"

  echo "==> Finished $country"
  echo
done
