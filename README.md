# dotfiles

Managed with [chezmoi](https://www.chezmoi.io/).

## Daily workflow

```sh
chezmoi status
chezmoi diff
chezmoi apply
```

Edit a managed file:

```sh
chezmoi edit ~/.zshrc
chezmoi diff
chezmoi apply
```

Add a new file:

```sh
chezmoi add ~/.config/example/config
chezmoi cd
git status
```

## New machine

### 1. Install Homebrew

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Install chezmoi

```sh
brew install chezmoi
```

### 3. Init this repo

Interactive setup:

```sh
chezmoi init <repo-url>
```

Non-interactive setup:

```sh
chezmoi init <repo-url> --promptChoice profile=personal
chezmoi init <repo-url> --promptChoice profile=server
```

The profile is stored in the machine-local chezmoi config generated from `.chezmoi.toml.tmpl`.

Profiles:

- `personal`: personal workstation package set
- `work`: work workstation package set, without personal-only apps
- `server`: headless/server package set
- `minimal`: core CLI tools only

Check the current profile:

```sh
chezmoi data | grep '"profile"'
```

### 4. Prepare Bitwarden CLI if applying secret-backed templates

Some templates read secrets from Bitwarden. Before applying those templates on a fresh machine:

```sh
brew install bitwarden-cli
bw login
export BW_SESSION="$(bw unlock --raw)"
```

### 5. Apply dotfiles and install packages

```sh
chezmoi diff
chezmoi apply
brew bundle --global
```

`dot_Brewfile.tmpl` renders to `~/.Brewfile`. Homebrew Bundle then installs packages from that file.

## Homebrew packages

The global Homebrew bundle is managed by:

```text
dot_Brewfile.tmpl
```

After installing a new Homebrew package manually, add it to `dot_Brewfile.tmpl` so new machines get it too.

Render/test the Brewfile for a profile:

```sh
printf '{"profile":"personal"}' >/tmp/chezmoi-data.json
chezmoi execute-template --override-data-file /tmp/chezmoi-data.json < dot_Brewfile.tmpl
```

## Externals

Oh My Zsh and Powerlevel10k are managed by chezmoi externals in:

```text
.chezmoiexternal.toml
```

They refresh weekly:

```toml
refreshPeriod = "168h"
```

Force-refresh externals:

```sh
chezmoi apply --refresh-externals=always
```

## Pi / CliproxyAPI

Pi model config is managed in:

```text
dot_pi/agent/models.json.tmpl
```

It uses the MagicDNS host:

```text
http://home-server-m4:8317/v1
```

## Mac mini server

Manual server setup notes are in:

```text
MAC_SERVER.md
```

Use the `server` chezmoi profile for Mac mini/server machines.

## Notes

Do not add secrets, `.env` files, SSH keys, app tokens, or dependency folders unless encryption is configured first.
