#!/bin/sh

set -eu

usage() {
  cat <<EOF
Usage: ${0##*/} [profile] [--no-apply] [chezmoi init flags]
       ${0##*/} --profile profile [--no-apply] [chezmoi init flags]
       CHEZMOI_PROFILE=profile ${0##*/} [--no-apply] [chezmoi init flags]

Profiles: personal, work, server, minimal

By default this runs 'chezmoi init --apply'. Use --no-apply to only initialize
chezmoi so you can review the diff before applying.

Examples:
  ${0##*/} server
  ${0##*/} --profile server --no-apply
  CHEZMOI_PROFILE=server ${0##*/}
EOF
}

is_valid_profile() {
  case "$1" in
    personal|work|server|minimal) return 0 ;;
    *) return 1 ;;
  esac
}

prompt_for_profile() {
  exec 9>&2
  if ! exec 2>/dev/null 3</dev/tty 4>/dev/tty; then
    exec 2>&9
    exec 9>&-
    cat >&2 <<EOF
No profile was provided, and this shell has no usable TTY for a prompt.

Run one of:
  CHEZMOI_PROFILE=server ${0##*/}
  ${0##*/} server

Profiles: personal, work, server, minimal
EOF
    exit 1
  fi
  exec 2>&9
  exec 9>&-

  printf '\nChoose chezmoi profile:\n' >&4
  printf '  1) personal  - personal workstation package set\n' >&4
  printf '  2) work      - work workstation package set\n' >&4
  printf '  3) server    - headless/server package set\n' >&4
  printf '  4) minimal   - core CLI tools only\n' >&4

  while :; do
    printf 'Profile [1/personal]: ' >&4
    IFS= read -r choice <&3 || choice=

    case "$choice" in
      ''|1|p|personal) profile=personal; break ;;
      2|w|work) profile=work; break ;;
      3|s|server) profile=server; break ;;
      4|m|minimal) profile=minimal; break ;;
      q|quit|exit)
        printf 'Aborted.\n' >&4
        exec 3<&-
        exec 4>&-
        exit 1
        ;;
      *)
        printf 'Invalid profile: %s\n' "$choice" >&4
        printf 'Enter 1, 2, 3, 4, personal, work, server, or minimal.\n' >&4
        ;;
    esac
  done

  exec 3<&-
  exec 4>&-
}

profile="${CHEZMOI_PROFILE:-}"
apply=1
can_take_bare_profile=1

# Parse bootstrap-script options while preserving any remaining chezmoi init
# flags exactly in "$@". A bare profile is accepted only before passthrough
# chezmoi flags, avoiding accidental consumption of flag values such as
# '--branch server'.
argc=$#
while [ "$argc" -gt 0 ]; do
  arg=$1
  shift
  argc=$((argc - 1))

  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    --profile)
      if [ "$argc" -lt 1 ]; then
        echo "--profile requires an argument." >&2
        usage >&2
        exit 2
      fi
      profile=$1
      shift
      argc=$((argc - 1))
      can_take_bare_profile=0
      ;;
    --profile=*)
      profile=${arg#--profile=}
      can_take_bare_profile=0
      ;;
    -a|--apply|--apply=true)
      apply=1
      ;;
    --no-apply|--apply=false)
      apply=0
      ;;
    personal|work|server|minimal)
      if [ "$can_take_bare_profile" -eq 1 ]; then
        profile=$arg
        can_take_bare_profile=0
      else
        set -- "$@" "$arg"
      fi
      ;;
    --)
      set -- "$@" "$arg"
      while [ "$argc" -gt 0 ]; do
        arg=$1
        shift
        argc=$((argc - 1))
        set -- "$@" "$arg"
      done
      break
      ;;
    *)
      case "$arg" in
        -*)
          set -- "$@" "$arg"
          can_take_bare_profile=0
          ;;
        *)
          if [ "$can_take_bare_profile" -eq 1 ]; then
            echo "Invalid profile: $arg" >&2
            echo "Valid profiles: personal, work, server, minimal" >&2
            exit 2
          fi
          set -- "$@" "$arg"
          ;;
      esac
      ;;
  esac
done

if [ -z "$profile" ]; then
  prompt_for_profile
fi

if ! is_valid_profile "$profile"; then
  echo "Invalid profile: $profile" >&2
  echo "Valid profiles: personal, work, server, minimal" >&2
  exit 2
fi

if command -v chezmoi >/dev/null 2>&1; then
  chezmoi=chezmoi
else
  bin_dir="$HOME/.local/bin"
  chezmoi="$bin_dir/chezmoi"
  mkdir -p "$bin_dir"

  if command -v curl >/dev/null 2>&1; then
    sh -c "$(curl -fsLS https://get.chezmoi.io)" -- -b "$bin_dir"
  elif command -v wget >/dev/null 2>&1; then
    sh -c "$(wget -qO- https://get.chezmoi.io)" -- -b "$bin_dir"
  else
    echo "To install chezmoi, you must have curl or wget installed." >&2
    exit 1
  fi
fi

# POSIX way to get this script's directory.
script_dir="$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd -P)"

if [ "$apply" -eq 1 ]; then
  echo "Initializing and applying chezmoi with profile: $profile"
  exec "$chezmoi" init "--source=$script_dir" --promptChoice "profile=$profile" --apply "$@"
fi

echo "Initializing chezmoi with profile: $profile (--no-apply)"
exec "$chezmoi" init "--source=$script_dir" --promptChoice "profile=$profile" "$@"
