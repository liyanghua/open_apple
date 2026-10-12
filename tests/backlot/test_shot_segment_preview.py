"""Run the real shot renderer against a minimal DOM/media event boundary.

Browser decoding/seeking is verified separately in the live review page.
"""
from pathlib import Path
import json
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def preview():
    script = r"""
import fs from 'node:fs';
import vm from 'node:vm';
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.listeners = {}; this.dataset = {};
    this.attributes = {}; this.seekWrites = 0; this.currentTime = 0; this.duration = 12.446;
    this.playbackRate = 1; this.paused = true; this.readyState = 0;
    this.textContent = ''; this.isConnected = true;
  }
  append(...items) { this.children.push(...items); }
  replaceWith(element) { this.children = [element]; }
  get currentTime() { return this._time; }
  set currentTime(value) { this._time = Math.floor(value * 1e6) / 1e6; this.seekWrites++; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(name, callback) { (this.listeners[name] ??= []).push(callback); }
  dispatch(name) { for (const fn of this.listeners[name] || []) fn({target:this}); }
  pause() { this.paused = true; this.dispatch('pause'); }
  async play() { this.paused = false; this.dispatch('play'); }
}
const all = (root, tag) => [root, ...root.children.flatMap(c => all(c, tag))].filter(e => !tag || e.tagName === tag);
global.document = {createElement: tag => new Element(tag)};
const modulePath = './backlot/ui/operator/segment_preview.js';
const module = fs.existsSync(modulePath) ? await import(modulePath) : {};
const context = vm.createContext({document, ...module, APPROVAL_COPY:{playbackFailed:'播放失败'}});
const source = fs.readFileSync('./backlot/ui/operator/approval.js', 'utf8');
for (const name of ['node','detailRow','hasText','secondsRange','mediaVideo','renderShotPlanDetail']) {
  const match = source.match(new RegExp('(?:export )?function '+name+'\\([^]*?^\\}', 'm'));
  if (!match) throw new Error('Missing renderer '+name);
  vm.runInContext(match[0].replace(/^export /,''), context);
}
const shot = {id:'s02', title:'第二镜', preview_url:'/source.mp4',
  source_in_seconds:38/30, source_out_seconds:68/30,
  timeline_in_seconds:1.4, timeline_out_seconds:2.5};
const render = (data) => {
  const root = new Element('div');
  context.renderShotPlanDetail(root, {shots:[data]});
  return root;
};
const root = render(shot), video = all(root,'video')[0];
video.readyState = 1; video.dispatch('loadedmetadata');
const initial = {time:video.currentTime, rate:video.playbackRate, muted:video.muted, nativeControls:video.controls};
video.currentTime=38/30;
const writesBefore=video.seekWrites;
for(let i=0;i<5;i++) video.dispatch('seeking');
const boundarySeekWrites=video.seekWrites-writesBefore;
const slider = all(root,'input').find(e=>e.type==='range');
const buttons = all(root,'button');
video.currentTime = 0; await video.play();
const startOnPlay = video.currentTime;
video.currentTime = 2.4; video.dispatch('timeupdate');
const stopped = {time:video.currentTime, paused:video.paused};
await video.play(); const replayTime = video.currentTime;
video.currentTime = 0; video.dispatch('seeking'); const seekLow = video.currentTime;
video.currentTime = 10; video.dispatch('seeking'); const seekHigh = video.currentTime;
if (slider) { slider.value='0.55'; slider.dispatch('input'); }
const sliderTime = video.currentTime;
video.dispatch('error');
const invalid = render({...shot, source_out_seconds:0});
const absent = render({...shot, source_in_seconds:undefined, source_out_seconds:undefined});
const generated = render({id:'s06',title:'待生成',timeline_in_seconds:7.3,timeline_out_seconds:10.5});
const reference = render({id:'ref',reference_evidence:{preview_url:'/ref.mp4',start_seconds:5,end_seconds:6}});
const rv = all(reference,'video')[0]; rv.readyState=1; rv.dispatch('loadedmetadata');
console.log(JSON.stringify({initial,boundarySeekWrites,startOnPlay,stopped,replayTime,seekLow,seekHigh,sliderTime,
  slider:slider && {min:slider.min,max:slider.max,step:slider.step},buttons:buttons.map(e=>e.textContent),
  fullLinks:all(root,'a').map(e=>({href:e.href,label:e.textContent})),
  text:all(root).map(e=>e.textContent).join(' '), invalidVideoCount:all(invalid,'video').length,
  missingVideoCount:all(absent,'video').length,generatedVideoCount:all(generated,'video').length,
  generatedText:all(generated).map(e=>e.textContent).join(' '), referenceStart:rv.currentTime}));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_metadata_seeks_to_shot_and_uses_planned_speed(preview):
    assert preview["initial"]["time"] == pytest.approx(38 / 30)
    assert preview["initial"]["rate"] == pytest.approx(1 / 1.1)
    assert preview["initial"]["muted"] is True


def test_play_and_replay_begin_at_source_in(preview):
    assert preview["startOnPlay"] == pytest.approx(38 / 30)
    assert preview["replayTime"] == pytest.approx(38 / 30)


def test_playback_stops_inside_exclusive_end(preview):
    assert preview["stopped"]["paused"] is True
    assert 38 / 30 <= preview["stopped"]["time"] < 68 / 30


def test_seeking_cannot_escape_selected_source_interval(preview):
    assert preview["seekLow"] == pytest.approx(38 / 30)
    assert 38 / 30 <= preview["seekHigh"] < 68 / 30


def test_scrubber_is_clip_relative_and_retimed(preview):
    assert preview["initial"]["nativeControls"] is False
    assert float(preview["slider"]["min"]) == 0
    assert float(preview["slider"]["max"]) == pytest.approx(1.1)
    assert preview["sliderTime"] == pytest.approx(38 / 30 + 0.5)


def test_full_source_is_separate_and_error_is_visible(preview):
    assert {"href":"/source.mp4", "label":"查看完整原片（另开）"} in preview["fullLinks"]
    assert "重播本镜" in preview["buttons"]
    assert "播放失败" in preview["text"]


def test_invalid_or_missing_range_does_not_silently_play_full_video(preview):
    assert preview["invalidVideoCount"] == 0
    assert preview["missingVideoCount"] == 0


def test_ungenerated_shot_has_explicit_placeholder(preview):
    assert preview["generatedVideoCount"] == 0
    assert "尚无片段预览" in preview["generatedText"]


def test_reference_evidence_also_uses_its_own_range(preview):
    assert preview["referenceStart"] == pytest.approx(5)


def test_microsecond_rounding_does_not_cause_repeated_seeks(preview):
    assert preview["boundarySeekWrites"] == 0


def test_fractional_frame_duration_does_not_snap_scrubber_below_end(preview):
    assert preview["slider"]["step"] == "any"
