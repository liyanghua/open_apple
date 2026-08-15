import React from "react";
import { Composition } from "remotion";
import { FinalRender, FinalRenderProps, calculateFinalMetadata } from "./Composition";
import finalProps from "./artifacts/final_props.json";

export const Root: React.FC = () => (
  <Composition<FinalRenderProps>
    id="TransparentMatFinal"
    component={FinalRender}
    defaultProps={finalProps as unknown as FinalRenderProps}
    durationInFrames={finalProps.durationInFrames}
    fps={finalProps.fps}
    width={finalProps.width}
    height={finalProps.height}
    calculateMetadata={calculateFinalMetadata}
  />
);
