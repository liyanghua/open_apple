// Read-only shot review. Bounds are source seconds; controls use output seconds.
const finite = value => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
const element = (tag, text) => {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  return el;
};

export function createSegmentPreview(shot, label = "本镜片段预览") {
  const wrapper = element("div");
  wrapper.className = "shot-segment-preview";
  const status = element("p");
  status.className = "approval-detail-copy";
  status.setAttribute("role", "status");
  if (!shot.preview_url) {
    status.textContent = "尚无片段预览：待生成或待准备，当前只审核镜头安排。";
    wrapper.append(status);
    return wrapper;
  }
  const full = element("a", "查看完整原片（另开）");
  full.href = shot.preview_url;
  full.target = "_blank";
  full.rel = "noopener noreferrer";
  const start = Number(shot.source_in_seconds), end = Number(shot.source_out_seconds);
  if (!finite(shot.source_in_seconds) || !finite(shot.source_out_seconds) || start < 0 || end <= start) {
    status.textContent = "片段区间缺失或无效，暂不能按镜头预览；不会自动播放完整原片。";
    wrapper.append(status, full);
    return wrapper;
  }
  const span = end - start;
  const epsilon = 0.00001; // Native currentTime may be quantized to microseconds.
  const seekStart = Math.ceil(start * 1e6) / 1e6;
  const timelineSpan = Number(shot.timeline_out_seconds) - Number(shot.timeline_in_seconds);
  const duration = finite(shot.timeline_in_seconds) && finite(shot.timeline_out_seconds) && timelineSpan > 0 ? timelineSpan : span;
  const rate = span / duration;
  // Seek just inside the half-open interval, never onto the next shot's first frame.
  const lastTime = end - Math.min(1 / 60, span / 2);
  const video = element("video");
  video.className = "approval-detail-video";
  video.controls = false;
  video.playsInline = true;
  video.preload = "metadata";
  video.muted = true;
  video.setAttribute("aria-label", label);
  if (shot.poster_url) video.poster = shot.poster_url;
  video.src = `${shot.preview_url.split("#")[0]}#t=${start},${end}`;
  const description = element("p", `仅播放源片 ${start.toFixed(3)}–${end.toFixed(3)} 秒 · 本镜 ${duration.toFixed(3)} 秒 · ${rate.toFixed(3)} 倍速 · 原片画面，非新成片（原音静音）`);
  description.className = "approval-detail-copy";
  const controls = element("div"); controls.className = "shot-segment-controls";
  const play = element("button", "播放本镜"); play.type = "button";
  const replay = element("button", "重播本镜"); replay.type = "button";
  const slider = element("input");
  slider.type = "range"; slider.min = "0"; slider.max = String(duration); slider.step = "any"; slider.value = "0";
  slider.setAttribute("aria-label", `${label}进度（仅本镜）`);
  const time = element("output");
  controls.append(play, replay, slider, time);
  wrapper.append(video, description, controls, status, full);
  let complete = false, valid = true, frameRequest = null;
  const update = () => {
    const elapsed = complete ? duration : Math.max(0, Math.min(duration, (video.currentTime - start) / rate));
    slider.value = String(elapsed);
    slider.setAttribute("aria-valuetext", `${elapsed.toFixed(2)} / ${duration.toFixed(2)} 秒`);
    time.textContent = `${elapsed.toFixed(2)} / ${duration.toFixed(2)} 秒`;
    play.textContent = video.paused ? "播放本镜" : "暂停本镜";
  };
  const cancelWatch = () => {
    if (frameRequest !== null) cancelAnimationFrame(frameRequest);
    frameRequest = null;
  };
  const stopAtEnd = () => {
    complete = true;
    video.pause();
    if (Math.abs(video.currentTime - lastTime) > epsilon) video.currentTime = lastTime;
    update();
  };
  const checkBounds = () => {
    if (!valid) return;
    if (video.currentTime >= lastTime) stopAtEnd();
    else if (video.currentTime < start - epsilon) video.currentTime = seekStart;
    update();
  };
  const watch = () => {
    frameRequest = null;
    if (!wrapper.isConnected) { video.pause(); return; }
    checkBounds();
    if (!video.paused) frameRequest = requestAnimationFrame(watch);
  };
  const fail = message => {
    valid = false;
    video.pause();
    play.disabled = replay.disabled = slider.disabled = true;
    status.textContent = message;
  };
  const initialize = () => {
    if (!Number.isFinite(video.duration) || start >= video.duration || end > video.duration + 0.002) {
      fail("片段区间超出当前媒体时长，请检查原片与代理片段绑定；不会播放错误区间。");
      return;
    }
    try {
      video.playbackRate = rate;
      video.currentTime = seekStart;
      update();
    } catch { fail("当前浏览器无法按计划速度预览此片段。"); }
  };
  const begin = async (restart = false) => {
    if (!valid) return;
    if (restart || complete || video.currentTime < start - epsilon || video.currentTime >= lastTime) {
      complete = false; video.currentTime = seekStart;
    }
    try { await video.play(); }
    catch { status.textContent = "播放未启动，请再次点击播放本镜。"; }
  };
  play.addEventListener("click", () => video.paused ? begin() : video.pause());
  replay.addEventListener("click", () => begin(true));
  slider.addEventListener("input", () => {
    const value = Math.max(0, Math.min(duration, Number(slider.value)));
    complete = value >= duration;
    if (complete) video.pause();
    video.currentTime = Math.max(seekStart, Math.min(lastTime, start + value * rate));
    update();
  });
  video.addEventListener("loadedmetadata", initialize);
  video.addEventListener("play", () => {
    if (!valid) { video.pause(); return; }
    if (complete || video.currentTime < start - epsilon || video.currentTime >= lastTime) {
      complete = false; video.currentTime = seekStart;
    }
    update();
    cancelWatch();
    if (typeof requestAnimationFrame === "function") frameRequest = requestAnimationFrame(watch);
  });
  video.addEventListener("pause", () => { cancelWatch(); update(); });
  video.addEventListener("timeupdate", checkBounds);
  video.addEventListener("seeking", checkBounds);
  video.addEventListener("ended", stopAtEnd);
  video.addEventListener("error", () => fail("片段播放失败，请检查素材是否可读取或刷新页面。"));
  update();
  if (video.readyState >= 1) initialize();
  return wrapper;
}
