from __future__ import annotations


def test_selected_media_uploads_into_project_input_directory(backlot_client, projects_root) -> None:
    from tests.backlot.test_skill_catalog import _intake

    create = backlot_client.post(
        "/api/v2/projects",
        headers={"Origin": "http://testserver", "X-CSRF-Token": "test-csrf", "Idempotency-Key": "create-upload-project"},
        json={"project_id": "upload-demo", "title": "上传演示", "skill_id": "ecommerce-viral-remix", "skill_version": "1.0.0", "intake": _intake()},
    )
    assert create.status_code == 200, create.text
    response = backlot_client.post(
        "/api/v2/projects/upload-demo/inputs/reference",
        headers={"Origin": "http://testserver", "X-CSRF-Token": "test-csrf", "X-Upload-Path": "reference.mp4", "Content-Type": "video/mp4"},
        content=b"selected-video-bytes",
    )
    assert response.status_code == 200, response.text
    assert response.json()["path"] == "inputs/reference/reference.mp4"
    assert (projects_root / "upload-demo/inputs/reference/reference.mp4").read_bytes() == b"selected-video-bytes"
    source = backlot_client.post(
        "/api/v2/projects/upload-demo/inputs/source",
        headers={"Origin": "http://testserver", "X-CSRF-Token": "test-csrf", "X-Upload-Path": "product.mov", "Content-Type": "video/quicktime"},
        content=b"product-video-bytes",
    )
    assert source.json()["path"] == "inputs/source/video/product/product.mov"
    assert (projects_root / "upload-demo/inputs/source/video/product/product.mov").read_bytes() == b"product-video-bytes"


def test_upload_decodes_non_ascii_filename_from_ascii_header(backlot_client, make_project, projects_root) -> None:
    make_project(projects_root, "unicode-upload", "cinematic-fast")
    response = backlot_client.post(
        "/api/v2/projects/unicode-upload/inputs/source",
        headers={
            "Origin": "http://testserver", "X-CSRF-Token": "test-csrf",
            "X-Upload-Path": "%E9%80%8F%E6%98%8E%E6%A1%8C%E5%9E%AB-%E9%98%B2%E5%88%AE.MP4",
            "Content-Type": "video/mp4",
        },
        content=b"unicode-name-video",
    )
    assert response.status_code == 200, response.text
    assert response.json()["path"] == "inputs/source/video/product/透明桌垫-防刮.MP4"
    assert (projects_root / "unicode-upload/inputs/source/video/product/透明桌垫-防刮.MP4").is_file()


def test_input_upload_rejects_unsafe_names_and_unsupported_media(backlot_client, make_project, projects_root) -> None:
    make_project(projects_root, "upload-guard", "cinematic-fast")
    headers = {"Origin": "http://testserver", "X-CSRF-Token": "test-csrf", "Content-Type": "application/octet-stream"}
    for name in ("../private.mov", "notes.txt"):
        response = backlot_client.post(
            "/api/v2/projects/upload-guard/inputs/source",
            headers={**headers, "X-Upload-Path": name}, content=b"x",
        )
        assert response.status_code == 422


def test_project_intake_rejects_absolute_media_paths(backlot_client) -> None:
    from tests.backlot.test_skill_catalog import _intake

    intake = _intake()
    intake["reference_paths"] = ["/Users/example/reference.mp4"]
    response = backlot_client.post(
        "/api/v2/projects",
        headers={"Origin": "http://testserver", "X-CSRF-Token": "test-csrf", "Idempotency-Key": "unsafe-path-project"},
        json={"project_id": "unsafe-path-project", "title": "不安全路径", "skill_id": "ecommerce-viral-remix", "skill_version": "1.0.0", "intake": intake},
    )
    assert response.status_code == 422
