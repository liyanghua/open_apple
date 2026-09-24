"""Read-only, file-bound production evidence for the existing pipeline."""
from pathlib import Path

from lib.production_evidence import build_production_subject, quality_summary, read_object
from lib.production_quality import collect_production_quality
from lib.media_fingerprint import fingerprint_media
import subprocess
from tools.base_tool import BaseTool, ToolResult


class ProductionAudit(BaseTool):
    name = "production_audit"
    description = "Collect measured final-film evidence or verify a production record; never approves a film."
    capability = "analysis"
    provider = "local"
    input_schema = {"type": "object", "required": ["operation", "project_dir", "record_path"],
                    "properties": {"operation": {"enum": ["collect", "verify", "fingerprint"]},
                                   "project_dir": {"type": "string"}, "record_path": {"type": "string"},
                                   "evidence_refs": {"type": "object", "additionalProperties": {"type": "string"}}}}

    def execute(self, inputs):
        try:
            root = Path(inputs["project_dir"]).resolve()
            record = read_object(root, inputs["record_path"])
            if inputs["operation"] == "fingerprint":
                from lib.production_evidence import project_file
                return ToolResult(success=True, data={"media_fingerprint": fingerprint_media(project_file(root, record["render"]["path"]))})
            if inputs["operation"] == "collect":
                report = collect_production_quality(root, record, inputs.get("evidence_refs", {}))
                return ToolResult(success=True, data={"quality_report": report})
            if inputs["operation"] == "verify":
                return ToolResult(success=True, data={"subject": build_production_subject(root, inputs["record_path"]),
                                                      "quality": quality_summary(root, record)})
            raise ValueError("Unsupported audit operation")
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            return ToolResult(success=False, error=str(exc))
