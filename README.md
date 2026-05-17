# dotfiles

Managed with [chezmoi](https://www.chezmoi.io/).

## Repository layout

This repo uses `.chezmoiroot`:

```text
.chezmoiroot  -> home
```

The chezmoi source state lives under `home/`, mirroring files that should be applied into `$HOME`.
Top-level files such as `README.md`, `MAC_SERVER.md`, and `install.sh` are repository/bootstrap files and are not applied to `$HOME`.

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

Or let `install.sh` install chezmoi into `~/.local/bin` if it is missing.

### 3. Init this repo

Direct chezmoi init over SSH:

```sh
chezmoi init git@github.com:Golfrey/dotfiles.git --promptChoice profile=personal
chezmoi init git@github.com:Golfrey/dotfiles.git --promptChoice profile=server
```

If SSH keys are not set up and the repo is accessible over HTTPS:

```sh
chezmoi init https://github.com/Golfrey/dotfiles.git --promptChoice profile=server
```

Alternatively, clone the repo and run the bootstrap script from the checkout:

```sh
git clone git@github.com:Golfrey/dotfiles.git ~/.local/share/chezmoi
CHEZMOI_PROFILE=server ~/.local/share/chezmoi/install.sh
```

`install.sh` intentionally runs `chezmoi init` without applying by default, so you can review the diff first. To apply immediately, pass `--apply`:

```sh
CHEZMOI_PROFILE=server ~/.local/share/chezmoi/install.sh --apply
```

The profile is stored in the machine-local chezmoi config generated from `home/.chezmoi.toml.tmpl`.

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

`home/dot_Brewfile.tmpl` renders to `~/.Brewfile`. Homebrew Bundle then installs packages from that file.

## Homebrew packages

The global Homebrew bundle is managed by:

```text
home/dot_Brewfile.tmpl
```

After installing a new Homebrew package manually, add it to `home/dot_Brewfile.tmpl` so new machines get it too.

Render/test the Brewfile for a profile:

```sh
printf '{"profile":"personal"}' >/tmp/chezmoi-data.json
chezmoi execute-template --override-data-file /tmp/chezmoi-data.json < home/dot_Brewfile.tmpl
```

## Externals

Oh My Zsh and Powerlevel10k are managed by chezmoi externals in:

```text
home/.chezmoiexternal.toml
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
home/dot_pi/agent/models.json.tmpl
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
