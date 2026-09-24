import React, {useEffect, useState} from "react";
import {AbsoluteFill, Audio, cancelRender, Composition, continueRender, delayRender, Img, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from "remotion";
import type {ProductionBrandProfile, ProductionBrandProps} from "./types";

const asset = (src: string) => /^(https?:|data:|blob:)/.test(src) ? src : staticFile(src);

export const incomingOpacity = (localFrame: number, first: boolean, transitionFrames = 5) =>
  first ? 1 : Math.max(0, Math.min(1, localFrame / Math.max(1, transitionFrames - 1)));

/** Input intervals are contiguous. Extend only the outgoing source under the next fade. */
export const buildBrandShotSchedule = (props: ProductionBrandProps) => props.scenes.map((shot, i) => ({
  ...shot,
  src: props.footage[shot.footageKey],
  sourceStartFrame: Math.round(shot.sourceInSeconds * props.fps),
  renderDurationInFrames: shot.durationInFrames + (i < props.scenes.length - 1 ? props.profile.production.transition.frames : 0),
  first: i === 0,
}));

export const getBrandFrameState = (props: ProductionBrandProps, frame: number) => ({
  title: [...props.titles].reverse().find(t => frame >= t.fromFrame)?.text ?? "",
  caption: props.captions.find(c => frame * 1000 / props.fps >= c.startMs && frame * 1000 / props.fps < c.endMs)?.text ?? "",
});

type LoadedFonts = {status: "pass" | "not_run"; family: string; hashes: string[]};

/** Verify the actual public bytes before FontFace registration; errors block rendering. */
export async function loadProductionFonts(profile: ProductionBrandProfile): Promise<LoadedFonts> {
  if (profile.production.font_mode === "legacy_appearance") {
    return {status: "not_run", family: profile.production.legacy_font_stack, hashes: []};
  }
  const files = profile.font.files ?? [];
  if (files.length !== 2 || [...files.map(f => f.weight)].sort().join(",") !== "400,700") {
    throw new Error("Strict production font requires pinned weights 400 and 700");
  }
  const family = `ProductionBrand-${profile.profile_id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
  const buffers = await Promise.all(files.map(async file => {
    const response = await fetch(asset(file.src));
    if (!response.ok) throw new Error(`Font fetch failed: ${file.src}`);
    const bytes = await response.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const hash = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
    if (hash !== file.sha256) throw new Error(`Font hash mismatch: ${file.src}`);
    return {file, bytes};
  }));
  const faces = await Promise.all(buffers.map(({file, bytes}) => new FontFace(family, bytes, {weight: String(file.weight), style: "normal"}).load()));
  faces.forEach(face => document.fonts.add(face));
  await document.fonts.ready;
  return {status: "pass", family, hashes: files.map(f => f.sha256)};
}

const Footage: React.FC<{shot: ReturnType<typeof buildBrandShotSchedule>[number]; transitionFrames: number}> = ({shot, transitionFrames}) => {
  const localFrame = useCurrentFrame();
  if (!shot.src) throw new Error(`Missing footage for ${shot.id}`);
  return <AbsoluteFill style={{opacity: incomingOpacity(localFrame, shot.first, transitionFrames), overflow: "hidden"}}>
    <OffthreadVideo muted src={asset(shot.src)} startFrom={shot.sourceStartFrame} playbackRate={shot.playbackRate}
      style={{width: "100%", height: "100%", objectFit: "cover", transform: `scale(${shot.cropScale})`}} />
  </AbsoluteFill>;
};

/** Separate from every shot Sequence, so cuts never fade brand or caption layers. */
export const ProductionBrandOverlay: React.FC<{props: ProductionBrandProps; frame: number; fontFamily: string}> = ({props, frame, fontFamily}) => {
  const {logo, title, caption, underline} = props.profile.production;
  const current = getBrandFrameState(props, frame);
  const fontSynthesis = props.profile.production.font_mode === "strict" ? "none" : undefined;
  return <AbsoluteFill data-brand-overlay="persistent" style={{pointerEvents: "none", color: "#111111"}}>
    <AbsoluteFill style={{background: "linear-gradient(to bottom, rgba(255,255,255,.32), transparent 28%, transparent 66%, rgba(255,255,255,.45) 86%, transparent)"}} />
    <Img data-brand-role="logo" src={asset(props.logoSrc)} style={{position: "absolute", right: logo.right, top: logo.top, width: logo.width, height: "auto"}} />
    <div style={{position: "absolute", left: title.left, top: title.top, width: "max-content", fontFamily, fontSize: title.font_size, fontWeight: title.font_weight, fontSynthesis, lineHeight: title.line_height, whiteSpace: "nowrap"}}>
      <div data-brand-role="title">{current.title}</div>
      <div data-brand-role="underline" style={{marginTop: underline.gap, width: "100%", height: underline.height, backgroundColor: underline.color}} />
    </div>
    <div style={{position: "absolute", left: caption.left, right: caption.right, top: caption.top, minHeight: 52, fontFamily, fontSize: caption.font_size, fontWeight: caption.font_weight, fontSynthesis, lineHeight: caption.line_height, textAlign: "center", whiteSpace: "nowrap"}}>
      <span data-brand-role="caption" style={{display: "inline-block"}}>{current.caption}</span>
    </div>
  </AbsoluteFill>;
};

export const ProductionBrandFilm: React.FC<ProductionBrandProps> = props => {
  const frame = useCurrentFrame();
  const [handle] = useState(() => delayRender("Load hash-pinned production brand fonts"));
  const [fonts, setFonts] = useState<LoadedFonts | null>(null);
  const profileKey = JSON.stringify(props.profile);
  useEffect(() => {
    const loadingHandle = delayRender("Verify production font bytes and load both weights");
    continueRender(handle);
    let active = true;
    loadProductionFonts(props.profile).then(loaded => {
      if (active) {setFonts(loaded); continueRender(loadingHandle);}
    }).catch(error => {if (active) cancelRender(error);});
    return () => {active = false; continueRender(loadingHandle);};
  }, [handle, profileKey]);
  const family = fonts?.family ?? (props.profile.production.font_mode === "legacy_appearance" ? props.profile.production.legacy_font_stack : "ProductionBrand-pending");
  return <AbsoluteFill data-production-brand={props.profile.profile_id} data-brand-frame={frame}
    data-brand-font-status={fonts?.status ?? "pending"} data-brand-font-hashes={JSON.stringify(fonts?.hashes ?? [])}
    data-brand-width={props.width} data-brand-height={props.height}
    data-brand-clear-space={props.profile.production.logo.clear_space} style={{backgroundColor: "#d4dce2"}}>
    {buildBrandShotSchedule(props).map(shot => <Sequence key={shot.id} from={shot.fromFrame} durationInFrames={shot.renderDurationInFrames} premountFor={props.fps}>
      <Footage shot={shot} transitionFrames={props.profile.production.transition.frames} />
    </Sequence>)}
    <ProductionBrandOverlay props={props} frame={frame} fontFamily={family} />
    {props.audio && <Audio src={asset(props.audio.narrationSrc)} />}
    {props.audio?.bgmSrc && <Audio src={asset(props.audio.bgmSrc)} volume={props.audio.bgmVolume ?? 0.12} loop />}
  </AbsoluteFill>;
};

/** Include this in an atelier registerRoot entry, passing real props from a JSON artifact. */
export const ProductionBrandComposition: React.FC<{defaultProps: ProductionBrandProps; id?: string}> = ({defaultProps, id = "ProductionBrand"}) =>
  <Composition id={id} component={ProductionBrandFilm} defaultProps={defaultProps} width={defaultProps.width} height={defaultProps.height}
    fps={defaultProps.fps} durationInFrames={defaultProps.durationInFrames}
    calculateMetadata={({props}) => ({width: props.width, height: props.height, fps: props.fps, durationInFrames: props.durationInFrames})} />;

/** Call from the real browser at title/caption changes and cuts; persist results in QA. */
export function collectBrandDomEvidence(root: ParentNode = document) {
  const container = root.querySelector<HTMLElement>("[data-production-brand]");
  if (!container) return {check_id: "brand_dom_layout", status: "not_run", evidence: {reason: "brand composition not mounted"}};
  if (container.dataset.brandFontStatus === "pending") return {check_id: "brand_dom_layout", status: "not_run", evidence: {reason: "font loading still pending"}};
  const bounds = container.getBoundingClientRect();
  const width = Number(container.dataset.brandWidth), height = Number(container.dataset.brandHeight);
  if (!bounds.width || !bounds.height) return {check_id: "brand_dom_layout", status: "error", evidence: {reason: "composition has zero bounds"}};
  const boxes = [...container.querySelectorAll<HTMLElement>("[data-brand-role]")].map(el => {
    const rect = el.getBoundingClientRect();
    const css = getComputedStyle(el);
    return {role: el.dataset.brandRole!, text: el.textContent ?? "", x: (rect.x - bounds.x) * width / bounds.width,
      y: (rect.y - bounds.y) * height / bounds.height, width: rect.width * width / bounds.width,
      height: rect.height * height / bounds.height, fontFamily: css.fontFamily, fontWeight: css.fontWeight};
  });
  const issues: string[] = [];
  for (const role of ["logo", "title", "underline", "caption"]) {
    if (boxes.filter(box => box.role === role).length !== 1) issues.push(`${role}: expected exactly one mounted element`);
  }
  const margin = Number(container.dataset.brandClearSpace);
  const occupied = boxes.filter(b => b.width > 0).map(b => b.role === "logo" ? {...b, x: b.x - margin, y: b.y - margin, width: b.width + 2 * margin, height: b.height + 2 * margin} : b);
  occupied.forEach((a, i) => {
    if (a.x < 0 || a.y < 0 || a.x + a.width > width || a.y + a.height > height) issues.push(`${a.role}: out of frame`);
    occupied.slice(i + 1).forEach(b => {
      if (a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height) issues.push(`${a.role}/${b.role}: overlap`);
    });
  });
  const title = boxes.find(b => b.role === "title"), line = boxes.find(b => b.role === "underline");
  if (title && line && Math.abs(title.width - line.width) > .5) issues.push("underline width differs from title");
  return {check_id: "brand_dom_layout", status: issues.length ? "fail" : "pass", evidence: {
    frame: Number(container.dataset.brandFrame), width, height, boxes, issues,
    font_loading_status: container.dataset.brandFontStatus, font_sha256: JSON.parse(container.dataset.brandFontHashes ?? "[]"),
    scope: "actual browser bounds; scene-background logo contrast requires visual review",
  }};
}
