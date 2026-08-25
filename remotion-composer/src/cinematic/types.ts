export type CinematicTone = "cold" | "steel" | "void" | "neutral";

export interface CinematicBaseScene {
  id: string;
  startSeconds: number;
  durationSeconds: number;
}

export interface CinematicVideoScene extends CinematicBaseScene {
  kind: "video";
  src: string;
  tone?: CinematicTone;
  trimBeforeSeconds?: number;
  trimAfterSeconds?: number;
  playbackRate?: number;
  filter?: string;
  fadeInFrames?: number;
  fadeOutFrames?: number;
}

export interface CinematicTitleScene extends CinematicBaseScene {
  kind: "title";
  text: string;
  accent?: string;
  intensity?: number;
  backgroundSrc?: string;
  backgroundTrimBeforeSeconds?: number;
  backgroundTrimAfterSeconds?: number;
  variant?: "plate" | "overlay";
}

export type CinematicScene = CinematicVideoScene | CinematicTitleScene;

export interface CinematicSoundtrack {
  src: string;
  volume?: number;
  trimBeforeSeconds?: number;
  trimAfterSeconds?: number;
  fadeInSeconds?: number;
  fadeOutSeconds?: number;
}

export interface CinematicWordCaption {
  word: string;
  startMs: number;
  endMs: number;
}

export interface CinematicCaptionConfig {
  words: CinematicWordCaption[];
  wordsPerPage?: number;
  fontSize?: number;
  color?: string;
  highlightColor?: string;
  backgroundColor?: string;
  captionStyle?: import("../components/SafeCaptionTrack").CaptionStyleSpec;
}

export type TransitionRecipeType = "cut" | "impact" | "fade" | "flash";

export interface TransitionRecipeSpec {
  recipe_id: string;
  type: TransitionRecipeType;
  scale?: number;
  flash?: number;
  flash_seconds?: number;
  duration_frames?: number;
  fallback_used?: boolean;
}

export type CaptionEntrance = "pop" | "fade" | "none" | "slide_up";
export type CaptionEmphasis = "scale" | "underline" | "none";

export interface CaptionRecipeSpec {
  recipe_id: string;
  entrance: CaptionEntrance;
  emphasis: CaptionEmphasis;
  energy: "high" | "low";
  fallback_used?: boolean;
}

export interface CinematicRendererProps {
  [key: string]: unknown;
  scenes: CinematicScene[];
  titleFontSize?: number;
  titleWidth?: number;
  signalLineCount?: number;
  soundtrack?: CinematicSoundtrack;
  music?: CinematicSoundtrack;
  captions?: CinematicCaptionConfig;
  /** scene_id -> transition recipe（lib.recipe_router 派生，P2） */
  transitionRecipes?: Record<string, TransitionRecipeSpec>;
  /** scene_id -> caption recipe（lib.recipe_router 派生，P2） */
  captionRecipes?: Record<string, CaptionRecipeSpec>;
}
