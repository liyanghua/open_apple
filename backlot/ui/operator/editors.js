function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = String(text);
  return element;
}

function field(label, input) {
  const wrap = node("label", "edit-field");
  wrap.append(node("span", "edit-label", label), input);
  return wrap;
}

function textInput(value, onInput) {
  const input = document.createElement("input"); input.type = "text"; input.value = value || "";
  input.addEventListener("input", () => onInput(input.value)); return input;
}

function textarea(value, onInput) {
  const input = document.createElement("textarea"); input.rows = 3; input.value = value || "";
  input.addEventListener("input", () => onInput(input.value)); return input;
}

function numberInput(value, onChange) {
  const input = document.createElement("input");
  input.type = "number";
  input.min = "0";
  input.step = "0.1";
  input.value = value == null ? "" : value;
  input.addEventListener("change", () => onChange(Number(input.value)));
  return input;
}

function rangeInput(value, onChange) {
  const input = document.createElement("input");
  input.type = "range"; input.min = "0"; input.max = "1"; input.step = "0.01"; input.value = value == null ? 0 : value;
  input.addEventListener("input", () => onChange(Number(input.value)));
  return input;
}

function shotPreview(shot) {
  if (!shot.preview_url) return null;
  const video = document.createElement("video");
  video.className = "edit-shot-preview"; video.controls = true; video.playsInline = true; video.preload = "none";
  const start = Number(shot.source_in_seconds || 0);
  const end = shot.source_out_seconds == null ? null : Number(shot.source_out_seconds);
  video.src = `${shot.preview_url}#t=${start}${end == null ? "" : `,${end}`}`;
  video.setAttribute("aria-label", `${shot.title}素材预览`);
  return video;
}

export function renderTypedEditor(container, stage, editor, { editable, onOperation }) {
  container.replaceChildren();
  const data = editor?.data || {};
  const add = (label, input) => container.append(field(label, input));
  if (!editable) {
    container.append(node("p", "read-only-note", "当前账号只能查看，修改需要项目编辑权限"));
  }
  const emit = (operation) => { if (editable) onOperation(operation); };
  if (editor?.type === "proposal_choice") {
    (data.concepts || []).forEach((concept) => {
      const radio = document.createElement("input"); radio.type = "radio"; radio.name = "concept";
      radio.checked = concept.id === data.selected_id; radio.disabled = !editable;
      radio.addEventListener("change", () => emit({ op: "select_concept", concept_id: concept.id }));
      const label = field(concept.title || "创意方案", radio); label.classList.add("edit-choice"); container.append(label);
    });
    add("开头钩子", textInput(data.concepts?.find((item) => item.id === data.selected_id)?.hook, (text) => emit({ op: "replace_hook", text })));
  } else if (editor?.type === "shot_mapping") {
    container.append(node("p", "editor-help", "为每条分镜选择原视频中要使用的片段，填写开始和结束秒数；参考视频仅用于分析，不会进入成片。"));
    (data.shots || []).forEach((shot) => {
      const group = node("fieldset", "shot-range-editor");
      const legend = node("legend", "shot-range-title", `${shot.id || "镜头"} 这条素材用哪一段`);
      const source = node("p", "editor-help", `素材：${shot.source_label || "尚未映射"}`);
      const range = node("div", "shot-range-inputs");
      const start = numberInput(shot.source_in_seconds ?? shot.in_seconds ?? 0, () => emitRange());
      const end = numberInput(shot.source_out_seconds ?? shot.out_seconds ?? 0, () => emitRange());
      start.disabled = !editable;
      end.disabled = !editable;
      const emitRange = () => emit({
        op: "set_source_range",
        shot_id: shot.id,
        in_seconds: Number(start.value),
        out_seconds: Number(end.value),
      });
      range.append(field("从第几秒开始", start), field("到第几秒结束", end));
      group.append(legend, source, range);
      container.append(group);
    });
  } else if (editor?.type === "asset_review") {
    add("口播音色", textInput("温馨自然", (voice) => emit({ op: "set_tts", provider: "doubao", model: "seed-tts", voice, rate: 1 })));
    add("背景音乐", textInput("温馨生活感", (track) => emit({ op: "set_bgm", source: "library", track_id: track })));
  } else if (editor?.type === "sample_review") {
    add("时间点意见", textarea("", (text) => emit({ op: "add_timecode_comment", start_seconds: 0, end_seconds: 1, text })));
  } else if (editor?.type === "edit_review") {
    container.append(node("p", "editor-help", "先在下面改草稿；点击“预览修改影响”后，会明确显示哪些镜头、声音和后续阶段会变化。确认提交后才生成新版样片。"));
    (data.shots || []).forEach((shot) => {
      const group = node("fieldset", "edit-shot-editor");
      const legend = node("legend", "shot-range-title", `${shot.id} · ${shot.title}`);
      const keep = document.createElement("input"); keep.type = "checkbox"; keep.checked = shot.enabled !== false; keep.disabled = !editable;
      keep.addEventListener("change", () => emit({ op: "set_shot_enabled", shot_id: shot.id, enabled: keep.checked }));
      const keepLabel = field("保留这个镜头", keep); keepLabel.classList.add("edit-choice");
      const source = node("p", "editor-help", `素材：${shot.source_label} · ${shot.reason || "已按当前分镜安排"}`);
      const range = node("div", "shot-range-inputs");
      const start = numberInput(shot.source_in_seconds, () => emitRange()); start.disabled = !editable;
      const end = numberInput(shot.source_out_seconds, () => emitRange()); end.disabled = !editable;
      const emitRange = () => emit({ op: "set_source_range", shot_id: shot.id, in_seconds: Number(start.value), out_seconds: Number(end.value) });
      range.append(field("素材从第几秒开始", start), field("素材到第几秒结束", end));
      const speed = numberInput(shot.speed || 1, () => emit({ op: "set_shot_speed", shot_id: shot.id, speed: Number(speed.value) }));
      speed.min = "0.25"; speed.max = "3"; speed.step = "0.05"; speed.disabled = !editable;
      const caption = textarea(shot.caption, (text) => emit({ op: "set_caption", shot_id: shot.id, text })); caption.rows = 2; caption.disabled = !editable;
      group.append(legend, keepLabel, source, range, field("播放速度（1.0 为原速）", speed), field("这一镜字幕", caption));
      const preview = shotPreview(shot); if (preview) group.append(preview);
      container.append(group);
    });
    const audio = data.audio || {};
    const audioGroup = node("fieldset", "edit-audio-editor");
    audioGroup.append(node("legend", "shot-range-title", "声音强度"));
    const music = rangeInput(audio.music_volume, (value) => emit({ op: "set_audio_mix", music_volume: value, sfx_volume: Number(sfx.value), narration_enabled: narration.checked }));
    const sfx = rangeInput(audio.sfx_volume, (value) => emit({ op: "set_audio_mix", music_volume: Number(music.value), sfx_volume: value, narration_enabled: narration.checked }));
    const narration = document.createElement("input"); narration.type = "checkbox"; narration.checked = audio.narration_enabled !== false; narration.disabled = !editable;
    narration.addEventListener("change", () => emit({ op: "set_audio_mix", music_volume: Number(music.value), sfx_volume: Number(sfx.value), narration_enabled: narration.checked }));
    music.disabled = !editable; sfx.disabled = !editable;
    audioGroup.append(field("背景音乐音量", music), field("音效音量", sfx));
    const narrationLabel = field("保留口播", narration); narrationLabel.classList.add("edit-choice"); audioGroup.append(narrationLabel);
    container.append(audioGroup);
  } else {
    container.append(node("p", "empty-copy", "该阶段暂时没有可编辑内容"));
  }
}
