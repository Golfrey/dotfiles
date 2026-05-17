---
name: pi-models
description: Fetches live model IDs from the user's configured Pi model endpoints in ~/.pi/agent/models.json, especially OpenAI-compatible /v1/models endpoints, and enriches them with model details from https://pi.dev/models. Use when the user asks what models are currently available, wants endpoint model lists, or needs Pi model metadata like context window, max tokens, input modalities, reasoning, provider, and cost.
---

# Pi Models

Use this skill when the user asks to list, inspect, compare, or refresh the models available through Pi-configured endpoints.

The workflow combines two sources:

1. **Live endpoint list** from the user's Pi config: read `~/.pi/agent/models.json`, take each provider `baseUrl`, and call `<baseUrl>/models` with the configured auth.
2. **Catalog details** from `https://pi.dev/models`: parse the Pi model catalog and model detail pages for context window, max output tokens, input modalities, reasoning support, costs, provider/API, and copyable Pi model config JSON.

Never print API keys, Authorization headers, or resolved secret values.

## Helper script

This skill includes a zero-dependency helper script:

```bash
./scripts/pi-models.py --help
```

When using it from the agent, resolve the path relative to this skill directory. In this chezmoi repo that is usually:

```bash
python3 home/dot_pi/agent/skills/pi-models/scripts/pi-models.py <command>
```

After chezmoi applies the dotfiles, the installed skill path is usually:

```bash
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py <command>
```

## Common commands

### List live models from configured Pi endpoints

```bash
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py live
```

This reads `~/.pi/agent/models.json`. For each provider with `baseUrl`, it fetches `<baseUrl>/models`. For OpenAI-compatible endpoints this is normally `/v1/models` because `baseUrl` often already ends with `/v1`.

Useful options:

```bash
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py live --format json
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py live --provider cliproxyapi
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py live --config /path/to/models.json
```

### Enrich live endpoint models with pi.dev metadata

```bash
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py enrich
```

This is the default choice when the user asks for "all models we have right now" with details. It returns live endpoint model IDs plus matching `https://pi.dev/models` details when available.

Useful options:

```bash
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py enrich --format json
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py enrich --provider cliproxyapi
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py enrich --pi-provider azure-openai-responses
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py enrich --no-details
```

Use `--no-details` if a quick answer is enough; it only parses the catalog table and avoids fetching one detail page per model.

The pi.dev catalog table is cached at `~/.cache/pi-models/catalog.json` for one hour. Use `--refresh-catalog` to force a fresh fetch, or `--cache-ttl 0` to avoid using a warm cache.

### Search the pi.dev catalog

```bash
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py catalog --query gpt-5.5
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py catalog --pi-provider openai --limit 20
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py catalog --id gpt-5.5 --format json
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py catalog --query gpt-5.5 --refresh-catalog
```

The catalog may include many providers and hundreds of models. Use `--query`, `--pi-provider`, `--id`, and `--limit` to keep output concise.

### Fetch details for one model

```bash
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py details gpt-5.5
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py details gpt-5.5 --pi-provider azure-openai-responses --config-json
python3 ~/.pi/agent/skills/pi-models/scripts/pi-models.py details --url https://pi.dev/models/azure-openai-responses/gpt-5-5
```

Use `--config-json` when the user wants a ready-to-copy Pi `models.json` snippet.

## Provider matching notes

A model ID can appear under many pi.dev providers. The script prefers providers in this order unless overridden:

1. `azure-openai-responses`
2. `openai-responses`
3. `openai`
4. `openai-codex`
5. `opencode`
6. `github-copilot`
7. `cloudflare-ai-gateway`
8. `vercel-ai-gateway`
9. `anthropic`
10. `google`
11. `google-vertex`

Override with:

```bash
--pi-provider <provider>
--provider-preference provider1,provider2,...
```

## Security and secret handling

- Do not echo API keys or headers.
- The script resolves Pi `apiKey`/`headers` values the same way Pi configs usually work: literal values, environment variable names, and shell commands prefixed with `!`.
- Shell-command secrets are executed by default so the endpoint request can authenticate. If the user only wants static inspection or you do not want to execute config commands, pass:

```bash
--no-exec-api-key-commands
```

## Answering style

For user-facing answers:

- State which endpoint(s) were fetched, but never include secrets.
- Distinguish **live endpoint availability** from **static local configuration** if both are relevant.
- If a live model has no pi.dev match, say `no pi.dev match` rather than guessing details.
- Include compact tables for lists.
- For a single model, include: model ID, endpoint provider, pi.dev provider, input modalities, reasoning, context window, max tokens, and costs.
