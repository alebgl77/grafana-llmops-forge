#!/usr/bin/env python3
"""Contrôles autonomes de reproductibilité du paquet et de son SBOM."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import warnings
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "tools" / "package.py"
SBOM = ROOT / "tools" / "sbom.py"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def run(*args: object, expect: int = 0) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONUTF8="1")
    result = subprocess.run(
        [sys.executable, *(str(arg) for arg in args)], cwd=ROOT, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if result.returncode != expect:
        raise AssertionError(
            f"code {result.returncode}, attendu {expect}: {' '.join(map(str, args))}\n"
            f"{result.stdout}"
        )
    return result


def verification_code(files: list[dict[str, object]]) -> str:
    sha1s = []
    for entry in files:
        checksums = entry["checksums"]
        assert isinstance(checksums, list)
        by_algorithm = {item["algorithm"]: item["checksumValue"]
                        for item in checksums}
        assert set(by_algorithm) == {"SHA1", "SHA256"}
        sha1s.append(by_algorithm["SHA1"])
    return hashlib.sha1("".join(sorted(sha1s)).encode("ascii")).hexdigest()


def verify_release_workflow() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    lines = workflow.splitlines()
    starts = [index for index, line in enumerate(lines)
              if line.strip() == "python - <<'PY'"]
    assert len(starts) == 1, "freshness check Python introuvable ou ambigu"
    start = starts[0]
    end = next(index for index in range(start + 1, len(lines))
               if lines[index].strip() == "PY")
    fragment = textwrap.dedent("\n".join(lines[start + 1:end]))
    compile(fragment, f"{RELEASE_WORKFLOW}:freshness-check", "exec")

    assert "--clobber" not in workflow
    draft = workflow.index("gh release create \"${GITHUB_REF_NAME}\" --draft")
    attest_build = workflow.index("- name: Attest build provenance")
    attest_sbom = workflow.index("- name: Attest SPDX SBOM")
    publish = workflow.index("- name: Publish only after both attestations succeed")
    assert draft < attest_build < attest_sbom < publish
    assert workflow.count("--draft=false") == 1
    upload = workflow[draft:attest_build]
    for asset in ("dist/grafana-llmops-forge.skill",
                  "dist/grafana-llmops-forge.spdx.json", "dist/SHA256SUMS"):
        assert asset in upload, f"asset de release manquant: {asset}"


def main() -> int:
    verify_release_workflow()
    with tempfile.TemporaryDirectory(prefix="forge-supply-chain-") as tmp_name:
        tmp = pathlib.Path(tmp_name)
        first = tmp / "package.skill"
        second = tmp / "second.skill"
        sbom_a = tmp / "sbom-a.json"
        sbom_b = tmp / "sbom-b.json"

        run(PACKAGE, "--out", first)
        run(PACKAGE, "--out", second)
        assert first.read_bytes() == second.read_bytes(), "paquets non reproductibles"
        run(PACKAGE, "--out", first, "--verify")

        run(SBOM, first, "--out", sbom_a)
        run(SBOM, first, "--out", sbom_b)
        assert sbom_a.read_bytes() == sbom_b.read_bytes(), "SBOM non reproductible"
        run(SBOM, first, "--out", sbom_a, "--verify")

        document = json.loads(sbom_a.read_text(encoding="utf-8"))
        assert document["spdxVersion"] == "SPDX-2.3"
        assert document["creationInfo"]["created"] == "1980-01-01T00:00:00Z"
        with zipfile.ZipFile(first) as package:
            members = sorted(package.namelist())
        assert f"grafana-llmops-forge/scripts/pricing_sources.py" in members
        assert not any(name.endswith(("model_registry.local.json",
                                      "model_registry.artificial-analysis.cache.json"))
                       for name in members), (
            "aucun registre local ou cache de prix tiers ne doit etre redistribue")
        files = document["files"]
        assert [entry["fileName"][2:] for entry in files] == members
        assert document["packages"][0]["packageVerificationCode"][
            "packageVerificationCodeValue"] == verification_code(files)
        relationship_types = [item["relationshipType"]
                              for item in document["relationships"]]
        assert relationship_types.count("DESCRIBES") == 1
        assert relationship_types.count("CONTAINS") == len(members)

        tampered = json.loads(sbom_a.read_text(encoding="utf-8"))
        tampered["files"][0]["checksums"][0]["checksumValue"] = "0" * 40
        bad_sbom = tmp / "tampered.json"
        bad_sbom.write_text(json.dumps(tampered), encoding="utf-8")
        run(SBOM, first, "--out", bad_sbom, "--verify", expect=1)

        duplicate = tmp / "duplicate.skill"
        shutil.copyfile(first, duplicate)
        with zipfile.ZipFile(first) as package:
            member = package.infolist()[0]
            content = package.read(member)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(duplicate, "a") as package:
                package.writestr(member.filename, content)
        run(PACKAGE, "--out", duplicate, "--verify", expect=1)
        run(SBOM, duplicate, "--out", tmp / "duplicate.json", expect=1)

    print("SUPPLY CHAIN PROPRE: paquet + SPDX reproductibles et vérifiés")
    return 0


if __name__ == "__main__":
    sys.exit(main())
