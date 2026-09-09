import React from "react";
import {AbsoluteFill, Audio, OffthreadVideo, Sequence, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {resolveAsset} from "../lib/resolveAsset";
import {SafeCaptionTrack} from "../components/SafeCaptionTrack";
import type {Caption} from "@remotion/captions";
import type {EditorialClip, EditorialTimelineProps, EditorialTrack} from "./types";

const TRACK_ORDER: Record<EditorialTrack["kind"], number> = {video: 0, narration: 1, music: 2, text: 3, subtitle: 4};

export function buildEditorialSchedule(props: EditorialTimelineProps): EditorialTrack[] {
  return [...props.tracks]
    .sort((a, b) => (TRACK_ORDER[a.kind] - TRACK_ORDER[b.kind]) || a.id.localeCompare(b.id))
    .map((track) => ({
      ...track,
      clips: [...track.clips].sort((a, b) => (a.startSeconds - b.startSeconds) || a.id.localeCompare(b.id)).map((clip) => {
        const duration = track.kind === "video"
          ? ((clip.sourceOutSeconds ?? 0) - (clip.sourceInSeconds ?? 0)) / (clip.playbackRate ?? clip.speed ?? 1)
          : ((clip.endSeconds ?? clip.startSeconds) - clip.startSeconds);
        return {...clip, startFrame: Math.round(clip.startSeconds * props.fps), durationInFrames: Math.max(1, Math.round(duration * props.fps))};
      }),
    }));
}

export function textPlacementStyle(position: EditorialClip["position"], styleToken?: string): React.CSSProperties {
  const style: React.CSSProperties = {position: "absolute", left: "50%", transform: "translateX(-50%)", zIndex: 30};
  if (position === "top_center") Object.assign(style, {top: 96});
  else if (position === "bottom_center") Object.assign(style, {bottom: 120, whiteSpace: "nowrap"});
  else Object.assign(style, {top: "50%", transform: "translate(-50%, -50%)"});
  if (styleToken === "taobao_selling_point_v1") Object.assign(style, {left: 72, transform: "none", writingMode: "vertical-rl", letterSpacing: 8, fontSize: 72, fontWeight: 800});
  if (styleToken === "taobao_subtitle_v1") Object.assign(style, {whiteSpace: "nowrap", fontSize: 44});
  return style;
}

export function audioGainAtFrame(clip: EditorialClip, frame: number, fps: number, narrationActive = frame >= 0): number {
  let gain = clip.gainDb ?? 0;
  const local = frame - Math.round(clip.startSeconds * fps);
  const duration = Math.max(1, Math.round(((clip.endSeconds ?? clip.startSeconds) - clip.startSeconds) * fps));
  const fadeIn = Math.round((clip.fadeInSeconds ?? 0) * fps);
  const fadeOut = Math.round((clip.fadeOutSeconds ?? 0) * fps);
  if (fadeIn > 0 && local < fadeIn) gain += 20 * (local / fadeIn - 1);
  if (fadeOut > 0 && local > duration - fadeOut) gain += 20 * ((duration - local) / fadeOut - 1);
  if (clip.ducking?.enabled && narrationActive) gain += clip.ducking.reductionDb;
  return gain;
}

const dbToLinear = (db: number) => Math.pow(10, db / 20);

const TextClip: React.FC<{clip: EditorialClip}> = ({clip}) => {
  if (clip.enabled === false || !clip.text) return null;
  return <div style={{...textPlacementStyle(clip.position, clip.styleToken), color: "#fff", textShadow: "0 2px 12px #000", fontFamily: "sans-serif"}}>{clip.text}</div>;
};

const VideoClip: React.FC<{clip: EditorialClip}> = ({clip}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const duration = clip.durationInFrames ?? 1;
  const transitionFrames = clip.transition === "fade" || clip.transition === "crossfade" ? 8 : 0;
  const fadeIn = Math.max(transitionFrames, Math.round((clip.fadeInSeconds ?? 0) * fps));
  const fadeOut = Math.max(transitionFrames, Math.round((clip.fadeOutSeconds ?? 0) * fps));
  const fadeInOpacity = fadeIn > 0 ? interpolate(frame, [0, fadeIn], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}) : 1;
  const fadeOutOpacity = fadeOut > 0 ? interpolate(frame, [Math.max(0, duration - fadeOut), duration], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}) : 1;
  const opacity = Math.min(fadeInOpacity, fadeOutOpacity);
  const transform = clip.transform ?? {};
  return <OffthreadVideo src={resolveAsset(clip.source ?? "")} startFrom={Math.round((clip.sourceInSeconds ?? 0) * fps)} playbackRate={clip.playbackRate ?? clip.speed ?? 1} muted style={{width: "100%", height: "100%", objectFit: "cover", opacity, zIndex: clip.zIndex ?? 0, transform: `translate(${transform.x ?? 0}px, ${transform.y ?? 0}px) scale(${transform.scale ?? 1}) rotate(${transform.rotationDegrees ?? 0}deg)`}} />;
};

const AudioClip: React.FC<{clip: EditorialClip; narrationWindows?: Array<[number, number]>}> = ({clip, narrationWindows = []}) => {
  const {fps} = useVideoConfig();
  const clipStart = clip.startFrame ?? Math.round(clip.startSeconds * fps);
  return <Audio src={resolveAsset(clip.source ?? "")} volume={(frame) => {
    const globalFrame = clipStart + frame;
    const narrationActive = narrationWindows.some(([start, end]) => start <= globalFrame && globalFrame < end);
    return dbToLinear(audioGainAtFrame(clip, globalFrame, fps, narrationActive));
  }} />;
};

export const EditorialTimeline: React.FC<EditorialTimelineProps> = (props) => {
  const schedule = buildEditorialSchedule(props);
  const narrationClips = schedule.filter((track) => track.kind === "narration").flatMap((track) => track.clips);
  const narrationWindows: Array<[number, number]> = narrationClips.map((clip) => [clip.startFrame ?? 0, (clip.startFrame ?? 0) + (clip.durationInFrames ?? 1)]);
  const subtitleClips = schedule.filter((track) => track.kind === "subtitle").flatMap((track) => track.clips).filter((clip) => clip.enabled !== false);
  const textClips = schedule.filter((track) => track.kind === "text").flatMap((track) => track.clips);
  const videoClips = schedule.filter((track) => track.kind === "video").flatMap((track) => track.clips);
  const musicClips = schedule.filter((track) => track.kind === "music").flatMap((track) => track.clips);
  const subtitles: Caption[] = subtitleClips.map((clip) => ({text: clip.text ?? "", startMs: clip.startSeconds * 1000, endMs: (clip.endSeconds ?? clip.startSeconds) * 1000, timestampMs: null, confidence: null}));
  return <AbsoluteFill style={{background: "#111"}}>
    {videoClips.map((clip) => <Sequence key={clip.id} from={clip.startFrame ?? 0} durationInFrames={clip.durationInFrames ?? 1}><VideoClip clip={clip} /></Sequence>)}
    {textClips.map((clip) => <Sequence key={clip.id} from={clip.startFrame ?? 0} durationInFrames={clip.durationInFrames ?? 1}><TextClip clip={clip} /></Sequence>)}
    {subtitles.length > 0 ? <SafeCaptionTrack captions={subtitles} safeZoneProfile="taobao_detail_3_4" fontMin={36} fontMax={52} singleLine /> : null}
    {narrationClips.map((clip) => <Sequence key={clip.id} from={clip.startFrame ?? 0} durationInFrames={clip.durationInFrames ?? 1}><AudioClip clip={clip} /></Sequence>)}
    {musicClips.map((clip) => <Sequence key={clip.id} from={clip.startFrame ?? 0} durationInFrames={clip.durationInFrames ?? 1}><AudioClip clip={clip} narrationWindows={narrationWindows} /></Sequence>)}
  </AbsoluteFill>;
};
