from __future__ import annotations

import json
from copy import deepcopy

import pytest

from lib import artifact_io
from lib.artifact_hashing import attach_hashes


def _data() -> dict:
    return {
        "version": "2.0",
        "project_id": "demo",
        "created_at": "2026-08-14T10:00:00Z",
        "producer": "tests",
        "input_hashes": {},
        "payload": "ok",
    }


def test_write_artifact_atomic_writes_loadable_v2_envelope(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda name, data: None)

    envelope = artifact_io.write_artifact_atomic(
        "artifacts/example.json", "example", _data()
    )

    disk = json.loads((tmp_path / "artifacts/example.json").read_text())
    assert disk == envelope["data"]
    assert envelope["name"] == "example"
    assert envelope["path"] == "artifacts/example.json"
    assert envelope["semantic_sha256"] == envelope["data"]["semantic_sha256"]
    assert envelope["artifact_sha256"] == envelope["data"]["artifact_sha256"]
    assert artifact_io.load_artifact_envelope(tmp_path, envelope) == envelope["data"]


def test_absolute_write_path_must_belong_to_explicit_project(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda name, data: None)
    project_dir = tmp_path / "project"
    target = project_dir / "artifacts/example.json"

    envelope = artifact_io.write_artifact_atomic(
        target, "example", _data(), project_dir=project_dir
    )
    assert envelope["path"] == "artifacts/example.json"

    unrelated = tmp_path / "other" / "artifacts/example.json"
    with pytest.raises(ValueError, match="belong to project_dir"):
        artifact_io.write_artifact_atomic(
            unrelated, "example", _data(), project_dir=project_dir
        )


def test_absolute_write_without_project_dir_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda name, data: None)
    with pytest.raises(ValueError, match="project_dir"):
        artifact_io.write_artifact_atomic(
            tmp_path / "artifacts/example.json", "example", _data()
        )


def test_relative_write_uses_explicit_project_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda name, data: None)
    project_dir = tmp_path / "project"

    envelope = artifact_io.write_artifact_atomic(
        "artifacts/example.json", "example", _data(), project_dir=project_dir
    )

    assert envelope["path"] == "artifacts/example.json"
    assert json.loads((project_dir / envelope["path"]).read_text()) == envelope["data"]


def test_load_accepts_legacy_disk_envelope(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda name, data: None)
    data = attach_hashes(_data())
    envelope = {
        "name": "example",
        "path": "artifacts/example.json",
        "semantic_sha256": data["semantic_sha256"],
        "artifact_sha256": data["artifact_sha256"],
        "data": data,
    }
    target = tmp_path / envelope["path"]
    target.parent.mkdir()
    target.write_text(json.dumps(envelope), encoding="utf-8")

    assert artifact_io.load_artifact_envelope(tmp_path, envelope) == data


def test_atomic_write_failure_preserves_existing_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda name, data: None)
    target = tmp_path / "artifacts/example.json"
    target.parent.mkdir()
    target.write_text('{"old":true}', encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(artifact_io.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        artifact_io.write_artifact_atomic(
            "artifacts/example.json", "example", _data()
        )

    assert target.read_text(encoding="utf-8") == '{"old":true}'


@pytest.mark.parametrize(
    "bad_path",
    ["../outside.json", "artifacts/../../outside.json", "/tmp/outside.json", "assets/x.json"],
)
def test_artifact_paths_cannot_escape_project_artifacts(bad_path, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda name, data: None)
    with pytest.raises(ValueError, match="project-relative.*artifacts"):
        artifact_io.write_artifact_atomic(bad_path, "example", _data())


def test_load_rejects_path_escape(tmp_path) -> None:
    data = attach_hashes(_data())
    envelope = {
        "name": "example",
        "path": "../outside.json",
        "semantic_sha256": data["semantic_sha256"],
        "artifact_sha256": data["artifact_sha256"],
        "data": data,
    }
    with pytest.raises(ValueError, match="project-relative.*artifacts"):
        artifact_io.load_artifact_envelope(tmp_path, envelope)


def test_load_rejects_disk_embedded_mismatch_and_hash_replay(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda name, data: None)
    envelope = artifact_io.write_artifact_atomic(
        "artifacts/example.json", "example", _data()
    )

    replay = deepcopy(envelope)
    replay["data"]["payload"] = "tampered"
    replay["data"] = attach_hashes(replay["data"])
    replay["semantic_sha256"] = replay["data"]["semantic_sha256"]
    replay["artifact_sha256"] = replay["data"]["artifact_sha256"]
    with pytest.raises(ValueError, match="disk.*embedded"):
        artifact_io.load_artifact_envelope(tmp_path, replay)

    disk_replay = deepcopy(envelope["data"])
    disk_replay["payload"] = "tampered"
    (tmp_path / "artifacts/example.json").write_text(json.dumps(disk_replay))
    with pytest.raises(ValueError, match="hash"):
        artifact_io.load_artifact_envelope(tmp_path, envelope)


def test_unwrap_checkpoint_artifact_supports_legacy_dict_and_string_path(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda name, data: None)
    raw = {"version": "1.0", "payload": "legacy"}
    assert artifact_io.unwrap_checkpoint_artifact(tmp_path, "example", raw) == raw

    path = tmp_path / "artifacts/legacy.json"
    path.parent.mkdir()
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert artifact_io.unwrap_checkpoint_artifact(
        tmp_path, "example", "artifacts/legacy.json"
    ) == raw


def test_scoped_artifact_path_is_contained(tmp_path) -> None:
    target = artifact_io.scoped_artifact_path(tmp_path, "evaluation_report", "final")
    assert target == (tmp_path / "artifacts" / "evaluation_report.final.json").resolve()


def test_scoped_artifact_path_rejects_unknown_scope(tmp_path) -> None:
    with pytest.raises(ValueError, match="does not support scope"):
        artifact_io.scoped_artifact_path(tmp_path, "evaluation_report", "draft")
    with pytest.raises(ValueError, match="does not support scope"):
        artifact_io.scoped_artifact_path(tmp_path, "script", "final")
