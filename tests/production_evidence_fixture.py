"""Synthetic bound source-report fixtures; never real media/VI certification."""
import json
from pathlib import Path

from lib.production_quality import collect_production_quality


def create_bound_quality(root, record, *, prefix="fixture-evidence"):
    root = Path(root)

    def put(name, data):
        ref = f"{prefix}/{name}.json"
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return ref

    render = record["render"]
    sha = render["sha256"]
    if not record.get("canonical_artifacts"):
        record["canonical_artifacts"] = {"final_props": put("props", {"fixture_only": True})}
    refs = {"technical": put("technical", {
        "fixture_only": True, "metadata": {"media_sha256": sha},
        "checks": {"media_integrity": {"decode_ok": True, "profile_ok": True},
                   "technical_probe": {"duration_seconds": render.get("seconds", 4), "has_audio": True}},
    })}
    for source, names, method in (
        ("brand_dom", ("font_identity", "text_layout"), "rendered_browser_measurement"),
        ("narration", ("narration_content",), "independent_asr"),
        ("alignment", ("caption_alignment",), "measured_word_alignment"),
        ("product_review", ("fact_source", "product_identity"), "product_evidence_review"),
        ("continuity", ("visual_continuity",), "rendered_continuity_check"),
    ):
        refs[source] = put(source, {"fixture_only": True, "render_sha256": sha,
            "method": method, "checks": [{"id": name, "status": "pass", "issues": []} for name in names]})
    return collect_production_quality(root, record, refs)
