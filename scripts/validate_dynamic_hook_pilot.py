#!/usr/bin/env python3
"""Validate an approved dynamic-opening pilot without generating or approving media."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.dynamic_hook_pilot import PilotEvidenceError, validate_generation_gate, validate_preview_evidence
from lib.production_evidence import read_object


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--packet", required=True, help="Project-relative, SHA-bound pilot packet")
    parser.add_argument("--phase", choices=("gate", "preview"), required=True)
    args = parser.parse_args()
    try:
        packet = read_object(args.project_dir, args.packet)
        result = (validate_generation_gate(args.project_dir, packet) if args.phase == "gate"
                  else validate_preview_evidence(args.project_dir, packet))
    except (PilotEvidenceError, ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 1
    items = result["items"]
    print(json.dumps({"status": result["status"], "slots": [item["slot_id"] for item in items],
                      "technical_statuses": ({item["slot_id"]: item["technical_status"] for item in items}
                                             if args.phase == "preview" else None),
                      "final_film_approved": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
