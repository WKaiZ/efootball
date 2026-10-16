_efootball_completion_root=${${(%):-%N}:A:h:h}

_efootball_run_workflow() {
  local -a candidates nations
  nations=(${(f)"$(find "$_efootball_completion_root/nations" -mindepth 2 -maxdepth 2 -type d -exec basename {} \; | sort)"})
  candidates=(--refetch --lineup-only --game-index contender contenders challenger challengers backup reserve "${nations[@]}")
  compadd -- "${candidates[@]}"
}

compdef _efootball_run_workflow ./run_workflow.sh run_workflow.sh
