"""Grafana simulé pour les tests de panne : latence, 403 ciblés, réponses partielles.

Ce que le harnais hors ligne ne peut pas couvrir : le comportement quand une
instance répond mal. Un 403 de permissions en production doit produire un message
qu'un exploitant comprend, pas une trace Python.

    python3 tests/fake_grafana.py nofolder &   # puis pointer GRAFANA_URL dessus
"""

import hashlib, json, re, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
MODE = sys.argv[1] if len(sys.argv) > 1 else "ok"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9198
STATE = {}
class H(BaseHTTPRequestHandler):
    def _j(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _b(self, code, body, content_type):
        self.send_response(code); self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p = self.path.split("?")[0]
        if MODE == "slow": time.sleep(3)
        if MODE == "orgscope" and self.headers.get("X-Grafana-Org-Id") != "9":
            return self._j(412, {"message":"organization header missing"})
        if p == "/api/health": return self._j(200, {"version":"11.2.0","database":"ok"})
        if p == "/api/org":
            if MODE == "noorg": return self._j(403, {"message":"Forbidden"})
            if MODE == "orgmismatch": return self._j(200, {"id":7})
            return self._j(200, {"id":9 if MODE == "orgscope" else 7})
        if p.startswith("/render/"):
            if MODE.startswith("render") and MODE[6:].isdigit():
                code = int(MODE[6:])
                return self._j(code, {"message":"renderer failure"})
            if MODE == "renderok":
                return self._b(200, b"\x89PNG\r\n\x1a\n" + b"x" * 1024, "image/png")
            return self._j(200, {})
        if p == "/api/datasources":
            if MODE in ("nods", "ds403"): return self._j(403, {"message":"Forbidden"})
            if MODE == "ds429": return self._j(429, {"message":"rate limited"})
            if MODE == "ds500": return self._j(500, {"message":"upstream failed"})
            if MODE == "dsempty": return self._j(200, [])
            return self._j(200, [{"uid":"p1","name":"Prom","type":"prometheus","isDefault":True}])
        if p == "/api/frontend/settings": return self._j(200, {"buildInfo":{"edition":"oss"}})
        if p.startswith("/api/datasources/proxy"):
            if MODE == "proxy500": return self._j(500, {"message":"proxy failed"})
            if "label/__name__/values" in self.path:
                return self._j(200, {"data":["gen_ai_client_operation_duration_seconds_bucket",
                    "gen_ai_client_operation_duration_seconds_count",
                    "gen_ai_client_token_usage_token_sum"]})
            return self._j(200, {"data":["gpt-5.4"]})
        if p.startswith("/api/folders"): return self._j(404, {"message":"not found"})
        if p.startswith("/api/dashboards/uid/"):
            uid = p.rsplit("/", 1)[-1]
            legacy = set()
            for name in ("ai-executive-finops", "ai-gateway-operations", "ai-agents-rag",
                         "ai-adoption", "ai-inference-selfhosted",
                         "ai-governance-eu-ai-act", "ai-quality-evals"):
                h = hashlib.sha1(name.encode()).hexdigest()[:10]
                slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:26]
                legacy.add(f"llmops-{slug}-{h}"[:40])
            if MODE == "collision" and uid in legacy:
                return self._j(200, {"meta":{"folderUid":"other-folder"},
                                     "dashboard":{"uid":uid}})
            return self._j(404, {"message":"not found"})
        if p == "/api/v1/provisioning/contact-points": return self._j(200, [])
        if p.startswith("/api/v1/provisioning/alert-rules/"):
            uid = p.rsplit("/", 1)[-1]
            folder = STATE.get("folder_uid", "unknown-folder")
            existing = {"uid":uid, "title":"foreign", "folderUID":folder,
                        "orgID":7, "ruleGroup":"llmops-slo",
                        "labels":{"origin":"llmops-forge"}}
            if MODE == "alertcollision-folder": existing["folderUID"] = "other-folder"
            elif MODE == "alertcollision-org": existing["orgID"] = 99
            elif MODE == "alertcollision-identity": existing["labels"]["origin"] = "foreign"
            else: existing = None
            if existing is not None: return self._j(200, existing)
        if p.startswith("/api/v1/provisioning"):
            return self._j(403 if MODE == "alertfail" else 404,
                           {"message":"Forbidden" if MODE == "alertfail" else "not found"})
        return self._j(200, {})
    def do_POST(self):
        p = self.path.split("?")[0]
        ln = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(ln)
        obj = json.loads(raw) if raw else {}
        if p == "/api/folders":
            if MODE == "nofolder": return self._j(403, {"message":"Forbidden"})
            STATE["folder_uid"] = obj.get("uid", "f1")
            return self._j(200, {"uid":obj.get("uid", "f1"),
                                 "title":obj.get("title", "AI Observability")})
        if p == "/api/dashboards/db":
            if MODE == "dashfail": return self._j(403, {"message":"Forbidden"})
            return self._j(200, {"uid":"d1","url":"/d/d1/x"})
        if p.startswith("/api/v1/provisioning"):
            return self._j(403 if MODE == "alertfail" else 200,
                           {"message":"Forbidden" if MODE == "alertfail" else "ok"})
        return self._j(200, {})
    do_PUT = do_POST
    def log_message(self,*a): pass
HTTPServer(("127.0.0.1", PORT), H).serve_forever()
