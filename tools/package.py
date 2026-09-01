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
import collections
import hashlib
import os
import pathlib
import sys
import tempfile
from typing import Optional
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "grafana-llmops-forge"
PAYLOAD = ["SKILL.md", "scripts", "references"]
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".skill"}
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
ZIP_MODE = 0o100644


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
    tmp: Optional[pathlib.Path] = None
    try:
        with tempfile.NamedTemporaryFile(
                prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent,
                delete=False) as handle:
            tmp = pathlib.Path(handle.name)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for src, arc in sources():
                # Tous les champs dépendant de l'hôte sont fixés. En particulier,
                # create_system évite un ZIP différent entre Windows et Linux.
                info = zipfile.ZipInfo(arc, date_time=ZIP_DATE)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = ZIP_MODE << 16
                z.writestr(info, src.read_bytes(), compresslevel=9)
        os.replace(tmp, dest)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return dest


def verify(pkg: pathlib.Path) -> int:
    """L'archive contient-elle exactement les sources du dépôt ?"""
    if not pkg.exists():
        print(f"absent : {pkg}", file=sys.stderr)
        return 1
    expected = {arc: hashlib.sha256(src.read_bytes()).hexdigest()
                for src, arc in sources()}
    with zipfile.ZipFile(pkg) as z:
        infos = z.infolist()
        names = [info.filename for info in infos]
        duplicates = sorted(n for n, count in collections.Counter(names).items()
                            if count > 1)
        got = {n: hashlib.sha256(z.read(n)).hexdigest() for n in names}
    extra = sorted(set(got) - set(expected))
    missing = sorted(set(expected) - set(got))
    differing = sorted(n for n in set(got) & set(expected) if got[n] != expected[n])
    wrong_order = names != sorted(expected)
    wrong_metadata = sorted(
        info.filename for info in infos
        if (info.date_time != ZIP_DATE or info.create_system != 3
            or info.compress_type != zipfile.ZIP_DEFLATED
            or info.external_attr >> 16 != ZIP_MODE)
    )
    for label, items in (("en trop", extra), ("manquant", missing),
                         ("divergent", differing), ("dupliqué", duplicates),
                         ("métadonnées non reproductibles", wrong_metadata)):
        for i in items:
            print(f"  [ERROR] {label} : {i}")
    if wrong_order:
        print("  [ERROR] ordre des membres non reproductible")
    if extra or missing or differing or duplicates or wrong_order or wrong_metadata:
        return 1
    print(f"  [OK] {len(expected)} fichiers, identiques aux sources du dépôt")
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
