#!/usr/bin/env python3
"""Génère et vérifie le SBOM SPDX 2.3 déterministe d'une archive `.skill`.

Le document décrit l'archive comme un package et chaque membre comme un
fichier. Aucune dépendance d'exécution n'est requise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import tempfile
from typing import Optional
import zipfile

TOOL_NAME = "grafana-llmops-forge-sbom/1.0"
CREATED = "1980-01-01T00:00:00Z"


def _digest(data: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, data).hexdigest()


def _members(archive: pathlib.Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)):
            raise ValueError("l'archive contient des noms de membre dupliqués")
        members: list[tuple[str, bytes]] = []
        for info in package.infolist():
            path = pathlib.PurePosixPath(info.filename)
            if (info.is_dir() or path.is_absolute() or ".." in path.parts
                    or "\\" in info.filename):
                raise ValueError(f"membre d'archive non sûr : {info.filename}")
            members.append((info.filename, package.read(info)))
    return sorted(members)


def document(archive: pathlib.Path) -> dict[str, object]:
    archive_bytes = archive.read_bytes()
    archive_sha1 = _digest(archive_bytes, "sha1")
    archive_sha256 = _digest(archive_bytes, "sha256")
    members = _members(archive)
    files = []
    sha1_values = []
    relationships = [{
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": "SPDXRef-Package",
    }]
    for index, (name, data) in enumerate(members, 1):
        spdx_id = f"SPDXRef-File-{index:04d}"
        sha1 = _digest(data, "sha1")
        sha1_values.append(sha1)
        files.append({
            "SPDXID": spdx_id,
            "fileName": f"./{name}",
            "checksums": [
                {"algorithm": "SHA1", "checksumValue": sha1},
                {"algorithm": "SHA256", "checksumValue": _digest(data, "sha256")},
            ],
            "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        })
        relationships.append({
            "spdxElementId": "SPDXRef-Package",
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": spdx_id,
        })
    verification_code = _digest("".join(sorted(sha1_values)).encode("ascii"), "sha1")
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{archive.name} SBOM",
        "documentNamespace": (
            "https://github.com/alebgl77/grafana-llmops-forge/"
            f"sbom/{archive_sha256}"
        ),
        "creationInfo": {
            "created": CREATED,
            "creators": [f"Tool: {TOOL_NAME}"],
        },
        "packages": [{
            "SPDXID": "SPDXRef-Package",
            "name": archive.name,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": True,
            "checksums": [
                {"algorithm": "SHA1", "checksumValue": archive_sha1},
                {"algorithm": "SHA256", "checksumValue": archive_sha256},
            ],
            "packageVerificationCode": {
                "packageVerificationCodeValue": verification_code,
            },
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        }],
        "files": files,
        "relationships": relationships,
    }


def encoded_document(archive: pathlib.Path) -> bytes:
    return (json.dumps(document(archive), ensure_ascii=False, indent=2,
                       sort_keys=True) + "\n").encode("utf-8")


def write_atomic(dest: pathlib.Path, content: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp: Optional[pathlib.Path] = None
    try:
        with tempfile.NamedTemporaryFile(
                prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent,
                delete=False) as handle:
            tmp = pathlib.Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def verify(archive: pathlib.Path, sbom: pathlib.Path) -> int:
    if not archive.is_file():
        print(f"archive absente : {archive}", file=sys.stderr)
        return 1
    if not sbom.is_file():
        print(f"SBOM absent : {sbom}", file=sys.stderr)
        return 1
    try:
        actual = json.loads(sbom.read_text(encoding="utf-8"))
        expected = document(archive)
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"SBOM invalide : {exc}", file=sys.stderr)
        return 1
    if actual != expected:
        print("SBOM divergent de l'archive", file=sys.stderr)
        return 1
    print(f"  [OK] SPDX 2.3 : {len(expected['files'])} membres vérifiés")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    output = args.out or archive_sbom_path(args.archive)
    if args.verify:
        return verify(args.archive, output)
    try:
        content = encoded_document(args.archive)
        write_atomic(output, content)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"génération SBOM impossible : {exc}", file=sys.stderr)
        return 1
    print(f"{output} ({len(content)} octets)")
    return verify(args.archive, output)


def archive_sbom_path(archive: pathlib.Path) -> pathlib.Path:
    return archive.with_name(f"{archive.stem}.spdx.json")


if __name__ == "__main__":
    sys.exit(main())
