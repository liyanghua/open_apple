import {describe, expect, it} from "vitest";
import fixture from "../../../tests/fixtures/caption_layout/social_v1_cases.json";

import {
  DEFAULT_FONT_FAMILY,
  captionBoxForCue,
  fitCjkFontSize,
  isInsideSafeZone,
  stripTrailingPunctuation,
} from "./SafeCaptionTrack";

describe("SafeCaptionTrack deterministic layout", () => {
  it("strips trailing Chinese and English punctuation", () => {
    for (const testCase of fixture.strip_cases) {
      expect(stripTrailingPunctuation(testCase.input)).toBe(testCase.expected);
    }
  });

  it("matches the Python social-v1 layout fixture", () => {
    for (const testCase of fixture.layout_cases) {
      const box = captionBoxForCue({
        text: testCase.text,
        startMs: 0,
        endMs: 1000,
        timestampMs: 0,
        confidence: 1,
      });
      expect(fitCjkFontSize(testCase.text)).toBe(testCase.expected.font_size);
      expect({
        font_size: box.fontSize,
        line_count: box.lineCount,
        left: box.left,
        right: box.right,
        top: box.top,
        bottom: box.bottom,
      }).toEqual(testCase.expected);
      expect(isInsideSafeZone(box)).toBe(true);
    }
  });

  it("uses a Songti-family fallback without browser font measurement", () => {
    expect(DEFAULT_FONT_FAMILY).toContain("Songti SC");
    expect(DEFAULT_FONT_FAMILY).toContain("STSong");
  });

  it("rejects an emphasis box that crosses the safe rectangle", () => {
    const term = "透明桌垫透明桌垫透明桌垫透明桌垫透明";
    const box = captionBoxForCue(
      {text: term, startMs: 0, endMs: 1000, timestampMs: 0, confidence: 1},
      {
        fontMin: 52,
        fontMax: 52,
        emphasisRules: [{term, color: "#D9A441", effect: "scale"}],
      },
    );
    expect(box.emphasisBoxes).toHaveLength(1);
    expect(isInsideSafeZone(box.emphasisBoxes[0])).toBe(false);
  });
});
