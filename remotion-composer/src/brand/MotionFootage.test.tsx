import {describe, expect, test, vi} from "vitest";
import {createElement} from "react";
import {MotionFootage, mapMotionRegions} from "./MotionFootage";
import type {MotionFraming} from "./types";
const {renderToStaticMarkup}: {renderToStaticMarkup: (element: React.ReactElement) => string} = require("react-dom/server");

vi.mock("remotion", async original => ({...await original<typeof import("remotion")>(),
  OffthreadVideo: ({startFrom, playbackRate, ...props}: any) => createElement("video", {...props, "data-start": startFrom, "data-rate": playbackRate}),
}));
const framing: MotionFraming = {source: {width: 960, height: 960}, viewport: {x: 0, y: 350, width: 1080, height: 1080},
  fit: "contain", position: {x: .5, y: .5}, actionCoverage: "whole_shot_envelope",
  actionRegions: [{x: 0, y: 0, width: 960, height: 960}], background: {blurPx: 48, opacity: .3, scale: 1.1}};

describe("motion footage", () => {
  test("contain preserves the complete square source in the portrait viewport", () => {
    const mapped = mapMotionRegions(framing);
    expect(mapped.media).toEqual({x: 0, y: 350, width: 1080, height: 1080});
    expect(mapped.actions).toEqual([mapped.media]);
    expect(mapped.cropped).toBe(false);
  });
  test("crop maps only a safe centered action region while exposing source crop", () => {
    const mapped = mapMotionRegions({...framing, source: {width: 1920, height: 1080}, fit: "crop",
      actionRegions: [{x: 540, y: 0, width: 840, height: 1080}]});
    expect(mapped.media).toEqual({x: -420, y: 350, width: 1920, height: 1080});
    expect(mapped.actions[0]).toEqual({x: 120, y: 350, width: 840, height: 1080});
    expect(mapped.cropped).toBe(true);
  });
  test("foreground and blur background use the identical silent source state", () => {
    const markup = renderToStaticMarkup(createElement(MotionFootage, {src: "motion.mp4", sourceStartFrame: 15, playbackRate: 1, framing}));
    expect(markup.match(/muted=""/g)).toHaveLength(2);
    expect(markup.match(/data-start="15"/g)).toHaveLength(2);
    expect(markup).toContain("left:0;top:350px;width:1080px;height:1080px");
    expect(markup).toContain("blur(48px)");
    expect(markup).toContain("opacity:0.3");
    expect(markup).toContain("scale(1.1)");
    expect(markup).not.toContain("data-brand-role");
  });
});
