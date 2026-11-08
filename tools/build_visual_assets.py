"""Build documentation diagrams from shared tokens and runtime blueprint names.

Pure stdlib. Run with --check in CI to detect source/asset drift. These SVGs
are explanatory illustrations, never evidence of a live Grafana deployment.
The separate dashboard-finops.png is a historical live capture, not generated.
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from discover import DIALECT_SIGNATURES
from forge_dashboards import BLUEPRINTS, CROSSWALK_ROWS

BG, SURFACE, LINE = "#0d1117", "#161b22", "#3d4856"
INK, MUTED, ORANGE, BLUE, GREEN = "#e6edf3", "#b0bac5", "#ff9830", "#79c0ff", "#80d495"
FONT = "Arial, Helvetica, sans-serif"


class SVG:
    def __init__(self, width, height, title, desc):
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                      f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
                      f'<title id="title">{html.escape(title)}</title>',
                      f'<desc id="desc">{html.escape(desc)}</desc>']
        self.rect(0, 0, width, height, BG, BG, radius=0)

    def rect(self, x, y, w, h, fill=SURFACE, stroke=LINE, radius=10, key=None):
        mark = f' data-stage="{key}"' if key else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                          f'rx="{radius}" fill="{fill}" stroke="{stroke}"{mark}/>')

    def text(self, x, y, value, size=18, color=INK, bold=False):
        self.parts.append(f'<text x="{x}" y="{y}" font-family="{FONT}" '
                          f'font-size="{size}" font-weight="{700 if bold else 400}" '
                          f'fill="{color}">{html.escape(value)}</text>')

    def lines(self, x, y, values, size=17, color=MUTED, step=25):
        for i, value in enumerate(values):
            self.text(x, y + i * step, value, size, color)

    def box(self, x, y, w, h, title, lines, accent=BLUE, key=None):
        self.rect(x, y, w, h, key=key)
        self.rect(x, y + 16, 3, h - 32, accent, accent, 0)
        self.text(x + 20, y + 33, title, 20, accent, True)
        self.lines(x + 20, y + 61, lines)

    def path(self, d, color=LINE, width=2, key=None):
        mark = f' data-flow="{key}"' if key else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{mark}/>')

    def arrow(self, x1, y1, x2, y2, color=BLUE, key=None):
        self.path(f'M{x1} {y1} L{x2} {y2}', color, key=key)
        if x1 == x2:
            self.path(f'M{x2-5} {y2-7} L{x2} {y2} L{x2+5} {y2-7}', color)
        else:
            self.path(f'M{x2-7} {y2-5} L{x2} {y2} L{x2-7} {y2+5}', color)

    def finish(self):
        return "\n".join(self.parts + ["</svg>", ""])


def banner(social=False):
    s = SVG(1280, 640 if social else 400, "Grafana LLMOps Forge",
            "Discover telemetry, generate dashboards, deploy, capture and review separately.")
    y = 110 if social else 32
    s.text(48, y + 37, "Grafana", 34, INK, True)
    s.text(48, y + 102, "LLMOps Forge", 56, ORANGE, True)
    s.lines(48, y + 148, ["Turn existing telemetry into", "AI observability dashboards."], 25, INK, 34)
    s.text(48, y + 240, f'{len(BLUEPRINTS)} dashboards · {len(DIALECT_SIGNATURES)} dialects', 23, BLUE)
    s.text(48, y + 276, "FinOps, SLOs, agents, adoption, inference,", 18)
    s.text(48, y + 302, "quality and governance evidence.", 18)
    s.box(725, y, 507, 104, "Discover and generate", ["Use the metrics your platform actually emits."], ORANGE, key='discover')
    s.arrow(978, y + 106, 978, y + 128, key="deploy")
    s.box(725, y + 132, 507, 88, "Deploy and capture", ["Grafana APIs, renderer or Playwright."], key='deploy')
    s.arrow(978, y + 222, 978, y + 244, GREEN, key="review")
    s.box(725, y + 248, 507, 88, "Review the evidence", ["A separate human or vision-agent step."], GREEN, key='review')
    if social:
        s.text(48, 588, "github.com/alebgl77/grafana-llmops-forge", 20, MUTED)
    return s.finish()


def architecture():
    s = SVG(1280, 1040, "Grafana LLMOps Forge architecture",
            "Independent capability and pricing inputs feed seven blueprints. Deployment, capture and review have distinct outcomes.")
    s.text(40, 48, "From observed signals to reviewable evidence", 31, INK, True)
    s.text(40, 79, "Runtime pipeline and its explicit boundaries", 18, MUTED)
    s.box(40, 112, 360, 126, "Grafana and datasources", ["Prometheus / Mimir, Loki, Tempo", "Read through grafana_client.py"], key='inputs')
    s.arrow(400, 175, 450, 175, key="discovery")
    s.box(454, 112, 360, 126, "discover.py", ["Observed metrics and label bindings", "capability_map.json"], key='discovery')
    s.box(860, 112, 380, 126, "Pricing and declarations", ["pricing_sources.py + model registry", "Optional deployment inventory"], ORANGE, key='registry')
    s.path('M634 238 V265 H640', BLUE, key='capability')
    s.path('M1050 238 V265 H640', ORANGE, key='registry')
    s.arrow(640, 265, 640, 290, key="forge")
    s.box(40, 294, 1200, 108, "forge_dashboards.py", [f'{len(BLUEPRINTS)} blueprints selected by available signals · English by default, --locale fr',
          "One financial datasource; ambiguous sources require explicit selection."], ORANGE, key='forge')
    labels = {"finops": ("FinOps & Cost", "Native, recorded or estimated cost"),
              "gateway": ("Gateway SLO", "Latency, TTFT and errors"),
              "agents": ("Agents & RAG", "Tools, operations and traces"),
              "adoption": ("Adoption", "Usage by model and team"),
              "inference": ("Inference", "Queues, tokens and GPU"),
              "quality": ("Quality & Evaluations", "Scores and guardrail signals"),
              "governance": ("Governance", "Observed and declared evidence")}
    for i, key in enumerate(BLUEPRINTS):
        row, col = divmod(i, 4)
        x, y = 40 + col * 304, 430 + row * 108
        title, subtitle = labels[key]
        s.parts.append(f'<g data-blueprint="{key}">')
        s.rect(x, y, 288, 88, key="blueprint-" + key)
        s.text(x + 16, y + 32, title, 19, BLUE, True)
        s.text(x + 16, y + 60, subtitle, 15, MUTED)
        s.parts.append('</g>')
    s.text(970, 566, "Missing signals are reported.", 17, MUTED)
    s.text(970, 590, "Data availability is checked later.", 16, MUTED)
    s.path('M640 631 V644 H330 V658', BLUE, key='deploy')
    s.path('M640 644 H950 V658', ORANGE, key='rules')
    s.box(40, 662, 580, 118, "Deploy via grafana_client.py", ["Scoped folder, deterministic UIDs, optional alerts", "deploy_manifest.json records per-resource status"], key='deploy')
    s.box(660, 662, 580, 118, "Prometheus recording rules", ["Exported as YAML and PrometheusRule CRD", "Install, reload, then rediscover after evaluation"], ORANGE, key='rules')
    s.arrow(330, 781, 330, 812, key="capture")
    s.box(40, 816, 580, 124, "visual_audit.py", ["Renderer / Playwright: PNGs and DOM prechecks", "audit_manifest.json describes capture status"], BLUE, key='capture')
    s.arrow(620, 876, 656, 876, GREEN, key="review")
    s.box(660, 816, 580, 124, "Separate visual review", ["Human or vision-capable agent inspects the PNGs", "Fix source, regenerate and recapture if needed"], GREEN, key='review')
    s.text(40, 985, "CI: offline contracts, live Prometheus queries, value invariants and Grafana deployment.", 18, MUTED)
    s.text(40, 1013, "CI success does not constitute a semantic visual review.", 18, INK, True)
    return s.finish()


def pricing():
    s = SVG(1280, 700, "Financial source selection", "Auto selects recorded, then native, then inline; equal-priority datasource ambiguity is rejected.")
    s.text(40, 48, "One financial source, with explicit provenance", 31, INK, True)
    s.text(40, 80, "Auto priority: recorded → native → inline. Equal-priority ambiguity requires --datasource.", 19, MUTED)
    s.box(40, 120, 376, 142, "Recorded cost", ["llm:cost_usd_per_second", "Use existing cost recording rules", "Upstream coverage is unverified."], ORANGE, key='recorded')
    s.box(452, 120, 376, 142, "Native spend", ["LiteLLM USD spend counter", "Keep the upstream billed amounts", "Registry prices do not replace it."], BLUE, key='native')
    s.box(864, 120, 376, 142, "Inline estimate", ["Observed OTel token metrics", "Exact model / alias price match", "Report partial or unknown pricing."], GREEN, key='inline')
    s.arrow(1052, 264, 1052, 300, GREEN, key="lookup")
    s.box(660, 304, 580, 140, "Registry and optional fallback", ["Official prices first; no network call by default", "Artificial Analysis requires explicit opt-in", "No match or ambiguous match remains unpriced."], GREEN, key='lookup')
    s.path('M228 262 V477 H640', ORANGE, key='recorded')
    s.path('M640 262 V477', BLUE, key='native')
    s.path('M950 444 V477 H640', GREEN, key='inline')
    s.arrow(640, 477, 640, 510, key="output")
    s.box(40, 514, 1200, 110, "FinOps dashboards, coverage manifest and eligible budget alerts", ["Costs from separate datasources are never summed. Missing data is never silently turned into zero.",
          "Provider origin does not establish processing or storage location."], ORANGE, key='output')
    s.text(40, 667, "Generated rules are separate exports: deploy to Prometheus, reload and wait for evaluation before using them.", 18, MUTED)
    return s.finish()


def crosswalk():
    s = SVG(1440, 860, "Governance evidence crosswalk", "Indicative mapping from observable signals to EU AI Act, ISO/IEC 42001 and NIST AI RMF. Not a certification.")
    s.text(40, 49, "Governance evidence, with a defined scope", 31, INK, True)
    s.text(40, 81, "Indicative references: verify applicability and the licensed standard before an audit.", 19, MUTED)
    columns = [(40, 490, "Observable signal", INK), (545, 260, "EU AI Act", ORANGE),
               (820, 265, "ISO/IEC 42001", BLUE), (1100, 300, "NIST AI RMF", GREEN)]
    for x, w, title, color in columns:
        s.rect(x, 116, w, 50)
        s.text(x + 16, 148, title, 21, color, True)
    keys = ("eu-ai-act", "iso-42001", "nist-rmf")
    for i, (label, refs) in enumerate(CROSSWALK_ROWS):
        y = 182 + i * 66
        s.rect(40, y, 1360, 60, BG, LINE, 0, key=f"mapping-{i}")
        s.text(56, y + 35, label, 18)
        for (x, _, _, color), key in zip(columns[1:], keys):
            s.lines(x + 16, y + 25, textwrap.wrap(refs[key], width=27), 16, color, 22)
    s.box(40, 674, 1360, 94, "What the dashboard can support", ["Observed inventory, measured signals and surfaced alerts within the selected datasources and time window."], GREEN)
    s.text(40, 806, "Does not prove: complete inventory, configured retention, legal compliance or an effective management system.", 19, INK)
    s.text(40, 835, "Provider origin is not a processing or storage location. Deployment locations remain separate declarations.", 18, MUTED)
    return s.finish()


def mockup():
    s = SVG(1280, 720, "Illustrative FinOps dashboard", "Synthetic illustration of the native-spend blueprint; not a screenshot or validation result.")
    s.text(32, 43, "AI · Executive FinOps & Cost", 27, INK, True)
    s.text(32, 75, "Illustration only · Synthetic values · Native spend · Selected range: 24 hours", 18, MUTED)
    cards = [("Spend (selected range)", "$120.00", "24-hour total"),
             ("Spend rate per day", "$120.00", "Current rate, extrapolated"),
             ("Average cost per request", "$0.002", "60,000 requests in range"),
             ("Generated tokens/s", "708", "Output throughput")]
    for i, (title, value, note) in enumerate(cards):
        x = 32 + 308 * i
        s.rect(x, 105, 292, 146)
        s.text(x + 16, 139, title, 18)
        s.text(x + 16, 194, value, 41, INK, True)
        s.text(x + 16, 227, note, 16, MUTED)
    for x, title, unit in [(32, "Spend by team (USD/s)", "USD/s"), (656, "Output tokens by model/s", "tokens/s")]:
        s.rect(x, 275, 600, 334)
        s.text(x + 18, 309, title, 22, INK, True)
        s.text(x + 18, 340, unit, 15, MUTED)
        for i in range(4):
            yy = 370 + i * 58
            s.path(f'M{x+60} {yy} H{x+570}', LINE, 1)
        if x == 32:
            for i, val in enumerate([".002", ".0015", ".001", ".0005"]):
                s.text(x + 8, 375 + i * 58, val, 14, MUTED)
            spend_y = 602 - (120 / 86400) * 116000
            s.path(f'M{x+60} {spend_y:.2f} H{x+570}', BLUE, 3, key='spend')
            s.text(x + 60, 584, "Demo team: constant illustrative rate", 16, BLUE)
        else:
            for i, val in enumerate(["800", "600", "400", "200"]):
                s.text(x + 14, 375 + i * 58, val, 14, MUTED)
            s.path(f'M{x+60} {602 - 416 * .29:.2f} H{x+570}', ORANGE, 3, key='tokens-a')
            s.path(f'M{x+60} {602 - 292 * .29:.2f} H{x+570}', GREEN, 3, key='tokens-b')
            s.text(x + 60, 584, "Example A: 416/s", 16, ORANGE)
            s.text(x + 315, 584, "Example B: 292/s", 16, GREEN)
        s.text(x + 60, 565, "24h ago", 14, MUTED)
        s.text(x + 536, 565, "now", 14, MUTED)
    s.text(32, 652, "Source: native spend. Upstream cost completeness remains unverified.", 19)
    s.text(32, 684, "For a real historical Grafana capture, see dashboard-finops.png. Live review must be repeated after deployment.", 17, MUTED)
    return s.finish()


def assets():
    return {"banner.svg": banner(), "social-preview.svg": banner(True),
            "architecture.svg": architecture(), "pricing-flow.svg": pricing(),
            "governance-crosswalk.svg": crosswalk(), "dashboard-finops.svg": mockup()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    stale = []
    for name, content in assets().items():
        path = ROOT / "docs" / "assets" / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
        else:
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
    if stale:
        print("Stale documentation visuals: " + ", ".join(stale))
        return 1
    print("Documentation SVGs match their source." if args.check else "Generated documentation SVGs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
