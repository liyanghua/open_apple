import type {Caption} from "@remotion/captions";
import type {CSSProperties, ReactNode} from "react";
import {AbsoluteFill, Sequence, useVideoConfig} from "remotion";

export type SafeZoneProfile =
  | "douyin_9_16"
  | "wechat_9_16"
  | "xiaohongshu_9_16";

export type EmphasisRule = {
  term: string;
  color: string;
  effect: "scale" | "underline" | "color";
};

export type SafeCaptionProps = {
  captions: Caption[];
  safeZoneProfile?: SafeZoneProfile;
  fontMin?: number;
  fontMax?: number;
  maxWidth?: number;
  stripTrailingPunctuation?: boolean;
  emphasisRules?: EmphasisRule[];
};

type LayoutOptions = Omit<SafeCaptionProps, "captions">;

export type CaptionBox = {
  text: string;
  left: number;
  right: number;
  top: number;
  bottom: number;
  width: number;
  height: number;
  fontSize: number;
  lineCount: number;
  lineHeight: number;
  emphasisBoxes: Array<CaptionBox & {term: string}>;
};

export const DEFAULT_FONT_FAMILY =
  '"Songti SC", STSong, "Noto Serif CJK SC", serif';

export const SAFE_ZONE_PROFILES: Record<
  SafeZoneProfile,
  {
    left: number;
    right: number;
    top: number;
    bottom: number;
    maxWidth: number;
    maxLines: number;
    lineHeight: number;
  }
> = {
  douyin_9_16: {left: 72, right: 72, top: 120, bottom: 300, maxWidth: 864, maxLines: 2, lineHeight: 1.24},
  wechat_9_16: {left: 72, right: 72, top: 120, bottom: 300, maxWidth: 864, maxLines: 2, lineHeight: 1.24},
  xiaohongshu_9_16: {left: 72, right: 72, top: 120, bottom: 300, maxWidth: 864, maxLines: 2, lineHeight: 1.24},
};

export const stripTrailingPunctuation = (text: string): string =>
  String(text).replace(/[\s，。！？；：、,.!?;:…]+$/gu, "").trimEnd();

const characterUnits = (text: string): number => {
  let units = 0;
  for (const character of Array.from(text)) {
    const code = character.codePointAt(0) ?? 0;
    if (/\s/u.test(character)) units += 0.32;
    else if (
      (code >= 0x2e80 && code <= 0x9fff) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xff00 && code <= 0xffef)
    ) units += 1;
    else if (/[A-Z0-9]/u.test(character)) units += 0.62;
    else if (/[a-z]/u.test(character)) units += 0.56;
    else units += 0.5;
  }
  return Math.max(units, 1);
};

export const fitCjkFontSize = (
  text: string,
  options: {
    fontMin?: number;
    fontMax?: number;
    maxWidth?: number;
    maxLines?: number;
    widthMultiplier?: number;
  } = {},
): number => {
  const fontMin = options.fontMin ?? 44;
  const fontMax = options.fontMax ?? 52;
  if (fontMin > fontMax) throw new Error("fontMin must be <= fontMax");
  const maxWidth = options.maxWidth ?? 864;
  const maxLines = options.maxLines ?? 2;
  const widthMultiplier = Math.max(options.widthMultiplier ?? 1, 0.01);
  const fitted = Math.floor(
    (maxWidth * maxLines) / (characterUnits(text) * widthMultiplier),
  );
  return Math.max(fontMin, Math.min(fontMax, fitted));
};

export const captionBoxForCue = (
  cue: Caption,
  options: LayoutOptions = {},
): CaptionBox => {
  const profile = SAFE_ZONE_PROFILES[options.safeZoneProfile ?? "douyin_9_16"];
  const maxWidth = Math.min(options.maxWidth ?? profile.maxWidth, profile.maxWidth);
  const text = options.stripTrailingPunctuation === false
    ? cue.text.trim()
    : stripTrailingPunctuation(cue.text.trim());
  const emphasisRules = options.emphasisRules ?? [];
  const scaleMultiplier = emphasisRules.some(
    (rule) => rule.effect === "scale" && text.includes(rule.term),
  ) ? 1.08 : 1;
  const fontSize = fitCjkFontSize(text, {
    fontMin: options.fontMin,
    fontMax: options.fontMax,
    maxWidth,
    maxLines: profile.maxLines,
    widthMultiplier: scaleMultiplier,
  });
  const textWidth = Math.round(characterUnits(text) * fontSize);
  const lineCount = Math.max(1, Math.ceil(textWidth / maxWidth));
  const width = lineCount === 1 ? Math.min(maxWidth, textWidth) : maxWidth;
  const left = Math.round((1080 - width) / 2);
  const bottom = 1920 - profile.bottom;
  const height = Math.round(fontSize * profile.lineHeight * lineCount);
  const top = bottom - height;
  const emphasisBoxes = emphasisRules
    .filter((rule) => rule.term && text.includes(rule.term))
    .map((rule) => {
      const multiplier = rule.effect === "scale" ? 1.08 : 1;
      const emphasisWidth = Math.round(characterUnits(rule.term) * fontSize * multiplier);
      const emphasisHeight = Math.round(fontSize * profile.lineHeight * multiplier);
      const emphasisLeft = Math.round((1080 - emphasisWidth) / 2);
      return {
        term: rule.term,
        text: rule.term,
        left: emphasisLeft,
        right: emphasisLeft + emphasisWidth,
        top,
        bottom: top + emphasisHeight,
        width: emphasisWidth,
        height: emphasisHeight,
        fontSize,
        lineCount: 1,
        lineHeight: profile.lineHeight,
        emphasisBoxes: [],
      };
    });
  return {
    text,
    left,
    right: left + width,
    top,
    bottom,
    width,
    height,
    fontSize,
    lineCount,
    lineHeight: profile.lineHeight,
    emphasisBoxes,
  };
};

export const isInsideSafeZone = (
  box: Pick<CaptionBox, "left" | "right" | "top" | "bottom" | "width" | "lineCount">,
  safeZoneProfile: SafeZoneProfile = "douyin_9_16",
): boolean => {
  const profile = SAFE_ZONE_PROFILES[safeZoneProfile];
  return box.left >= profile.left &&
    box.right <= 1080 - profile.right &&
    box.top >= profile.top &&
    box.bottom <= 1920 - profile.bottom &&
    box.width <= profile.maxWidth &&
    box.lineCount <= profile.maxLines;
};

const emphasisStyle = (rule: EmphasisRule): CSSProperties => {
  if (rule.effect === "underline") {
    return {borderBottom: `4px solid ${rule.color}`, paddingBottom: 2};
  }
  if (rule.effect === "scale") {
    return {color: rule.color, display: "inline-block", transform: "scale(1.08)"};
  }
  return {color: rule.color};
};

const renderEmphasis = (text: string, rules: EmphasisRule[]): ReactNode[] => {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  while (cursor < text.length) {
    const matches = rules
      .map((rule) => ({rule, index: text.indexOf(rule.term, cursor)}))
      .filter((match) => match.rule.term && match.index >= 0)
      .sort((a, b) => a.index - b.index || b.rule.term.length - a.rule.term.length);
    const match = matches[0];
    if (!match) {
      nodes.push(text.slice(cursor));
      break;
    }
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    nodes.push(
      <span key={`emphasis-${key++}`} style={emphasisStyle(match.rule)}>
        {match.rule.term}
      </span>,
    );
    cursor = match.index + match.rule.term.length;
  }
  return nodes;
};

export const SafeCaptionTrack: React.FC<SafeCaptionProps> = ({
  captions,
  safeZoneProfile = "douyin_9_16",
  fontMin = 44,
  fontMax = 52,
  maxWidth = 864,
  stripTrailingPunctuation: shouldStrip = true,
  emphasisRules = [],
}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{pointerEvents: "none"}}>
      {captions.map((caption, index) => {
        const from = Math.max(0, Math.round((caption.startMs / 1000) * fps));
        const durationInFrames = Math.max(
          1,
          Math.round(((caption.endMs - caption.startMs) / 1000) * fps),
        );
        const box = captionBoxForCue(caption, {
          safeZoneProfile,
          fontMin,
          fontMax,
          maxWidth,
          stripTrailingPunctuation: shouldStrip,
          emphasisRules,
        });
        return (
          <Sequence key={`${caption.startMs}-${index}`} from={from} durationInFrames={durationInFrames}>
            <div style={{
              position: "absolute",
              left: box.left,
              top: box.top,
              width: box.width,
              minHeight: box.height,
              color: "#FFFDF8",
              fontFamily: DEFAULT_FONT_FAMILY,
              fontSize: box.fontSize,
              fontWeight: 700,
              lineHeight: box.lineHeight,
              textAlign: "center",
              textShadow: "0 2px 5px rgba(0,0,0,0.82)",
              wordBreak: "break-all",
              overflow: "hidden",
              display: "-webkit-box",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: 2,
            }}>
              {renderEmphasis(box.text, emphasisRules)}
            </div>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
