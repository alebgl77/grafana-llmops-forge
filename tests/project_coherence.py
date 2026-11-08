"""Cross-file contracts missed by checking only counts or headline phrases."""
import json
from pathlib import Path
import re
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))
import forge_dashboards as forge
import build_visual_assets as visuals


class CoherenceTests(unittest.TestCase):
    def test_each_blueprint_is_documented_and_drawn_once(self):
        spec = (ROOT / "references/dashboard_blueprints.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## \d+\. `([^`]+)`", spec, re.M)
        arch = ET.parse(ROOT / "docs/assets/architecture.svg")
        depicted = [node.attrib["data-blueprint"] for node in arch.iter()
                    if "data-blueprint" in node.attrib]
        for names in (headings, depicted):
            self.assertEqual(set(names), set(forge.BLUEPRINTS))
            self.assertEqual(len(names), len(set(names)))

    def test_visual_sources_are_current_and_accessible(self):
        ns = {"svg": "http://www.w3.org/2000/svg"}
        for name, expected in visuals.assets().items():
            with self.subTest(asset=name):
                actual = (ROOT / "docs/assets" / name).read_text(encoding="utf-8")
                self.assertEqual(actual, expected, "Run python tools/build_visual_assets.py")
                root = ET.fromstring(actual)
                self.assertEqual(root.get("role"), "img")
                self.assertTrue(root.find("svg:title", ns).text)
                self.assertTrue(root.find("svg:desc", ns).text)

    def test_governance_and_quality_default_copy_is_english_with_french_translation(self):
        registry = json.loads((ROOT / "references/model_registry.json").read_text(encoding="utf-8"))
        ctx = forge.Ctx(forge.selftest_capability(), registry)
        governance = forge.bp_governance(ctx).d
        quality = forge.bp_quality(ctx).d
        timeline = next(p for p in governance["panels"] if p["title"] == "Regulatory timeline")
        body = timeline["options"]["content"]
        self.assertIn("AI Act milestones", body)
        self.assertIn("queries do not verify retention", next(
            p["description"] for p in governance["panels"]
            if p["title"] == "Logging evidence (log volume)"))
        self.assertIn("They do not establish", body)
        self.assertNotIn("imminent", body)
        self.assertNotIn("adoption formelle en cours", body)
        self.assertNotIn("Calendrier", body)
        self.assertNotIn("Documentez", json.dumps(quality, ensure_ascii=False))
        translated = forge.localize(timeline, forge.load_locale("fr"))
        self.assertIn("Repères AI Act", translated["options"]["content"])
        self.assertIn("ne prouvent", translated["options"]["content"])
        self.assertEqual(timeline["targets"], translated["targets"])

    def test_make_package_builds_and_rule_reload_does_not_hide_errors(self):
        make = (ROOT / "Makefile").read_text(encoding="utf-8")
        package = make.split("\npackage:", 1)[1].split("\nscan:", 1)[0]
        rules = make.split("\nrules:", 1)[1].split("\nshots:", 1)[0]
        self.assertIn("python3 tools/package.py", package)
        self.assertIn("--verify", package)
        self.assertIn("curl --fail", rules)
        self.assertNotIn("|| true", rules)


if __name__ == "__main__":
    unittest.main()
