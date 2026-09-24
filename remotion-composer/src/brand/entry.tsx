/** Dedicated production entry: supply the actual JSON artifact with --props. */
import React from "react";
import {getInputProps, registerRoot} from "remotion";
import {ProductionBrandComposition} from "./ProductionBrand";
import type {ProductionBrandProps} from "./types";

const props = getInputProps<ProductionBrandProps>();
if (!props.profile?.production || !props.scenes?.length || !props.durationInFrames) {
  throw new Error("ProductionBrand requires the validated real composition props artifact via --props");
}
registerRoot(() => <ProductionBrandComposition defaultProps={props} />);
