"""Client Grafana universel — OSS / Cloud / Enterprise, Grafana 9 → 13+.

Zéro dépendance externe (stdlib uniquement) : portable partout où Python 3.8+ existe.
Auth : GRAFANA_TOKEN (service account, recommandé) ou GRAFANA_USER/GRAFANA_PASSWORD.
Gère les deux générations d'API :
  - legacy      /api/...                          (universelle, v9+)
  - resource    /apis/dashboard.grafana.app/...   (K8s-style, v12+, namespacée)
Le token n'est jamais loggé.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class GrafanaError(RuntimeError):
    def __init__(self, status, message, body=""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.body = body


def det_uid(name: str, prefix: str = "llmops") -> str:
    """UID déterministe (≤40 chars) : relancer la forge met à jour, ne duplique jamais."""
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:26]
    return f"{prefix}-{slug}-{h}"[:40]


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
        self._health = None
        self._namespace = None

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        else:
            cred = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            h["Authorization"] = f"Basic {cred}"
        return h

    def request(self, method: str, path: str, payload=None, params: dict | None = None,
                raw: bool = False):
        url = self.base + path
        if params:
            sep = "&" if "?" in url else "?"
            url += sep + urllib.parse.urlencode(params, doseq=True)
        data = json.dumps(payload).encode() if payload is not None else None
        last_err = None
        for attempt in range(self.retries):
            req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                    body = resp.read().decode("utf-8", "replace")
                    if raw:
                        return body
                    return json.loads(body) if body.strip() else {}
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:2000]
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    last_err = GrafanaError(e.code, e.reason, body)
                    continue
                raise GrafanaError(e.code, e.reason, body)
            except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
                if attempt < self.retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    last_err = e
                    continue
                raise SystemExit(f"Instance injoignable ({self.base}) : {e}")
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
            with urllib.request.urlopen(req, timeout=max(self.timeout, 90),
                                        context=self.ctx) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise GrafanaError(e.code, e.reason, e.read().decode("utf-8", "replace")[:500])

    def post(self, path, payload=None, **kw):
        return self.request("POST", path, payload=payload, **kw)

    def put(self, path, payload=None, **kw):
        return self.request("PUT", path, payload=payload, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

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

    def edition(self) -> str:
        """oss | enterprise | cloud (heuristique robuste)."""
        if ".grafana.net" in self.base:
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
        """Org courante du token — ne jamais supposer 1 (multi-org Enterprise/Cloud)."""
        try:
            return int(self.get("/api/org").get("id", 1))
        except (GrafanaError, ValueError, TypeError):
            return 1

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
        if ".grafana.net" in self.base:
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
        return self.get("/api/datasources")

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
        """Noms de métriques matchant un sélecteur — le cœur du discovery-first."""
        try:
            r = self.ds_proxy(ds, "api/v1/label/__name__/values",
                              params={"match[]": f'{{__name__=~"{match}"}}'})
            return sorted(r.get("data", []) or [])
        except GrafanaError:
            return []

    def prom_label_values(self, ds: dict, label: str, match: str | None = None) -> list:
        params = {"match[]": match} if match else None
        try:
            r = self.ds_proxy(ds, f"api/v1/label/{label}/values", params=params)
            return r.get("data", []) or []
        except GrafanaError:
            return []

    def loki_labels(self, ds: dict) -> list:
        try:
            r = self.ds_proxy(ds, "loki/api/v1/labels")
            return r.get("data", []) or []
        except GrafanaError:
            return []

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
        payload = {"dashboard": dashboard, "folderUid": folder_uid,
                   "overwrite": True, "message": message}
        try:
            return self.post("/api/dashboards/db", payload)
        except GrafanaError as e:
            if e.status not in (404, 405):
                raise
        # Fallback K8s-style (instances futures où l'API legacy serait retirée)
        ns = self.namespace()
        name = dashboard.get("uid") or det_uid(dashboard.get("title", "dash"))
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
        try:
            self.get(f"/api/v1/provisioning/alert-rules/{uid}")
            return self.put(f"/api/v1/provisioning/alert-rules/{uid}", rule)
        except GrafanaError as e:
            if e.status == 404:
                return self.post("/api/v1/provisioning/alert-rules", rule)
            raise


if __name__ == "__main__":
    c = GrafanaClient()
    print(json.dumps({"version": c.version(), "edition": c.edition(),
                      "namespace": c.namespace(),
                      "resource_api": c.has_resource_api()},
                     indent=2), file=sys.stdout)
