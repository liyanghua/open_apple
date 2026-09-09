export type EditorialTrackKind = "video" | "narration" | "music" | "text" | "subtitle";
export type EditorialPosition = "top_center" | "center" | "bottom_center";

export interface EditorialClip {
  id: string;
  source?: string;
  text?: string;
  startSeconds: number;
  endSeconds?: number;
  sourceInSeconds?: number;
  sourceOutSeconds?: number;
  speed?: number;
  playbackRate?: number;
  durationInFrames?: number;
  startFrame?: number;
  position?: EditorialPosition;
  styleToken?: string;
  enabled?: boolean;
  zIndex?: number;
  transition?: "cut" | "fade" | "crossfade";
  fadeInSeconds?: number;
  fadeOutSeconds?: number;
  gainDb?: number;
  ducking?: {enabled: boolean; reductionDb: number};
  transform?: {scale?: number; x?: number; y?: number; rotationDegrees?: number};
  claimIds?: string[];
}

export interface EditorialTrack {
  id: string;
  kind: EditorialTrackKind;
  clips: EditorialClip[];
}

export interface EditorialTimelineProps {
  fps: number;
  width: number;
  height: number;
  safeZone?: string;
  durationInFrames?: number;
  tracks: EditorialTrack[];
}
