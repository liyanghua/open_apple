import {describe, expect, it} from "vitest";
import fixture from "../../../tests/fixtures/caption_layout/social_v1_cases.json";

import {
  DEFAULT_FONT_FAMILY,
  captionBoxForCue,
  fitCjkFontSize,
  isInsideSafeZone,
  resolveCaptionOverlayStyle,
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

describe("caption style spec (P1-1)", () => {
  it("resolves defaults when no style is provided", () => {
    const style = resolveCaptionOverlayStyle(undefined);
    expect(style.fontWeight).toBe(700);
    expect(style.position).toBe("bottom");
    expect(style.entranceAnimation).toBe("pop");
    expect(style.opacity).toBe(1);
    expect(style.bottomOffsetPx).toBe(120);
  });

  it("mirrors the Python to_overlay_spec mapping", () => {
    const style = resolveCaptionOverlayStyle({
      fontFamily: "Noto Sans CJK SC",
      fontSize: 48,
      emphasizeFontSize: 60,
      fontWeight: 600,
      fillColor: "#FFFFFF",
      strokeColor: "#000000",
      strokeWidthPx: 3,
      backgroundColor: "rgba(0,0,0,0.6)",
      opacity: 0.95,
      position: "bottom",
      entranceAnimation: "fade",
      bottomOffsetPx: 120,
    });
    expect(style.fontFamily).toBe("Noto Sans CJK SC");
    expect(style.fontSize).toBe(48);
    expect(style.emphasizeFontSize).toBe(60);
    expect(style.fontWeight).toBe(600);
    expect(style.strokeColor).toBe("#000000");
    expect(style.strokeWidthPx).toBe(3);
    expect(style.position).toBe("bottom");
    expect(style.entranceAnimation).toBe("fade");
    expect(style.opacity).toBe(0.95);
    expect(style.bottomOffsetPx).toBe(120);
  });

  it("carries a declared bottom offset (评审 #9b single source)", () => {
    const style = resolveCaptionOverlayStyle({bottomOffsetPx: 90});
    expect(style.bottomOffsetPx).toBe(90);
  });
});

import {buildPages} from "./CaptionOverlay";

describe("caption paging (每屏一条卖点修复)", () => {
  it("wordsPerPage=1 keeps one phrase per page", () => {
    const words = [
      {word: "透明保护", startMs: 0, endMs: 2300},
      {word: "贴合桌角", startMs: 2300, endMs: 4700},
      {word: "防刮测试", startMs: 4700, endMs: 7000},
    ];
    const pages = buildPages(words, 1);
    expect(pages).toHaveLength(3);
    for (const page of pages) {
      expect(page.words).toHaveLength(1);
    }
    expect(pages[0].words[0].word).toBe("透明保护");
    expect(pages[1].startMs).toBe(2300);
  });

  it("default paging groups six words per page", () => {
    const words = Array.from({length: 7}, (_, i) => ({word: `w${i}`, startMs: i * 1000, endMs: (i + 1) * 1000}));
    const pages = buildPages(words, 6);
    expect(pages).toHaveLength(2);
    expect(pages[0].words).toHaveLength(6);
    expect(pages[1].words).toHaveLength(1);
  });
});
