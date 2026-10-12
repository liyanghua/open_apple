"""Run deterministic sample QA for the table-mat strict-clone Atelier render."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lib.caption_layout import layout_captions
from tools.tool_registry import registry


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "table-mat-mix-v1"
SAMPLE_REL = "renders/sample-v1-540x960.mp4"
SAMPLE = PROJECT / SAMPLE_REL
PROFILE = "social_vertical_sample_540p30"


def load(name: str) -> dict:
    return json.loads((PROJECT / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    if not SAMPLE.is_file():
        raise FileNotFoundError(SAMPLE)

    props = load("final_props")
    captions = props.get("captions") or []
    caption_contract = {
        "captions": captions,
        "render_mode": "remotion_overlay",
        "font_size": 22,
        "bottom_offset_px": 150,
    }
    props_hash = hashlib.sha256(
        json.dumps(caption_contract, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    caption_spec = {
        "captions": captions,
        "computed_boxes": layout_captions(
            captions,
            width=540,
            height=960,
            font_size=22,
            side_margin=36,
            bottom_margin=150,
        ),
        "props_hash": props_hash,
    }
    declaration = {
        "caption_render_mode": "remotion_overlay",
        "caption_source": "artifacts/final_props.json#captions",
        "safe_zone_profile": "douyin_9_16",
        "bottom_offset_px": 150,
    }

    registry.discover()
    final_qa = registry.get("final_qa").execute(
        {
            "mode": "quick",
            "input_path": str(SAMPLE),
            "expected_profile": PROFILE,
            "caption_declaration": declaration,
            "caption_spec": caption_spec,
            "output_path": str(PROJECT / "artifacts" / "final_qa_sample.json"),
        }
    )

    shots = props.get("shots") or []
    text_sources = [
        {"source": "shot_copy", "shot_id": shot["id"], "text": shot.get("claim", "")}
        for shot in shots
        if shot.get("claim")
    ]
    text_sources.append(
        {
            "source": "captions",
            "text": " ".join(str(caption.get("text") or "") for caption in captions),
        }
    )
    shot_map = [
        {
            "shot_id": shot["id"],
            "start_s": shot["fromFrame"] / 30,
            "end_s": shot["toFrameExclusive"] / 30,
        }
        for shot in shots
    ]
    subject_hash = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    l1a = registry.get("technical_validator").execute(
        {
            "project_id": PROJECT.name,
            "project_dir": str(PROJECT),
            "input_path": str(SAMPLE),
            "scope": "sample",
            "expected_profile": PROFILE,
            "expected_duration_s": 373 / 30,
            "duration_tolerance_s": 0.08,
            "expected_facts": {
                "params": [
                    "实厚不虚标",
                    "纯净原料透度高",
                    "防油渗透960小时",
                    "久用不发黄质保两年",
                    "无味使用更安心",
                ]
            },
            "text_sources": text_sources,
            "shot_map": shot_map,
            "caption_declaration": declaration,
            "caption_spec": caption_spec,
            "subject_ref": {"name": "sample_video", "path": SAMPLE_REL},
            "subject_version": "1.0",
            "subject_hash": subject_hash,
            "output_path": str(PROJECT / "artifacts" / "l1a_sample.json"),
        }
    )
    print(
        json.dumps(
            {
                "final_qa": (final_qa.data or {}).get("status"),
                "final_qa_success": final_qa.success,
                "l1a": (l1a.data or {}).get("status"),
                "l1a_success": l1a.success,
                "l1a_recommended_action": (l1a.data or {}).get("recommended_action"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
