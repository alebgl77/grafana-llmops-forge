#!/usr/bin/env python3
"""Construit `dist/<name>.skill` à partir des sources du dépôt.

Le paquet est un artefact de build : il n'est pas versionné. Il est produit ici,
par la CI au moment d'une release, et attaché à la release GitHub. Un dépôt qui
committe son propre zip exécutable donne exactement la forme que les scanners de
chaîne d'approvisionnement cherchent, et à raison, puisque rien ne garantit
alors que l'archive corresponde aux sources lisibles.

Le bytecode est exclu sans condition : un `__pycache__` oublié dans l'arbre de
travail partirait sinon dans l'archive distribuée.

    python3 tools/package.py              # -> dist/grafana-llmops-forge.skill
    python3 tools/package.py --verify     # compare l'archive aux sources
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "grafana-llmops-forge"
PAYLOAD = ["SKILL.md", "scripts", "references"]
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".skill"}


def sources() -> list[tuple[pathlib.Path, str]]:
    """(chemin absolu, chemin dans l'archive), ordonné pour un zip reproductible."""
    out = []
    for item in PAYLOAD:
        p = ROOT / item
        if p.is_file():
            out.append((p, f"{NAME}/{item}"))
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if not f.is_file():
                    continue
                if set(f.parts) & EXCLUDE_DIRS or f.suffix in EXCLUDE_SUFFIX:
                    continue
                out.append((f, f"{NAME}/{f.relative_to(ROOT).as_posix()}"))
        else:
            raise SystemExit(f"source manquante : {p}")
    return sorted(out, key=lambda t: t[1])


def build(dest: pathlib.Path) -> pathlib.Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in sources():
            # date figée : deux builds des mêmes sources donnent le même sha256
            info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, src.read_bytes())
    return dest


def verify(pkg: pathlib.Path) -> int:
    """L'archive contient-elle exactement les sources du dépôt ?"""
    if not pkg.exists():
        print(f"absent : {pkg}", file=sys.stderr)
        return 1
    expected = {arc: hashlib.sha256(src.read_bytes()).hexdigest()
                for src, arc in sources()}
    with zipfile.ZipFile(pkg) as z:
        got = {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}
    extra = sorted(set(got) - set(expected))
    missing = sorted(set(expected) - set(got))
    differing = sorted(n for n in set(got) & set(expected) if got[n] != expected[n])
    for label, items in (("en trop", extra), ("manquant", missing),
                         ("divergent", differing)):
        for i in items:
            print(f"  ❌ {label} : {i}")
    if extra or missing or differing:
        return 1
    print(f"  ✅ {len(expected)} fichiers, identiques aux sources du dépôt")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "dist" / f"{NAME}.skill"))
    ap.add_argument("--verify", action="store_true",
                    help="Vérifier un paquet existant au lieu d'en construire un")
    a = ap.parse_args()
    pkg = pathlib.Path(a.out)
    if a.verify:
        return verify(pkg)
    build(pkg)
    digest = hashlib.sha256(pkg.read_bytes()).hexdigest()
    print(f"{pkg} ({pkg.stat().st_size} octets)")
    print(f"sha256 {digest}")
    return verify(pkg)


if __name__ == "__main__":
    sys.exit(main())
