export type ProductionFontFile = {path: string; src: string; sha256: string; weight: 400 | 700};
export type ProductionRecipe = {id: string; default_raw_seconds?: number; raw_action_seconds: [number, number]; body_cut_seconds: [number, number]};
export type ProductionBrandProfile = {
  version: string;
  profile_id: string;
  font: {family: string; fallbacks?: string[]; files?: ProductionFontFile[]};
  production: {
    font_mode: "strict" | "legacy_appearance";
    legacy_font_stack: string;
    logo: {right: number; top: number; width: number; clear_space: number};
    title: {left: number; top: number; font_size: number; font_weight: 700; line_height: number; characters: [number, number]};
    underline: {height: number; gap: number; color: string; width: "title"};
    caption: {left: number; right: number; top: number; font_size: number; font_weight: 400; line_height: number};
    transition: {frames: 5; rule: "incoming_only"};
    slogan: string;
    min_tail_seconds: number;
    recipe: ProductionRecipe;
  };
};
export type ProductionShot = {
  id: string; footageKey: string; fromFrame: number; durationInFrames: number;
  sourceInSeconds: number; sourceDurationSeconds: number; playbackRate: number;
  cropScale: number; role: "hook" | "body" | "tail";
};
export type ProductionTimedText = {text: string; startMs: number; endMs: number};
export type ProductionBrandProps = {
  profile: ProductionBrandProfile;
  fps: number; width: number; height: number; durationInFrames: number;
  logoSrc: string; footage: Record<string, string>; scenes: ProductionShot[];
  titles: {fromFrame: number; text: string}[];
  captions: ProductionTimedText[]; words: ProductionTimedText[];
  timingSource: "measured_word_timestamps";
  recipe?: ProductionRecipe;
  audio?: {narrationSrc: string; bgmSrc?: string; bgmVolume?: number};
};
