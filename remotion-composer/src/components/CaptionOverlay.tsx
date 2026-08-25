import type {CSSProperties} from "react";
import {
  AbsoluteFill,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont as loadLongCang } from "@remotion/google-fonts/LongCang";
import { loadFont as loadMaShanZheng } from "@remotion/google-fonts/MaShanZheng";
import {
  SAFE_ZONE_PROFILES,
  fitCjkFontSize,
  stripTrailingPunctuation as stripCuePunctuation,
  resolveCaptionOverlayStyle,
  type CaptionEntrance,
  type CaptionPosition,
  type CaptionStyleSpec,
  type EmphasisRule,
  type SafeZoneProfile,
} from "./SafeCaptionTrack";
import type { CaptionRecipeSpec } from "../cinematic/types";

// 参考片书法花字字体（行书 + 楷书），供 vertical/brush caption 使用。
const longCangFont = loadLongCang("normal", {}).fontFamily;
const maShanZhengFont = loadMaShanZheng("normal", {}).fontFamily;

// Word-level caption for TikTok-style highlight display
export interface WordCaption {
  word: string;
  startMs: number;
  endMs: number;
}

export type CaptionOverlayProps = {
  words: WordCaption[];
  // How many words to show at once in a "page"
  wordsPerPage?: number;
  fontSize?: number;
  color?: string;
  highlightColor?: string;
  backgroundColor?: string;
  fontFamily?: string;
  safeZoneProfile?: SafeZoneProfile;
  fontMin?: number;
  fontMax?: number;
  maxWidth?: number;
  stripTrailingPunctuation?: boolean;
  emphasisRules?: EmphasisRule[];
  /** Style from caption_style_fingerprint (P1-1); wins over the defaults above. */
  captionStyle?: CaptionStyleSpec;
  /** scene_id -> caption recipe（lib.recipe_router 派生，P2） */
  captionRecipes?: Record<string, CaptionRecipeSpec>;
  /** 场景时间线，用于按字幕时间戳定位到场景并取 recipe */
  scenes?: { id: string; startSeconds: number; durationSeconds: number }[];
};

interface CaptionPage {
  words: WordCaption[];
  startMs: number;
  endMs: number;
}

export function buildPages(words: WordCaption[], wordsPerPage: number): CaptionPage[] {
  const pages: CaptionPage[] = [];
  for (let i = 0; i < words.length; i += wordsPerPage) {
    const pageWords = words.slice(i, i + wordsPerPage);
    if (pageWords.length === 0) continue;
    pages.push({
      words: pageWords,
      startMs: pageWords[0].startMs,
      endMs: pageWords[pageWords.length - 1].endMs,
    });
  }
  return pages;
}

const PageRenderer: React.FC<{
  page: CaptionPage;
  fontSize: number;
  emphasizeFontSize: number;
  color: string;
  highlightColor: string;
  backgroundColor: string;
  fontFamily: string;
  fontWeight: number;
  strokeColor: string;
  strokeWidthPx: number;
  opacity: number;
  position: CaptionPosition;
  entranceAnimation: CaptionEntrance;
  bottomOffsetPx: number;
  safeZoneProfile: SafeZoneProfile;
  fontMin: number;
  fontMax: number;
  maxWidth: number;
  stripTrailingPunctuation: boolean;
  emphasisRules: EmphasisRule[];
  recipe?: CaptionRecipeSpec;
  vertical?: boolean;
}> = ({
  page,
  fontSize,
  emphasizeFontSize,
  color,
  highlightColor,
  backgroundColor,
  fontFamily,
  fontWeight,
  strokeColor,
  strokeWidthPx,
  opacity,
  position,
  entranceAnimation,
  bottomOffsetPx,
  safeZoneProfile,
  fontMin,
  fontMax,
  maxWidth,
  stripTrailingPunctuation,
  emphasisRules,
  recipe,
  vertical,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  const currentMs = page.startMs + (frame / fps) * 1000;

  // recipe 覆盖入场 + 强调能量（P2：intent → recipe → 渲染规格）
  const effectiveEntrance = recipe?.entrance ?? entranceAnimation;
  const energyBoost = recipe?.energy === "high" ? 1.12 : 1;
  const effectiveEmphasizeFontSize = emphasizeFontSize * energyBoost;
  // 书法花字（参考片）：竖排 + 行书/楷书字体 + 白字黑描边。按字体名解析到已加载字体。
  const FONT_MAP: Record<string, string> = {
    "Long Cang": longCangFont,
    "Ma Shan Zheng": maShanZhengFont,
  };
  const effectiveFontFamily = FONT_MAP[fontFamily] ?? fontFamily;

  // Entrance: pop = spring scale+rise (default), fade = opacity only,
  // slide_up = rise only, none = instant.
  const springEntrance = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  const fadeEntrance = interpolate(frame, [0, 6], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const entrance =
    effectiveEntrance === "fade" ? fadeEntrance
    : effectiveEntrance === "none" ? 1
    : springEntrance;
  const risePx =
    effectiveEntrance === "fade" || effectiveEntrance === "none" ? 0
    : interpolate(entrance, [0, 1], [20, 0]);

  const profile = SAFE_ZONE_PROFILES[safeZoneProfile];
  const pageText = page.words.map((word) => word.word).join(" ");
  // 竖排书法花字：一列一列堆叠，宽不受限，字号给大（80+）保证可读。
  const fittedFontSize = vertical
    ? Math.max(fontSize, 80)
    : fitCjkFontSize(pageText, {
        fontMin: Math.min(fontMin, fontSize, fontMax),
        fontMax: Math.min(fontSize, fontMax),
        maxWidth: Math.min(maxWidth, profile.maxWidth),
      });
  const containerStyle: CSSProperties =
    position === "center"
      ? { justifyContent: "center", alignItems: "center", paddingBottom: 0 }
      : position === "top"
        ? { justifyContent: "flex-start", alignItems: "center", paddingTop: profile.top, paddingBottom: 0 }
        : position === "topleft"
          ? {
              justifyContent: "flex-start",
              alignItems: "flex-start",
              paddingTop: Math.round(height * 0.1),
              paddingLeft: Math.round(width * 0.1),
              paddingBottom: 0,
            }
          : { justifyContent: "flex-end", alignItems: "center", paddingBottom: bottomOffsetPx };

  return (
    <AbsoluteFill style={containerStyle}>
      <div
        style={{
          opacity: entrance * opacity,
          transform: `translateY(${risePx}px)`,
          backgroundColor,
          borderRadius: 12,
          padding: backgroundColor && backgroundColor !== "transparent" ? "14px 28px" : 0,
          maxWidth: Math.min(maxWidth, profile.maxWidth),
          textAlign: position === "topleft" ? "left" : "center",
          // 书法花字：竖排堆叠
          display: vertical ? "flex" : undefined,
          flexDirection: vertical ? "column" : undefined,
          alignItems: vertical ? (position === "topleft" ? "flex-start" : "center") : undefined,
        }}
      >
        <span
          style={{
            fontSize: fittedFontSize,
            fontWeight,
            fontFamily: effectiveFontFamily,
            lineHeight: 1.4,
            whiteSpace: "pre-wrap",
            WebkitTextStroke: strokeWidthPx > 0 ? `${strokeWidthPx}px ${strokeColor}` : undefined,
            color,
            // 竖排：让字作为 flex 子项真正纵向堆叠
            display: vertical ? "flex" : undefined,
            flexDirection: vertical ? "column" : undefined,
            alignItems: vertical ? (position === "topleft" ? "flex-start" : "center") : undefined,
          }}
        >
          {vertical
            ? pageText.replace(/\s+/g, "").split("").map((ch, i) => (
                <span
                  key={`c-${i}`}
                  style={{
                    fontSize: fittedFontSize,
                    fontWeight,
                    fontFamily: effectiveFontFamily,
                    // 尊重已批准样式：color(=fillColor)/strokeColor/strokeWidthPx。
                    // 细笔画字体若样式带粗描边可致填充被盖，故这里也叠加柔阴影保可读性。
                    color,
                    WebkitTextStroke: strokeWidthPx > 0 ? `${strokeWidthPx}px ${strokeColor}` : undefined,
                    textShadow: "0 3px 8px rgba(0,0,0,0.8)",
                    display: "block",
                    lineHeight: 1.15,
                  }}
                >
                  {ch}
                </span>
              ))
            : page.words.map((w, i) => {
                const isActive = w.startMs <= currentMs && w.endMs > currentMs;
                const isPast = w.endMs <= currentMs;
                const emphasis = emphasisRules.find((rule) => w.word.includes(rule.term));
                const displayWord = stripTrailingPunctuation && i === page.words.length - 1
                  ? stripCuePunctuation(w.word)
                  : w.word;
                // recipe.emphasis：未显式 emphasisRules 时，recipe 的强调（scale/underline）作用于当前词。
                const recipeScale = recipe?.emphasis === "scale" && isActive;
                const recipeUnderline = recipe?.emphasis === "underline" && isActive;
                return (
                  <span
                    key={`${w.startMs}-${i}`}
                    style={{
                      fontSize: isActive ? effectiveEmphasizeFontSize : undefined,
                      color: isActive ? highlightColor : isPast ? color : `${color}99`,
                      transition: "none", // CSS transitions forbidden in Remotion
                      borderBottom: emphasis?.effect === "underline" || recipeUnderline
                        ? `4px solid ${emphasis?.color ?? highlightColor}`
                        : undefined,
                      display: emphasis?.effect === "scale" || recipeScale ? "inline-block" : undefined,
                      transform: emphasis?.effect === "scale" || recipeScale ? "scale(1.08)" : undefined,
                      textShadow: isActive
                        ? `0 0 20px ${highlightColor}66, 0 2px 4px rgba(0,0,0,0.5)`
                        : "0 2px 4px rgba(0,0,0,0.5)",
                    }}
                  >
                    <span style={emphasis?.effect === "color" ? { color: emphasis.color } : undefined}>
                      {displayWord}
                    </span>{i < page.words.length - 1 ? " " : ""}
                  </span>
                );
              })}
        </span>
      </div>
    </AbsoluteFill>
  );
};

export const CaptionOverlay: React.FC<CaptionOverlayProps> = ({
  words,
  wordsPerPage = 6,
  fontSize = 42,
  color = "#F8FAFC",
  highlightColor = "#22D3EE",
  backgroundColor = "rgba(15, 23, 42, 0.75)",
  fontFamily = "Space Grotesk, Inter, system-ui, sans-serif",
  safeZoneProfile = "douyin_9_16",
  fontMin = 44,
  fontMax = 52,
  maxWidth = 864,
  stripTrailingPunctuation = true,
  emphasisRules = [],
  captionStyle,
  captionRecipes,
  scenes,
}) => {
  const { fps } = useVideoConfig();
  const pages = buildPages(words, wordsPerPage);
  const style = resolveCaptionOverlayStyle(captionStyle);
  const effectiveFontSize = captionStyle?.fontSize ?? fontSize;
  const effectiveColor = captionStyle?.fillColor ?? color;
  const effectiveHighlight = captionStyle?.fillColor ? style.fillColor : highlightColor;
  // 有 captionStyle 时以样式制品为准：transparent 就是无背景，不落入主题背景条
  const effectiveBackground = captionStyle ? style.backgroundColor : backgroundColor;
  const effectiveFontFamily = captionStyle?.fontFamily ?? fontFamily;

  // P2：按字幕时间戳定位到场景，取该场景的 caption recipe。
  const recipeForMs = (ms: number): CaptionRecipeSpec | undefined => {
    if (!captionRecipes || !scenes) return undefined;
    const seconds = ms / 1000;
    const scene = scenes.find(
      (s) => seconds >= s.startSeconds && seconds < s.startSeconds + s.durationSeconds
    );
    return scene ? captionRecipes[scene.id] : undefined;
  };

  return (
    <AbsoluteFill>
      {pages.map((page, i) => {
        const fromFrame = Math.round((page.startMs / 1000) * fps);
        const nextStart = pages[i + 1]?.startMs ?? page.endMs + 500;
        const duration = Math.max(
          1,
          Math.round(((nextStart - page.startMs) / 1000) * fps)
        );

        return (
          <Sequence key={i} from={fromFrame} durationInFrames={duration}>
            <PageRenderer
              page={page}
              fontSize={effectiveFontSize}
              emphasizeFontSize={style.emphasizeFontSize}
              color={effectiveColor}
              highlightColor={effectiveHighlight}
              backgroundColor={effectiveBackground}
              fontFamily={effectiveFontFamily}
              fontWeight={style.fontWeight}
              strokeColor={style.strokeColor}
              strokeWidthPx={style.strokeWidthPx}
              opacity={style.opacity}
              position={style.position}
              entranceAnimation={style.entranceAnimation}
              bottomOffsetPx={style.bottomOffsetPx}
              safeZoneProfile={safeZoneProfile}
              fontMin={fontMin}
              fontMax={fontMax}
              maxWidth={maxWidth}
              stripTrailingPunctuation={stripTrailingPunctuation}
              emphasisRules={emphasisRules}
              recipe={recipeForMs(page.startMs)}
              vertical={style.vertical}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
