"""Derive validated Remotion sample props from canonical sample artifacts."""

from __future__ import annotations

from typing import Any, Mapping


def _number(value: Any, *, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"sample payload {field} must be numeric")
    return float(value)


def _asset_index(asset_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    assets = asset_manifest.get("assets") or asset_manifest.get("planned_assets") or []
    if not isinstance(assets, list):
        raise ValueError("sample payload asset_manifest.assets must be a list")
    return {
        str(asset["id"]): asset
        for asset in assets
        if isinstance(asset, Mapping) and asset.get("id")
    }


def build_sample_render_payload(sample_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build sequential cuts while keeping source trim separate from timeline.

    ``final_props`` owns the canonical frame timeline.  The returned payload is
    intentionally runtime-only: Remotion receives ``in_seconds`` as the
    cumulative output position and ``source_in_seconds`` as the source seek.
    """
    final_props = sample_payload.get("final_props")
    asset_manifest = sample_payload.get("asset_manifest")
    if not isinstance(final_props, Mapping):
        raise ValueError("sample payload requires final_props")
    if not isinstance(asset_manifest, Mapping):
        raise ValueError("sample payload requires asset_manifest")
    fps = _number(final_props.get("fps"), field="final_props.fps")
    if fps <= 0:
        raise ValueError("sample payload final_props.fps must be positive")
    scenes = final_props.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("sample payload final_props.scenes must be a non-empty list")

    assets = _asset_index(asset_manifest)
    footage = final_props.get("footage") if isinstance(final_props.get("footage"), Mapping) else {}
    ordered = sorted(scenes, key=lambda scene: _number(scene.get("fromFrame"), field="scene.fromFrame"))
    cuts: list[dict[str, Any]] = []
    expected_from = 0.0
    for scene in ordered:
        if not isinstance(scene, Mapping):
            raise ValueError("sample payload final_props.scenes contains an invalid scene")
        scene_id = str(scene.get("id") or "")
        if not scene_id:
            raise ValueError("sample payload scene.id is required")
        from_frame = _number(scene.get("fromFrame"), field=f"{scene_id}.fromFrame")
        to_frame = _number(scene.get("toFrameExclusive"), field=f"{scene_id}.toFrameExclusive")
        if to_frame <= from_frame:
            raise ValueError(f"sample payload {scene_id} has an invalid frame range")
        if from_frame < expected_from:
            raise ValueError(f"sample payload timeline overlap before {scene_id}")
        if from_frame > expected_from:
            raise ValueError(f"sample payload timeline gap before {scene_id}")

        asset_id = str(scene.get("assetId") or "")
        asset = assets.get(asset_id)
        source = None
        if asset is not None:
            source = asset.get("path") or asset.get("output_path")
        if not source and scene.get("footageKey"):
            source = footage.get(str(scene["footageKey"]))
        if not isinstance(source, str) or not source:
            raise ValueError(f"sample payload {scene_id} has no resolvable media source")

        timeline_duration = (to_frame - from_frame) / fps
        source_in = _number(scene.get("sourceInSeconds", 0.0), field=f"{scene_id}.sourceInSeconds")
        if source_in < 0:
            raise ValueError(f"sample payload {scene_id} has a negative source trim")
        asset_duration = None
        if asset is not None:
            asset_duration = asset.get("source_duration_seconds")
            if asset_duration is None:
                asset_duration = asset.get("duration_seconds")
        if isinstance(asset_duration, (int, float)) and timeline_duration > float(asset_duration) + 1e-6:
            raise ValueError(f"sample payload {scene_id} timeline exceeds source duration")
        if isinstance(asset_duration, (int, float)):
            # final_props.scenes.sourceInSeconds records the approved
            # source_selection in ORIGINAL-source coordinates, but the render
            # asset is a scene-length proxy clip (duration == timeline). Seek it
            # from the proxy's own start (0) unless the asset is long enough to
            # honor the requested source window, so the source trim must be
            # clamped — never silently trusted.
            max_in = max(0.0, float(asset_duration) - timeline_duration)
            source_in = min(source_in, max_in)
        source_out = source_in + timeline_duration

        cuts.append({
            "id": scene_id,
            "source": source,
            "in_seconds": round(from_frame / fps, 6),
            "out_seconds": round(to_frame / fps, 6),
            "source_in_seconds": source_in,
            "source_out_seconds": source_out,
        })
        expected_from = to_frame

    runtime = str(sample_payload.get("render_runtime") or "remotion")
    renderer_family = str(sample_payload.get("renderer_family") or "explainer-data")
    metadata = dict(sample_payload.get("metadata") or {})
    metadata.setdefault("durationInFrames", final_props.get("durationInFrames", int(expected_from)))
    raw_audio = final_props.get("audio") or sample_payload.get("audio") or {}
    audio = dict(raw_audio) if isinstance(raw_audio, Mapping) else {}
    if isinstance(audio.get("mix"), Mapping):
        mix = audio["mix"]
        narration = mix.get("narration") if isinstance(mix.get("narration"), Mapping) else {}
        music = mix.get("music") if isinstance(mix.get("music"), Mapping) else {}
        # A reuse-assets render must reproduce the already-approved mix, not
        # re-mix the raw generation sources. final_props.audio.mix records the
        # source of each role (e.g. the raw SUNO bgm.mp3), but the approved
        # render muxes the *derived* products recorded in asset_manifest (e.g.
        # narration-mix.mp3 + bgm-ducked.mp3). Prefer those derived audio assets.
        derived = [
            asset for asset in assets.values()
            if isinstance(asset, Mapping) and str(asset.get("type", "")) == "audio"
        ]
        narration_src = narration.get("path")
        music_src = music.get("path")
        nar_asset = next(
            (a for a in derived
             if (a.get("path") or a.get("output_path")) == narration_src),
            None,
        )
        if nar_asset is not None:
            narration_src = nar_asset.get("path") or narration_src
        other_derived = [a for a in derived if a is not nar_asset]
        music_derived = False
        if music_src:
            if len(other_derived) == 1:
                music_src = other_derived[0].get("path") or music_src
                music_derived = True
            else:
                match = next(
                    (a for a in other_derived
                     if (a.get("path") or a.get("output_path")) == music_src),
                    None,
                )
                if match is not None:
                    music_src = match.get("path") or music_src
                    music_derived = True
        audio = {}
        if narration_src:
            audio["narration"] = {"src": narration_src}
        # 已批准的成品混音（sample-mix 等）本身已含 ducked BGM：
        # 渲染器不得再叠一条音乐轨（旧实现叠 0.1 音量导致 True-Peak 超标）。
        # 派生双轨流（narration-mix.mp3 + bgm-ducked.mp3）不受影响：music 指向
        # 已压好的 bgm-ducked，本身即成品，无需再衰减。
        mix_product = str(narration_src or "").rsplit("/", 1)[-1] if narration_src else ""
        mix_includes_music = mix_product == "sample-mix.mp3"
        if music_src and not mix_includes_music:
            audio["music"] = {"src": music_src}
            # Derived mix products are pre-mixed to the approved level; only
            # attenuate when falling back to a raw generation source.
            if not music_derived:
                audio["music"]["volume"] = 0.1
    raw_captions = list(final_props.get("captions") or sample_payload.get("captions") or [])
    # The Explainer's CaptionOverlay renders WordCaption[{word, startMs, endMs}].
    # Canonical final_props.captions store the approved short-word captions as
    # phrase entries {text, startMs, endMs}; normalize them to the word shape so
    # the render never emits a literal "undefined". Each phrase is shown on its
    # own page (captionWordsPerPage=1) so it appears aligned to its shot.
    captions: list[dict[str, Any]] = []
    for cap in raw_captions:
        if not isinstance(cap, Mapping):
            raise ValueError("sample payload captions 含非对象项")
        start_ms = cap.get("startMs")
        end_ms = cap.get("endMs")
        if start_ms is None or end_ms is None or end_ms <= start_ms:
            raise ValueError("sample payload 字幕缺少有效起止时间(startMs/endMs)")
        caption_word = cap.get("word") if cap.get("word") is not None else cap.get("text")
        if caption_word is None or not str(caption_word).strip():
            raise ValueError("sample payload 字幕缺少文案(word/text)")
        captions.append({"word": str(caption_word), "startMs": start_ms, "endMs": end_ms})

    payload: dict[str, Any] = {
        "render_runtime": runtime,
        "composition_mode": str(sample_payload.get("composition_mode") or "templated"),
        "renderer_family": renderer_family,
        "cuts": cuts,
        "audio": audio,
        "captions": captions,
        "captionWordsPerPage": 1 if captions else None,
        "caption_render_mode": sample_payload.get("caption_render_mode", "remotion_overlay"),
        "caption_source": sample_payload.get("caption_source", "artifacts/final_props.json#captions"),
        "subtitles": dict(sample_payload.get("subtitles") or {}),
        "metadata": metadata,
    }
    # 口播字幕轨：narration 逐句（script sections → 底部 SafeCaptionTrack），与花字双层共存。
    narration_subs = _narration_subtitles(sample_payload.get("script"))
    if narration_subs:
        payload["narrationSubtitles"] = narration_subs

    # 花字风格：显式 captionStyle 优先，否则从 caption_style_fingerprint 派生。
    if sample_payload.get("captionStyle"):
        payload["captionStyle"] = sample_payload["captionStyle"]
    elif sample_payload.get("caption_style_fingerprint"):
        from lib.caption_style import to_overlay_spec

        fingerprint = sample_payload["caption_style_fingerprint"]
        applicability = str(fingerprint.get("applicability") or "") if isinstance(fingerprint, Mapping) else ""
        style = fingerprint.get("style") if isinstance(fingerprint, Mapping) else None
        # 仅 extracted / needs_review 应用样式；not_applicable（参考片无字幕）
        # 走渲染器通用默认，绝不强制特定产品花字。
        if applicability in {"extracted", "needs_review"} and isinstance(style, Mapping):
            payload["captionStyle"] = to_overlay_spec(style)

    # P2：scene_plan 的 caption/transition recipe intent → 渲染级规格。
    # 渲染器按 **cut.id（shot-NN）** 查 captionRecipes/transitionRecipes；而 scene_plan 的
    # recipe 按 scene_id（scene-NNN）索引 —— 这里按时间线顺序做 1:1 重映射（评审 P1-4：
    # 两组 key 交集原本为空，转场/花字 recipe 从未生效）。
    scene_plan = sample_payload.get("scene_plan")
    if isinstance(scene_plan, Mapping) and scene_plan.get("scenes"):
        from lib.recipe_router import scene_recipe_specs

        specs = scene_recipe_specs(scene_plan, runtime)
        scene_ids = [str(s.get("id") or "") for s in scene_plan["scenes"] if isinstance(s, Mapping)]

        def _remap(by_scene: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for idx, cut in enumerate(cuts):
                if idx >= len(scene_ids):
                    break
                value = by_scene.get(scene_ids[idx])
                if value is not None:
                    out[str(cut["id"])] = value
            return out

        if specs["caption_recipes"]:
            payload["captionRecipes"] = _remap(specs["caption_recipes"])
        if specs["transition_recipes"]:
            payload["transitionRecipes"] = _remap(specs["transition_recipes"])
    return payload


def _narration_subtitles(script: Any) -> list[dict[str, Any]]:
    """Derive the bottom narration-subtitle track from the approved script.

    One cue per section with non-empty narration, timed by the section's own
    timeline window.  Shape matches ``@remotion/captions`` ``Caption``
    (``{text, startMs, endMs}``) as consumed by the Explainer's
    ``SafeCaptionTrack`` (bottom safe-zone, 口播字幕轨), which co-exists with
    the 花字 ``CaptionOverlay`` as the second caption layer.
    """
    if not isinstance(script, Mapping):
        return []
    sections = script.get("sections")
    if not isinstance(sections, list):
        return []
    cues: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        text = section.get("narration")
        if not isinstance(text, str) or not text.strip():
            continue
        start = section.get("start_seconds")
        end = section.get("end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if float(end) <= float(start):
            continue
        cues.append({
            "text": text.strip(),
            "startMs": int(round(float(start) * 1000)),
            "endMs": int(round(float(end) * 1000)),
        })
    return cues
