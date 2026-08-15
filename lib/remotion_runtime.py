"""Read-only local Remotion runtime probe; never installs or downloads browsers."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable


def _first_executable(candidates: Iterable[str | Path]) -> str | None:
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    return None


def _version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        line = (result.stdout or result.stderr).splitlines()
        return line[0].strip() if line else None
    except (OSError, subprocess.SubprocessError):
        return None


def _font_available(font: str) -> bool:
    matcher = shutil.which("fc-match")
    if matcher:
        result = subprocess.run([matcher, "-f", "%{family}", font], capture_output=True, text=True, timeout=5, check=False)
        return result.returncode == 0 and bool(result.stdout.strip())
    return platform.system() == "Darwin" and any(Path(p).exists() for p in ("/System/Library/Fonts/Songti.ttc", "/System/Library/Fonts/STHeiti Light.ttc"))


def probe_remotion_runtime(
    *,
    explicit_chromium: str | None = None,
    chromium_paths: Iterable[str | Path] | None = None,
    remotion_dir: Path | None = None,
    project_dir: Path | None = None,
    props_path: Path | None = None,
    composition_id: str = "TransparentMatFinal",
) -> dict[str, Any]:
    root = Path(remotion_dir or Path(__file__).resolve().parent.parent / "remotion-composer")
    env_path = os.environ.get("REMOTION_CHROMIUM_EXECUTABLE")
    home = Path.home()
    candidates: list[str | Path] = [p for p in (explicit_chromium, env_path) if p]
    candidates.extend(chromium_paths or [])
    candidates.extend([
        home / ".cache" / "remotion" / "chrome-headless-shell",
        home / "Library" / "Caches" / "remotion" / "chrome-headless-shell",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    ])
    for cache_root in (home / "Library" / "Caches" / "ms-playwright", home / ".cache" / "ms-playwright"):
        candidates.extend(cache_root.glob("**/chrome-headless-shell"))
        candidates.extend(cache_root.glob("**/Chromium"))
    path_chromium = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if path_chromium:
        candidates.append(path_chromium)
    chromium = _first_executable(candidates)
    props_valid = True
    media_valid = True
    warnings: list[str] = []
    if props_path and props_path.is_file():
        try:
            from lib.final_props import validate_final_props
            validate_final_props(json.loads(props_path.read_text()), project_dir=project_dir)
        except Exception as exc:
            props_valid = False
            warnings.append(f"final props invalid: {exc}")
    elif project_dir:
        warnings.append("final props not provided for validation")
    if not chromium:
        warnings.append("Chromium/Chrome executable not found; install it or configure REMOTION_CHROMIUM_EXECUTABLE")
    package_version = None
    package_json = root / "node_modules" / "remotion" / "package.json"
    if package_json.is_file():
        try:
            package_version = json.loads(package_json.read_text()).get("version")
        except (OSError, ValueError):
            pass
    return {
        "node_version": _version(["node", "--version"]),
        "remotion_version": package_version,
        "chromium_executable": chromium,
        "ffmpeg_version": _version(["ffmpeg", "-version"]),
        "fonts": {"Songti SC": _font_available("Songti SC")},
        "composition_id": composition_id,
        "props_valid": props_valid,
        "media_valid": media_valid,
        "recommended_concurrency": max(1, min(4, (os.cpu_count() or 1))),
        "warnings": warnings,
    }
