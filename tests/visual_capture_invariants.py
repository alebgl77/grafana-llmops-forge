"""Evidence files must remain attributable when dashboard titles collide."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import visual_audit as audit


class CaptureIdentityTests(unittest.TestCase):
    def test_plan_ignores_blank_uids_and_preserves_manifest_panels(self):
        with tempfile.TemporaryDirectory() as tmp:
            dash = {"uid": "a", "title": "FinOps", "panels": [
                {"id": 1, "type": "stat", "title": "Spend"}]}
            Path(tmp, "deploy_manifest.json").write_text(
                json.dumps({"dashboards": [dash]}), encoding="utf-8")
            plan = audit.load_plan(SimpleNamespace(dashboards=tmp, uids="a,, b, b, "))
            self.assertEqual(plan, [dash, {"uid": "b", "title": "b", "panels": []}])

    def test_title_slug_collisions_do_not_overwrite_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboards = [{"uid": uid, "title": title, "panels": []}
                          for uid, title in [("one", "FinOps"), ("two", "FinOps"),
                                             ("three", "FinOps!")]]
            client = SimpleNamespace(base="https://grafana.example", resolve_org=lambda _: 7)

            def capture(_client, dash, out, _args):
                path = Path(out, "full.png")
                path.write_bytes(dash["uid"].encode())
                return {"engine": "renderer", "files": [str(path)], "warnings": []}

            with patch.object(audit, "load_plan", return_value=dashboards), \
                    patch.object(audit, "GrafanaClient", return_value=client), \
                    patch.object(audit, "capture_renderer", side_effect=capture), \
                    patch.object(audit.time, "sleep"), \
                    patch.object(sys, "argv", ["visual_audit", "--engine", "renderer", "--out", tmp]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audit.main(), 0)
            manifest = json.loads(Path(tmp, "audit_manifest.json").read_text(encoding="utf-8"))
            paths = [entry["files"][0] for entry in manifest["dashboards"]]
            self.assertEqual(len(set(paths)), 3)
            for entry in manifest["dashboards"]:
                self.assertEqual(Path(entry["files"][0]).read_bytes(), entry["uid"].encode())

    def test_instance_org_and_uid_are_part_of_capture_identity(self):
        dash = {"title": "A / ../ title", "uid": "stable"}
        first = audit.capture_directory("https://grafana.example", 1, dash)
        self.assertEqual(first, audit.capture_directory("https://grafana.example/", 1, dash))
        self.assertNotEqual(first, audit.capture_directory("https://grafana.example", 2, dash))
        self.assertNotEqual(first, audit.capture_directory("https://other.example", 1, dash))
        self.assertNotEqual(first, audit.capture_directory("https://grafana.example/subpath", 1, dash))
        self.assertNotEqual(first, audit.capture_directory("https://grafana.example", 1, {**dash, "uid": "other"}))
        self.assertRegex(first, r"^[a-z0-9-]+--[0-9a-f]{16}$")


if __name__ == "__main__":
    unittest.main()
