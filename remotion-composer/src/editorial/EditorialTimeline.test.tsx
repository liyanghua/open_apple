import {describe, expect, test} from "vitest";
import {audioGainAtFrame, buildEditorialSchedule, textPlacementStyle} from "./EditorialTimeline";
import type {EditorialTimelineProps} from "./types";

const fixture: EditorialTimelineProps = {
  fps: 30, width: 1080, height: 1440,
  tracks: [
    {id: "subtitle", kind: "subtitle", clips: [{id: "s1", text: "一句话字幕", startSeconds: 1, endSeconds: 2, position: "bottom_center", styleToken: "taobao_subtitle_v1"}]},
    {id: "video", kind: "video", clips: [
      {id: "v2", source: "b.mp4", startSeconds: 1, sourceInSeconds: 2, sourceOutSeconds: 3, speed: 2, zIndex: 2},
      {id: "v1", source: "a.mp4", startSeconds: 0, sourceInSeconds: 0, sourceOutSeconds: 1, speed: 1, zIndex: 1},
    ]},
    {id: "text", kind: "text", clips: [{id: "t1", text: "吸水快", startSeconds: 0, endSeconds: 1, position: "top_center", styleToken: "taobao_selling_point_v1"}]},
    {id: "music", kind: "music", clips: [{id: "m1", source: "bgm.mp3", startSeconds: 0, endSeconds: 3, gainDb: -12, fadeInSeconds: 1, fadeOutSeconds: 1, ducking: {enabled: true, reductionDb: -8}}]},
    {id: "narration", kind: "narration", clips: [{id: "n1", source: "voice.mp3", startSeconds: 0, endSeconds: 2, gainDb: 0}]},
  ],
};

describe("EditorialTimeline", () => {
  test("orders tracks/clips deterministically and applies speed duration", () => {
    const schedule = buildEditorialSchedule(fixture);
    expect(schedule.map((track) => track.kind)).toEqual(["video", "narration", "music", "text", "subtitle"]);
    expect(schedule[0].clips.map((clip) => clip.id)).toEqual(["v1", "v2"]);
    expect(schedule[0].clips[1].durationInFrames).toBe(15);
  });

  test("renders every track of the same kind and suppresses disabled subtitles", () => {
    const multi = {...fixture, tracks: [
      ...fixture.tracks,
      {id: "text-2", kind: "text" as const, clips: [{id: "t2", text: "第二卖点", startSeconds: 1, endSeconds: 2, position: "top_center" as const, styleToken: "taobao_selling_point_v1"}]},
      {id: "subtitle-2", kind: "subtitle" as const, clips: [{id: "s2", text: "隐藏字幕", startSeconds: 1, endSeconds: 2, position: "bottom_center" as const, styleToken: "taobao_subtitle_v1", enabled: false}]},
    ]};
    const schedule = buildEditorialSchedule(multi);
    expect(schedule.filter((track) => track.kind === "text")).toHaveLength(2);
    expect(schedule.filter((track) => track.kind === "subtitle")[1].clips[0].enabled).toBe(false);
  });
  test("keeps selling point and one-line subtitle placements", () => {
    expect(textPlacementStyle("top_center", "taobao_selling_point_v1")).toMatchObject({top: 96});
    expect(textPlacementStyle("bottom_center", "taobao_subtitle_v1")).toMatchObject({bottom: 120, whiteSpace: "nowrap"});
  });
  test("applies narration-priority ducking and music fades", () => {
    expect(audioGainAtFrame(fixture.tracks[3].clips[0], 0, 30)).toBeCloseTo(-40);
    expect(audioGainAtFrame(fixture.tracks[3].clips[0], 30, 30)).toBeCloseTo(-20);
    expect(audioGainAtFrame(fixture.tracks[3].clips[0], 60, 30, false)).toBeCloseTo(-12);
  });
});
