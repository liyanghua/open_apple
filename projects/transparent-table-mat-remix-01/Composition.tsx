import React from "react";
import type { Caption } from "@remotion/captions";
import { Audio } from "@remotion/media";
import {
  AbsoluteFill,
  CalculateMetadataFunction,
  Easing,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CaptionTrack } from "./CaptionTrack";

// ----------------------------------------------------------------------------
// ATELIER (BESPOKE) — hand-authored from scratch.
//
// HARD RULES (enforced by tools/video/video_compose.py → _run_atelier_checks
//             and skills/meta/reviewer.md → Composition Authoring Mode Review):
//   1. Do NOT import from remotion-composer/src/components, src/Explainer,
//      src/CinematicRenderer, src/{TitledVideo,TalkingHead,CollageBurst,...}.
//      The stock registry is a mechanics codex, not a parts bin.
//   2. Read skills/meta/bespoke-composition.md FIRST.
//   3. Fill in art-direction.md BEFORE writing the scene.
//
// Engine knowledge you MAY reuse freely (from `remotion`, `@remotion/*`):
//   useCurrentFrame, useVideoConfig, spring, interpolate, Sequence,
//   AbsoluteFill, Audio, OffthreadVideo, Img, staticFile, random, Easing.
// ----------------------------------------------------------------------------

export interface SceneProps {
  [key: string]: unknown;
  durationSeconds: number;
  footage: {
    sauce: string;
    scratch: string;
    spread: string;
  };
  audio: {
    mix: string;
  };
  captions: Caption[];
}

export interface FinalSceneProps {
  [key: string]: unknown;
  footage: FinalRenderProps["footage"];
  audio: {
    mix: string;
  };
  captions: Caption[];
  scenes: TimelineScene[];
}

export type TimelineScene = {
  id: string;
  assetId: string;
  footageKey: keyof FinalRenderProps["footage"];
  fromFrame: number;
  toFrameExclusive: number;
  durationInFrames: number;
  sourceInSeconds?: number;
  sourceOutSeconds?: number;
  playbackRate?: number;
  playbackMode?: "normal" | "loop" | "hold";
  scale?: number;
  scaleTo?: number;
  x?: number;
  y?: number;
  segments?: TimelineScene[];
  [key: string]: unknown;
};

export interface FinalRenderProps {
  [key: string]: unknown;
  footage: {
    diningTable: string;
    scratch: string;
    sauceWipe: string;
    meterTest: string;
    cornerFlex: string;
    spreadAlign: string;
  };
  audio: {mix: string};
  captions: Caption[];
  scenes: TimelineScene[];
  compositionId: string;
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  durationSeconds?: number;
}

const palette = {
  ink: "#171412",
  paper: "#FFFDF8",
  red: "#E2332E",
  warm: "#F2C66D",
};

const FONT = '"Songti SC", "STSong", "SimSun", serif';

const fullBleed: React.CSSProperties = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
};

const Clip: React.FC<{
  src: string;
  trimSeconds: number;
  playbackRate?: number;
  startScale?: number;
  endScale?: number;
  x?: number;
  y?: number;
  durationFrames?: number;
  filter?: string;
}> = ({
  src,
  trimSeconds,
  playbackRate = 1,
  startScale = 1.02,
  endScale = 1.06,
  x = 0,
  y = 0,
  filter = "contrast(1.04) saturate(0.96) brightness(0.98)",
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const scale = interpolate(frame, [0, durationInFrames], [startScale, endScale], {
    easing: Easing.out(Easing.quad),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ overflow: "hidden", background: palette.ink }}>
      <OffthreadVideo
        src={staticFile(src)}
        trimBefore={Math.round(trimSeconds * fps)}
        playbackRate={playbackRate}
        muted
        style={{
          ...fullBleed,
          transform: `translate(${x}px, ${y}px) scale(${scale})`,
          filter,
        }}
      />
    </AbsoluteFill>
  );
};

const ReadabilityLayer: React.FC<{ strong?: boolean }> = ({ strong = false }) => (
  <>
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, rgba(18,14,11,${strong ? 0.78 : 0.62}) 0%, rgba(18,14,11,0.34) 23%, transparent 47%)`,
      }}
    />
    <AbsoluteFill
      style={{
        background: "linear-gradient(90deg, rgba(18,14,11,0.18), transparent 42%)",
      }}
    />
  </>
);

const Type: React.FC<{
  title: string;
  kicker?: string;
  accent?: string;
  top?: number;
  compact?: boolean;
}> = ({ title, kicker, accent, top = 176, compact = false }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({
    frame,
    fps,
    durationInFrames: 14,
    config: { damping: 22, stiffness: 210, mass: 0.8 },
  });
  const opacity = interpolate(frame, [0, 5], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        top,
        left: 72,
        width: 900,
        color: palette.paper,
        transform: `translateY(${interpolate(enter, [0, 1], [28, 0])}px)`,
        opacity,
        fontFamily: FONT,
        textShadow: "0 4px 18px rgba(0,0,0,0.62)",
      }}
    >
      {kicker ? (
        <div
          style={{
            marginBottom: 18,
            fontSize: 28,
            lineHeight: 1,
            fontWeight: 700,
            color: palette.warm,
            letterSpacing: 0,
          }}
        >
          {kicker}
        </div>
      ) : null}
      <div
        style={{
          maxWidth: 880,
          fontSize: compact ? 68 : 88,
          lineHeight: 1.12,
          fontWeight: 900,
          letterSpacing: 0,
          whiteSpace: "pre-line",
        }}
      >
        {title}
      </div>
      {accent ? (
        <div
          style={{
            marginTop: 22,
            width: interpolate(enter, [0, 1], [0, 280]),
            height: 8,
            background: palette.red,
          }}
        />
      ) : null}
    </div>
  );
};

const EvidenceTrace: React.FC<{
  left: number;
  top: number;
  width: number;
  direction?: "left" | "right";
}> = ({ left, top, width, direction = "right" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const draw = spring({
    frame: frame - 18,
    fps,
    durationInFrames: 18,
    config: { damping: 24, stiffness: 180 },
  });
  const lineWidth = interpolate(draw, [0, 1], [0, width]);
  const dotX = direction === "right" ? lineWidth - 9 : width - lineWidth - 9;

  return (
    <div style={{ position: "absolute", left, top, width, height: 24 }}>
      <div
        style={{
          position: "absolute",
          left: direction === "right" ? 0 : width - lineWidth,
          top: 9,
          width: lineWidth,
          height: 5,
          background: palette.red,
          boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: dotX,
          top: 3,
          width: 18,
          height: 18,
          borderRadius: "50%",
          background: palette.red,
          border: `4px solid ${palette.paper}`,
        }}
      />
    </div>
  );
};

const HookBeat: React.FC<{
  src: string;
  trimSeconds: number;
  word: string;
  number: string;
  scale?: number;
}> = ({ src, trimSeconds, word, number, scale = 1.1 }) => {
  const frame = useCurrentFrame();
  const hit = spring({
    frame,
    fps: 30,
    durationInFrames: 9,
    config: { damping: 17, stiffness: 260, mass: 0.65 },
  });

  return (
    <AbsoluteFill>
      <Clip src={src} trimSeconds={trimSeconds} startScale={scale} endScale={scale + 0.035} />
      <ReadabilityLayer strong />
      <div
        style={{
          position: "absolute",
          left: 70,
          top: 164,
          display: "flex",
          alignItems: "baseline",
          gap: 22,
          transform: `translateY(${interpolate(hit, [0, 1], [-30, 0])}px) scale(${interpolate(hit, [0, 1], [1.12, 1])})`,
          transformOrigin: "left center",
          color: palette.paper,
          fontFamily: FONT,
          textShadow: "0 5px 20px rgba(0,0,0,0.68)",
        }}
      >
        <span style={{ color: palette.red, fontSize: 34, fontWeight: 900, letterSpacing: 0 }}>
          {number}
        </span>
        <span style={{ fontSize: 94, fontWeight: 900, letterSpacing: 0 }}>{word}</span>
      </div>
    </AbsoluteFill>
  );
};

const SpreadBeat: React.FC<{ src: string }> = ({ src }) => (
  <AbsoluteFill>
    <Clip src={src} trimSeconds={0.1} playbackRate={1.2} startScale={1} endScale={1.025} />
    <ReadabilityLayer />
    <Type kicker="真实铺设过程" title={"人工铺开\n边缘对齐"} accent="red" compact />
  </AbsoluteFill>
);

const ScratchBeat: React.FC<{ src: string }> = ({ src }) => (
  <AbsoluteFill>
    <Clip src={src} trimSeconds={6.5} playbackRate={0.92} startScale={1.08} endScale={1.13} x={-24} y={32} />
    <ReadabilityLayer />
    <Type kicker="日常接触测试" title="餐具摩擦" accent="red" />
    <EvidenceTrace left={180} top={1010} width={520} />
  </AbsoluteFill>
);

const SauceBeat: React.FC<{ src: string }> = ({ src }) => (
  <AbsoluteFill>
    <Clip src={src} trimSeconds={0.1} startScale={1.08} endScale={1.11} />
    <ReadabilityLayer />
    <Type kicker="酱汁污渍" title="洒了？" accent="red" />
  </AbsoluteFill>
);

const WipeBeat: React.FC<{ src: string }> = ({ src }) => {
  const frame = useCurrentFrame();
  const resultOpacity = interpolate(frame, [42, 54], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill>
      <Clip src={src} trimSeconds={3.55} playbackRate={1.35} startScale={1.04} endScale={1.09} />
      <ReadabilityLayer />
      <div style={{ opacity: resultOpacity }}>
        <Type kicker="结果看得见" title={"擦净\n看桌面"} accent="red" compact />
      </div>
      <EvidenceTrace left={170} top={1095} width={620} />
    </AbsoluteFill>
  );
};

export const Scene: React.FC<SceneProps> = ({ footage, audio, captions }) => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: palette.ink }}>
      <Sequence from={0} durationInFrames={18} premountFor={fps}>
        <HookBeat src={footage.sauce} trimSeconds={0.25} word="酱汁" number="01" />
      </Sequence>
      <Sequence from={18} durationInFrames={20} premountFor={fps}>
        <HookBeat src={footage.scratch} trimSeconds={0.15} word="刮蹭" number="02" scale={1.15} />
      </Sequence>
      <Sequence from={38} durationInFrames={22} premountFor={fps}>
        <HookBeat src={footage.sauce} trimSeconds={4.75} word="擦净" number="03" scale={1.08} />
      </Sequence>
      <Sequence from={60} durationInFrames={90} premountFor={fps}>
        <SpreadBeat src={footage.spread} />
      </Sequence>
      <Sequence from={150} durationInFrames={90} premountFor={fps}>
        <ScratchBeat src={footage.scratch} />
      </Sequence>
      <Sequence from={240} durationInFrames={36} premountFor={fps}>
        <SauceBeat src={footage.sauce} />
      </Sequence>
      <Sequence from={276} durationInFrames={84} premountFor={fps}>
        <WipeBeat src={footage.sauce} />
      </Sequence>
      <Audio src={staticFile(audio.mix)} volume={1} />
      <CaptionTrack captions={captions} />
    </AbsoluteFill>
  );
};

export const calculateMetadata: CalculateMetadataFunction<SceneProps> = async ({ props }) => ({
  durationInFrames: Math.round(props.durationSeconds * 30),
  fps: 30,
  width: 1080,
  height: 1920,
});

const FinalClip: React.FC<{
  src: string;
  trimSeconds: number;
  playbackRate?: number;
  scale?: number;
  scaleTo?: number;
  x?: number;
  y?: number;
  durationFrames?: number;
}> = ({
  src,
  trimSeconds,
  playbackRate = 1,
  scale = 1,
  scaleTo = scale,
  x = 0,
  y = 0,
  durationFrames,
}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const localDuration = durationFrames ?? durationInFrames;
  const zoom = interpolate(frame, [0, Math.max(1, localDuration - 1)], [scale, scaleTo], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.quad),
  });
  return (
    <AbsoluteFill style={{overflow: "hidden", background: palette.ink}}>
      <OffthreadVideo
        src={staticFile(src)}
        trimBefore={Math.round(trimSeconds * fps)}
        playbackRate={playbackRate}
        muted
        style={{
          ...fullBleed,
          transform: `translate(${x}px, ${y}px) scale(${zoom})`,
          filter: "contrast(1.035) saturate(0.96) brightness(0.99)",
        }}
      />
    </AbsoluteFill>
  );
};

const UpperLabel: React.FC<{
  children: React.ReactNode;
  large?: boolean;
  center?: boolean;
  top?: number;
}> = ({children, large = false, center = false, top = 190}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({
    frame,
    fps,
    durationInFrames: 12,
    config: {damping: 23, stiffness: 205, mass: 0.78},
  });
  return (
    <div
      style={{
        position: "absolute",
        top: Math.max(180, top),
        left: center ? 72 : 72,
        right: center ? 72 : undefined,
        maxWidth: center ? undefined : 900,
        color: palette.paper,
        fontFamily: FONT,
        fontSize: large ? 86 : 42,
        lineHeight: 1.12,
        fontWeight: 900,
        letterSpacing: 0,
        textAlign: center ? "center" : "left",
        textShadow: "0 4px 18px rgba(0,0,0,0.72)",
        opacity: interpolate(frame, [0, 5], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        }),
        transform: `translateY(${interpolate(enter, [0, 1], [22, 0])}px)`,
      }}
    >
      {children}
    </div>
  );
};

const CornerBrandCover: React.FC = () => (
  <div
    style={{
      position: "absolute",
      left: 165,
      top: 1435,
      width: 610,
      height: 130,
      background: "rgba(181,126,82,0.01)",
      backdropFilter: "blur(24px)",
      WebkitBackdropFilter: "blur(24px)",
      WebkitMaskImage: "radial-gradient(ellipse at center, #000 58%, transparent 82%)",
      maskImage: "radial-gradient(ellipse at center, #000 58%, transparent 82%)",
    }}
  />
);

const BottleBrandCover: React.FC<{durationFrames: number}> = ({durationFrames}) => {
  const frame = useCurrentFrame();
  const end = Math.max(1, durationFrames - 1);
  const x = interpolate(frame, [0, end * 0.68, end], [430, 445, 625], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const y = interpolate(frame, [0, end * 0.68, end], [285, 305, 185], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const common: React.CSSProperties = {
    position: "absolute",
    background: "rgba(43,31,23,0.01)",
    backdropFilter: "blur(22px)",
    WebkitBackdropFilter: "blur(22px)",
    WebkitMaskImage: "radial-gradient(ellipse at center, #000 55%, transparent 82%)",
    maskImage: "radial-gradient(ellipse at center, #000 55%, transparent 82%)",
    transform: "rotate(18deg)",
  };
  return (
    <>
      <div style={{...common, left: x + 70, top: y + 120, width: 155, height: 120}} />
      <div style={{...common, left: x + 28, top: y + 270, width: 180, height: 155}} />
    </>
  );
};

const RedTrace: React.FC<{left?: number; top?: number; width?: number}> = ({
  left = 180,
  top = 1090,
  width = 500,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const draw = spring({frame: frame - 5, fps, config: {damping: 24, stiffness: 180}});
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width: interpolate(draw, [0, 1], [0, width]),
        height: 5,
        background: palette.red,
        boxShadow: "0 2px 9px rgba(0,0,0,0.35)",
      }}
    />
  );
};

const DarkTop: React.FC = () => (
  <AbsoluteFill
    style={{
      background: "linear-gradient(180deg, rgba(17,13,10,0.55), transparent 35%)",
      pointerEvents: "none",
    }}
  />
);

type SceneInput = {src: string; scene: TimelineScene};

const Scene01: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
    <BottleBrandCover durationFrames={scene.durationInFrames} />
    <DarkTop />
    <HookLabel />
  </AbsoluteFill>
);

const Scene02: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
    <DarkTop />
  </AbsoluteFill>
);

const Scene03: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
    <DarkTop />
  </AbsoluteFill>
);

const Scene04: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} />
    <DarkTop />
    <UpperLabel>人工铺设</UpperLabel>
  </AbsoluteFill>
);

const Scene05: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} scaleTo={scene.scaleTo ?? 1.1} />
    <DarkTop />
    <UpperLabel>贴合结果</UpperLabel>
  </AbsoluteFill>
);

const Scene06: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
    <DarkTop />
    <UpperLabel>测试 01｜餐具摩擦</UpperLabel>
    <Sequence from={16} durationInFrames={22} premountFor={30}>
      <RedTrace left={240} top={1050} width={430} />
    </Sequence>
  </AbsoluteFill>
);

const Scene07: React.FC<SceneInput> = ({src, scene}) => {
  const segments = scene.segments ?? [];
  return (
  <AbsoluteFill>
    <Sequence from={0} durationInFrames={segments[0]?.durationInFrames ?? scene.durationInFrames} premountFor={30}>
      <FinalClip src={src} trimSeconds={segments[0]?.sourceInSeconds ?? 0} playbackRate={segments[0]?.playbackRate ?? 1} scale={scene.scale ?? 1} durationFrames={segments[0]?.durationInFrames} />
    </Sequence>
    <Sequence from={segments[0]?.durationInFrames ?? 0} durationInFrames={segments[1]?.durationInFrames ?? 0} premountFor={30}>
      <FinalClip src={src} trimSeconds={segments[1]?.sourceInSeconds ?? 0} playbackRate={segments[1]?.playbackRate ?? 1} scale={scene.scale ?? 1} scaleTo={scene.scaleTo ?? 1.08} durationFrames={segments[1]?.durationInFrames} />
    </Sequence>
    <Sequence from={(segments[0]?.durationInFrames ?? 0) + (segments[1]?.durationInFrames ?? 0)} durationInFrames={segments[2]?.durationInFrames ?? 0} premountFor={30}>
      <FinalClip src={src} trimSeconds={segments[1]?.sourceInSeconds ?? 0} playbackRate={segments[2]?.playbackRate ?? 1} scale={scene.scale ?? 1} durationFrames={segments[2]?.durationInFrames} />
    </Sequence>
  </AbsoluteFill>
  );
};

const Scene08: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
    <BottleBrandCover durationFrames={scene.durationInFrames} />
    <DarkTop />
    <UpperLabel>测试 02｜防污</UpperLabel>
  </AbsoluteFill>
);

const Scene09: React.FC<SceneInput> = ({src, scene}) => (
  <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
);

const Scene10: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
    <Sequence from={48} durationInFrames={24} premountFor={30}>
      <RedTrace left={190} top={1100} width={570} />
    </Sequence>
  </AbsoluteFill>
);

const Scene11: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
    <CornerBrandCover />
    <DarkTop />
    <UpperLabel>测试 03｜柔韧</UpperLabel>
  </AbsoluteFill>
);

const Scene12: React.FC<SceneInput> = ({src, scene}) => {
  const segments = scene.segments ?? [];
  return (
  <AbsoluteFill>
    <Sequence from={0} durationInFrames={segments[0]?.durationInFrames ?? 0} premountFor={30}>
      <FinalClip src={src} trimSeconds={segments[0]?.sourceInSeconds ?? 0} playbackRate={segments[0]?.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
      <CornerBrandCover />
    </Sequence>
    <Sequence from={segments[0]?.durationInFrames ?? 0} durationInFrames={segments[1]?.durationInFrames ?? 0} premountFor={30}>
      <FinalClip src={src} trimSeconds={segments[1]?.sourceInSeconds ?? 0} playbackRate={segments[1]?.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
      <CornerBrandCover />
      <Sequence from={18} durationInFrames={20} premountFor={30}>
        <RedTrace left={300} top={1120} width={420} />
      </Sequence>
    </Sequence>
  </AbsoluteFill>
  );
};

const Scene13: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
    <DarkTop />
    <div
      style={{
        position: "absolute",
        left: 388,
        top: 760,
        width: 300,
        height: 300,
        border: "4px solid rgba(255,253,248,0.86)",
        boxShadow: "0 0 0 2px rgba(226,51,46,0.78)",
        borderRadius: 20,
      }}
    />
    <UpperLabel top={188}>仪表实测画面</UpperLabel>
    <div
      style={{
        position: "absolute",
        left: 110,
        right: 110,
        bottom: 465,
        color: palette.paper,
        background: "rgba(20,16,13,0.72)",
        padding: "14px 22px",
        fontFamily: FONT,
        fontSize: 31,
        lineHeight: 1.25,
        fontWeight: 700,
        textAlign: "center",
        letterSpacing: 0,
      }}
    >
      仪表实测画面，具体读数以画面为准
    </div>
  </AbsoluteFill>
);

const Scene14: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} />
    <DarkTop />
    <UpperLabel>透明材质</UpperLabel>
  </AbsoluteFill>
);

const Scene15: React.FC<SceneInput> = ({src, scene}) => {
  const frame = useCurrentFrame();
  const labels = ["防污易擦", "日常防护", "柔韧贴合"];
  return (
    <AbsoluteFill>
      <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} x={scene.x ?? 0} y={scene.y ?? 0} />
      <DarkTop />
      <div
        style={{
          position: "absolute",
          top: 205,
          left: 72,
          right: 72,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: 18,
          fontFamily: FONT,
        }}
      >
        {labels.map((label, index) => {
          const opacity = interpolate(frame, [index * 17, index * 17 + 6], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          return (
            <div
              key={label}
              style={{
                opacity,
                color: palette.paper,
                background: "rgba(20,16,13,0.67)",
                borderLeft: `6px solid ${palette.red}`,
                padding: "12px 22px",
                fontSize: 36,
                lineHeight: 1,
                fontWeight: 850,
                letterSpacing: 0,
              }}
            >
              {label}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const Scene16: React.FC<SceneInput> = ({src, scene}) => (
  <AbsoluteFill>
    <FinalClip src={src} trimSeconds={scene.sourceInSeconds ?? 0} playbackRate={scene.playbackRate ?? 1} scale={scene.scale ?? 1} scaleTo={scene.scaleTo ?? 1.035} />
    <DarkTop />
    <UpperLabel large center top={235}>
      透明桌垫
    </UpperLabel>
  </AbsoluteFill>
);

const HookLabel: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [5, 10, 20], [0, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <div style={{opacity}}><UpperLabel>先别让桌面扛</UpperLabel></div>;
};

const FinalVisual: React.FC<SceneInput> = (props) => {
  switch (props.scene.id) {
    case "n01": return <Scene01 {...props} />;
    case "n02": return <Scene02 {...props} />;
    case "n03": return <Scene03 {...props} />;
    case "n04": return <Scene04 {...props} />;
    case "n05": return <Scene05 {...props} />;
    case "n06": return <Scene06 {...props} />;
    case "n07": return <Scene07 {...props} />;
    case "n08": return <Scene08 {...props} />;
    case "n09": return <Scene09 {...props} />;
    case "n10": return <Scene10 {...props} />;
    case "n11": return <Scene11 {...props} />;
    case "n12": return <Scene12 {...props} />;
    case "n13": return <Scene13 {...props} />;
    case "n14": return <Scene14 {...props} />;
    case "n15": return <Scene15 {...props} />;
    case "n16": return <Scene16 {...props} />;
    default: return <AbsoluteFill />;
  }
};

export const FinalScene: React.FC<FinalSceneProps> = ({footage, audio, captions, scenes}) => (
  <AbsoluteFill style={{background: palette.ink}}>
    {scenes.map((scene) => (
      <Sequence key={scene.id} from={scene.fromFrame} durationInFrames={scene.durationInFrames} premountFor={30}>
        <FinalVisual scene={scene} src={footage[scene.footageKey]} />
      </Sequence>
    ))}
    <Audio src={staticFile(audio.mix)} volume={1} />
    <CaptionTrack captions={captions} />
  </AbsoluteFill>
);

export const FinalRender: React.FC<FinalRenderProps> = (props) => <FinalScene {...props} />;

export const calculateFinalMetadata: CalculateMetadataFunction<FinalRenderProps> = async ({props}) => ({
  durationInFrames: props.durationInFrames,
  fps: props.fps,
  width: props.width,
  height: props.height,
});
