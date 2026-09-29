import React from "react";
import {AbsoluteFill, OffthreadVideo, staticFile} from "remotion";
import type {MotionFraming, MotionRect} from "./types";

const asset = (src: string) => /^(https?:|data:|blob:)/.test(src) ? src : staticFile(src);

/** Same transform used by media CSS and source-space action-envelope preflight. */
export const mapMotionRegions = (framing: MotionFraming) => {
  const {source, viewport, position} = framing;
  const scale = (framing.fit === "contain" ? Math.min : Math.max)(viewport.width / source.width, viewport.height / source.height);
  const media: MotionRect = {x: viewport.x + (viewport.width - source.width * scale) * position.x,
    y: viewport.y + (viewport.height - source.height * scale) * position.y,
    width: source.width * scale, height: source.height * scale};
  return {media, actions: framing.actionRegions.map(box => ({x: media.x + box.x * scale, y: media.y + box.y * scale,
    width: box.width * scale, height: box.height * scale})),
    cropped: media.x < viewport.x || media.y < viewport.y || media.x + media.width > viewport.x + viewport.width || media.y + media.height > viewport.y + viewport.height};
};

/** Media-only: brand placement comes exclusively from ProductionBrandProfile. */
export const MotionFootage: React.FC<{src: string; sourceStartFrame: number; playbackRate: number; framing: MotionFraming}> =
  ({src, sourceStartFrame, playbackRate, framing}) => {
    const mapped = mapMotionRegions(framing), {viewport, background} = framing;
    const mediaProps = {src: asset(src), startFrom: sourceStartFrame, playbackRate, muted: true};
    return <AbsoluteFill data-motion-footage="framed" style={{overflow: "hidden"}}>
      {background && <OffthreadVideo {...mediaProps} data-motion-layer="background" style={{width: "100%", height: "100%", objectFit: "cover",
        objectPosition: `${framing.position.x * 100}% ${framing.position.y * 100}%`, filter: `blur(${background.blurPx}px)`, opacity: background.opacity, transform: `scale(${background.scale})`}} />}
      <div data-motion-layer="viewport" style={{position: "absolute", left: viewport.x, top: viewport.y, width: viewport.width, height: viewport.height, overflow: "hidden"}}>
        <OffthreadVideo {...mediaProps} data-motion-layer="foreground" style={{position: "absolute", left: mapped.media.x - viewport.x,
          top: mapped.media.y - viewport.y, width: mapped.media.width, height: mapped.media.height}} />
      </div>
    </AbsoluteFill>;
  };
