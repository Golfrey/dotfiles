#!/usr/bin/env python3
"""Fetch live Pi model IDs from configured endpoints and enrich them from pi.dev/models.

This script intentionally uses only the Python standard library so a Pi skill can run
it without extra setup.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PI_MODELS_URL = os.environ.get("PI_MODELS_CATALOG_URL", "https://pi.dev/models")
DEFAULT_CONFIG = Path(os.environ.get("PI_MODELS_CONFIG", "~/.pi/agent/models.json")).expanduser()
DEFAULT_CACHE_PATH = Path(os.environ.get("PI_MODELS_CACHE", "~/.cache/pi-models/catalog.json")).expanduser()
USER_AGENT = "pi-models-skill/1.0 (+https://pi.dev/models)"

# When multiple pi.dev providers expose the same model id, prefer the routes that
# tend to match the local CliProxy/Pi custom model configs best.
DEFAULT_PROVIDER_PREFERENCE = [
    "azure-openai-responses",
    "openai-responses",
    "openai",
    "openai-codex",
    "opencode",
    "github-copilot",
    "cloudflare-ai-gateway",
    "vercel-ai-gateway",
    "anthropic",
    "google",
    "google-vertex",
]


class PiModelsError(RuntimeError):
    pass


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<script\b.*?</script>", "", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<style\b.*?</style>", "", fragment, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "", fragment)
    return html.unescape(text).strip()


def parse_number(text: str) -> Optional[float]:
    text = html.unescape(text).strip()
    if not text or text in {"—", "-", "(none)", "none"}:
        return None
    text = text.replace("$", "").replace(",", "").strip()
    try:
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        return float(text)
    except ValueError:
        return None


def load_json_file(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise PiModelsError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PiModelsError(f"Invalid JSON in {path}: {exc}") from exc


def resolve_value(value: Any, *, execute_commands: bool = True) -> Optional[str]:
    """Resolve Pi models.json value syntax without printing secrets.

    Pi accepts literal values, environment variable names, and shell commands
    prefixed with '!'. The command form is useful but can execute arbitrary local
    code from models.json, so callers may disable it with --no-exec-api-key-commands.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    if value.startswith("!"):
        if not execute_commands:
            return None
        cmd = value[1:]
        try:
            return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError as exc:
            raise PiModelsError(f"API key/header command failed: {cmd!r} (exit {exc.returncode})") from exc
    if value in os.environ:
        return os.environ[value]
    return value


def resolve_headers(headers: Any, *, execute_commands: bool = True) -> Dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    resolved: Dict[str, str] = {}
    for key, value in headers.items():
        if value is None:
            continue
        resolved_value = resolve_value(value, execute_commands=execute_commands)
        if resolved_value is not None:
            resolved[str(key)] = resolved_value
    return resolved


def request_json_or_text(url: str, *, headers: Optional[Dict[str, str]] = None, timeout: float = 20) -> Tuple[int, str, str]:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
            return resp.status, resp.headers.get("content-type", ""), body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(exc.headers.get_content_charset() or "utf-8", errors="replace")
        return exc.code, exc.headers.get("content-type", ""), body
    except urllib.error.URLError as exc:
        raise PiModelsError(f"Failed to fetch {url}: {exc}") from exc


def models_endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/models"


def configured_providers(config_path: Path, provider_filter: Optional[set[str]], *, execute_commands: bool) -> List[Dict[str, Any]]:
    config = load_json_file(config_path)
    providers = config.get("providers")
    if not isinstance(providers, dict):
        raise PiModelsError(f"{config_path} does not contain a top-level 'providers' object")

    out: List[Dict[str, Any]] = []
    for provider_name, provider_config in providers.items():
        if provider_filter and provider_name not in provider_filter:
            continue
        if not isinstance(provider_config, dict):
            continue
        base_url = provider_config.get("baseUrl") or provider_config.get("baseURL")
        if not base_url:
            continue
        api_key = resolve_value(provider_config.get("apiKey"), execute_commands=execute_commands)
        headers = resolve_headers(provider_config.get("headers"), execute_commands=execute_commands)
        # For OpenAI-compatible /v1/models endpoints, Authorization: Bearer works.
        # A provider can set authHeader: false to suppress it.
        if api_key and provider_config.get("authHeader", True) is not False:
            headers.setdefault("Authorization", f"Bearer {api_key}")
        out.append(
            {
                "provider": provider_name,
                "baseUrl": str(base_url),
                "endpoint": models_endpoint(str(base_url)),
                "api": provider_config.get("api"),
                "headers": headers,
            }
        )
    return out


def extract_model_items(payload: Any) -> List[Dict[str, Any]]:
    """Normalize common model-list payloads to [{'id': ..., 'raw': ...}]."""
    if isinstance(payload, list):
        seq = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            seq = payload["data"]
        elif isinstance(payload.get("models"), list):
            seq = payload["models"]
        elif isinstance(payload.get("models"), dict):
            seq = [{"id": key, **(value if isinstance(value, dict) else {})} for key, value in payload["models"].items()]
        else:
            seq = []
    else:
        seq = []

    items: List[Dict[str, Any]] = []
    for item in seq:
        if isinstance(item, str):
            model_id = item
            raw = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
            raw = item
        else:
            continue
        if model_id:
            items.append({"id": str(model_id), "raw": raw})
    items.sort(key=lambda m: m["id"])
    return items


def fetch_live_models(config_path: Path, provider_filter: Optional[set[str]], *, timeout: float, execute_commands: bool) -> List[Dict[str, Any]]:
    providers = configured_providers(config_path, provider_filter, execute_commands=execute_commands)
    if not providers:
        raise PiModelsError(f"No providers with baseUrl found in {config_path}")

    results: List[Dict[str, Any]] = []
    for provider in providers:
        endpoint = provider["endpoint"]
        started = time.time()
        status, content_type, body = request_json_or_text(endpoint, headers=provider["headers"], timeout=timeout)
        elapsed_ms = round((time.time() - started) * 1000)
        if status < 200 or status >= 300:
            results.append(
                {
                    "provider": provider["provider"],
                    "api": provider.get("api"),
                    "baseUrl": provider["baseUrl"],
                    "endpoint": endpoint,
                    "ok": False,
                    "status": status,
                    "elapsedMs": elapsed_ms,
                    "error": strip_tags(body)[:500],
                    "models": [],
                }
            )
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            results.append(
                {
                    "provider": provider["provider"],
                    "api": provider.get("api"),
                    "baseUrl": provider["baseUrl"],
                    "endpoint": endpoint,
                    "ok": False,
                    "status": status,
                    "elapsedMs": elapsed_ms,
                    "error": f"Endpoint did not return JSON: {exc}",
                    "models": [],
                }
            )
            continue
        results.append(
            {
                "provider": provider["provider"],
                "api": provider.get("api"),
                "baseUrl": provider["baseUrl"],
                "endpoint": endpoint,
                "ok": True,
                "status": status,
                "elapsedMs": elapsed_ms,
                "models": extract_model_items(payload),
            }
        )
    return results


def parse_attrs(attr_text: str) -> Dict[str, str]:
    return {name: html.unescape(value) for name, value in re.findall(r'([\w:-]+)="([^"]*)"', attr_text)}


def parse_catalog(html_text: str, base_url: str = PI_MODELS_URL) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    row_re = re.compile(r'<tr\b(?=[^>]*data-model-row="true")(?P<attrs>[^>]*)>(?P<body>.*?)</tr>', re.I | re.S)
    link_re = re.compile(r'<a\b(?P<attrs>[^>]*)class="[^"]*models-model-link[^"]*"(?P<attrs2>[^>]*)>(?P<text>.*?)</a>', re.I | re.S)
    code_re = re.compile(r'<code>(.*?)</code>', re.I | re.S)
    td_re = re.compile(r'<td\b[^>]*>(.*?)</td>', re.I | re.S)

    for match in row_re.finditer(html_text):
        attrs = parse_attrs(match.group("attrs"))
        body = match.group("body")
        model_id = attrs.get("data-model-id")
        provider = attrs.get("data-model-provider")
        if not model_id or not provider:
            continue
        name = attrs.get("data-model-name", model_id)
        path = None
        title = None
        link_match = link_re.search(body)
        if link_match:
            link_attrs = parse_attrs(link_match.group("attrs") + " " + link_match.group("attrs2"))
            path = link_attrs.get("data-model-path") or link_attrs.get("href")
            title = strip_tags(link_match.group("text")) or None
        code_match = code_re.search(body)
        code_text = strip_tags(code_match.group(1)) if code_match else model_id
        columns = [strip_tags(x) for x in td_re.findall(body)]
        numeric = columns[1:] if len(columns) >= 6 else []
        row = {
            "id": model_id,
            "code": code_text,
            "name": title or name,
            "provider": provider,
            "path": path,
            "url": urllib.parse.urljoin(base_url, path) if path else None,
            "contextWindow": parse_number(numeric[0]) if len(numeric) > 0 else None,
            "cost": {
                "input": parse_number(numeric[1]) if len(numeric) > 1 else None,
                "output": parse_number(numeric[2]) if len(numeric) > 2 else None,
                "cacheRead": parse_number(numeric[3]) if len(numeric) > 3 else None,
                "cacheWrite": parse_number(numeric[4]) if len(numeric) > 4 else None,
            },
        }
        rows.append(row)
    return rows


def load_catalog_cache(path: Path, *, max_age_seconds: float) -> Optional[List[Dict[str, Any]]]:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    fetched_at = data.get("fetchedAt")
    rows = data.get("rows")
    if not isinstance(fetched_at, (int, float)) or not isinstance(rows, list):
        return None
    if max_age_seconds >= 0 and time.time() - fetched_at > max_age_seconds:
        return None
    return rows


def save_catalog_cache(path: Path, rows: List[Dict[str, Any]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": PI_MODELS_URL, "fetchedAt": time.time(), "rows": rows}))
    except OSError:
        # Cache writes are best effort.
        pass


def fetch_catalog(*, timeout: float, cache_path: Optional[Path] = DEFAULT_CACHE_PATH, cache_ttl: float = 3600, refresh: bool = False) -> List[Dict[str, Any]]:
    if cache_path and not refresh:
        cached = load_catalog_cache(cache_path, max_age_seconds=cache_ttl)
        if cached is not None:
            return cached
    status, _content_type, body = request_json_or_text(PI_MODELS_URL, timeout=timeout)
    if status < 200 or status >= 300:
        cached = load_catalog_cache(cache_path, max_age_seconds=-1) if cache_path else None
        if cached is not None:
            eprint(f"Warning: failed to fetch {PI_MODELS_URL} (HTTP {status}); using stale cache {cache_path}")
            return cached
        raise PiModelsError(f"Failed to fetch {PI_MODELS_URL}: HTTP {status}: {strip_tags(body)[:300]}")
    rows = parse_catalog(body, PI_MODELS_URL)
    if not rows:
        cached = load_catalog_cache(cache_path, max_age_seconds=-1) if cache_path else None
        if cached is not None:
            eprint(f"Warning: could not parse {PI_MODELS_URL}; using stale cache {cache_path}")
            return cached
        raise PiModelsError(f"Could not find model rows in {PI_MODELS_URL}")
    if cache_path:
        save_catalog_cache(cache_path, rows)
    return rows


def parse_detail(html_text: str) -> Dict[str, Any]:
    fields: Dict[str, str] = {}
    for dt, dd in re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", html_text, flags=re.I | re.S):
        key = strip_tags(dt)
        value = strip_tags(dd)
        if key:
            fields[key] = value

    config_json = None
    raw_match = re.search(r'<pre\b[^>]*class="[^"]*raw-data-panel[^"]*"[^>]*>(.*?)</pre>', html_text, flags=re.I | re.S)
    if raw_match:
        raw = html.unescape(raw_match.group(1))
        try:
            config_json = json.loads(raw)
        except json.JSONDecodeError:
            config_json = raw

    related: List[Dict[str, str]] = []
    related_block = re.search(r'<div\b[^>]*class="[^"]*models-related[^"]*"[^>]*>(.*?)</div>', html_text, flags=re.I | re.S)
    if related_block:
        for href, text in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', related_block.group(1), flags=re.I | re.S):
            related.append({"url": urllib.parse.urljoin(PI_MODELS_URL, html.unescape(href)), "text": strip_tags(text)})

    return {"fields": fields, "config": config_json, "related": related}


def fetch_detail(url: str, *, timeout: float) -> Dict[str, Any]:
    status, _content_type, body = request_json_or_text(url, timeout=timeout)
    if status < 200 or status >= 300:
        raise PiModelsError(f"Failed to fetch {url}: HTTP {status}: {strip_tags(body)[:300]}")
    detail = parse_detail(body)
    detail["url"] = url
    return detail


def provider_preference(args: argparse.Namespace) -> List[str]:
    if getattr(args, "provider_preference", None):
        return [p.strip() for p in args.provider_preference.split(",") if p.strip()]
    return DEFAULT_PROVIDER_PREFERENCE


def choose_catalog_row(rows: List[Dict[str, Any]], model_id: str, *, preferred_provider: Optional[str], preference: List[str]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    matches = [row for row in rows if row.get("id") == model_id or row.get("code") == model_id]
    if not matches:
        return None, []
    if preferred_provider:
        for row in matches:
            if row.get("provider") == preferred_provider:
                return row, matches
    for provider in preference:
        for row in matches:
            if row.get("provider") == provider:
                return row, matches
    matches.sort(key=lambda row: (str(row.get("provider")), str(row.get("id"))))
    return matches[0], matches


def filter_catalog(rows: List[Dict[str, Any]], *, query: Optional[str], providers: Optional[set[str]], ids: Optional[set[str]]) -> List[Dict[str, Any]]:
    filtered = rows
    if ids:
        filtered = [row for row in filtered if row.get("id") in ids or row.get("code") in ids]
    if providers:
        filtered = [row for row in filtered if row.get("provider") in providers]
    if query:
        q = query.lower()
        filtered = [row for row in filtered if q in str(row.get("id", "")).lower() or q in str(row.get("name", "")).lower() or q in str(row.get("provider", "")).lower()]
    return filtered


def fmt_bool(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return ""
    return str(value)


def fmt_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def compact_status(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 120:
        return text[:117] + "..."
    return text


def make_table(rows: List[Dict[str, Any]], columns: List[Tuple[str, str]]) -> str:
    if not rows:
        return "(no rows)"
    widths: List[int] = []
    rendered_rows: List[List[str]] = []
    for row in rows:
        rendered = [str(row.get(key, "")) for key, _label in columns]
        rendered_rows.append(rendered)
    for idx, (_key, label) in enumerate(columns):
        widths.append(max(len(label), *(len(row[idx]) for row in rendered_rows)))
    lines = []
    lines.append("  ".join(label.ljust(widths[idx]) for idx, (_key, label) in enumerate(columns)))
    lines.append("  ".join("-" * widths[idx] for idx in range(len(columns))))
    for rendered in rendered_rows:
        lines.append("  ".join(rendered[idx].ljust(widths[idx]) for idx in range(len(columns))))
    return "\n".join(lines)


def output_json(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, sort_keys=True)
    print()


def eprint_flush() -> None:
    try:
        sys.stderr.flush()
    except Exception:
        pass


def cmd_live(args: argparse.Namespace) -> None:
    provider_filter = set(args.provider) if args.provider else None
    live = fetch_live_models(args.config, provider_filter, timeout=args.timeout, execute_commands=not args.no_exec_api_key_commands)
    if args.format == "json":
        # Headers/secrets are intentionally not included in live results.
        output_json(live)
        return

    rows: List[Dict[str, Any]] = []
    for result in live:
        if not result["ok"]:
            rows.append({"provider": result["provider"], "id": "", "endpoint": result["endpoint"], "status": compact_status(f"ERROR {result['status']}: {result.get('error', '')}")})
            continue
        for model in result["models"]:
            rows.append({"provider": result["provider"], "id": model["id"], "endpoint": result["endpoint"], "status": f"HTTP {result['status']} {result['elapsedMs']}ms"})
    print(make_table(rows, [("provider", "provider"), ("id", "model id"), ("endpoint", "endpoint"), ("status", "status")]))


def cmd_catalog(args: argparse.Namespace) -> None:
    catalog = fetch_catalog(timeout=args.timeout, cache_path=args.cache, cache_ttl=args.cache_ttl, refresh=args.refresh_catalog)
    filtered = filter_catalog(catalog, query=args.query, providers=set(args.pi_provider) if args.pi_provider else None, ids=set(args.id) if args.id else None)
    filtered.sort(key=lambda row: (str(row.get("provider")), str(row.get("id"))))
    if args.limit:
        filtered = filtered[: args.limit]
    if args.format == "json":
        output_json(filtered)
        return
    rows = []
    for row in filtered:
        rows.append(
            {
                "provider": row["provider"],
                "id": row["id"],
                "name": row.get("name", ""),
                "context": fmt_number(row.get("contextWindow")),
                "in": fmt_number(row.get("cost", {}).get("input")),
                "out": fmt_number(row.get("cost", {}).get("output")),
                "cacheRead": fmt_number(row.get("cost", {}).get("cacheRead")),
                "cacheWrite": fmt_number(row.get("cost", {}).get("cacheWrite")),
            }
        )
    print(make_table(rows, [("provider", "pi.dev provider"), ("id", "model id"), ("name", "name"), ("context", "context"), ("in", "in$/M"), ("out", "out$/M"), ("cacheRead", "cache read"), ("cacheWrite", "cache write")]))
    eprint(f"{len(filtered)} / {len(catalog)} pi.dev catalog rows shown")


def detail_model_from_config(detail: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    config = detail.get("config")
    if not isinstance(config, dict):
        return None
    providers = config.get("providers")
    if not isinstance(providers, dict):
        return None
    for provider_data in providers.values():
        if isinstance(provider_data, dict) and isinstance(provider_data.get("models"), list) and provider_data["models"]:
            model = provider_data["models"][0]
            if isinstance(model, dict):
                return model
    return None


def cmd_details(args: argparse.Namespace) -> None:
    if args.url:
        row = {"url": args.url, "id": args.model or args.url, "provider": None}
        detail = fetch_detail(args.url, timeout=args.timeout)
        matches: List[Dict[str, Any]] = []
    else:
        if not args.model:
            raise PiModelsError("details requires a model id unless --url is provided")
        catalog = fetch_catalog(timeout=args.timeout, cache_path=args.cache, cache_ttl=args.cache_ttl, refresh=args.refresh_catalog)
        row, matches = choose_catalog_row(catalog, args.model, preferred_provider=args.pi_provider, preference=provider_preference(args))
        if not row:
            raise PiModelsError(f"Model {args.model!r} was not found in {PI_MODELS_URL}")
        if not row.get("url"):
            raise PiModelsError(f"Model {args.model!r} has no detail URL in the catalog")
        detail = fetch_detail(row["url"], timeout=args.timeout)

    if args.format == "json":
        output_json({"catalog": row, "detail": detail, "allMatches": matches})
        return

    fields = detail.get("fields", {})
    model_config = detail_model_from_config(detail) or {}
    rows = [
        {"field": "Name", "value": row.get("name") or fields.get("Model", "")},
        {"field": "Model", "value": fields.get("Model") or row.get("id", "")},
        {"field": "pi.dev provider", "value": fields.get("Provider") or row.get("provider", "")},
        {"field": "API", "value": fields.get("API", "")},
        {"field": "Base URL", "value": fields.get("Base URL", "")},
        {"field": "Input", "value": fields.get("Input") or ", ".join(model_config.get("input", [])) if isinstance(model_config.get("input"), list) else fields.get("Input", "")},
        {"field": "Reasoning", "value": fields.get("Reasoning") or fmt_bool(model_config.get("reasoning"))},
        {"field": "Context window", "value": fields.get("Context window") or fmt_number(model_config.get("contextWindow"))},
        {"field": "Max tokens", "value": fields.get("Max tokens") or fmt_number(model_config.get("maxTokens"))},
        {"field": "Input $/M", "value": fields.get("Cost / million input") or fmt_number((model_config.get("cost") or {}).get("input"))},
        {"field": "Output $/M", "value": fields.get("Cost / million output") or fmt_number((model_config.get("cost") or {}).get("output"))},
        {"field": "Cache read $/M", "value": fields.get("Cost / million cache read") or fmt_number((model_config.get("cost") or {}).get("cacheRead"))},
        {"field": "Cache write $/M", "value": fields.get("Cost / million cache write") or fmt_number((model_config.get("cost") or {}).get("cacheWrite"))},
        {"field": "URL", "value": detail.get("url", row.get("url", ""))},
    ]
    print(make_table(rows, [("field", "field"), ("value", "value")]))
    if len(matches) > 1:
        rows_related = [{"provider": p} for p in sorted({str(m.get("provider")) for m in matches})]
        print("\nAlso available from:")
        print(make_table(rows_related, [("provider", "pi.dev provider")]))
    if args.config_json:
        print("\nModel config JSON:")
        eprint_flush()
        output_json(detail.get("config"))


def enrich_from_live(args: argparse.Namespace) -> List[Dict[str, Any]]:
    provider_filter = set(args.provider) if args.provider else None
    live = fetch_live_models(args.config, provider_filter, timeout=args.timeout, execute_commands=not args.no_exec_api_key_commands)
    catalog = fetch_catalog(timeout=args.timeout, cache_path=args.cache, cache_ttl=args.cache_ttl, refresh=args.refresh_catalog)

    enriched: List[Dict[str, Any]] = []
    detail_budget = args.max_detail_pages
    pref = provider_preference(args)
    for endpoint_result in live:
        if not endpoint_result["ok"]:
            enriched.append(
                {
                    "endpointProvider": endpoint_result["provider"],
                    "endpoint": endpoint_result["endpoint"],
                    "ok": False,
                    "error": endpoint_result.get("error"),
                    "status": endpoint_result.get("status"),
                }
            )
            continue
        for live_model in endpoint_result["models"]:
            model_id = live_model["id"]
            row, matches = choose_catalog_row(catalog, model_id, preferred_provider=args.pi_provider, preference=pref)
            detail: Optional[Dict[str, Any]] = None
            model_config: Optional[Dict[str, Any]] = None
            detail_error = None
            if row and row.get("url") and not args.no_details and detail_budget > 0:
                try:
                    detail = fetch_detail(row["url"], timeout=args.timeout)
                    model_config = detail_model_from_config(detail)
                    detail_budget -= 1
                except PiModelsError as exc:
                    detail_error = str(exc)
            fields = detail.get("fields", {}) if detail else {}
            cost = (model_config or {}).get("cost") if isinstance(model_config, dict) else None
            if not isinstance(cost, dict):
                cost = row.get("cost", {}) if row else {}
            enriched.append(
                {
                    "endpointProvider": endpoint_result["provider"],
                    "endpoint": endpoint_result["endpoint"],
                    "id": model_id,
                    "liveRaw": live_model.get("raw"),
                    "matched": bool(row),
                    "piProvider": (fields.get("Provider") if fields else None) or (row.get("provider") if row else None),
                    "name": ((model_config or {}).get("name") if isinstance(model_config, dict) else None) or (row.get("name") if row else None),
                    "input": fields.get("Input") or (", ".join((model_config or {}).get("input", [])) if isinstance((model_config or {}).get("input"), list) else None),
                    "reasoning": fields.get("Reasoning") or fmt_bool((model_config or {}).get("reasoning") if isinstance(model_config, dict) else None),
                    "contextWindow": parse_number(fields.get("Context window", "")) if fields else ((model_config or {}).get("contextWindow") if isinstance(model_config, dict) else (row.get("contextWindow") if row else None)),
                    "maxTokens": parse_number(fields.get("Max tokens", "")) if fields else ((model_config or {}).get("maxTokens") if isinstance(model_config, dict) else None),
                    "cost": cost,
                    "catalogUrl": row.get("url") if row else None,
                    "allPiProviders": sorted({str(m.get("provider")) for m in matches}) if matches else [],
                    "detailError": detail_error,
                }
            )
    return enriched


def cmd_enrich(args: argparse.Namespace) -> None:
    enriched = enrich_from_live(args)
    if args.format == "json":
        output_json(enriched)
        return
    rows = []
    for item in enriched:
        if not item.get("ok", True):
            rows.append({"endpoint": item.get("endpointProvider", ""), "id": "", "pi": "", "name": "", "input": "", "reasoning": "", "context": "", "max": "", "in": "", "out": "", "cacheRead": "", "status": compact_status(f"ERROR {item.get('status')}: {item.get('error')}")})
            continue
        cost = item.get("cost") if isinstance(item.get("cost"), dict) else {}
        if item.get("matched"):
            status = "matched"
        else:
            status = "no pi.dev match"
        if item.get("detailError"):
            status = "catalog only; detail error"
        rows.append(
            {
                "endpoint": item.get("endpointProvider", ""),
                "id": item.get("id", ""),
                "pi": item.get("piProvider") or "",
                "name": item.get("name") or "",
                "input": item.get("input") or "",
                "reasoning": item.get("reasoning") or "",
                "context": fmt_number(item.get("contextWindow")),
                "max": fmt_number(item.get("maxTokens")),
                "in": fmt_number(cost.get("input")),
                "out": fmt_number(cost.get("output")),
                "cacheRead": fmt_number(cost.get("cacheRead")),
                "status": status,
            }
        )
    print(make_table(rows, [("endpoint", "endpoint"), ("id", "model id"), ("pi", "pi.dev provider"), ("name", "name"), ("input", "input"), ("reasoning", "reasoning"), ("context", "context"), ("max", "max tokens"), ("in", "in$/M"), ("out", "out$/M"), ("cacheRead", "cache read"), ("status", "status")]))


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout", type=float, default=20, help="HTTP timeout in seconds (default: 20)")
    parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format (default: table)")


def add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"Pi models config path (default: {DEFAULT_CONFIG})")
    parser.add_argument("--provider", action="append", help="Only fetch this configured Pi provider; repeatable")
    parser.add_argument("--no-exec-api-key-commands", action="store_true", help="Do not execute apiKey/header commands that start with !")


def add_catalog_cache_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH, help=f"pi.dev catalog cache path (default: {DEFAULT_CACHE_PATH})")
    parser.add_argument("--cache-ttl", type=float, default=3600, help="pi.dev catalog cache TTL in seconds (default: 3600)")
    parser.add_argument("--refresh-catalog", action="store_true", help="Ignore any cached pi.dev catalog and fetch a fresh copy")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch configured Pi endpoint models and enrich them from https://pi.dev/models")
    sub = parser.add_subparsers(dest="command", required=True)

    live = sub.add_parser("live", help="Fetch /models from providers in ~/.pi/agent/models.json")
    add_common_args(live)
    add_config_args(live)
    live.set_defaults(func=cmd_live)

    catalog = sub.add_parser("catalog", help="Search/list the pi.dev model catalog")
    add_common_args(catalog)
    add_catalog_cache_args(catalog)
    catalog.add_argument("--query", "-q", help="Case-insensitive substring search across model id/name/provider")
    catalog.add_argument("--pi-provider", action="append", help="Filter by pi.dev provider; repeatable")
    catalog.add_argument("--id", action="append", help="Filter by exact model id; repeatable")
    catalog.add_argument("--limit", type=int, help="Limit rows shown")
    catalog.set_defaults(func=cmd_catalog)

    details = sub.add_parser("details", help="Fetch a pi.dev detail page for one model id")
    add_common_args(details)
    add_catalog_cache_args(details)
    details.add_argument("model", nargs="?", help="Model id as shown in pi.dev catalog")
    details.add_argument("--pi-provider", help="Choose this pi.dev provider when model id is available from several providers")
    details.add_argument("--provider-preference", help="Comma-separated pi.dev provider preference order")
    details.add_argument("--url", help="Fetch this exact pi.dev detail URL instead of searching by model id")
    details.add_argument("--config-json", action="store_true", help="Also print the raw Model config JSON from pi.dev")
    details.set_defaults(func=cmd_details)

    enrich = sub.add_parser("enrich", help="Fetch live configured models and enrich with pi.dev details")
    add_common_args(enrich)
    add_config_args(enrich)
    add_catalog_cache_args(enrich)
    enrich.add_argument("--pi-provider", help="Prefer this pi.dev provider for details when ids are ambiguous")
    enrich.add_argument("--provider-preference", help="Comma-separated pi.dev provider preference order")
    enrich.add_argument("--no-details", action="store_true", help="Only use the pi.dev catalog table; do not fetch per-model details")
    enrich.add_argument("--max-detail-pages", type=int, default=50, help="Maximum per-model detail pages to fetch (default: 50)")
    enrich.set_defaults(func=cmd_enrich)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except PiModelsError as exc:
        eprint(f"pi-models: {exc}")
        return 2
    except KeyboardInterrupt:
        eprint("pi-models: interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
