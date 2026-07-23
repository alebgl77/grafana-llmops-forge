"""Audit visuel : capture le rendu réel des dashboards pour inspection par vision.

Deux moteurs, sélection automatique :
  renderer   — /render/... natif Grafana (plugin grafana-image-renderer ; inclus
               sur Grafana Cloud). PNG côté serveur, zéro dépendance locale.
  playwright — vrai navigateur headless (auth par header Bearer, mode kiosk),
               avec pré-scan DOM ("No data", erreurs de panel) avant la vision.
               Requiert : pip install playwright && playwright install chromium

Les PNG produits sont ensuite LUS PAR CLAUDE (vision) avec la checklist de
references/visual_verification.md. Ce script capture et pré-diagnostique ;
il ne juge pas la cohérence sémantique — c'est le rôle de la vision.

Usage :
    python3 visual_audit.py --dashboards generated_dashboards --out visual_audit
    python3 visual_audit.py --uids llmops-ai-executive-finops-xxxx --engine playwright
    python3 visual_audit.py --dashboards generated_dashboards --list-only
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grafana_client import GrafanaClient, GrafanaError  # noqa: E402

DOM_MARKERS = ["No data", "Panel plugin not found", "Datasource not found",
               "Error updating options", "Unauthorized", "Templating",
               "failed to load", "too many outstanding requests"]
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
        return ctype.startswith("image/") and len(data) > 500
    except (GrafanaError, SystemExit):
        return False


def capture_renderer(client: GrafanaClient, dash: dict, out: str, args) -> dict:
    res = {"engine": "renderer", "files": [], "warnings": []}
    common = {"from": args.time_from, "to": args.time_to, "timeout": 90,
              "tz": "UTC", "kiosk": "1"}
    try:
        data, ctype = client.get_bytes(
            f"/render/d/{dash['uid']}/x",
            params={**common, "width": args.width, "height": args.full_height})
        if ctype.startswith("image/"):
            p = os.path.join(out, "full.png")
            open(p, "wb").write(data)
            res["files"].append(p)
    except GrafanaError as e:
        res["warnings"].append(f"rendu pleine page indisponible ({e.status}) — "
                               "captures par panel uniquement")
    for pan in dash.get("panels", []):
        if pan["type"] not in VISION_PANEL_TYPES:
            continue
        try:
            data, ctype = client.get_bytes(
                f"/render/d-solo/{dash['uid']}/x",
                params={**{k: v for k, v in common.items() if k != "kiosk"},
                        "panelId": pan["id"], "width": 1000, "height": 500})
            if ctype.startswith("image/"):
                p = os.path.join(out, f"panel_{pan['id']:02d}_{slug(pan['title'])}.png")
                open(p, "wb").write(data)
                res["files"].append(p)
        except GrafanaError as e:
            res["warnings"].append(f"panel {pan['id']} « {pan['title']} » : "
                                   f"rendu KO ({e.status})")
    return res


# --------------------------------------------------------------------------- #
#  Moteur 2 : Playwright (navigateur réel + pré-scan DOM)                     #
# --------------------------------------------------------------------------- #

def capture_playwright(client: GrafanaClient, dash: dict, out: str, args) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright absent. Installer :\n"
              "  pip install playwright && playwright install chromium",
              file=sys.stderr)
        sys.exit(3)
    res = {"engine": "playwright", "files": [], "warnings": [], "dom_findings": {}}
    headers = {}
    if client.token:
        headers["Authorization"] = f"Bearer {client.token}"
    cookie = os.environ.get("GRAFANA_COOKIE", "")
    if cookie:  # setups derrière SSO/proxy où le Bearer ne passe pas
        headers["Cookie"] = cookie
    url = (f"{client.base}/d/{dash['uid']}/x?orgId=1&kiosk"
           f"&from={args.time_from}&to={args.time_to}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(
            extra_http_headers=headers, device_scale_factor=2,
            viewport={"width": args.width, "height": 950},
            ignore_https_errors=args.insecure).new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(args.settle_ms)  # laisser les requêtes finir
        body = page.inner_text("body")
        for marker in DOM_MARKERS:
            n = body.count(marker)
            if n:
                res["dom_findings"][marker] = n
        p = os.path.join(out, "full.png")
        page.screenshot(path=p, full_page=True)
        res["files"].append(p)
        for pan in dash.get("panels", []):
            if pan["type"] not in VISION_PANEL_TYPES:
                continue
            page.goto(url + f"&viewPanel={pan['id']}",
                      wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(max(args.settle_ms // 2, 1500))
            p = os.path.join(out, f"panel_{pan['id']:02d}_{slug(pan['title'])}.png")
            page.screenshot(path=p)
            res["files"].append(p)
        browser.close()
    return res


# --------------------------------------------------------------------------- #
#  CLI                                                                        #
# --------------------------------------------------------------------------- #

def main() -> int:
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
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()

    plan = load_plan(args)
    if not plan:
        print("Aucun dashboard à capturer (ni manifeste, ni JSON, ni --uids).",
              file=sys.stderr)
        return 2
    if args.list_only:
        for d in plan:
            vis = [p for p in d.get("panels", []) if p["type"] in VISION_PANEL_TYPES]
            print(f"{d['uid']}  « {d['title']} »  — full + {len(vis)} panel(s)")
        return 0

    client = GrafanaClient(insecure=args.insecure)
    engine = args.engine
    if engine == "auto":
        engine = "renderer" if renderer_available(client, plan[0]["uid"]) else "playwright"
        print(f"Moteur sélectionné : {engine}"
              + ("" if engine == "renderer"
                 else "  (renderer natif absent — voir visual_verification.md §renderer)"))

    manifest = {"engine": engine, "grafana": client.base,
                "time": {"from": args.time_from, "to": args.time_to},
                "dashboards": []}
    for dash in plan:
        out = os.path.join(args.out, slug(dash["title"]))
        os.makedirs(out, exist_ok=True)
        try:
            cap = (capture_renderer if engine == "renderer" else capture_playwright)(
                client, dash, out, args)
        except SystemExit:
            raise
        except Exception as e:  # un dashboard KO ne bloque pas les autres
            cap = {"engine": engine, "files": [],
                   "warnings": [f"capture impossible : {type(e).__name__}: {e}"]}
        entry = {"uid": dash["uid"], "title": dash["title"], **cap,
                 "panel_index": {f"panel_{p['id']:02d}": p["title"]
                                 for p in dash.get("panels", [])}}
        manifest["dashboards"].append(entry)
        print(f"[ok] {dash['title']} : {len(cap['files'])} capture(s) → {out}/")
        for w in cap.get("warnings", []):
            print(f"     ⚠ {w}")
        for m, n in cap.get("dom_findings", {}).items():
            print(f"     ⚠ DOM: « {m} » ×{n}")
        time.sleep(0.3)

    mpath = os.path.join(args.out, "audit_manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"\nManifeste → {mpath}")
    print("SUITE OBLIGATOIRE : ouvrir les PNG (vision) et appliquer la checklist "
          "de references/visual_verification.md — commencer par full.png de "
          "chaque dashboard, puis les panels signalés douteux.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
