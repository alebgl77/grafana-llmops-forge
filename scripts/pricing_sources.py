"""Fallback de prix tiers opt-in, borne et fail-open pour la forge.

Le cache Artificial Analysis est un overlay minimal. Il ne devient jamais un
registre de modeles et chaque entree est revalidee avant toute fusion.
"""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

AA_API_BASE = "https://artificialanalysis.ai/api/v2"
AA_URL = f"{AA_API_BASE}/language/models/free"
AA_ORIGIN = ("https", "artificialanalysis.ai", 443)
AA_ATTRIBUTION = "Artificial Analysis"
AA_PRICE_BASIS = "median_multi_provider"
AA_KEY_ENV = "ARTIFICIAL_ANALYSIS_API_KEY"
CACHE_FILENAME = "model_registry.artificial-analysis.cache.json"
CACHE_SCHEMA = "grafana-llmops-forge/artificial-analysis-pricing-overlay"
CACHE_VERSION = 1
DEFAULT_MAX_AGE_HOURS = 24.0
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_API_KEY_LENGTH = 512
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_PAGES = 20
MAX_MODELS = 5000
MAX_CACHE_BYTES = 2 * 1024 * 1024
MAX_PRICE_PER_MTOK = 1_000_000
_PRICE_KEYS = ("input_per_mtok", "output_per_mtok", "cached_input_per_mtok")


class PricingSourceError(RuntimeError):
    """Erreur volontairement depourvue de secret, URL variable ou corps HTTP."""


def normalize_model_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _safe_text(value: object, maximum: int = 512) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _validate_api_key(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_API_KEY_LENGTH:
        raise PricingSourceError("invalid API key")
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise PricingSourceError("invalid API key") from None
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise PricingSourceError("invalid API key")
    return value


def _origin(url: str) -> tuple[str, str, int | None]:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else None)
    except ValueError:
        raise PricingSourceError("redirect blocked") from None
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            absolute = urllib.parse.urljoin(req.full_url, newurl)
        except ValueError:
            raise PricingSourceError("redirect blocked") from None
        if _origin(absolute) != AA_ORIGIN:
            raise PricingSourceError("redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def _default_opener():
    return urllib.request.build_opener(SameOriginRedirectHandler())


def _safe_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if (not math.isfinite(number) or number < 0
            or number > MAX_PRICE_PER_MTOK):
        return None
    return number


def _read_bounded_json(response, limit: int = MAX_PAGE_BYTES) -> dict:
    length = response.headers.get("Content-Length") if response.headers else None
    if length:
        try:
            parsed_length = int(length)
        except ValueError:
            raise PricingSourceError("invalid Content-Length") from None
        if parsed_length < 0 or parsed_length > limit:
            raise PricingSourceError("response too large")
    try:
        body = response.read(limit + 1)
    except http.client.HTTPException:
        raise PricingSourceError("response read failed") from None
    if len(body) > limit:
        raise PricingSourceError("response too large")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise PricingSourceError("invalid JSON response") from None
    if not isinstance(value, dict):
        raise PricingSourceError("invalid response envelope")
    return value


def fetch_artificial_analysis(api_key: str, opener=None,
                              timeout: float = DEFAULT_TIMEOUT_SECONDS) -> list[dict]:
    """Charge le catalogue borne; la cle validee reste uniquement en entete."""
    key = _validate_api_key(api_key)
    client = opener or _default_opener()
    models: list[dict] = []
    for expected_page in range(1, MAX_PAGES + 1):
        url = AA_URL if expected_page == 1 else f"{AA_URL}?page={expected_page}"
        try:
            request = urllib.request.Request(
                url, method="GET",
                headers={"x-api-key": key, "Accept": "application/json",
                         "User-Agent": "grafana-llmops-forge/2.0.0"})
            with client.open(request, timeout=timeout) as response:
                status = response.getcode()
                if status != 200:
                    raise PricingSourceError(f"HTTP status {status}")
                envelope = _read_bounded_json(response)
        except urllib.error.HTTPError as exc:
            raise PricingSourceError(f"HTTP status {exc.code}") from None
        except PricingSourceError:
            raise
        except http.client.HTTPException:
            raise PricingSourceError("HTTP protocol failure") from None
        except ValueError:
            raise PricingSourceError("request rejected") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PricingSourceError(f"network failure ({type(exc).__name__})") from None

        data, pagination = envelope.get("data"), envelope.get("pagination")
        if not isinstance(data, list) or not isinstance(pagination, dict):
            raise PricingSourceError("invalid paginated response")
        page = pagination.get("page")
        total_pages = pagination.get("total_pages")
        page_size = pagination.get("page_size")
        has_more = pagination.get("has_more")
        ints_ok = all(isinstance(v, int) and not isinstance(v, bool)
                      for v in (page, total_pages, page_size))
        if (not ints_ok or page != expected_page or total_pages < 1
                or total_pages > MAX_PAGES or page > total_pages
                or page_size < 1 or page_size > MAX_MODELS
                or not isinstance(has_more, bool)
                or has_more != (page < total_pages)
                or any(not isinstance(item, dict) for item in data)):
            raise PricingSourceError("invalid pagination metadata")
        models.extend(data)
        if len(models) > MAX_MODELS:
            raise PricingSourceError("too many models")
        if not has_more:
            return models
    raise PricingSourceError("pagination limit exceeded")


def _catalog_names(item: dict) -> set[str]:
    values = [item.get("id"), item.get("slug"), item.get("name")]
    aliases = item.get("aliases", [])
    if isinstance(aliases, list):
        values.extend(aliases)
    return {normalize_model_name(value) for value in values
            if isinstance(value, str) and normalize_model_name(value)}


def _catalog_identity(item: dict) -> str | None:
    model_id = _safe_text(item.get("id"))
    return normalize_model_name(model_id) if model_id else None


def _catalog_prices(item: dict) -> dict | None:
    pricing = item.get("pricing")
    if not isinstance(pricing, dict):
        return None
    input_price = _safe_number(pricing.get("price_1m_input_tokens"))
    output_price = _safe_number(pricing.get("price_1m_output_tokens"))
    cache_raw = pricing.get("price_1m_cache_hit_tokens")
    cache_price = None if cache_raw is None else _safe_number(cache_raw)
    if input_price is None or output_price is None:
        return None
    if cache_raw is not None and cache_price is None:
        return None
    return {"input_per_mtok": input_price,
            "output_per_mtok": output_price,
            "cached_input_per_mtok": cache_price}


def strict_catalog_match(seen: str, catalog: list[dict]) -> tuple[dict | None, str]:
    """Match exact normalise et unique, jamais par sous-chaine."""
    needle = normalize_model_name(seen)
    candidates = [item for item in catalog if needle and needle in _catalog_names(item)]
    if len(candidates) != 1:
        return None, "absent" if not candidates else "ambiguous"
    item = candidates[0]
    if _catalog_identity(item) is None or _catalog_prices(item) is None:
        return None, "null"
    return item, "matched"


def _match_score(needle: str, key: str) -> int:
    if len(key) < 4:
        return 0
    if key == needle:
        return 10000 + len(key)
    if key in needle:
        return 1000 + len(key)
    if needle in key:
        return len(key)
    return 0


def _registry_match(seen: str, models: list[dict]) -> tuple[int | None, dict | None, str]:
    """Refuse tout ex aequo de specificite entre entrees du registre."""
    needle = normalize_model_name(seen)
    scored = []
    for index, model in enumerate(models):
        aliases = model.get("aliases", [])
        values = [model.get("id")] + (aliases if isinstance(aliases, list) else [])
        score = max((_match_score(needle, normalize_model_name(value))
                     for value in values), default=0)
        if score:
            scored.append((score, index))
    if not scored:
        return None, None, "absent"
    top = max(score for score, _ in scored)
    winners = [index for score, index in scored if score == top]
    if len(winners) != 1:
        return None, None, "ambiguous"
    index = winners[0]
    return index, models[index], "matched"


def _registry_destinations(seen: str, models: list[dict]) -> set[tuple]:
    """Retourne toutes les destinations maximales, meme en cas d'ambiguite."""
    needle = normalize_model_name(seen)
    scored = []
    for index, model in enumerate(models):
        aliases = model.get("aliases", [])
        values = [model.get("id")] + (aliases if isinstance(aliases, list) else [])
        score = max((_match_score(needle, normalize_model_name(value))
                     for value in values), default=0)
        if score:
            scored.append((score, index))
    if not scored:
        return {("new", needle)}
    top = max(score for score, _ in scored)
    return {("registry", index) for score, index in scored if score == top}


def models_needing_fallback(models_seen: list[str], registry: dict) -> list[str]:
    targets = []
    models = registry.get("models", []) if isinstance(registry.get("models"), list) else []
    for seen in models_seen:
        _, model, status = _registry_match(seen, models)
        if (status != "matched" or model is None
                or model.get("input_per_mtok") is None
                or model.get("output_per_mtok") is None):
            targets.append(seen)
    return targets


def official_registry_base(registry: dict) -> dict:
    """Retire aussi les caches fusionnes produits par les prereleases 2.0."""
    clean = copy.deepcopy(registry)
    meta = clean.get("_meta")
    marker = meta.pop("artificial_analysis_fallback", None) if isinstance(meta, dict) else None
    models = clean.get("models")
    if not isinstance(models, list):
        clean["models"] = []
        return clean
    if isinstance(marker, dict) and isinstance(marker.get("changes"), list):
        for change in marker["changes"]:
            if not isinstance(change, dict):
                continue
            fallback_id = normalize_model_name(change.get("fallback_id", ""))
            indexes = [index for index, model in enumerate(models)
                       if isinstance(model, dict)
                       and model.get("pricing_source_kind") == "artificial_analysis"
                       and normalize_model_name(model.get("id", "")) == fallback_id]
            if not indexes:
                continue
            original = change.get("original")
            if isinstance(original, dict):
                models[indexes[0]] = copy.deepcopy(original)
            elif original is None:
                models.pop(indexes[0])
    clean["models"] = [model for model in models if isinstance(model, dict)
                       and model.get("pricing_source_kind") != "artificial_analysis"]
    return clean


def _third_party_entry(seen: str, item: dict, original: dict | None,
                       verified_at: str) -> dict:
    prices = _catalog_prices(item)
    if prices is None:
        raise PricingSourceError("invalid pricing entry")
    entry = copy.deepcopy(original) if original is not None else {
        "id": seen,
        "aliases": [],
        "vendor": ((item.get("model_creator") or {}).get("name")
                   if isinstance(item.get("model_creator"), dict) else "Unknown"),
        "region": "unknown",
    }
    if original is None:
        entry["aliases"] = [value for value in (item.get("slug"), item.get("name"))
                            if _safe_text(value)
                            and normalize_model_name(value) != normalize_model_name(seen)]
    field_sources = {}
    for key, aa_value in prices.items():
        if original is not None and original.get(key) is not None:
            entry[key] = original[key]
            existing_fields = original.get("pricing_field_sources")
            existing_source = (existing_fields.get(key)
                               if isinstance(existing_fields, dict) else None)
            if isinstance(existing_source, dict):
                field_sources[key] = copy.deepcopy(existing_source)
            elif original.get("pricing_source_kind"):
                field_sources[key] = {
                    "pricing_source_kind": original["pricing_source_kind"],
                    "pricing_source_url": original.get("pricing_source_url"),
                    "pricing_verified_at": original.get("pricing_verified_at"),
                    "estimate": original.get("estimate", False),
                }
            else:
                field_sources[key] = {
                    "pricing_source_kind": "local_registry_legacy",
                    "attribution": "Local registry (legacy schema)",
                    "estimate": False,
                }
        else:
            entry[key] = aa_value
            field_sources[key] = {
                "pricing_source_kind": "artificial_analysis",
                "pricing_source_url": AA_URL,
                "pricing_verified_at": verified_at,
                "estimate": True,
                "attribution": AA_ATTRIBUTION,
            }
    entry.update({
        "pricing_source_kind": "artificial_analysis",
        "pricing_source_url": AA_URL,
        "pricing_verified_at": verified_at,
        "pricing_basis": AA_PRICE_BASIS,
        "estimate": True,
        "attribution": AA_ATTRIBUTION,
        "pricing_field_sources": field_sources,
    })
    return entry


def _resolve_plans(cache_plans: list[dict], api_plans: list[dict],
                   statuses: dict[str, str],
                   blocked_destinations: set[tuple] | None = None) -> dict:
    """Resout tous les plans ensemble avant la premiere mutation."""
    resolved_statuses = dict(statuses)
    all_plans = list(cache_plans) + list(api_plans)
    by_destination: dict[tuple, list[dict]] = {}
    for plan in all_plans:
        by_destination.setdefault(plan["destination"], []).append(plan)

    rejected_destinations = set(blocked_destinations or set())
    for destination, grouped in by_destination.items():
        if len({plan["identity"] for plan in grouped}) > 1:
            rejected_destinations.add(destination)
    for destination in rejected_destinations:
        for plan in by_destination.get(destination, []):
            resolved_statuses[plan["seen"]] = "ambiguous"

    api_identities = {
        plan["identity"] for plan in api_plans
        if plan["destination"] not in rejected_destinations
    }
    writers = []
    accepted_api = []
    accepted_cache = []
    priced = []
    superseded_cache = set()

    def writer_key(plan: dict) -> tuple:
        verified = _parse_utc(plan.get("verified_at"))
        timestamp = verified.timestamp() if verified is not None else float("-inf")
        return (timestamp, normalize_model_name(plan["seen"]), plan["seen"])

    for destination, grouped in by_destination.items():
        if destination in rejected_destinations:
            continue
        api_group = [plan for plan in grouped if plan["origin"] == "api"]
        cache_group = [plan for plan in grouped if plan["origin"] == "cache"]
        if api_group:
            selected = api_group
            for plan in cache_group:
                resolved_statuses[plan["seen"]] = "superseded"
                superseded_cache.add(normalize_model_name(plan["seen"]))
        else:
            selected = []
            for plan in cache_group:
                if plan["identity"] in api_identities:
                    resolved_statuses[plan["seen"]] = "superseded"
                    superseded_cache.add(normalize_model_name(plan["seen"]))
                else:
                    selected.append(plan)
        if not selected:
            continue

        writers.append(max(selected, key=writer_key))
        for plan in selected:
            resolved_statuses[plan["seen"]] = "matched"
            priced.append(plan["seen"])
            if plan["origin"] == "api":
                accepted_api.append(plan)
            else:
                accepted_cache.append(plan)

    if len({plan["destination"] for plan in writers}) != len(writers):
        raise PricingSourceError("duplicate pricing destination")
    return {
        "writers": writers,
        "accepted_api": accepted_api,
        "accepted_cache": accepted_cache,
        "priced": priced,
        "superseded_cache": superseded_cache,
        "rejected_destinations": rejected_destinations,
        "statuses": resolved_statuses,
    }


def _plan_catalog(registry: dict, targets: list[str], catalog: list[dict],
                  verified_at: str | None = None
                  ) -> tuple[list[dict], dict[str, str], set[tuple]]:
    """Calcule les matches bruts sans arbitrer entre les sources."""
    models = registry.get("models", []) if isinstance(registry.get("models"), list) else []
    plans, statuses, blocked_destinations = [], {}, set()
    for seen in targets:
        item, status = strict_catalog_match(seen, catalog)
        statuses[seen] = status
        if item is None:
            if status == "ambiguous":
                blocked_destinations.update(_registry_destinations(seen, models))
            continue
        index, original, registry_status = _registry_match(seen, models)
        if registry_status == "ambiguous":
            statuses[seen] = "ambiguous"
            blocked_destinations.update(_registry_destinations(seen, models))
            continue
        if (original is not None and original.get("pricing_source_kind") == "official"
                and original.get("input_per_mtok") is not None
                and original.get("output_per_mtok") is not None):
            statuses[seen] = "official"
            continue
        destination = ("registry", index) if index is not None else (
            "new", normalize_model_name(seen))
        plans.append({"seen": seen, "item": item, "identity": _catalog_identity(item),
                      "index": index, "original": original,
                      "destination": destination, "origin": "api",
                      "verified_at": verified_at})
    return plans, statuses, blocked_destinations


def _apply_plans(registry: dict, writers: list[dict]) -> dict:
    if len({plan["destination"] for plan in writers}) != len(writers):
        raise PricingSourceError("duplicate pricing destination")
    merged = copy.deepcopy(registry)
    for plan in writers:
        stamp = plan.get("verified_at")
        if not stamp:
            raise PricingSourceError("missing pricing verification time")
        entry = _third_party_entry(plan["seen"], plan["item"],
                                   plan["original"], stamp)
        if plan["index"] is None:
            merged.setdefault("models", []).append(entry)
        else:
            merged["models"][plan["index"]] = entry
    return merged


def _registry_fingerprint(registry: dict) -> str:
    raw = json.dumps(registry, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_utc(value: object) -> datetime | None:
    if (not isinstance(value, str)
            or not (value.endswith("Z") or value.endswith("+00:00"))):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _overlay_from_plan(plan: dict, verified_at: str) -> dict:
    item = plan["item"]
    prices = _catalog_prices(item)
    creator = item.get("model_creator")
    return {
        "seen": plan["seen"],
        "target_registry_id": (plan["original"].get("id")
                               if plan["original"] is not None else None),
        "aa_model_id": item.get("id"),
        "aa_slug": item.get("slug"),
        "aa_name": item.get("name"),
        "aa_aliases": [alias for alias in item.get("aliases", [])
                       if _safe_text(alias)] if isinstance(item.get("aliases", []), list)
                       else [],
        "vendor": creator.get("name") if isinstance(creator, dict) else "Unknown",
        **(prices or {}),
        "pricing_source_kind": "artificial_analysis",
        "pricing_source_url": AA_URL,
        "pricing_verified_at": verified_at,
        "pricing_basis": AA_PRICE_BASIS,
        "estimate": True,
        "attribution": AA_ATTRIBUTION,
    }


def _valid_source_url(value: object) -> bool:
    if value != AA_URL:
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (parsed.scheme == "https" and (host == "artificialanalysis.ai"
            or host.endswith(".artificialanalysis.ai")) and port in (None, 443))


def _validate_overlay(value: object, now: datetime,
                      max_age_hours: float) -> dict | None:
    if not isinstance(value, dict):
        return None
    seen = _safe_text(value.get("seen"))
    target_id = value.get("target_registry_id")
    if target_id is not None and _safe_text(target_id) is None:
        return None
    aa_id = _safe_text(value.get("aa_model_id"))
    slug = _safe_text(value.get("aa_slug"))
    name = _safe_text(value.get("aa_name"))
    aliases = value.get("aa_aliases")
    vendor = _safe_text(value.get("vendor"))
    verified = _parse_utc(value.get("pricing_verified_at"))
    input_price = _safe_number(value.get("input_per_mtok"))
    output_price = _safe_number(value.get("output_per_mtok"))
    cache_raw = value.get("cached_input_per_mtok")
    cache_price = None if cache_raw is None else _safe_number(cache_raw)
    provenance_ok = (
        value.get("pricing_source_kind") == "artificial_analysis"
        and value.get("estimate") is True
        and value.get("attribution") == AA_ATTRIBUTION
        and value.get("pricing_basis") == AA_PRICE_BASIS
        and _valid_source_url(value.get("pricing_source_url")))
    time_ok = (verified is not None and verified <= now + timedelta(minutes=5)
               and now - verified <= timedelta(hours=max_age_hours))
    if (not isinstance(aliases, list) or len(aliases) > 32
            or any(_safe_text(alias) is None for alias in aliases)):
        return None
    if (not seen or not aa_id or not slug or not name or not vendor
            or input_price is None or output_price is None
            or (cache_raw is not None and cache_price is None)
            or not provenance_ok or not time_ok):
        return None
    return {
        "seen": seen,
        "target_registry_id": target_id,
        "aa_model_id": aa_id,
        "aa_slug": slug,
        "aa_name": name,
        "aa_aliases": list(aliases),
        "vendor": vendor,
        "input_per_mtok": input_price,
        "output_per_mtok": output_price,
        "cached_input_per_mtok": cache_price,
        "pricing_source_kind": "artificial_analysis",
        "pricing_source_url": AA_URL,
        "pricing_verified_at": value["pricing_verified_at"],
        "pricing_basis": AA_PRICE_BASIS,
        "estimate": True,
        "attribution": AA_ATTRIBUTION,
    }


def _read_fresh_cache(path: str, registry: dict, max_age_hours: float,
                      now: datetime) -> list[dict]:
    try:
        if os.path.getsize(path) > MAX_CACHE_BYTES:
            return []
        with open(path, "rb") as handle:
            raw = handle.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            return []
        cache = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return []
    try:
        expected_fingerprint = _registry_fingerprint(registry)
    except (TypeError, ValueError):
        return []
    generated_at = _parse_utc(cache.get("generated_at")) if isinstance(cache, dict) else None
    if (not isinstance(cache, dict) or cache.get("schema") != CACHE_SCHEMA
            or cache.get("version") != CACHE_VERSION
            or cache.get("api_base") != AA_API_BASE
            or cache.get("source_url") != AA_URL
            or generated_at is None or generated_at > now + timedelta(minutes=5)
            or cache.get("base_registry_sha256") != expected_fingerprint
            or not isinstance(cache.get("entries"), list)
            or len(cache["entries"]) > MAX_MODELS):
        return []
    return [entry for raw_entry in cache["entries"]
            if (entry := _validate_overlay(raw_entry, now, max_age_hours)) is not None]


def _overlay_item(entry: dict) -> dict:
    return {
        "id": entry["aa_model_id"], "slug": entry["aa_slug"],
        "name": entry["aa_name"], "aliases": entry["aa_aliases"],
        "model_creator": {"name": entry["vendor"]},
        "pricing": {
            "price_1m_input_tokens": entry["input_per_mtok"],
            "price_1m_output_tokens": entry["output_per_mtok"],
            "price_1m_cache_hit_tokens": entry["cached_input_per_mtok"],
        },
    }


def _plan_overlays(registry: dict, targets: list[str],
                   entries: list[dict]
                   ) -> tuple[list[dict], dict[str, str], set[tuple]]:
    models = registry.get("models", []) if isinstance(registry.get("models"), list) else []
    plans, statuses, blocked_destinations = [], {}, set()
    for seen in targets:
        matches = [entry for entry in entries
                   if normalize_model_name(entry["seen"]) == normalize_model_name(seen)]
        if len(matches) != 1:
            statuses[seen] = "absent" if not matches else "ambiguous"
            if matches:
                blocked_destinations.update(_registry_destinations(seen, models))
            continue
        overlay = matches[0]
        item, overlay_status = strict_catalog_match(seen, [_overlay_item(overlay)])
        if item is None:
            statuses[seen] = overlay_status
            continue
        index, original, registry_status = _registry_match(seen, models)
        if registry_status == "ambiguous":
            statuses[seen] = "ambiguous"
            blocked_destinations.update(_registry_destinations(seen, models))
            continue
        current_target = original.get("id") if original is not None else None
        if current_target != overlay["target_registry_id"]:
            statuses[seen] = "stale"
            continue
        if (original is not None and original.get("pricing_source_kind") == "official"
                and original.get("input_per_mtok") is not None
                and original.get("output_per_mtok") is not None):
            statuses[seen] = "official"
            continue
        destination = ("registry", index) if index is not None else (
            "new", normalize_model_name(seen))
        plans.append({"seen": seen, "item": item,
                      "identity": normalize_model_name(overlay["aa_model_id"]),
                      "index": index, "original": original,
                      "destination": destination,
                      "origin": "cache",
                      "verified_at": overlay["pricing_verified_at"]})
    return plans, statuses, blocked_destinations


def _cache_document(base_registry: dict, entries: list[dict], now: datetime) -> dict:
    return {
        "schema": CACHE_SCHEMA,
        "version": CACHE_VERSION,
        "api_base": AA_API_BASE,
        "source_url": AA_URL,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "base_registry_sha256": _registry_fingerprint(base_registry),
        "entries": entries,
    }


def _atomic_write_json(path: str, value: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory,
                                         prefix=".artificial-analysis-pricing.",
                                         suffix=".tmp", delete=False) as handle:
            tmp_path = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def apply_artificial_analysis_fallback(registry: dict, models_seen: list[str],
                                       cache_path: str, api_key: str | None,
                                       max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
                                       opener=None, now: datetime | None = None) -> dict:
    """Fusionne uniquement des overlays valides dans une copie de la base."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = copy.deepcopy(registry)
    targets = models_needing_fallback(models_seen, base)
    result = {"registry": base, "priced": [], "statuses": {}, "warnings": [],
              "cache_used": False, "fetched": False}
    if not targets:
        return result

    cached_entries = _read_fresh_cache(cache_path, base, max_age_hours, current)
    cached_plans, cached_statuses, cached_blocked = _plan_overlays(
        base, targets, cached_entries)
    covered = {normalize_model_name(plan["seen"]) for plan in cached_plans}
    unresolved = [seen for seen in targets if normalize_model_name(seen) not in covered]

    def finish_with_cache_only(warning: str | None = None) -> dict:
        decision = _resolve_plans(cached_plans, [], cached_statuses,
                                  cached_blocked)
        merged = _apply_plans(base, decision["writers"])
        result.update({"registry": merged, "priced": decision["priced"],
                       "statuses": decision["statuses"],
                       "cache_used": bool(decision["accepted_cache"])})
        if warning:
            result["warnings"].append(warning)
        return result

    if not unresolved:
        return finish_with_cache_only()
    if not api_key:
        return finish_with_cache_only(
            "API key missing; unresolved models stay unpriced")

    try:
        catalog = fetch_artificial_analysis(api_key, opener=opener)
    except PricingSourceError as exc:
        return finish_with_cache_only(str(exc))
    result["fetched"] = True
    verified_at = current.isoformat().replace("+00:00", "Z")
    api_plans, api_statuses, api_blocked = _plan_catalog(
        base, unresolved, catalog, verified_at=verified_at)
    statuses = dict(cached_statuses)
    statuses.update(api_statuses)
    decision = _resolve_plans(cached_plans, api_plans, statuses,
                              cached_blocked | api_blocked)
    merged = _apply_plans(base, decision["writers"])
    result.update({"registry": merged, "statuses": decision["statuses"],
                   "priced": decision["priced"],
                   "cache_used": bool(decision["accepted_cache"])})

    new_overlays = [_overlay_from_plan(plan, verified_at)
                    for plan in decision["accepted_api"]]
    target_names = {normalize_model_name(seen) for seen in targets}
    accepted_cache = {normalize_model_name(plan["seen"])
                      for plan in decision["accepted_cache"]}
    previous = {normalize_model_name(entry["seen"]): entry
                for entry in cached_entries
                if (normalize_model_name(entry["seen"])
                    not in decision["superseded_cache"]
                    and (normalize_model_name(entry["seen"]) not in target_names
                         or normalize_model_name(entry["seen"]) in accepted_cache))}
    for entry in new_overlays:
        previous[normalize_model_name(entry["seen"])] = entry
    try:
        _atomic_write_json(cache_path, _cache_document(
            base, list(previous.values()), current))
    except (OSError, TypeError, ValueError):
        result["warnings"].append("local pricing cache could not be written")
    return result
