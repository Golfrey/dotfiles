# Restart CLIProxyAPI when a shell-invoked brew upgrade changes its active keg.
# `command brew ...` and scripts that do not source this file bypass the hook.
function brew() {
  if [[ "${1-}" != upgrade ]]; then
    command brew "$@"
    return $?
  fi

  local brew_prefix="${HOMEBREW_PREFIX:-}"
  local before='' after=''
  local upgrade_status=0 restart_status=0
  if [[ -z "$brew_prefix" ]]; then
    brew_prefix=$(command brew --prefix 2>/dev/null) || brew_prefix=''
  fi
  if [[ -n "$brew_prefix" ]]; then
    before=$(readlink "$brew_prefix/opt/cliproxyapi" 2>/dev/null) || before=''
  fi

  command brew "$@" || upgrade_status=$?

  if [[ -n "$before" ]]; then
    after=$(readlink "$brew_prefix/opt/cliproxyapi" 2>/dev/null) || after=''
    if [[ -n "$after" && "$after" != "$before" && -x "$brew_prefix/opt/cliproxyapi/bin/cliproxyapi" ]]; then
      print -r -- '==> CLIProxyAPI was upgraded; restarting its Homebrew service...'
      command brew services restart cliproxyapi || restart_status=$?
      if (( restart_status != 0 )); then
        print -u2 -r -- 'CLIProxyAPI restart failed. Retry with: brew services restart cliproxyapi'
      fi
    fi
  fi

  # A later formula can fail after CLIProxyAPI upgraded; still restart it above,
  # then preserve the upgrade failure for callers.
  if (( upgrade_status != 0 )); then
    return "$upgrade_status"
  fi
  return "$restart_status"
}
