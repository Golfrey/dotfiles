# Git worktree helpers for zsh.
#
# Commands:
#   new_worktree <name> [base-ref]  Create ../<name> from base-ref (default: origin/main).
#   rm_worktree [-f|--force] <name|path>
#                                  Remove a worktree, prune metadata, and delete the
#                                  matching branch when it is named after the worktree.

_worktree_primary_root() {
  emulate -L zsh

  command git worktree list --porcelain 2>/dev/null | command awk '
    /^worktree / {
      sub(/^worktree /, "")
      print
      exit
    }
  '
}

_worktree_target_path() {
  emulate -L zsh

  local target="$1"
  if [[ "$target" == "." ]]; then
    command git rev-parse --show-toplevel 2>/dev/null
    return $?
  fi

  if [[ "$target" == /* || "$target" == ./* || "$target" == ../* || "$target" == *"/"* ]]; then
    print -r -- "${target:A}"
    return 0
  fi

  local primary_root
  primary_root="$(_worktree_primary_root)" || return 1
  [[ -n "$primary_root" ]] || return 1

  print -r -- "${primary_root:h}/${target}"
}

_worktree_branch_for_path() {
  emulate -L zsh

  local target_path="$1"
  local wt_path="" wt_branch="" line

  while IFS= read -r line; do
    if [[ "$line" == worktree\ * ]]; then
      if [[ -n "$wt_path" && "$wt_path" == "$target_path" ]]; then
        print -r -- "$wt_branch"
        return 0
      fi
      wt_path="${line#worktree }"
      wt_branch=""
    elif [[ "$line" == branch\ refs/heads/* ]]; then
      wt_branch="${line#branch refs/heads/}"
    elif [[ -z "$line" ]]; then
      if [[ -n "$wt_path" && "$wt_path" == "$target_path" ]]; then
        print -r -- "$wt_branch"
        return 0
      fi
      wt_path=""
      wt_branch=""
    fi
  done < <(command git worktree list --porcelain 2>/dev/null)

  if [[ -n "$wt_path" && "$wt_path" == "$target_path" ]]; then
    print -r -- "$wt_branch"
  fi
}

new_worktree() {
  emulate -L zsh

  if (( $# < 1 || $# > 2 )); then
    print -u2 -- "usage: new_worktree <name> [base-ref]"
    print -u2 -- "example: new_worktree my-feature origin/main"
    return 2
  fi

  local worktree_name="$1"
  local base_ref="${2:-origin/main}"

  if [[ -z "$worktree_name" || "$worktree_name" == "." || "$worktree_name" == ".." || "$worktree_name" == *"/"* ]]; then
    print -u2 -- "new_worktree: name must be a single folder name, not a path: $worktree_name"
    return 2
  fi

  command git check-ref-format --branch "$worktree_name" >/dev/null 2>&1 || {
    print -u2 -- "new_worktree: '$worktree_name' is not a valid git branch name."
    return 2
  }

  command git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    print -u2 -- "new_worktree: run this from inside a git repository."
    return 1
  }

  local repo_root primary_root worktree_path
  repo_root="$(command git rev-parse --show-toplevel)" || return $?
  primary_root="$(_worktree_primary_root)" || return $?
  [[ -n "$primary_root" ]] || {
    print -u2 -- "new_worktree: could not find the primary worktree root."
    return 1
  }

  worktree_path="${primary_root:h}/${worktree_name}"

  if [[ -e "$worktree_path" ]]; then
    print -u2 -- "new_worktree: target already exists: $worktree_path"
    return 1
  fi

  command git -C "$repo_root" rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null || {
    print -u2 -- "new_worktree: base ref not found: $base_ref"
    print -u2 -- "new_worktree: fetch it first or pass another base ref."
    return 1
  }

  if command git -C "$repo_root" show-ref --verify --quiet "refs/heads/$worktree_name"; then
    print -r -- "Adding worktree for existing branch '$worktree_name' at $worktree_path"
    command git -C "$repo_root" worktree add "$worktree_path" "$worktree_name" || return $?
  else
    print -r -- "Creating worktree '$worktree_name' from '$base_ref' at $worktree_path"
    command git -C "$repo_root" worktree add -b "$worktree_name" "$worktree_path" "$base_ref" || return $?
  fi

  print -r -- "$worktree_path"
}

rm_worktree() {
  emulate -L zsh

  local force=0
  while (( $# > 0 )); do
    case "$1" in
      -f|--force)
        force=1
        shift
        ;;
      --)
        shift
        break
        ;;
      -*)
        print -u2 -- "usage: rm_worktree [-f|--force] <name|path>"
        return 2
        ;;
      *)
        break
        ;;
    esac
  done

  if (( $# != 1 )); then
    print -u2 -- "usage: rm_worktree [-f|--force] <name|path>"
    return 2
  fi

  command git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    print -u2 -- "rm_worktree: run this from inside a git repository."
    return 1
  }

  local repo_root primary_root target target_path current_root branch_name target_name
  repo_root="$(command git rev-parse --show-toplevel)" || return $?
  primary_root="$(_worktree_primary_root)" || return $?
  [[ -n "$primary_root" ]] || {
    print -u2 -- "rm_worktree: could not find the primary worktree root."
    return 1
  }

  target="$1"
  target_path="$(_worktree_target_path "$target")" || {
    print -u2 -- "rm_worktree: could not resolve target path: $target"
    return 1
  }
  current_root="$repo_root"

  if [[ "$target_path" == "$current_root" ]]; then
    if [[ "$current_root" == "$primary_root" ]]; then
      print -u2 -- "rm_worktree: cannot remove the primary worktree: $target_path"
      return 1
    fi

    print -r -- "rm_worktree: moving from current worktree to primary worktree: $primary_root"
    builtin cd "$primary_root" || return $?
    repo_root="$primary_root"
  fi

  branch_name="$(_worktree_branch_for_path "$target_path")"
  target_name="${target_path:t}"

  local remove_args=(worktree remove)
  (( force )) && remove_args+=(--force)
  remove_args+=("$target_path")

  if [[ -e "$target_path" ]]; then
    command git -C "$repo_root" "${remove_args[@]}" || return $?
  else
    print -r -- "rm_worktree: target path is missing; pruning stale worktree metadata for $target_path"
  fi

  command git -C "$repo_root" worktree prune || return $?

  if [[ -n "$branch_name" && "$branch_name" == "$target_name" ]]; then
    if (( force )); then
      command git -C "$repo_root" branch -D -- "$branch_name" || return $?
    else
      command git -C "$repo_root" branch -d -- "$branch_name" || {
        print -u2 -- "rm_worktree: worktree removed, but branch '$branch_name' was not deleted."
        print -u2 -- "rm_worktree: merge it first, delete it manually, or rerun with --force."
        return 1
      }
    fi
  elif [[ -n "$branch_name" ]]; then
    print -r -- "rm_worktree: kept branch '$branch_name' because it does not match worktree folder '$target_name'."
  fi

  print -r -- "Removed worktree: $target_path"
}
