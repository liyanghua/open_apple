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
    (data.shots || []).forEach((shot) => {
      const input = document.createElement("input"); input.type = "number"; input.min = "0"; input.step = "0.1"; input.value = shot.out_seconds || 0; input.disabled = !editable;
      input.value = shot.source_out_seconds ?? shot.out_seconds ?? 0;
      input.addEventListener("input", () => emit({ op: "set_source_range", shot_id: shot.id, in_seconds: Number(shot.source_in_seconds ?? shot.in_seconds ?? 0), out_seconds: Number(input.value) }));
      add(`${shot.id || "镜头"} 素材出点`, input);
    });
  } else if (editor?.type === "asset_review") {
    add("口播音色", textInput("温馨自然", (voice) => emit({ op: "set_tts", provider: "doubao", model: "seed-tts", voice, rate: 1 })));
    add("背景音乐", textInput("温馨生活感", (track) => emit({ op: "set_bgm", source: "library", track_id: track })));
  } else if (editor?.type === "sample_review") {
    add("时间点意见", textarea("", (text) => emit({ op: "add_timecode_comment", start_seconds: 0, end_seconds: 1, text })));
  } else {
    container.append(node("p", "empty-copy", "该阶段暂时没有可编辑内容"));
  }
}
