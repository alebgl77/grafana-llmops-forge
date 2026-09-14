"""Client Grafana universel : OSS / Cloud / Enterprise, Grafana 9 → 13+.

Zéro dépendance externe (stdlib uniquement) : portable partout où Python 3.8+ existe.
Auth : GRAFANA_TOKEN (service account, recommandé) ou GRAFANA_USER/GRAFANA_PASSWORD.
Gère les deux générations d'API :
  - legacy      /api/...                          (universelle, v9+)
  - resource    /apis/dashboard.grafana.app/...   (K8s-style, v12+, namespacée)
Le token n'est jamais loggé.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request


class GrafanaError(RuntimeError):
    def __init__(self, status, message, body=""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.body = body


def normalized_http_origin(url: str) -> tuple[str, str, int]:
    """Retourne une origine HTTP canonique, ports implicites compris."""
    try:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port or (443 if scheme == "https" else 80)
    except (UnicodeError, ValueError):
        raise GrafanaError(502, "redirect blocked") from None
    return scheme, hostname, port


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Autorise uniquement les redirections restant sur l'origine Grafana."""

    def __init__(self, allowed_origin: tuple[str, str, int]):
        super().__init__()
        self.allowed_origin = allowed_origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            absolute = urllib.parse.urljoin(req.full_url, newurl)
        except ValueError:
            raise GrafanaError(502, "redirect blocked") from None
        if normalized_http_origin(absolute) != self.allowed_origin:
            raise GrafanaError(502, "redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, absolute)


_PROMQL_LEGACY_NAME = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
_PROMQL_CONTROL_ESCAPES = {
    "\b": r"\b",
    "\f": r"\f",
    "\n": r"\n",
    "\r": r"\r",
    "\t": r"\t",
}


def promql_string_content(value: object) -> str:
    """Encode le contenu d'une chaine PromQL sans guillemets bruts."""
    out = []
    for char in str(value):
        if char == "\\":
            out.append(r"\\")
        elif char == '"':
            out.append(r'\"')
        elif char in _PROMQL_CONTROL_ESCAPES:
            out.append(_PROMQL_CONTROL_ESCAPES[char])
        elif unicodedata.category(char) in ("Cc", "Cs"):
            point = ord(char)
            if point <= 0xFF:
                out.append(f"\\x{point:02x}")
            elif point <= 0xFFFF:
                out.append(f"\\u{point:04x}")
            else:
                out.append(f"\\U{point:08x}")
        else:
            out.append(char)
    return "".join(out)


def promql_string(value: object) -> str:
    return '"' + promql_string_content(value) + '"'


def promql_name(value: object) -> str:
    name = str(value)
    return name if _PROMQL_LEGACY_NAME.fullmatch(name) else promql_string(name)


def promql_metric_selector(metric: object, selector: str = "") -> str:
    """Rend un nom de metrique, y compris UTF-8, avec son selecteur."""
    name = str(metric)
    if not name:
        return name
    if _PROMQL_LEGACY_NAME.fullmatch(name):
        return name + selector
    inner = (selector[1:-1].strip()
             if selector.startswith("{") and selector.endswith("}") else "")
    return "{" + promql_string(name) + ("," + inner if inner else "") + "}"


def promql_matcher(label: object, operator: str, value: object) -> str:
    if operator not in ("=", "!=", "=~", "!~"):
        raise ValueError("invalid PromQL matcher operator")
    return "{" + promql_name(label) + operator + promql_string(value) + "}"


def det_uid(name: str, prefix: str = "llmops", scope: str | None = None) -> str:
    """UID déterministe (≤40 chars), compatible legacy sans ``scope``.

    Un scope explicite sépare les mêmes blueprints déployés dans plusieurs
    dossiers. Il n'est volontairement pas ajouté au slug : seul le digest
    change, ce qui garde des UIDs courts et lisibles.
    """
    seed = name if scope is None else f"{scope}\0{name}"
    # SHA-1 ne protege aucun secret : il conserve des UIDs publics et deterministes.
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:26]
    return f"{prefix}-{slug}-{h}"[:40]


def alert_logical_identity(uid_name: str) -> str:
    """Identité complète d'une règle, indépendante de l'UID Grafana tronqué."""
    return hashlib.sha256(uid_name.encode("utf-8")).hexdigest()


def _is_forge_budget(rule: dict) -> bool:
    labels = rule.get("labels")
    return (isinstance(labels, dict) and labels.get("origin") == "llmops-forge"
            and labels.get("llmops_rule_identity") == alert_logical_identity("llm-daily-budget")
            and rule.get("ruleGroup") == "llmops-slo")


def _assert_alert_ownership(existing, rule: dict):
    """Shared upsert/pause collision guard; never infer ownership from an UID alone."""
    uid = rule["uid"]
    labels = rule.get("labels") or {}
    expected_identity = labels.get("llmops_rule_identity")
    if not isinstance(expected_identity, str) or not expected_identity:
        raise GrafanaError(400, f"alert rule {uid} has no logical identity; refusing write")
    if not isinstance(existing, dict):
        raise GrafanaError(409, f"alert rule UID {uid}: identity response is not an object; "
                           "refusing overwrite (use --uid-scope)")
    existing_labels = existing.get("labels")
    if not isinstance(existing_labels, dict):
        existing_labels = {}
    def org(value):
        if _is_forge_budget(rule) and (isinstance(value, bool) or not isinstance(value, (int, str))):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    conflicts = [field for field in ("uid", "folderUID", "ruleGroup") if existing.get(field) != rule.get(field)]
    if org(existing.get("orgID")) != org(rule.get("orgID")) or org(rule.get("orgID")) is None:
        conflicts.append("orgID")
    if not labels.get("origin") or existing_labels.get("origin") != labels["origin"]:
        conflicts.append("origin")
    if existing_labels.get("llmops_rule_identity") != expected_identity:
        conflicts.append("logical identity")
    if conflicts:
        raise GrafanaError(409, f"alert rule UID {uid} already belongs to an incompatible rule "
                           f"({', '.join(conflicts)}); refusing overwrite (use --uid-scope)")


def _assert_budget_response(existing, rule: dict):
    _assert_alert_ownership(existing, rule)
    if (type(existing.get("isPaused")) is not bool
            or any(not isinstance(existing.get(key), str) or not existing[key]
                   for key in ("title", "condition", "for", "noDataState", "execErrState"))
            or not isinstance(existing.get("data"), list) or not existing["data"]
            or any(not isinstance(query, dict) for query in existing["data"])
            or not isinstance(existing.get("annotations"), dict)):
        raise GrafanaError(502, f"budget alert {rule['uid']} returned an incomplete rule or ambiguous pause state")


class GrafanaClient:
    def __init__(self, url: str | None = None, token: str | None = None,
                 timeout: int = 20, retries: int = 3, insecure: bool = False):
        self.base = (url or os.environ.get("GRAFANA_URL", "")).rstrip("/")
        if not self.base:
            raise SystemExit("GRAFANA_URL manquant (export GRAFANA_URL=https://...)")
        self.token = token or os.environ.get("GRAFANA_TOKEN", "")
        self.user = os.environ.get("GRAFANA_USER", "")
        self.password = os.environ.get("GRAFANA_PASSWORD", "")
        if not self.token and not (self.user and self.password):
            raise SystemExit("Auth manquante : GRAFANA_TOKEN ou GRAFANA_USER/GRAFANA_PASSWORD")
        self.timeout = timeout
        self.retries = retries
        self.ctx = ssl._create_unverified_context() if insecure else None
        self._origin = normalized_http_origin(self.base)
        handlers = [SameOriginRedirectHandler(self._origin)]
        if self.ctx is not None:
            handlers.append(urllib.request.HTTPSHandler(context=self.ctx))
        self._opener = urllib.request.build_opener(*handlers)
        self._health = None
        self._namespace = None
        self._scoped_org_id = None

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        else:
            cred = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            h["Authorization"] = f"Basic {cred}"
        if self._scoped_org_id is not None:
            h["X-Grafana-Org-Id"] = str(self._scoped_org_id)
        return h

    def request(self, method: str, path: str, payload=None, params: dict | None = None,
                raw: bool = False):
        method = method.upper()
        url = self.base + path
        if params:
            sep = "&" if "?" in url else "?"
            url += sep + urllib.parse.urlencode(params, doseq=True)
        data = json.dumps(payload).encode() if payload is not None else None
        last_err = None
        retryable = method in {"GET", "HEAD", "OPTIONS", "PUT"}
        attempts = max(1, self.retries) if retryable else 1
        for attempt in range(attempts):
            req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
            try:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8", "replace")
                    if raw:
                        return body
                    if not body.strip():
                        return {}
                    try:
                        return json.loads(body)
                    except json.JSONDecodeError as e:
                        raise GrafanaError(resp.status, "invalid JSON response",
                                           body[:2000]) from e
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:2000]
                if (e.code in (429, 500, 502, 503, 504)
                        and attempt < attempts - 1):
                    time.sleep(1.5 * (attempt + 1))
                    last_err = GrafanaError(e.code, "request failed", body)
                    continue
                raise GrafanaError(e.code, "request failed", body)
            except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
                if attempt < attempts - 1:
                    time.sleep(1.5 * (attempt + 1))
                    last_err = e
                    continue
                raise SystemExit("Instance Grafana injoignable") from None
        raise last_err  # pragma: no cover

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def get_bytes(self, path, params: dict | None = None) -> tuple[bytes, str]:
        """GET binaire (rendus PNG). → (bytes, content_type)."""
        url = self.base + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with self._opener.open(req, timeout=max(self.timeout, 90)) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise GrafanaError(e.code, "request failed",
                               e.read().decode("utf-8", "replace")[:500])
        except (urllib.error.URLError, TimeoutError, ssl.SSLError):
            raise SystemExit("Instance Grafana injoignable") from None

    def post(self, path, payload=None, **kw):
        return self.request("POST", path, payload=payload, **kw)

    def put(self, path, payload=None, **kw):
        return self.request("PUT", path, payload=payload, **kw)

    # Pas de méthode delete() : le client ne peut physiquement pas supprimer un
    # dashboard, un dossier, une datasource ni une règle. La garantie de rayon de
    # souffle devient structurelle plutôt que conventionnelle ; un comité de
    # changement peut le vérifier en lisant ce fichier. Le retour arrière est une
    # action de l'exploitant (README, « What it touches »).

    # -------------------------------------------------------- Identité instance
    def health(self) -> dict:
        if self._health is None:
            self._health = self.get("/api/health")
        return self._health

    def version(self) -> str:
        return str(self.health().get("version", "unknown"))

    def major_version(self) -> int:
        m = re.match(r"(\d+)", self.version())
        return int(m.group(1)) if m else 0

    def _is_grafana_cloud_host(self) -> bool:
        hostname = self._origin[1].lower().rstrip(".")
        return hostname == "grafana.net" or hostname.endswith(".grafana.net")

    def edition(self) -> str:
        """oss | enterprise | cloud (heuristique robuste)."""
        if self._is_grafana_cloud_host():
            return "cloud"
        try:
            lic = self.get("/api/licensing/check")
            if isinstance(lic, dict) and lic.get("status") not in (None, 0, "", "invalid"):
                return "enterprise"
        except GrafanaError:
            pass
        try:
            fs = self.get("/api/frontend/settings")
            ed = str(fs.get("buildInfo", {}).get("edition", "")).lower()
            if "enterprise" in ed:
                return "enterprise"
        except GrafanaError:
            pass
        return "oss"

    def org_id(self) -> int:
        """Org courante du token ; ne jamais supposer 1 (multi-org Enterprise/Cloud)."""
        try:
            body = self.get("/api/org")
            org_id = int(body["id"])
        except KeyError as e:
            raise GrafanaError(502, "invalid /api/org response: missing id",
                               repr(body)) from e
        except (ValueError, TypeError) as e:
            raise GrafanaError(502, "invalid /api/org response: id is not an integer",
                               repr(body)) from e
        if org_id <= 0:
            raise GrafanaError(502, "invalid /api/org response: id must be positive",
                               repr(body))
        return org_id

    def resolve_org(self, requested_org_id: int | None = None) -> int:
        """Scope les requêtes et confirme l'organisation réellement effective.

        ``X-Grafana-Org-Id`` est supporté par les versions Grafana couvertes.
        Certains jetons restent néanmoins liés à leur organisation et ignorent
        l'en-tête. Le GET ``/api/org`` est donc obligatoire après sélection :
        aucune opération ne continue sur une organisation non confirmée.
        """
        previous = self._scoped_org_id
        if requested_org_id is not None:
            try:
                requested = int(requested_org_id)
            except (TypeError, ValueError) as e:
                raise GrafanaError(400, "org id must be an integer") from e
            if requested <= 0:
                raise GrafanaError(400, "org id must be a positive integer")
            self._scoped_org_id = requested
            try:
                effective = self.org_id()
            except GrafanaError as e:
                self._scoped_org_id = previous
                raise GrafanaError(
                    e.status, f"unable to confirm organization: {e}", e.body) from e
            except SystemExit:
                self._scoped_org_id = previous
                raise
            if effective != requested:
                self._scoped_org_id = previous
                raise GrafanaError(
                    409,
                    f"requested organization {requested}, but Grafana confirmed "
                    f"organization {effective}; refusing unscoped requests")
            return effective

        try:
            effective = self.org_id()
        except GrafanaError as e:
            raise GrafanaError(
                e.status, f"unable to confirm organization: {e}", e.body) from e
        self._scoped_org_id = effective
        return effective

    @staticmethod
    def has_exemplar_link(ds: dict) -> bool:
        """La datasource sait-elle router un exemplar vers Tempo ?"""
        dest = (ds.get("jsonData") or {}).get("exemplarTraceIdDestinations") or []
        return any(d.get("datasourceUid") or d.get("datasourceUID") for d in dest)

    def contact_points(self) -> list:
        try:
            return self.get("/api/v1/provisioning/contact-points") or []
        except GrafanaError:
            return []

    def namespace(self) -> str:
        """Namespace des APIs resource : 'default' (self-hosted) ou 'stacks-<id>' (Cloud)."""
        if self._namespace:
            return self._namespace
        if self._is_grafana_cloud_host():
            try:
                fs = self.get("/api/frontend/settings")
                ns = fs.get("namespace") or ""
                if ns:
                    self._namespace = ns
                    return ns
            except GrafanaError:
                pass
            self._namespace = "default"  # dernier recours ; l'API legacy reste utilisée
        else:
            self._namespace = "default"
        return self._namespace

    def has_resource_api(self) -> bool:
        try:
            self.get(f"/apis/dashboard.grafana.app/v1/namespaces/{self.namespace()}/dashboards",
                     params={"limit": 1})
            return True
        except (GrafanaError, SystemExit):
            return False

    # ---------------------------------------------------------------- Datasources
    def datasources(self) -> list:
        body = self.get("/api/datasources")
        if not isinstance(body, list):
            raise GrafanaError(502, "invalid datasource list response", repr(body)[:2000])
        return body

    def prometheus_like(self) -> list:
        return [d for d in self.datasources()
                if d.get("type") in ("prometheus", "grafana-amazonprometheus-datasource",
                                     "grafana-azureprometheus-datasource")
                or "mimir" in (d.get("type") or "")]

    def lokis(self) -> list:
        return [d for d in self.datasources() if d.get("type") == "loki"]

    def tempos(self) -> list:
        return [d for d in self.datasources() if d.get("type") == "tempo"]

    def ds_proxy(self, ds: dict, subpath: str, params: dict | None = None):
        """Requête via le proxy datasource. Préfère l'UID (stable), fallback ID (vieilles versions)."""
        uid = ds.get("uid")
        try:
            return self.get(f"/api/datasources/proxy/uid/{uid}/{subpath.lstrip('/')}", params=params)
        except GrafanaError as e:
            if e.status == 404 and ds.get("id"):
                return self.get(f"/api/datasources/proxy/{ds['id']}/{subpath.lstrip('/')}",
                                params=params)
            raise

    def prom_metric_names(self, ds: dict, match: str) -> list:
        """Noms de métriques matchant un sélecteur ; le cœur du discovery-first."""
        r = self.ds_proxy(ds, "api/v1/label/__name__/values",
                          params={"match[]": promql_matcher("__name__", "=~", match)})
        return sorted(self._proxy_list(r, "Prometheus metric names"))

    def prom_label_values(self, ds: dict, label: str, match: str | None = None) -> list:
        params = {"match[]": match} if match else None
        r = self.ds_proxy(ds, f"api/v1/label/{label}/values", params=params)
        return self._proxy_list(r, f"Prometheus label {label}")

    def loki_labels(self, ds: dict) -> list:
        r = self.ds_proxy(ds, "loki/api/v1/labels")
        return self._proxy_list(r, "Loki labels")

    @staticmethod
    def _proxy_list(body, operation: str) -> list:
        """Valide une réponse proxy : seul ``data: []`` est un vide sain."""
        if (not isinstance(body, dict) or body.get("status") == "error"
                or not isinstance(body.get("data"), list)):
            raise GrafanaError(502, f"invalid {operation} proxy response",
                               repr(body)[:2000])
        return body["data"]

    # ------------------------------------------------------------------ Folders
    def ensure_folder(self, title: str, uid: str | None = None) -> dict:
        uid = uid or det_uid(title, "fold")
        try:
            return self.get(f"/api/folders/{uid}")
        except GrafanaError as e:
            if e.status != 404:
                raise
        return self.post("/api/folders", {"uid": uid, "title": title})

    # --------------------------------------------------------------- Dashboards
    def upsert_dashboard(self, dashboard: dict, folder_uid: str, message: str = "forge") -> dict:
        """Upsert via API legacy (universelle). Fallback API resource si legacy indisponible."""
        uid = dashboard.get("uid") or det_uid(dashboard.get("title", "dash"))
        try:
            existing = self.get(f"/api/dashboards/uid/{uid}")
        except GrafanaError as e:
            if e.status != 404:
                raise
        else:
            existing_folder = ((existing.get("meta") or {}).get("folderUid")
                               if isinstance(existing, dict) else None)
            if existing_folder != folder_uid:
                detail = existing_folder if existing_folder is not None else "unknown"
                raise GrafanaError(
                    409,
                    f"dashboard UID {uid} already exists in folder {detail}; "
                    "refusing cross-folder overwrite (use --uid-scope)",
                    repr(existing)[:2000])
        payload = {"dashboard": dashboard, "folderUid": folder_uid,
                   "overwrite": True, "message": message}
        try:
            return self.post("/api/dashboards/db", payload)
        except GrafanaError as e:
            if e.status not in (404, 405):
                raise
        # Fallback K8s-style (instances futures où l'API legacy serait retirée)
        ns = self.namespace()
        name = uid
        body = {"metadata": {"name": name,
                             "annotations": {"grafana.app/folder": folder_uid,
                                             "grafana.app/message": message}},
                "spec": dashboard}
        try:
            return self.put(f"/apis/dashboard.grafana.app/v1/namespaces/{ns}/dashboards/{name}",
                            body)
        except GrafanaError as e:
            if e.status == 404:
                return self.post(f"/apis/dashboard.grafana.app/v1/namespaces/{ns}/dashboards", body)
            raise

    def dashboard_url(self, result: dict, dashboard: dict) -> str:
        if isinstance(result, dict) and result.get("url"):
            return self.base + result["url"]
        uid = (result.get("uid") if isinstance(result, dict) else None) or dashboard.get("uid", "")
        return f"{self.base}/d/{uid}"

    # ----------------------------------------------------------------- Alerting
    def upsert_alert_rule(self, rule: dict) -> dict:
        """Provisioning API (Grafana ≥ 9.4). Idempotent via UID déterministe."""
        uid = rule["uid"]
        expected_identity = (rule.get("labels") or {}).get("llmops_rule_identity")
        if not isinstance(expected_identity, str) or not expected_identity:
            raise GrafanaError(
                400, f"alert rule {uid} has no logical identity; refusing write")
        try:
            existing = self.get(f"/api/v1/provisioning/alert-rules/{uid}")
        except GrafanaError as e:
            if e.status == 404:
                return self.post("/api/v1/provisioning/alert-rules", rule)
            raise

        _assert_alert_ownership(existing, rule)
        if _is_forge_budget(rule):
            _assert_budget_response(existing, rule)
            # Coverage recovery updates the calculation but never silently resumes a budget.
            payload = dict(rule, isPaused=existing["isPaused"])
            result = self.put(f"/api/v1/provisioning/alert-rules/{uid}", payload)
            _assert_budget_response(result, rule)
            if result["isPaused"] != payload["isPaused"]:
                raise GrafanaError(502, f"budget alert {uid}: pause preservation was not confirmed")
            return result
        return self.put(f"/api/v1/provisioning/alert-rules/{uid}", rule)

    def pause_budget_alert_rule(self, rule: dict) -> str:
        """Pause one owned budget in its resolved scope; never create or list rules."""
        if not _is_forge_budget(rule):
            raise GrafanaError(400, "refusing to pause anything other than the Forge financial budget")
        uid = rule["uid"]
        path = f"/api/v1/provisioning/alert-rules/{uid}"
        try:
            existing = self.get(path)
        except GrafanaError as error:
            if error.status == 404:
                return "absent"
            raise
        _assert_budget_response(existing, rule)
        if existing["isPaused"]:
            return "already_paused"
        payload = copy.deepcopy(existing)
        payload["isPaused"] = True
        result = self.put(path, payload)
        _assert_budget_response(result, rule)
        if result["isPaused"] is not True:
            raise GrafanaError(502, f"budget alert {uid}: pause was not confirmed")
        return "paused"


if __name__ == "__main__":
    c = GrafanaClient()
    print(json.dumps({"version": c.version(), "edition": c.edition(),
                      "namespace": c.namespace(),
                      "resource_api": c.has_resource_api()},
                     indent=2), file=sys.stdout)
