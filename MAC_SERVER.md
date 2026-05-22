# Mac mini server manual setup

This note covers the manual steps for setting up a Mac mini as an always-on server with this chezmoi repo.

The automated baseline is in:

```text
home/run_once_after_configure-macos-server.sh.tmpl
```

It runs only when the chezmoi profile is `server`.

## 1. Initialize chezmoi with the server profile

On the Mac mini:

```sh
chezmoi init git@github.com:Golfrey/dotfiles.git --promptChoice profile=server --apply
```

If SSH keys are not set up yet, either add a GitHub SSH key first or use HTTPS if the repo is accessible:

```sh
chezmoi init https://github.com/Golfrey/dotfiles.git --promptChoice profile=server --apply
```

Alternatively, clone and run the repository bootstrap script:

```sh
git clone git@github.com:Golfrey/dotfiles.git ~/.local/share/chezmoi
~/.local/share/chezmoi/install.sh server
```

`install.sh` runs `chezmoi init --apply` by default. If you omit `server`, the script prompts for a profile interactively. If Bitwarden is not ready yet, use `--no-apply`, prepare Bitwarden, then apply. You can also run:

```sh
~/.local/share/chezmoi/install.sh --profile server
CHEZMOI_PROFILE=server ~/.local/share/chezmoi/install.sh
```

To initialize only and review the diff before applying, pass `--no-apply`:

```sh
~/.local/share/chezmoi/install.sh server --no-apply
chezmoi diff
chezmoi apply
```

Or, if already initialized, regenerate the local chezmoi config and choose `server`:

```sh
chezmoi init --promptChoice profile=server --apply
```

Check the active profile:

```sh
chezmoi data | grep '"profile"'
```

Optional: set a hostname before applying:

```sh
export CHEZMOI_SERVER_HOSTNAME=macmini
```

If you initialized with `--no-apply`, apply after Bitwarden is ready:

```sh
chezmoi diff
chezmoi apply
```

The server setup script configures:

- no system sleep;
- display sleep after 1 minute;
- no disk sleep;
- wake for network access;
- automatic restart after power failure;
- SSH remote login;
- macOS firewall;
- firewall stealth mode;
- automatic security/system data updates;
- no automatic full macOS upgrades.

## 2. Install packages

After `chezmoi apply`, install the server Homebrew bundle:

```sh
HOMEBREW_NO_AUTO_UPDATE=1 brew bundle --global --no-upgrade --jobs=auto
```

`HOMEBREW_NO_AUTO_UPDATE=1` avoids a slow Homebrew metadata update. `--no-upgrade` keeps setup focused on missing packages instead of upgrading everything already installed. `--jobs=auto` lets Homebrew install independent formulae in parallel.

For the `server` profile, the Brewfile includes server/headless packages such as:

- `cliproxyapi`
- `transmission-cli`

Tailscale is intentionally not installed by Homebrew. Install the official GUI app manually from the Tailscale website.

## 3. Tailscale

Install Tailscale manually from the official website:

```text
https://tailscale.com/download/mac
```

Use the GUI app to log in and authorize the Mac mini.

Recommended:

- enable MagicDNS in the Tailscale admin console;
- give the Mac mini a stable Tailscale machine name, for example `home-server-m4` or `macmini`;
- enable Tailscale SSH if desired;
- use Tailscale instead of exposing SSH to the public internet.

## 4. FileVault decision

Decide this manually.

### FileVault off

Pros:

- best unattended recovery after reboot or power loss;
- services can start without physical unlock.

Cons:

- weaker protection if the Mac mini is stolen.

### FileVault on

Pros:

- better protection for data at rest.

Cons:

- after reboot, power loss, or OS update, the machine may need manual unlock before services are available.

For a home server where unattended recovery matters, FileVault off is often more practical. If the machine stores sensitive data, consider FileVault on and accept the manual unlock requirement.

## 5. Screen Sharing

The script enables SSH, but not GUI remote access.

If you want GUI access:

```text
System Settings → General → Sharing → Screen Sharing
```

Enable `Screen Sharing`.

For most server work, SSH and Tailscale are preferred.

## 6. Network identity

Recommended:

1. Set a stable hostname, either through `CHEZMOI_SERVER_HOSTNAME` before applying or manually:

   ```sh
   sudo scutil --set HostName macmini
   sudo scutil --set LocalHostName macmini
   sudo scutil --set ComputerName macmini
   sudo dscacheutil -flushcache
   ```

2. Reserve a static DHCP lease in your router.

3. Prefer Tailscale MagicDNS names for remote access.

## 7. Software updates

The script configures macOS to:

- check for updates;
- download updates;
- install security responses/system files;
- not automatically install full macOS updates.

Manual full macOS updates are recommended so you can control downtime.

Check manually:

```text
System Settings → General → Software Update
```

## 8. Power/display behavior

The intended server power settings are:

```sh
sudo pmset -a sleep 0
sudo pmset -a displaysleep 1
sudo pmset -a disksleep 0
sudo pmset -a womp 1
sudo pmset -a autorestart 1
```

Check current settings:

```sh
pmset -g
```

Meaning:

- the Mac does not sleep;
- the display output turns off after 1 minute;
- disks do not sleep;
- the Mac can wake for network access;
- the Mac restarts after power loss.

## 9. Firewall

The script enables the macOS application firewall and stealth mode.

Review manually:

```text
System Settings → Network → Firewall
```

If using Tailscale, avoid exposing services directly to the public internet unless necessary.

## 10. Bitwarden secrets

Some chezmoi templates use Bitwarden, for example Pi/opencode API keys.

Before applying secret-backed templates on a fresh server:

```sh
brew install bitwarden-cli
bw login
export BW_SESSION="$(bw unlock --raw)"
chezmoi apply
```

After these dotfiles are applied, use `bw-unlock` instead. It logs in if needed,
unlocks the vault, exports `BW_SESSION` for the current shell, and saves the
session token in the macOS Keychain for new zsh sessions. Use `bw-session` to
inspect the cache and `bw-lock` or `bw-session-clear` to remove it.

The Bitwarden item currently used for CliProxyAPI is:

```text
CliProxyAPI Key
```

## 11. Services

Use Homebrew services or launchd for long-running services.

Check Homebrew services:

```sh
brew services list
```

Start a Homebrew service:

```sh
brew services start <service>
```

### CPA Usage Keeper

For the `server` profile, chezmoi manages CPA Usage Keeper as an external release package from:

```text
https://github.com/Willxup/cpa-usage-keeper
```

Managed paths:

```text
~/.local/share/cpa-usage-keeper
~/.config/cpa-usage-keeper/env
~/.local/bin/cpa-usage-keeper
~/Library/LaunchAgents/com.golfrey.cpa-usage-keeper.plist
```

Before applying, unlock Bitwarden or provide the key directly:

```sh
bw-unlock
# or, before bw-unlock has been installed by these dotfiles:
export BW_SESSION="$(bw unlock --raw)"
# or:
export CPA_USAGE_KEEPER_CPA_MANAGEMENT_KEY="..."
```

The env file reads the CPA management key from the Bitwarden item `CliProxyAPI Management Key` unless `CPA_USAGE_KEEPER_CPA_MANAGEMENT_KEY` is set while applying chezmoi.

After `chezmoi apply`, the LaunchAgent should be loaded automatically. Check it with:

```sh
launchctl print gui/$(id -u)/com.golfrey.cpa-usage-keeper
```

Open the dashboard at:

```text
https://home-server-m4.taila3a41d.ts.net:8080
```

Avoid relying on a GUI login session for server processes where possible.

## 12. Quick checklist

- [ ] Initialize chezmoi with `profile=server`.
- [ ] Optionally set `CHEZMOI_SERVER_HOSTNAME`.
- [ ] Unlock Bitwarden CLI if applying secret-backed templates.
- [ ] Run `chezmoi apply`.
- [ ] Run `HOMEBREW_NO_AUTO_UPDATE=1 brew bundle --global --no-upgrade --jobs=auto`.
- [ ] Install Tailscale GUI from the official website.
- [ ] Log in to Tailscale and enable Tailscale SSH if desired.
- [ ] Decide FileVault on/off.
- [ ] Enable Screen Sharing only if GUI remote access is needed.
- [ ] Reserve static DHCP lease in router.
- [ ] Verify power settings with `pmset -g`.
- [ ] Verify SSH access from another machine.
