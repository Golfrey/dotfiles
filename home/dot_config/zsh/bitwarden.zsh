# Bitwarden CLI session helpers for zsh.
#
# Stores the Bitwarden CLI session token in macOS Keychain so new terminal
# sessions can reuse it without retyping the master password.
#
# Commands:
#   bw-unlock [bw login args...]  Log in if needed, unlock, cache session.
#   bw-login-session [...]        Alias for bw-unlock.
#   bw-session                    Show BW_SESSION/cache status.
#   bw-lock [bw lock args...]     Lock vault and remove cached session.
#   bw-logout [bw logout args...] Log out and remove cached session.
#   bw-session-clear              Remove cached session and unset BW_SESSION.
#
# Security: the cached token grants vault access until `bw lock`, `bw logout`,
# or Bitwarden invalidates it. It is not your master password.

(( $+commands[bw] )) || return 0

typeset -g BW_SESSION_KEYCHAIN_SERVICE="${BW_SESSION_KEYCHAIN_SERVICE:-bitwarden-cli-session}"
typeset -g BW_SESSION_KEYCHAIN_ACCOUNT="${BW_SESSION_KEYCHAIN_ACCOUNT:-${USER:-default}}"

_bw_session_json_status() {
  emulate -L zsh

  local session_token="${1:-}"
  local output bw_state

  if [[ -n "$session_token" ]]; then
    output="$(BW_SESSION="$session_token" command bw status 2>/dev/null)" || return 1
  else
    output="$(command bw status 2>/dev/null)" || return 1
  fi

  if (( $+commands[jq] )); then
    bw_state="$(printf '%s\n' "$output" | command jq -r '.status // empty' 2>/dev/null)" || bw_state=""
  else
    case "$output" in
      *'"status":"unlocked"'*|*'"status": "unlocked"'*) bw_state="unlocked" ;;
      *'"status":"locked"'*|*'"status": "locked"'*) bw_state="locked" ;;
      *'"status":"unauthenticated"'*|*'"status": "unauthenticated"'*) bw_state="unauthenticated" ;;
      *) bw_state="" ;;
    esac
  fi

  [[ -n "$bw_state" ]] || return 1
  print -r -- "$bw_state"
}

_bw_session_keychain_read() {
  emulate -L zsh

  (( $+commands[security] )) || return 1
  command security find-generic-password \
    -a "$BW_SESSION_KEYCHAIN_ACCOUNT" \
    -s "$BW_SESSION_KEYCHAIN_SERVICE" \
    -w 2>/dev/null
}

_bw_session_keychain_write() {
  emulate -L zsh

  local session_token="$1"
  [[ -n "$session_token" ]] || return 1
  (( $+commands[security] )) || return 1

  command security add-generic-password -U \
    -a "$BW_SESSION_KEYCHAIN_ACCOUNT" \
    -s "$BW_SESSION_KEYCHAIN_SERVICE" \
    -l "Bitwarden CLI BW_SESSION" \
    -w "$session_token" >/dev/null
}

_bw_session_keychain_delete() {
  emulate -L zsh

  (( $+commands[security] )) || return 0
  command security delete-generic-password \
    -a "$BW_SESSION_KEYCHAIN_ACCOUNT" \
    -s "$BW_SESSION_KEYCHAIN_SERVICE" >/dev/null 2>&1 || true
}

_bw_session_restore() {
  emulate -L zsh

  [[ -n "${BW_SESSION:-}" ]] && return 0
  (( $+commands[security] )) || return 0

  local session_token bw_state
  session_token="$(_bw_session_keychain_read)" || return 0
  [[ -n "$session_token" ]] || return 0

  bw_state="$(_bw_session_json_status "$session_token" 2>/dev/null)" || {
    _bw_session_keychain_delete
    return 0
  }

  if [[ "$bw_state" == "unlocked" ]]; then
    export BW_SESSION="$session_token"
  else
    _bw_session_keychain_delete
  fi
}

bw-unlock() {
  emulate -L zsh

  local bw_state session_token

  if [[ -n "${BW_SESSION:-}" ]]; then
    bw_state="$(_bw_session_json_status "$BW_SESSION" 2>/dev/null)" || bw_state=""
    if [[ "$bw_state" == "unlocked" ]]; then
      _bw_session_keychain_write "$BW_SESSION" >/dev/null 2>&1 || true
      print -r -- "Bitwarden CLI is already unlocked; BW_SESSION is cached for new shells."
      return 0
    fi
  fi

  bw_state="$(_bw_session_json_status 2>/dev/null)" || bw_state=""
  if [[ "$bw_state" == "unauthenticated" ]]; then
    print -r -- "Bitwarden CLI is not logged in; running 'bw login' first."
    command bw login "$@" || return $?
  elif (( $# > 0 )); then
    print -u2 -- "bw-unlock: Bitwarden is already logged in; ignoring login arguments: $*"
  fi

  session_token="$(command bw unlock --raw)" || return $?
  [[ -n "$session_token" ]] || {
    print -u2 -- "bw-unlock: bw unlock returned an empty session."
    return 1
  }

  export BW_SESSION="$session_token"

  if _bw_session_keychain_write "$session_token"; then
    print -r -- "Bitwarden CLI unlocked; BW_SESSION saved in macOS Keychain for new shells."
  else
    print -r -- "Bitwarden CLI unlocked for this shell; macOS Keychain was unavailable, so the session was not cached."
  fi
}

bw-login-session() {
  bw-unlock "$@"
}

bw-session() {
  emulate -L zsh

  local bw_state cached="no"
  bw_state="$(_bw_session_json_status "${BW_SESSION:-}" 2>/dev/null)" || bw_state="unknown"

  if (( $+commands[security] )) && _bw_session_keychain_read >/dev/null; then
    cached="yes"
  fi

  print -r -- "bw status: ${bw_state}"
  if [[ -n "${BW_SESSION:-}" ]]; then
    print -r -- "BW_SESSION: set in this shell"
  else
    print -r -- "BW_SESSION: not set in this shell"
  fi
  print -r -- "Keychain cache: ${cached}"
}

bw-session-clear() {
  emulate -L zsh

  _bw_session_keychain_delete
  unset BW_SESSION
  print -r -- "Bitwarden cached session removed; BW_SESSION unset."
}

bw-lock() {
  emulate -L zsh

  local rc=0
  command bw lock "$@" || rc=$?
  _bw_session_keychain_delete
  unset BW_SESSION

  if (( rc == 0 )); then
    print -r -- "Bitwarden CLI locked; cached BW_SESSION removed."
  fi
  return $rc
}

bw-logout() {
  emulate -L zsh

  local rc=0
  command bw logout "$@" || rc=$?
  _bw_session_keychain_delete
  unset BW_SESSION

  if (( rc == 0 )); then
    print -r -- "Bitwarden CLI logged out; cached BW_SESSION removed."
  fi
  return $rc
}

if [[ -z "${BW_SESSION_DISABLE_AUTO_RESTORE:-}" ]]; then
  _bw_session_restore
fi
