"""Grafana simulé pour les tests de panne : latence, 403 ciblés, réponses partielles.

Ce que le harnais hors ligne ne peut pas couvrir : le comportement quand une
instance répond mal. Un 403 de permissions en production doit produire un message
qu'un exploitant comprend, pas une trace Python.

    python3 tests/fake_grafana.py nofolder &   # puis pointer GRAFANA_URL dessus
"""

import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
MODE = sys.argv[1] if len(sys.argv) > 1 else "ok"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9198
class H(BaseHTTPRequestHandler):
    def _j(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path.split("?")[0]
        if MODE == "slow": time.sleep(3)
        if p == "/api/health": return self._j(200, {"version":"11.2.0","database":"ok"})
        if p == "/api/org": return self._j(200 if MODE!="noorg" else 403, {"id": 7})
        if p == "/api/datasources":
            if MODE == "nods": return self._j(403, {"message":"Forbidden"})
            return self._j(200, [{"uid":"p1","name":"Prom","type":"prometheus","isDefault":True}])
        if p == "/api/frontend/settings": return self._j(200, {"buildInfo":{"edition":"oss"}})
        if p.startswith("/api/datasources/proxy"):
            if "label/__name__/values" in self.path:
                return self._j(200, {"data":["gen_ai_client_operation_duration_seconds_bucket",
                    "gen_ai_client_operation_duration_seconds_count",
                    "gen_ai_client_token_usage_token_sum"]})
            return self._j(200, {"data":["gpt-5.4"]})
        if p.startswith("/api/folders"): return self._j(404, {"message":"not found"})
        if p.startswith("/api/v1/provisioning"): return self._j(403, {"message":"Forbidden"})
        return self._j(200, {})
    def do_POST(self):
        p = self.path.split("?")[0]
        ln = int(self.headers.get("Content-Length") or 0); self.rfile.read(ln)
        if p == "/api/folders":
            if MODE == "nofolder": return self._j(403, {"message":"Forbidden"})
            return self._j(200, {"uid":"f1","title":"AI Observability"})
        if p == "/api/dashboards/db":
            if MODE == "dashfail": return self._j(403, {"message":"Forbidden"})
            return self._j(200, {"uid":"d1","url":"/d/d1/x"})
        if p.startswith("/api/v1/provisioning"): return self._j(403, {"message":"Forbidden"})
        return self._j(200, {})
    do_PUT = do_POST
    def log_message(self,*a): pass
HTTPServer(("127.0.0.1", PORT), H).serve_forever()
