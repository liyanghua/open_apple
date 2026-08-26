from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_video_scene_honors_hard_cut_tokens_and_backing_color() -> None:
    source = (REPO_ROOT / "remotion-composer/src/Explainer.tsx").read_text(
        encoding="utf-8"
    )

    # 评审 P1-4：默认（无 recipe、无显式过渡）= 硬切（不再每镜默认 0.27s 淡入淡出 → 切点暗帧）；
    # 显式 cut/none/dissolve/flash/impact 均硬切；仅 "fade" 在 clip 内部淡入淡出。
    assert '["cut", "none", "dissolve", "flash", "impact"].includes(tIn)' in source or "hardTokens.includes(tIn)" in source
    assert "!tIn" in source
    assert "!tOut" in source
    assert "recipeFades" in source
    assert "transitionIn={cut.transition_in}" in source
    assert "transitionOut={cut.transition_out}" in source
    assert "sceneDurationSeconds={cut.out_seconds - cut.in_seconds}" in source
    assert "Math.round(sceneDurationSeconds * fps)" in source
    assert "durationInFrames - transitionFrames" in source
    assert "backgroundColor={cut.backgroundColor}" in source
    # dissolve 桥：动作匹配切用重叠交叉溶解（Layer 1b），不产生暗帧。
    assert "DissolveBridge" in source
    assert "durationInFrames={overlap}" in source


def test_cinematic_fades_are_bounded_by_each_scene_duration() -> None:
    source = (REPO_ROOT / "remotion-composer/src/CinematicRenderer.tsx").read_text(
        encoding="utf-8"
    )

    assert "Math.round(scene.durationSeconds * fps)" in source
    assert "durationInFrames - fadeOutFrames" in source
