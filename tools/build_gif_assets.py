"""Animate documentation SVGs; --check uses only the standard library.

Authoring requires tools/visual-requirements.txt. Geometry and text come from
the SVG generator; timing only lives here. These are explanatory illustrations,
not live telemetry or evidence of a Grafana rendering review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/assets"
NAMES = ("banner", "social-preview", "architecture", "pricing-flow",
         "governance-crosswalk", "dashboard-finops")
MANIFEST = ASSETS / "animations.json"
FRAME_MS = 50
MAX_BYTES = 2_000_000
ORANGE, BLUE, GREEN = "#ff9830", "#79c0ff", "#80d495"


def fingerprint():
    files = [Path(__file__), ROOT / "tools/build_visual_assets.py",
             ROOT / "tools/visual-requirements.txt"]
    files.extend(ASSETS / (name + ".svg") for name in NAMES)
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def check():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == fingerprint(), "Animation sources changed; rebuild the GIFs."
    assert set(manifest["assets"]) == {name + ".gif" for name in NAMES}
    for name, meta in manifest["assets"].items():
        data = (ASSETS / name).read_bytes()
        assert data[:6] == b"GIF89a", name
        assert len(data) == meta["bytes"] <= MAX_BYTES, name
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], name
        assert meta["frames"] > 1 and meta["loop"] == 0, name
        assert int.from_bytes(data[6:8], "little") == meta["width"], name
        assert int.from_bytes(data[8:10], "little") == meta["height"], name
    print("Six animated GIFs match their source and size budget.")


def points(d):
    """Read the explicit, absolute M/L/H/V polylines used by our SVG source."""
    tokens = re.findall(r"[MLHV]|-?\d+(?:\.\d+)?", d)
    if re.sub(r"[MLHV\d.\s,-]", "", d):
        raise ValueError("Unsupported animation path: " + d)
    out, x, y, i = [], 0.0, 0.0, 0
    while i < len(tokens):
        command = tokens[i]
        i += 1
        if command in ("M", "L"):
            x, y = float(tokens[i]), float(tokens[i + 1])
            i += 2
        elif command == "H":
            x = float(tokens[i])
            i += 1
        elif command == "V":
            y = float(tokens[i])
            i += 1
        else:
            raise ValueError("Expected an explicit path command")
        out.append((x, y))
    assert len(out) >= 2, d
    return out


def position(path, progress):
    lengths = [math.dist(a, b) for a, b in zip(path, path[1:])]
    remaining = max(0, min(1, progress)) * sum(lengths)
    for a, b, length in zip(path, path[1:], lengths):
        if remaining <= length and length:
            t = remaining / length
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        remaining -= length
    return path[-1]


def sequence(name, stage_names):
    """(start, end, stage keys, flow keys, color), all times in seconds."""
    if name in ("banner", "social-preview"):
        return 5.0, [(0.2, 1.6, ["discover"], [], ORANGE),
                     (1.6, 3.1, ["deploy"], ["deploy"], BLUE),
                     (3.1, 4.7, ["review"], ["review"], GREEN)]
    if name == "architecture":
        boards = [key for key in stage_names if key.startswith("blueprint-")]
        return 8.0, [(0.2, 1.4, ["inputs", "discovery"], ["discovery"], BLUE),
                     (1.4, 2.6, ["registry", "forge"], ["registry", "capability", "forge"], ORANGE),
                     (2.6, 3.8, boards, [], BLUE),
                     (3.8, 5.0, ["deploy", "rules"], ["deploy", "rules"], BLUE),
                     (5.0, 6.2, ["capture"], ["capture"], BLUE),
                     (6.2, 7.7, ["review"], ["review"], GREEN)]
    if name == "pricing-flow":
        # Alternatives, never simultaneous aggregation of separate cost sources.
        return 9.0, [(0.2, 1.6, ["recorded"], ["recorded"], ORANGE),
                     (1.6, 2.7, ["output"], ["output"], ORANGE),
                     (3.2, 4.6, ["native"], ["native"], BLUE),
                     (4.6, 5.7, ["output"], ["output"], BLUE),
                     (6.2, 7.1, ["inline", "lookup"], ["lookup"], GREEN),
                     (7.1, 8.0, ["lookup"], ["inline"], GREEN),
                     (8.0, 8.7, ["output"], ["output"], GREEN)]
    if name == "governance-crosswalk":
        rows = [key for key in stage_names if key.startswith("mapping-")]
        # Each row is a correspondence, not a transfer between legal frameworks.
        return len(rows) * 1.1 + 0.6, [
            (0.2 + i * 1.1, 1.25 + i * 1.1, [key], [], BLUE)
            for i, key in enumerate(rows)]
    return 5.0, []  # FinOps: a cursor traverses fixed illustrative time series.


def render(name):
    import fitz
    from PIL import Image, ImageColor, ImageDraw

    source = (ASSETS / (name + ".svg")).read_bytes()
    root = ET.fromstring(source)
    w, h = float(root.get("width")), float(root.get("height"))
    scale = min(1, 1280 / w)
    size = round(w * scale), round(h * scale)
    with fitz.open(stream=source, filetype="svg") as document:
        pix = document[0].get_pixmap(matrix=fitz.Matrix(scale * 2, scale * 2), alpha=False)
        base = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).resize(size, Image.Resampling.LANCZOS)
    stages, flows = {}, {}
    for element in root.iter():
        if "data-stage" in element.attrib:
            key = element.get("data-stage")
            assert key not in stages, key
            stages[key] = tuple(float(element.get(v)) for v in ("x", "y", "width", "height", "rx"))
        if "data-flow" in element.attrib:
            key = element.get("data-flow")
            assert key not in flows, key
            flows[key] = points(element.get("d")), element.get("stroke")
    duration, plan = sequence(name, stages)
    for _, _, stage_keys, flow_keys, _ in plan:
        assert set(stage_keys) <= stages.keys(), stage_keys
        assert set(flow_keys) <= flows.keys(), flow_keys
    frames = []
    # One global palette avoids text shimmer and permits small delta frames.
    swatches = Image.new("RGB", (size[0], 24))
    sd = ImageDraw.Draw(swatches)
    for i, color in enumerate((ORANGE, BLUE, GREEN, "#ffffff")):
        sd.rectangle((i * size[0] // 4, 0, (i + 1) * size[0] // 4, 24), fill=color)
    palette_source = Image.new("RGB", (size[0], size[1] + 24))
    palette_source.paste(base)
    palette_source.paste(swatches, (0, size[1]))
    palette = palette_source.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    zoom = scale * 2

    for frame in range(round(duration * 1000 / FRAME_MS)):
        t = frame * FRAME_MS / 1000
        layer = Image.new("RGBA", (size[0] * 2, size[1] * 2))
        draw = ImageDraw.Draw(layer)

        def line(coords, color, alpha=255, width=3):
            draw.line([(round(x * zoom), round(y * zoom)) for x, y in coords],
                      fill=(*ImageColor.getrgb(color), round(alpha)), width=max(1, round(width * zoom)))

        def dot(point, color, alpha=255, radius=4):
            x, y = point
            draw.ellipse(tuple(round(v * zoom) for v in (x-radius, y-radius, x+radius, y+radius)),
                         fill=(*ImageColor.getrgb(color), round(alpha)))

        for start, end, stage_keys, flow_keys, color in plan:
            if not start <= t < end:
                continue
            p = (t - start) / (end - start)
            envelope = min(1, p * 7, (1 - p) * 7)
            for key in stage_keys:
                x, y, width, height, radius = stages[key]
                box = tuple(round(v * zoom) for v in (x+1, y+1, x+width-1, y+height-1))
                draw.rounded_rectangle(box, radius=round(radius * zoom),
                                       outline=(*ImageColor.getrgb(color), round(210 * envelope)),
                                       width=max(1, round(2 * zoom)))
                line([(x+12, y+height-5), (x+12+(width-24)*p, y+height-5)], color, 210*envelope, 2)
            for key in flow_keys:
                path, path_color = flows[key]
                # The shared output inherits the selected source's color.
                flow_color = color if key == "output" else path_color
                for tail in range(10, -1, -1):
                    q = p - tail * 0.012
                    if q >= 0:
                        dot(position(path, q), flow_color, (1-tail/12)*220*envelope, 3)
                dot(position(path, p), "#ffffff", 255*envelope, 2.3)
        if name == "dashboard-finops" and 0.2 <= t <= 4.8:
            p = (t - 0.2) / 4.6
            alpha = min(1, p * 9, (1-p) * 9)
            for key, (path, color) in flows.items():
                x, y = position(path, p)
                if key != "tokens-b":
                    line([(x, 354), (x, 545)], color, 65*alpha, 1)
                dot((x, y), color, 255*alpha, 5)
                dot((x, y), "#ffffff", 255*alpha, 2)
        overlay = layer.resize(size, Image.Resampling.LANCZOS)
        frame_image = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
        frames.append(frame_image.quantize(palette=palette, dither=Image.Dither.NONE))
    target = ASSETS / (name + ".gif")
    frames[0].save(target, save_all=True, append_images=frames[1:], duration=FRAME_MS,
                   loop=0, optimize=True, disposal=1)
    data = target.read_bytes()
    assert len(data) <= MAX_BYTES, f"{name} exceeds the 2 MB budget"
    with Image.open(target) as decoded:
        total_ms = 0
        hashes = set()
        for i in range(decoded.n_frames):
            decoded.seek(i)
            total_ms += decoded.info["duration"]
            hashes.add(hashlib.sha256(decoded.convert("RGB").tobytes()).digest())
        assert len(hashes) > 10, f"{name} has no meaningful animation"
        assert total_ms == len(frames) * FRAME_MS
        assert decoded.info["loop"] == 0
        meta = dict(width=size[0], height=size[1], frames=decoded.n_frames,
                    duration_ms=total_ms, loop=0, bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest())
    print(f"{target.name}: {meta['frames']} frames, {total_ms/1000:g}s, {len(data)/1024:.0f} KiB")
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check()
        return
    from importlib.metadata import version
    from build_visual_assets import assets
    for name, content in assets().items():
        assert (ASSETS / name).read_text(encoding="utf-8") == content, "Regenerate the SVGs first."
    manifest = {"source_sha256": fingerprint(), "frame_ms": FRAME_MS,
                "dependencies": {name: version(name) for name in ("Pillow", "PyMuPDF")},
                "assets": {name + ".gif": render(name) for name in NAMES}}
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    check()


if __name__ == "__main__":
    main()
