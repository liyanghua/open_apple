"""Build and attest the small same-origin OpenReel integration bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    else:
        for child in sorted(path.rglob("*")):
            if child.is_file():
                digest.update(str(child.relative_to(path)).encode("utf-8"))
                digest.update(child.read_bytes())
    return digest.hexdigest()


def build_manifest(source: Path, output: Path, *, revision: str, license_path: Path) -> dict[str, Any]:
    source = Path(source).resolve()
    output = Path(output).resolve()
    license_path = Path(license_path).resolve()
    if not source.is_dir():
        raise ValueError("OpenReel source directory is missing")
    if not revision.strip():
        raise ValueError("a pinned source revision is required")
    if not license_path.is_file() or license_path.parent != source:
        raise ValueError("the source license must be present at the source root")
    if not (source / "shell.js").is_file():
        raise ValueError("the shell bridge target is missing")
    output.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name == "manifest.json":
            continue
        target = output / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)
    manifest = {
        "schema_version": "editorial-editor-build-1.0",
        "source_revision": revision,
        "license_file": license_path.name,
        "bundle_sha256": _sha256(output),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--license", dest="license_path", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_manifest(args.source, args.output, revision=args.revision, license_path=args.license_path), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
