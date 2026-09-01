"""Audit visuel : capture le rendu réel des dashboards pour inspection par vision.

Deux moteurs, sélection automatique :
  renderer   : /render/... natif Grafana (plugin grafana-image-renderer ; inclus
               sur Grafana Cloud). PNG côté serveur, zéro dépendance locale.
  playwright : vrai navigateur headless (auth Grafana limitée à son origine,
               mode kiosk),
               avec pré-scan DOM ("No data", erreurs de panel) avant la vision.
               Requiert : pip install playwright && playwright install chromium

Les PNG produits sont ensuite LUS PAR CLAUDE (vision) avec la checklist de
references/visual_verification.md. Ce script capture et pré-diagnostique ;
il ne juge pas la cohérence sémantique ; c'est le rôle de la vision.

Usage :
    python3 visual_audit.py --dashboards generated_dashboards --out visual_audit
    python3 visual_audit.py --uids llmops-ai-executive-finops-xxxx --engine playwright
    python3 visual_audit.py --dashboards generated_dashboards --list-only
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import re
import sys
import time
import urllib.parse
from http.cookies import SimpleCookie

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grafana_client import GrafanaClient, GrafanaError  # noqa: E402

DOM_MARKERS = ["No data", "Panel plugin not found", "Datasource not found",
               "Error updating options", "Unauthorized", "Templating",
               "failed to load", "too many outstanding requests",
               "Welcome to Grafana", "Sign in to Grafana", "Log in to Grafana",
               "Forgot your password?"]
CRITICAL_DOM_MARKERS = set(DOM_MARKERS) - {"No data"}
VISION_PANEL_TYPES = {"timeseries", "stat", "table", "barchart", "piechart",
                      "heatmap", "gauge"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "x"


# --------------------------------------------------------------------------- #
#  Plan de capture : quels dashboards, quels panels                           #
# --------------------------------------------------------------------------- #

def load_plan(args) -> list[dict]:
    plan = []
    if args.dashboards:
        mpath = os.path.join(args.dashboards, "deploy_manifest.json")
        if os.path.exists(mpath):
            with open(mpath, encoding="utf-8") as f:
                plan = json.load(f).get("dashboards", [])
        else:
            for path in sorted(glob.glob(os.path.join(args.dashboards, "*.json"))):
                if "alert_" in os.path.basename(path) or "manifest" in path:
                    continue
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                if "panels" not in d:
                    continue
                plan.append({"uid": d["uid"], "title": d["title"],
                             "panels": [{"id": p["id"], "title": p.get("title", ""),
                                         "type": p["type"]} for p in d["panels"]]})
    for uid in (args.uids.split(",") if args.uids else []):
        plan.append({"uid": uid.strip(), "title": uid.strip(), "panels": []})
    return plan


# --------------------------------------------------------------------------- #
#  Moteur 1 : renderer natif Grafana                                          #
# --------------------------------------------------------------------------- #

def renderer_available(client: GrafanaClient, uid: str) -> bool:
    try:
        data, ctype = client.get_bytes(f"/render/d-solo/{uid}/x",
                                       params={"panelId": 1, "width": 80,
                                               "height": 60, "timeout": 30})
    except GrafanaError as e:
        if e.status == 404:
            return False
        raise
    if not ctype.startswith("image/") or len(data) <= 500:
        raise GrafanaError(502, "renderer probe returned no valid image",
                           f"content-type={ctype!r}, bytes={len(data)}")
    return True


def capture_renderer(client: GrafanaClient, dash: dict, out: str, args) -> dict:
    res = {"engine": "renderer", "files": [], "warnings": []}
    common = {"from": args.time_from, "to": args.time_to, "timeout": 90,
              "tz": "UTC", "kiosk": "1", "orgId": args.resolved_org_id}
    data, ctype = client.get_bytes(
        f"/render/d/{dash['uid']}/x",
        params={**common, "width": args.width, "height": args.full_height})
    if not ctype.startswith("image/") or len(data) <= 500:
        raise GrafanaError(502, "renderer returned no valid full-dashboard image",
                           f"content-type={ctype!r}, bytes={len(data)}")
    p = os.path.join(out, "full.png")
    open(p, "wb").write(data)
    res["files"].append(p)
    for pan in dash.get("panels", []):
        if pan["type"] not in VISION_PANEL_TYPES:
            continue
        data, ctype = client.get_bytes(
            f"/render/d-solo/{dash['uid']}/x",
            params={**{k: v for k, v in common.items() if k != "kiosk"},
                    "panelId": pan["id"], "width": 1000, "height": 500})
        if not ctype.startswith("image/") or len(data) <= 500:
            raise GrafanaError(502, f"renderer returned no valid image for panel {pan['id']}",
                               f"content-type={ctype!r}, bytes={len(data)}")
        p = os.path.join(out, f"panel_{pan['id']:02d}_{slug(pan['title'])}.png")
        open(p, "wb").write(data)
        res["files"].append(p)
    return res


# --------------------------------------------------------------------------- #
#  Moteur 2 : Playwright (navigateur réel + pré-scan DOM)                     #
# --------------------------------------------------------------------------- #

def playwright_dashboard_url(client: GrafanaClient, dash: dict, args) -> str:
    return (f"{client.base}/d/{dash['uid']}/x?orgId={args.resolved_org_id}&kiosk"
            f"&from={args.time_from}&to={args.time_to}")


def _url_origin(parts) -> tuple:
    try:
        scheme = parts.scheme.lower()
        port = parts.port or ({"http": 80, "https": 443}.get(scheme))
        return scheme, (parts.hostname or "").lower(), port
    except ValueError as e:
        raise GrafanaError(502, "Playwright navigation returned an invalid URL",
                           parts.geturl()) from e


def _dashboard_prefix(parts) -> tuple[str, str] | None:
    segments = parts.path.split("/")
    try:
        index = segments.index("d")
        uid = urllib.parse.unquote(segments[index + 1])
    except (ValueError, IndexError):
        return None
    prefix = "/".join(segments[:index + 2])
    return prefix, uid


def _checked_goto(page, url: str, timeout: int = 60000):
    response = page.goto(url, wait_until="networkidle", timeout=timeout)
    status = getattr(response, "status", None)
    if not isinstance(status, int):
        raise GrafanaError(502, "Playwright navigation returned no HTTP status", url)
    if status < 200 or status >= 300:
        raise GrafanaError(status, "Playwright navigation failed", url)
    final_url = getattr(page, "url", "") or getattr(response, "url", "")
    requested, final = urllib.parse.urlsplit(url), urllib.parse.urlsplit(final_url)
    if not final_url or _url_origin(final) != _url_origin(requested):
        raise GrafanaError(403, "Playwright navigation left the Grafana origin",
                           final_url or "missing final URL")
    final_segments = {segment.casefold() for segment in final.path.split("/") if segment}
    if final_segments & {"login", "signin", "sign-in"}:
        raise GrafanaError(401, "Playwright was redirected to a login page", final_url)
    expected_dashboard = _dashboard_prefix(requested)
    actual_dashboard = _dashboard_prefix(final)
    if (expected_dashboard is None or actual_dashboard is None
            or actual_dashboard[1] != expected_dashboard[1]
            or (actual_dashboard[0] != expected_dashboard[0]
                and not actual_dashboard[0].startswith(expected_dashboard[0] + "/"))):
        raise GrafanaError(403, "Playwright left the expected dashboard", final_url)
    return response


def _scan_dom(body: str, findings: dict) -> None:
    folded = body.casefold()
    for marker in DOM_MARKERS:
        n = folded.count(marker.casefold())
        if n:
            findings[marker] = findings.get(marker, 0) + n


def _scoped_request_headers(client: GrafanaClient, request_url: str,
                            request_headers: dict) -> dict:
    """Injecte les secrets Grafana uniquement sur son origine exacte."""
    headers = dict(request_headers)
    secret_names = {"authorization", "cookie", "x-grafana-org-id"}
    same_origin = (_url_origin(urllib.parse.urlsplit(request_url)) == _url_origin(
        urllib.parse.urlsplit(client.base)))
    for name in list(headers):
        if name.casefold() in secret_names and (not same_origin or name.casefold() != "cookie"):
            del headers[name]
    if not same_origin:
        return headers
    if client.token:
        headers["Authorization"] = f"Bearer {client.token}"
    elif client.user and client.password:
        encoded = base64.b64encode(
            f"{client.user}:{client.password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    if client._scoped_org_id is not None:
        headers["X-Grafana-Org-Id"] = str(client._scoped_org_id)
    return headers


def _playwright_cookies(client: GrafanaClient) -> list[dict]:
    raw = os.environ.get("GRAFANA_COOKIE", "")
    if not raw:
        return []
    parsed = urllib.parse.urlsplit(client.base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise GrafanaError(400, "invalid Grafana origin for Playwright cookies",
                           client.base)
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception as e:
        raise GrafanaError(400, "invalid GRAFANA_COOKIE") from e
    if not jar:
        raise GrafanaError(400, "invalid GRAFANA_COOKIE")
    path = parsed.path.rstrip("/") or "/"
    return [{"name": name, "value": morsel.value, "domain": parsed.hostname,
             "path": path, "secure": parsed.scheme == "https", "sameSite": "Lax"}
            for name, morsel in jar.items()]


def _basic_http_credentials(client: GrafanaClient) -> dict | None:
    if client.token or not (client.user and client.password):
        return None
    parsed = urllib.parse.urlsplit(client.base)
    origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    return {"username": client.user, "password": client.password, "origin": origin}


def _route_grafana_request(client: GrafanaClient, route, request) -> None:
    source_headers = (request.all_headers() if hasattr(request, "all_headers")
                      else request.headers)
    route.continue_(headers=_scoped_request_headers(
        client, request.url, source_headers))


def capture_playwright(client: GrafanaClient, dash: dict, out: str, args) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright absent. Installer :\n"
              "  pip install playwright && playwright install chromium",
              file=sys.stderr)
        raise RuntimeError("Playwright is not installed")
    res = {"engine": "playwright", "files": [], "warnings": [], "dom_findings": {}}
    url = playwright_dashboard_url(client, dash, args)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context_args = {
            "device_scale_factor": 2,
            "viewport": {"width": args.width, "height": 950},
            "ignore_https_errors": args.insecure,
        }
        credentials = _basic_http_credentials(client)
        if credentials:
            context_args["http_credentials"] = credentials
        try:
            context = browser.new_context(**context_args)
        except Exception as e:
            # Les anciennes versions de Playwright ne connaissent pas ``origin``.
            # Ne jamais retomber sur des credentials globaux : le routeur same-origin
            # ci-dessous assure alors lui-même Basic.
            if credentials and "origin" in str(e).casefold():
                context_args.pop("http_credentials", None)
                context = browser.new_context(**context_args)
            else:
                browser.close()
                raise
        cookies = _playwright_cookies(client)
        if cookies:
            context.add_cookies(cookies)
        context.route("**/*", lambda route, request:
                      _route_grafana_request(client, route, request))
        page = context.new_page()
        try:
            _checked_goto(page, url)
            page.wait_for_timeout(args.settle_ms)  # laisser les requêtes finir
            _scan_dom(page.inner_text("body"), res["dom_findings"])
            p = os.path.join(out, "full.png")
            page.screenshot(path=p, full_page=True)
            res["files"].append(p)
            for pan in dash.get("panels", []):
                if pan["type"] not in VISION_PANEL_TYPES:
                    continue
                _checked_goto(page, url + f"&viewPanel={pan['id']}")
                page.wait_for_timeout(max(args.settle_ms // 2, 1500))
                _scan_dom(page.inner_text("body"), res["dom_findings"])
                p = os.path.join(out, f"panel_{pan['id']:02d}_{slug(pan['title'])}.png")
                page.screenshot(path=p)
                res["files"].append(p)
        finally:
            try:
                context.close()
            finally:
                browser.close()
    return res


# --------------------------------------------------------------------------- #
#  CLI                                                                        #
# --------------------------------------------------------------------------- #

def _write_json_atomic(path: str, value: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _expected_files(dash: dict) -> list[str]:
    expected = ["full.png"]
    expected.extend(f"panel_{p['id']:02d}_{slug(p['title'])}.png"
                    for p in dash.get("panels", [])
                    if p["type"] in VISION_PANEL_TYPES)
    return expected

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dashboards", default="generated_dashboards",
                    help="Dossier des JSON forge (utilise deploy_manifest.json si présent)")
    ap.add_argument("--uids", default=None, help="UIDs additionnels, séparés par des virgules")
    ap.add_argument("--engine", choices=["auto", "renderer", "playwright"], default="auto")
    ap.add_argument("--out", default="visual_audit")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--full-height", type=int, default=2200)
    ap.add_argument("--time-from", default="now-24h")
    ap.add_argument("--time-to", default="now")
    ap.add_argument("--settle-ms", type=int, default=5000)
    ap.add_argument("--list-only", action="store_true",
                    help="Afficher le plan de capture sans réseau")
    ap.add_argument("--org-id", type=int, default=None,
                    help="Override explicite de l'organisation Grafana (sinon /api/org)")
    ap.add_argument("--allow-empty", action="store_true",
                    help="Retourner 0 uniquement si aucune capture n'a pu être produite "
                         "sans erreur HTTP/DOM critique; le manifeste reste failed")
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()

    if args.org_id is not None and args.org_id <= 0:
        ap.error("--org-id must be a positive integer")

    plan = load_plan(args)
    if args.list_only:
        if not plan:
            print("Aucun dashboard à capturer (ni manifeste, ni JSON, ni --uids).",
                  file=sys.stderr)
            return 2
        for d in plan:
            vis = [p for p in d.get("panels", []) if p["type"] in VISION_PANEL_TYPES]
            print(f"{d['uid']}  « {d['title']} » : full + {len(vis)} panel(s)")
        return 0

    try:
        client = GrafanaClient(insecure=args.insecure)
        args.resolved_org_id = client.resolve_org(args.org_id)
    except (GrafanaError, SystemExit) as e:
        print(f"[fail] unable to resolve Grafana organization: {e}", file=sys.stderr)
        return 2
    engine = args.engine
    manifest = {"schema": "grafana-llmops-forge/visual-audit-manifest",
                "version": 2, "audit_status": "success",
                "engine": engine, "grafana": client.base,
                "org_id": args.resolved_org_id,
                "time": {"from": args.time_from, "to": args.time_to},
                "errors": [], "dashboards": []}
    hard_failure = False
    if engine == "auto" and plan:
        try:
            engine = ("renderer" if renderer_available(client, plan[0]["uid"])
                      else "playwright")
        except (GrafanaError, SystemExit) as e:
            manifest["audit_status"] = "failed"
            hard_failure = True
            manifest["errors"].append(
                {"resource_type": "renderer-probe",
                 "status": getattr(e, "status", 0), "message": str(e)})
            os.makedirs(args.out, exist_ok=True)
            _write_json_atomic(os.path.join(args.out, "audit_manifest.json"), manifest)
            print(f"[fail] renderer probe failed: {e}", file=sys.stderr)
            return 4
        manifest["engine"] = engine
        print(f"Moteur sélectionné : {engine}"
              + ("" if engine == "renderer"
                 else "  (renderer natif absent ; voir visual_verification.md §renderer)"))
    if not plan:
        manifest["audit_status"] = "failed"
        manifest["errors"].append(
            {"resource_type": "capture-plan", "message": "no dashboard to capture"})
    for dash in plan:
        out = os.path.join(args.out, slug(dash["title"]))
        os.makedirs(out, exist_ok=True)
        try:
            cap = (capture_renderer if engine == "renderer" else capture_playwright)(
                client, dash, out, args)
        except (Exception, SystemExit) as e:  # un dashboard KO ne bloque pas les autres
            cap = {"engine": engine, "files": [],
                   "warnings": [f"capture impossible : {type(e).__name__}: {e}"]}
            hard_failure = True
            manifest["errors"].append(
                {"resource_type": "capture-engine", "uid": dash["uid"],
                 "status": getattr(e, "status", 0), "message": str(e)})
        entry = {"uid": dash["uid"], "title": dash["title"], **cap,
                 "panel_index": {f"panel_{p['id']:02d}": p["title"]
                                 for p in dash.get("panels", [])}}
        actual = {os.path.basename(p) for p in cap["files"]}
        missing = [name for name in _expected_files(dash) if name not in actual]
        entry["expected_files"] = _expected_files(dash)
        entry["missing_files"] = missing
        critical = {marker: count for marker, count in cap.get("dom_findings", {}).items()
                    if marker in CRITICAL_DOM_MARKERS}
        entry["critical_dom_findings"] = critical
        entry["status"] = "failed" if missing or critical else "success"
        if missing or critical:
            manifest["audit_status"] = "failed"
            for name in missing:
                manifest["errors"].append(
                    {"resource_type": "capture", "uid": dash["uid"],
                     "expected_file": name, "message": "expected capture is missing"})
            for marker, count in critical.items():
                hard_failure = True
                manifest["errors"].append(
                    {"resource_type": "critical-dom", "uid": dash["uid"],
                     "marker": marker, "count": count,
                     "message": "critical Grafana error marker is visible"})
        manifest["dashboards"].append(entry)
        print(f"[{'ok' if entry['status'] == 'success' else 'fail'}] {dash['title']} : "
              f"{len(cap['files'])} capture(s) -> {out}/")
        for w in cap.get("warnings", []):
            print(f"     [warn] {w}")
        for m, n in cap.get("dom_findings", {}).items():
            print(f"     [warn] DOM: '{m}' x{n}")
        time.sleep(0.3)

    mpath = os.path.join(args.out, "audit_manifest.json")
    os.makedirs(args.out, exist_ok=True)
    _write_json_atomic(mpath, manifest)
    print(f"\nManifest -> {mpath}")
    if manifest["audit_status"] == "failed":
        captures = sum(len(d.get("files", [])) for d in manifest["dashboards"])
        if not (args.allow_empty and captures == 0 and not hard_failure):
            return 4
    print("SUITE OBLIGATOIRE : ouvrir les PNG (vision) et appliquer la checklist "
          "de references/visual_verification.md ; commencer par full.png de "
          "chaque dashboard, puis les panels signalés douteux.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
