_efootball_completion_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

_efootball_run_workflow_complete() {
  local current nation nation_dir
  local -a candidates
  current="${COMP_WORDS[COMP_CWORD]}"
  candidates=(--refetch --lineup-only --game-index contender contenders challenger challengers backup reserve)
  for nation_dir in "$_efootball_completion_root"/nations/*/*; do
    [ -d "$nation_dir" ] || continue
    nation="${nation_dir##*/}"
    candidates+=("$nation")
  done
  COMPREPLY=($(compgen -W "${candidates[*]}" -- "$current"))
}

complete -F _efootball_run_workflow_complete ./run_workflow.sh run_workflow.sh
