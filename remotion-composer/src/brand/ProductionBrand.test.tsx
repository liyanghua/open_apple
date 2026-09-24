import {describe, expect, test, vi} from "vitest";
import {createElement} from "react";
import {buildBrandShotSchedule, collectBrandDomEvidence, incomingOpacity, getBrandFrameState, loadProductionFonts, ProductionBrandOverlay} from "./ProductionBrand";
import type {ProductionBrandProps} from "./types";

const {renderToStaticMarkup}: {renderToStaticMarkup: (element: React.ReactElement) => string} = require("react-dom/server");

// Img's media-loading hook needs a running Remotion composition; keep DOM styles real.
vi.mock("remotion", async importOriginal => ({
  ...await importOriginal<typeof import("remotion")>(),
  Img: (props: React.ImgHTMLAttributes<HTMLImageElement>) => createElement("img", props),
}));

const profile: ProductionBrandProps["profile"] = {
  version: "1.0", profile_id: "test", font: {family: "Microsoft YaHei", fallbacks: [], files: []},
  production: {
    font_mode: "legacy_appearance", legacy_font_stack: 'Arial, "Microsoft YaHei", STHeiti, sans-serif',
    logo: {right: 72, top: 96, width: 120, clear_space: 16},
    title: {left: 72, top: 220, font_size: 64, font_weight: 700, line_height: 1.15, characters: [2, 4]},
    underline: {height: 8, gap: 22, color: "#4874CB", width: "title"},
    caption: {left: 72, right: 72, top: 1470, font_size: 38, font_weight: 400, line_height: 1.25},
    transition: {frames: 5, rule: "incoming_only"}, slogan: "PLAYBOY，让日常更有质感。", min_tail_seconds: 0.4,
    recipe: {id: "display", default_raw_seconds: 4, raw_action_seconds: [3, 5], body_cut_seconds: [1.8, 2.6]},
  },
};
const props: ProductionBrandProps = {
  profile, width: 1080, height: 1920, fps: 30, durationInFrames: 240, logoSrc: "logo.png",
  footage: {a: "real-a.mp4", b: "real-b.mp4"},
  scenes: [
    {id: "a", footageKey: "a", fromFrame: 0, durationInFrames: 120, sourceInSeconds: 1, sourceDurationSeconds: 10, playbackRate: 1, cropScale: 1, role: "body"},
    {id: "b", footageKey: "b", fromFrame: 120, durationInFrames: 120, sourceInSeconds: 0, sourceDurationSeconds: 10, playbackRate: 1, cropScale: 1, role: "body"},
  ],
  titles: [{fromFrame: 0, text: "柔软"}, {fromFrame: 120, text: "吸水"}],
  captions: [{startMs: 3000, endMs: 5000, text: "真实口播字幕"}],
  words: [], timingSource: "measured_word_timestamps",
  audio: {narrationSrc: "voice.wav", bgmSrc: "approved-suno.mp3", bgmVolume: 0.12},
};

describe("production brand", () => {
  test("only incoming footage fades for exactly five frames and outgoing has source handles", () => {
    expect([0, 1, 2, 3, 4, 5].map(f => incomingOpacity(f, false, 5))).toEqual([0, .25, .5, .75, 1, 1]);
    expect(incomingOpacity(0, true, 5)).toBe(1);
    const schedule = buildBrandShotSchedule(props);
    expect(schedule.map(s => s.renderDurationInFrames)).toEqual([125, 120]);
    expect(schedule.map(s => s.src)).toEqual(["real-a.mp4", "real-b.mp4"]);
  });
  test("respects the supplied fps, footage offsets and long story duration", () => {
    const schedule = buildBrandShotSchedule({...props, fps: 60, durationInFrames: 1920});
    expect(schedule[0].sourceStartFrame).toBe(60);
    expect(schedule[1].fromFrame).toBe(120);
  });
  test("brand and measured caption are independently selected at a cut", () => {
    expect(getBrandFrameState(props, 119)).toEqual({title: "柔软", caption: "真实口播字幕"});
    expect(getBrandFrameState(props, 120)).toEqual({title: "吸水", caption: "真实口播字幕"});
    expect(getBrandFrameState(props, 150).caption).toBe("");
  });
  test("overlay contains persistent brand geometry with intrinsic full-title underline", () => {
    const markup = renderToStaticMarkup(createElement(ProductionBrandOverlay, {props, frame: 120, fontFamily: profile.production.legacy_font_stack}));
    expect(markup).toContain("right:72px;top:96px;width:120px");
    expect(markup).toContain("font-size:64px");
    expect(markup).toContain("width:max-content");
    expect(markup).toContain("margin-top:22px;width:100%;height:8px;background-color:#4874CB");
    expect(markup).toContain("top:1470px");
    expect(markup).toContain("font-size:38px");
    expect(markup).toContain("吸水");
    expect(markup).toContain("真实口播字幕");
    expect(markup).not.toContain("opacity:0");
    expect(markup).not.toContain("font-synthesis:none");
  });
  test("strict loading cannot proceed without regular and bold pinned assets", async () => {
    await expect(loadProductionFonts({...profile, production: {...profile.production, font_mode: "strict"}})).rejects.toThrow("400 and 700");
  });
  test("legacy appearance explicitly reports unverified font identity", async () => {
    expect(await loadProductionFonts(profile)).toMatchObject({status: "not_run", family: profile.production.legacy_font_stack});
  });
  test("font hash mismatch stops before browser font registration", async () => {
    const strict = {...profile, production: {...profile.production, font_mode: "strict" as const}, font: {...profile.font, files: [400, 700].map(weight => ({path: "font.ttf", src: "font.ttf", sha256: "0".repeat(64), weight: weight as 400 | 700}))}};
    vi.stubGlobal("fetch", vi.fn(async () => ({ok: true, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer})));
    try { await expect(loadProductionFonts(strict)).rejects.toThrow("hash mismatch"); }
    finally { vi.unstubAllGlobals(); }
  });
  test("verified public bytes load both exact weights before reporting ready", async () => {
    const bytes = new Uint8Array([1, 2, 3]).buffer;
    const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(b => b.toString(16).padStart(2, "0")).join("");
    const strict = {...profile, production: {...profile.production, font_mode: "strict" as const}, font: {...profile.font, files: [400, 700].map(weight => ({path: "font.ttf", src: "font.ttf", sha256: hash, weight: weight as 400 | 700}))}};
    const weights: string[] = [], add = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => ({ok: true, arrayBuffer: async () => bytes})));
    vi.stubGlobal("FontFace", class {
      constructor(_family: string, _bytes: ArrayBuffer, options: {weight: string}) {weights.push(options.weight);}
      async load() {return this;}
    });
    vi.stubGlobal("document", {fonts: {add, ready: Promise.resolve()}});
    try {
      expect(await loadProductionFonts(strict)).toMatchObject({status: "pass", hashes: [hash, hash]});
      expect(weights).toEqual(["400", "700"]);
      expect(add).toHaveBeenCalledTimes(2);
    } finally {vi.unstubAllGlobals();}
  });
  test("unmounted DOM cannot create positive layout evidence", () => {
    expect(collectBrandDomEvidence({querySelector: () => null} as unknown as ParentNode).status).toBe("not_run");
  });
  test("a mounted composition with missing brand elements cannot pass DOM layout", () => {
    const container = {
      dataset: {brandWidth: "1080", brandHeight: "1920", brandClearSpace: "16", brandFontStatus: "pass", brandFrame: "0", brandFontHashes: "[]"},
      getBoundingClientRect: () => ({x: 0, y: 0, width: 1080, height: 1920}),
      querySelectorAll: () => [],
    };
    const result = collectBrandDomEvidence({querySelector: () => container} as unknown as ParentNode);
    expect(result.status).toBe("fail");
  });
  test("actual browser bounds flag overlaps and wait for strict font loading", () => {
    const nodes = [
      {role: "logo", x: 888, y: 96, width: 120, height: 60},
      {role: "title", x: 72, y: 220, width: 128, height: 73.6},
      {role: "underline", x: 72, y: 315.6, width: 128, height: 8},
      {role: "caption", x: 300, y: 1470, width: 480, height: 47.5},
    ];
    const container = {
      dataset: {brandWidth: "1080", brandHeight: "1920", brandClearSpace: "16", brandFontStatus: "pass", brandFrame: "120", brandFontHashes: "[]"},
      getBoundingClientRect: () => ({x: 0, y: 0, width: 1080, height: 1920}),
      querySelectorAll: () => nodes.map(node => ({dataset: {brandRole: node.role}, textContent: "实际文字", getBoundingClientRect: () => node})),
    };
    const root = {querySelector: () => container} as unknown as ParentNode;
    vi.stubGlobal("getComputedStyle", () => ({fontFamily: "ProductionBrand-test", fontWeight: "700"}));
    try {
      expect(collectBrandDomEvidence(root).status).toBe("pass");
      nodes[3].x = 72; nodes[3].y = 220;
      expect(collectBrandDomEvidence(root).status).toBe("fail");
      nodes[3].y = 1470;
      container.dataset.brandFontStatus = "pending";
      expect(collectBrandDomEvidence(root).status).toBe("not_run");
    } finally {vi.unstubAllGlobals();}
  });
});
