const Sl=new Map;function Dt(a){Sl.set(a.type,a)}const kl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_levels;
uniform float u_scale;
out vec4 fragColor;

const float bayer[16] = float[16](
  0.0, 8.0, 2.0, 10.0,
  12.0, 4.0, 14.0, 6.0,
  3.0, 11.0, 1.0, 9.0,
  15.0, 7.0, 13.0, 5.0
);

float bayerValue(vec2 pixel) {
  int x = int(mod(pixel.x, 4.0));
  int y = int(mod(pixel.y, 4.0));
  return bayer[y * 4 + x] / 16.0;
}

void main() {
  vec4 src = texture(u_input, vUv);
  float scale = max(u_scale, 1.0);
  float levels = max(u_levels, 2.0);
  vec2 pixel = floor((vUv * u_resolution) / scale);
  float threshold = bayerValue(pixel) - 0.5;
  vec3 scaled = src.rgb * (levels - 1.0);
  vec3 quantized = floor(scaled + 0.5 + threshold) / (levels - 1.0);
  fragColor = vec4(clamp(quantized, 0.0, 1.0), src.a);
}
`,Cl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_mix;
out vec4 fragColor;

const vec3 stopDark = vec3(0.05, 0.02, 0.18);
const vec3 stopLight = vec3(1.0, 0.86, 0.45);

void main() {
  vec4 src = texture(u_input, vUv);
  float luma = dot(src.rgb, vec3(0.2126, 0.7152, 0.0722));
  vec3 mapped = mix(stopDark, stopLight, luma);
  vec3 result = mix(src.rgb, mapped, clamp(u_mix, 0.0, 1.0));
  fragColor = vec4(result, src.a);
}
`,Ol=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_size;
out vec4 fragColor;

void main() {
  float size = max(u_size, 1.0);
  vec2 blocks = max(u_resolution / size, vec2(1.0));
  vec2 quantized = (floor(vUv * blocks) + 0.5) / blocks;
  fragColor = texture(u_input, quantized);
}
`,Tl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_dotSize;
uniform float u_angle;
out vec4 fragColor;

void main() {
  vec4 src = texture(u_input, vUv);
  float luma = dot(src.rgb, vec3(0.2126, 0.7152, 0.0722));
  float dotSize = max(u_dotSize, 2.0);
  float rad = radians(u_angle);
  vec2 pixel = vUv * u_resolution;
  mat2 rot = mat2(cos(rad), -sin(rad), sin(rad), cos(rad));
  vec2 rotated = rot * pixel;
  vec2 cell = mod(rotated, dotSize) - dotSize * 0.5;
  float dist = length(cell) / (dotSize * 0.5);
  float radius = sqrt(1.0 - clamp(luma, 0.0, 1.0));
  float ink = step(dist, radius);
  vec3 result = mix(vec3(1.0), vec3(0.0), ink);
  fragColor = vec4(result, src.a);
}
`,Ul=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_intensity;
uniform float u_scanlines;
uniform float u_jitter;
out vec4 fragColor;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

void main() {
  float intensity = clamp(u_intensity, 0.0, 1.0);
  float frame = floor(u_time * 24.0);
  float lineNoise = hash(vec2(frame, floor(vUv.y * 90.0)));
  float horizontalJitter = (lineNoise - 0.5) * u_jitter * 0.035;
  horizontalJitter *= step(0.82, lineNoise);
  vec2 uv = vec2(clamp(vUv.x + horizontalJitter, 0.0, 1.0), vUv.y);
  float split = (1.0 + u_jitter * 4.0) / max(u_resolution.x, 1.0);
  vec4 src = texture(u_input, uv);
  vec3 vhs = vec3(
    texture(u_input, vec2(clamp(uv.x + split, 0.0, 1.0), uv.y)).r,
    src.g,
    texture(u_input, vec2(clamp(uv.x - split, 0.0, 1.0), uv.y)).b
  );
  float scan = sin(vUv.y * u_resolution.y * 3.14159265);
  vhs *= 1.0 - (0.5 + 0.5 * scan) * clamp(u_scanlines, 0.0, 1.0) * 0.32;
  float grain = (hash(vUv * u_resolution + frame) - 0.5) * 0.11;
  vhs += grain * intensity;
  fragColor = vec4(clamp(mix(src.rgb, vhs, intensity), 0.0, 1.0), src.a);
}
`,Il=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_levels;
uniform float u_mix;
out vec4 fragColor;

void main() {
  vec4 src = texture(u_input, vUv);
  float levels = max(2.0, floor(u_levels));
  vec3 posterized = floor(src.rgb * (levels - 1.0) + 0.5) / (levels - 1.0);
  fragColor = vec4(mix(src.rgb, posterized, clamp(u_mix, 0.0, 1.0)), src.a);
}
`,Al=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform vec4 u_shadowColor;
uniform vec4 u_highlightColor;
uniform float u_mix;
uniform float u_contrast;
out vec4 fragColor;

void main() {
  vec4 src = texture(u_input, vUv);
  float luma = dot(src.rgb, vec3(0.2126, 0.7152, 0.0722));
  luma = clamp((luma - 0.5) * max(u_contrast, 0.1) + 0.5, 0.0, 1.0);
  vec3 mapped = mix(u_shadowColor.rgb, u_highlightColor.rgb, luma);
  fragColor = vec4(mix(src.rgb, mapped, clamp(u_mix, 0.0, 1.0)), src.a);
}
`,Ml=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_angle;
uniform float u_mix;
out vec4 fragColor;

void main() {
  vec2 texel = 1.0 / max(u_resolution, vec2(1.0));
  float rad = radians(u_angle);
  vec2 direction = vec2(cos(rad), sin(rad));
  vec2 offset = direction * texel * u_amount;
  vec4 src = texture(u_input, vUv);
  vec3 prism = vec3(
    texture(u_input, clamp(vUv + offset, vec2(0.0), vec2(1.0))).r,
    src.g,
    texture(u_input, clamp(vUv - offset, vec2(0.0), vec2(1.0))).b
  );
  fragColor = vec4(mix(src.rgb, prism, clamp(u_mix, 0.0, 1.0)), src.a);
}
`,Bl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_strength;
uniform float u_radius;
out vec4 fragColor;

void main() {
  vec2 aspect = vec2(u_resolution.x / max(u_resolution.y, 1.0), 1.0);
  vec2 centered = (vUv - 0.5) * aspect;
  float distanceFromCenter = length(centered);
  float radius = max(u_radius, 0.1);
  float falloff = 1.0 - smoothstep(radius * 0.75, radius, distanceFromCenter);
  float distortion = 1.0 + u_strength * dot(centered, centered) * falloff;
  vec2 distorted = centered * distortion;
  vec2 uv = clamp(distorted / aspect + 0.5, vec2(0.0), vec2(1.0));
  vec4 src = texture(u_input, vUv);
  vec4 warped = texture(u_input, uv);
  fragColor = vec4(warped.rgb, src.a);
}
`,Vl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_amplitude;
uniform float u_frequency;
uniform float u_speed;
out vec4 fragColor;

void main() {
  float phase = vUv.y * u_frequency * 6.2831853 + u_time * u_speed;
  vec2 uv = vec2(clamp(vUv.x + sin(phase) * u_amplitude, 0.0, 1.0), vUv.y);
  vec4 warped = texture(u_input, uv);
  vec4 src = texture(u_input, vUv);
  fragColor = vec4(warped.rgb, src.a);
}
`,Rl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_density;
uniform float u_intensity;
uniform float u_speed;
out vec4 fragColor;

void main() {
  vec4 src = texture(u_input, vUv);
  float position = vUv.y * u_density + u_time * u_speed * 20.0;
  float line = 0.5 + 0.5 * sin(position * 3.14159265);
  float shade = 1.0 - line * clamp(u_intensity, 0.0, 1.0);
  fragColor = vec4(src.rgb * shade, src.a);
}
`,Pl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_strength;
uniform float u_radius;
uniform vec4 u_color;
out vec4 fragColor;

float lumaAt(vec2 uv) {
  return dot(texture(u_input, clamp(uv, vec2(0.0), vec2(1.0))).rgb, vec3(0.2126, 0.7152, 0.0722));
}

void main() {
  vec4 src = texture(u_input, vUv);
  vec2 texel = max(u_radius, 0.5) / max(u_resolution, vec2(1.0));
  float gx = lumaAt(vUv + vec2(texel.x, 0.0)) - lumaAt(vUv - vec2(texel.x, 0.0));
  float gy = lumaAt(vUv + vec2(0.0, texel.y)) - lumaAt(vUv - vec2(0.0, texel.y));
  float edge = clamp(length(vec2(gx, gy)) * u_strength, 0.0, 1.0);
  vec3 result = src.rgb + u_color.rgb * edge * u_color.a;
  fragColor = vec4(clamp(result, 0.0, 1.0), src.a);
}
`,Dl=[{id:"dither",name:"Dither",category:"effect",glsl:kl,params:[{name:"levels",label:"Levels",type:"number",default:4,min:2,max:16,step:1},{name:"scale",label:"Scale",type:"number",default:1,min:1,max:8,step:1}]},{id:"gradient-map",name:"Gradient Map",category:"effect",glsl:Cl,params:[{name:"mix",label:"Mix",type:"number",default:1,min:0,max:1,step:.01}]},{id:"pixelate",name:"Pixelate",category:"effect",glsl:Ol,params:[{name:"size",label:"Size",type:"number",default:8,min:1,max:64,step:1}]},{id:"halftone",name:"Halftone",category:"effect",glsl:Tl,params:[{name:"dotSize",label:"Dot Size",type:"number",default:8,min:2,max:32,step:1},{name:"angle",label:"Angle",type:"number",default:15,min:0,max:90,step:1}]},{id:"vhs",name:"VHS",category:"effect",glsl:Ul,params:[{name:"intensity",label:"Intensity",type:"number",default:.75,min:0,max:1,step:.01},{name:"scanlines",label:"Scanlines",type:"number",default:.4,min:0,max:1,step:.01},{name:"jitter",label:"Jitter",type:"number",default:.45,min:0,max:1,step:.01}]},{id:"posterize",name:"Posterize",category:"effect",glsl:Il,params:[{name:"levels",label:"Levels",type:"number",default:5,min:2,max:16,step:1},{name:"mix",label:"Mix",type:"number",default:1,min:0,max:1,step:.01}]},{id:"duotone",name:"Duotone",category:"effect",glsl:Al,params:[{name:"shadowColor",label:"Shadow",type:"color",default:"#11133f",min:0,max:1,step:.01},{name:"highlightColor",label:"Highlight",type:"color",default:"#ffca6b",min:0,max:1,step:.01},{name:"mix",label:"Mix",type:"number",default:.9,min:0,max:1,step:.01},{name:"contrast",label:"Contrast",type:"number",default:1.15,min:.25,max:2.5,step:.05}]},{id:"prism",name:"Prism Split",category:"effect",glsl:Ml,params:[{name:"amount",label:"Offset",type:"number",default:8,min:0,max:40,step:.5},{name:"angle",label:"Angle",type:"number",default:0,min:0,max:360,step:1},{name:"mix",label:"Mix",type:"number",default:1,min:0,max:1,step:.01}]},{id:"fisheye",name:"Fisheye",category:"effect",glsl:Bl,params:[{name:"strength",label:"Strength",type:"number",default:.55,min:-1,max:1.5,step:.05},{name:"radius",label:"Radius",type:"number",default:.8,min:.2,max:1.5,step:.05}]},{id:"wave-warp",name:"Wave Warp",category:"effect",glsl:Vl,params:[{name:"amplitude",label:"Amplitude",type:"number",default:.025,min:0,max:.15,step:.005},{name:"frequency",label:"Frequency",type:"number",default:5,min:1,max:20,step:.5},{name:"speed",label:"Speed",type:"number",default:1.5,min:0,max:8,step:.1}]},{id:"scanlines",name:"Scanlines",category:"effect",glsl:Rl,params:[{name:"density",label:"Density",type:"number",default:360,min:40,max:1200,step:10},{name:"intensity",label:"Intensity",type:"number",default:.3,min:0,max:1,step:.01},{name:"speed",label:"Speed",type:"number",default:.2,min:0,max:4,step:.05}]},{id:"edge-glow",name:"Edge Glow",category:"effect",glsl:Pl,params:[{name:"strength",label:"Strength",type:"number",default:4,min:0,max:12,step:.25},{name:"radius",label:"Radius",type:"number",default:1.5,min:.5,max:6,step:.25},{name:"color",label:"Glow Color",type:"color",default:"#4de8ff",min:0,max:1,step:.01}]}],zl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_scale;
uniform float u_speed;
uniform float u_contrast;
out vec4 fragColor;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float valueNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {
  float sum = 0.0;
  float amp = 0.5;
  for (int i = 0; i < 5; i++) {
    sum += amp * valueNoise(p);
    p *= 2.0;
    amp *= 0.5;
  }
  return sum;
}

void main() {
  float scale = max(u_scale, 1.0);
  vec2 p = vUv * scale;
  float flow = u_time * u_speed;
  float field = fbm(p + vec2(flow, flow * 0.5));
  field += 0.4 * sin((p.x + p.y) * 1.5 + field * 6.2831 + flow);
  float ramp = 0.5 + 0.5 * sin(field * 6.2831 * u_contrast);
  float metal = pow(clamp(ramp, 0.0, 1.0), 1.6);
  vec3 color = mix(vec3(0.08, 0.09, 0.11), vec3(0.92, 0.94, 0.98), metal);
  fragColor = vec4(color, 1.0);
}
`,Fl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_scale;
uniform float u_bleed;
out vec4 fragColor;

float hash(vec2 p) {
  p = fract(p * vec2(91.73, 53.41));
  p += dot(p, p + 21.97);
  return fract(p.x * p.y);
}

float valueNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

void main() {
  float scale = max(u_scale, 1.0);
  vec2 p = vUv * scale;
  float bleed = clamp(u_bleed, 0.0, 1.0);
  float base = valueNoise(p);
  float mid = valueNoise(p * 2.0 + 7.3);
  float fine = valueNoise(p * 4.0 + 19.1);
  float mottle = base * 0.55 + mid * 0.3 + fine * 0.15;
  float soft = mix(mottle, smoothstep(0.2, 0.8, mottle), bleed);
  vec3 paper = mix(vec3(0.97, 0.96, 0.92), vec3(0.74, 0.78, 0.86), soft);
  fragColor = vec4(paper, 1.0);
}
`,Nl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_scale;
uniform float u_warp;
out vec4 fragColor;

float hash(vec2 p) {
  p = fract(p * vec2(127.1, 311.7));
  p += dot(p, p + 34.45);
  return fract(p.x * p.y);
}

float valueNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

void main() {
  float scale = max(u_scale, 1.0);
  float warp = clamp(u_warp, 0.0, 1.0);
  vec2 p = vUv * scale;
  vec2 offset = vec2(valueNoise(p + 1.7), valueNoise(p + 9.2));
  vec2 warped = p + warp * (offset - 0.5) * 4.0;
  float field = valueNoise(warped);
  vec3 lo = vec3(0.12, 0.20, 0.45);
  vec3 hi = vec3(0.95, 0.55, 0.30);
  vec3 color = mix(lo, hi, clamp(field, 0.0, 1.0));
  fragColor = vec4(color, 1.0);
}
`,El=[{id:"liquid-metal",name:"Liquid Metal",category:"fill",glsl:zl,params:[{name:"scale",label:"Scale",type:"number",default:6,min:1,max:20,step:.5,control:"number"},{name:"speed",label:"Speed",type:"number",default:0,min:0,max:2,step:.05,control:"number"},{name:"contrast",label:"Contrast",type:"number",default:1.4,min:.5,max:3,step:.1,control:"number"}]},{id:"watercolor",name:"Watercolor",category:"fill",glsl:Fl,params:[{name:"scale",label:"Scale",type:"number",default:5,min:1,max:16,step:.5,control:"number"},{name:"bleed",label:"Bleed",type:"number",default:.5,min:0,max:1,step:.05,control:"slider"}]},{id:"gradient-noise",name:"Gradient Noise",category:"fill",glsl:Nl,params:[{name:"scale",label:"Scale",type:"number",default:8,min:1,max:24,step:.5,control:"number"},{name:"warp",label:"Warp",type:"number",default:.4,min:0,max:1,step:.05,control:"slider"}]}],Ll=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform float u_time;
uniform float u_progress;
uniform float u_edgeWidth;
uniform float u_scale;
out vec4 fragColor;
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p){
  vec2 i = floor(p); vec2 f = fract(p);
  vec2 u = f*f*(3.0-2.0*f);
  return mix(mix(hash(i), hash(i+vec2(1,0)), u.x),
             mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), u.x), u.y);
}
void main(){
  vec4 src = texture(u_input, vUv);
  float n = vnoise(vUv * u_scale + u_time * 0.05);
  float edge = max(u_edgeWidth, 0.001);
  float reveal = smoothstep(n - edge, n + edge, u_progress);
  fragColor = vec4(src.rgb, src.a * reveal);
}
`,$l=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_progress;
uniform float u_glow;
uniform float u_softness;
out vec4 fragColor;
void main(){
  vec4 src = texture(u_input, vUv);
  float softness = clamp(u_softness, 0.0, 1.0);
  vec2 texel = 1.0 / max(u_resolution, vec2(1.0));
  float radius = 1.0 + softness * 3.0;
  float coverage = 0.0;
  coverage += texture(u_input, vUv + texel * vec2(radius, 0.0)).a;
  coverage += texture(u_input, vUv - texel * vec2(radius, 0.0)).a;
  coverage += texture(u_input, vUv + texel * vec2(0.0, radius)).a;
  coverage += texture(u_input, vUv - texel * vec2(0.0, radius)).a;
  coverage += texture(u_input, vUv + texel * radius).a;
  coverage += texture(u_input, vUv - texel * radius).a;
  coverage *= 0.16666667;
  float peak = sin(clamp(u_progress, 0.0, 1.0) * 3.14159265);
  float glow = max(u_glow, 0.0) * peak;
  vec3 lit = src.rgb + src.rgb * glow;
  float halo = coverage * glow;
  vec3 color = lit + vec3(halo);
  float alpha = clamp(src.a + halo, 0.0, 1.0);
  fragColor = vec4(color, alpha);
}
`,jl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform float u_progress;
uniform float u_amount;
out vec4 fragColor;
void main(){
  float p = clamp(u_progress, 0.0, 1.0);
  float split = max(u_amount, 0.0) * (1.0 - p);
  vec2 shift = vec2(split, 0.0);
  float r = texture(u_input, vUv + shift).r;
  vec4 g = texture(u_input, vUv);
  float b = texture(u_input, vUv - shift).b;
  float alpha = max(g.a, max(texture(u_input, vUv + shift).a, texture(u_input, vUv - shift).a));
  fragColor = vec4(r, g.g, b, alpha);
}
`,Wl=`#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D u_input;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_progress;
uniform float u_lines;
uniform float u_jitter;
out vec4 fragColor;
float hash(float x){ return fract(sin(x * 78.233) * 43758.5453); }
void main(){
  vec4 src = texture(u_input, vUv);
  float p = clamp(u_progress, 0.0, 1.0);
  float lines = max(u_lines, 1.0);
  float jitter = clamp(u_jitter, 0.0, 1.0);
  float row = floor(vUv.y * lines);
  float flicker = (hash(row + floor(u_time * 30.0)) - 0.5) * jitter;
  float fade = smoothstep(0.0, 0.15, p) * smoothstep(0.0, 0.15, 1.0 - p);
  float thr = clamp(p + flicker * fade, 0.0, 1.0);
  float reveal = step(vUv.y, thr);
  fragColor = vec4(src.rgb, src.a * reveal);
}
`,Gl=[{id:"glyph-dissolve",name:"Glyph Dissolve",category:"text",glsl:Ll,params:[{name:"edgeWidth",label:"Edge Width",type:"number",default:.15,min:0,max:1,step:.01,control:"slider"},{name:"scale",label:"Scale",type:"number",default:12,min:2,max:40,step:1,control:"number"}]},{id:"glyph-glow-wave",name:"Glyph Glow Wave",category:"text",glsl:$l,params:[{name:"glow",label:"Glow",type:"number",default:1.4,min:0,max:3,step:.1,control:"number"},{name:"softness",label:"Softness",type:"number",default:.5,min:0,max:1,step:.05,control:"slider"}]},{id:"chromatic-cascade",name:"Chromatic Cascade",category:"text",glsl:jl,params:[{name:"amount",label:"Amount",type:"number",default:.03,min:0,max:.1,step:.005,control:"slider"}]},{id:"scanline-materialize",name:"Scanline Materialize",category:"text",glsl:Wl,params:[{name:"lines",label:"Lines",type:"number",default:80,min:10,max:200,step:5,control:"number"},{name:"jitter",label:"Jitter",type:"number",default:.3,min:0,max:1,step:.05,control:"slider"}]}];new Set([...Dl,...El,...Gl].map(a=>a.id));function Ge(a,e){for(const t of a.timeline.tracks){const o=t.clips.find(i=>i.id===e);if(o)return o}}function oo(a,e,t){const o=a.timeline;let i=!1;return o.tracks=o.tracks.map(r=>({...r,clips:r.clips.map(n=>n.id===e?(i=!0,{...n,...t}):n)})),i}function jt(a){return{type:a.type,validate(e,t){const o=e.params,i=o.clipId,r=[];if((typeof i!="string"||!Ge(t,i))&&r.push({code:"CLIP_NOT_FOUND",message:`Clip not found: ${String(i)}`}),a.validateValue){const n=a.validateValue(o[a.paramKey]);n&&r.push({code:"INVALID_PARAMS",message:n})}return{valid:r.length===0,errors:r}},apply(e,t){const o=e.params,i=o.clipId,r=o[a.paramKey],n=a.transform?a.transform(r):r;oo(t,i,{[a.field]:n})},invert(e,t){const i=e.params.clipId,r=Ge(t,i);if(!r)return null;const n=r[a.field];return{type:a.type,id:`inverse-${e.id}`,timestamp:Date.now(),params:{clipId:i,[a.paramKey]:n}}}}}const Yl=.1,ql=20,Hl=a=>typeof a=="number"&&Number.isFinite(a),Xl={type:"clip/setSpeed",validate(a,e){const t=a.params,o=[];return(typeof t.clipId!="string"||!Ge(e,t.clipId))&&o.push({code:"CLIP_NOT_FOUND",message:`Clip not found: ${String(t.clipId)}`}),t.speed!=null&&!Hl(t.speed)&&o.push({code:"INVALID_PARAMS",message:"speed must be a number"}),{valid:o.length===0,errors:o}},apply(a,e){const t=a.params,o=Ge(e,t.clipId);if(!o)return;const i=Math.max(Yl,Math.min(ql,Number(t.speed))),r=o.outPoint-o.inPoint;oo(e,t.clipId,{speed:i,duration:r>0?r/i:o.duration})},invert(a,e){const t=a.params,o=Ge(e,t.clipId);return o?{type:"clip/setSpeed",id:`inverse-${a.id}`,timestamp:Date.now(),params:{clipId:t.clipId,speed:o.speed??1}}:null}},Kl={type:"speed/setRampData",validate(a,e){const t=a.params;return typeof t.clipId=="string"&&Ge(e,t.clipId)?{valid:!0,errors:[]}:{valid:!1,errors:[{code:"CLIP_NOT_FOUND",message:`Clip not found: ${String(t.clipId)}`}]}},apply(a,e){const t=a.params;oo(e,t.clipId,{speedKeyframes:t.keyframes,freezeFrames:t.freezeFrames,pitchCorrection:t.pitchCorrection})},invert(a,e){const t=a.params,o=Ge(e,t.clipId);return o?{type:"speed/setRampData",id:`inverse-${a.id}`,timestamp:Date.now(),params:{clipId:t.clipId,keyframes:o.speedKeyframes,freezeFrames:o.freezeFrames,pitchCorrection:o.pitchCorrection}}:null}},Ql=[Xl,Kl,jt({type:"clip/setReverse",paramKey:"reversed",field:"reversed",validateValue:a=>a==null||typeof a=="boolean"?null:"reversed must be a boolean"}),jt({type:"clip/setPitchCorrection",paramKey:"pitchCorrection",field:"pitchCorrection",validateValue:a=>a==null||typeof a=="boolean"?null:"pitchCorrection must be a boolean"}),jt({type:"clip/setStabilization",paramKey:"stabilization",field:"stabilization",validateValue:a=>a==null||typeof a=="object"?null:"stabilization must be an object"}),jt({type:"clip/setChromaKey",paramKey:"chromaKey",field:"chromaKey",validateValue:a=>a==null||typeof a=="object"?null:"chromaKey must be an object"}),jt({type:"speed/setKeyframes",paramKey:"keyframes",field:"speedKeyframes",validateValue:a=>a==null||Array.isArray(a)?null:"keyframes must be an array"}),jt({type:"speed/setFreezeFrames",paramKey:"freezeFrames",field:"freezeFrames",validateValue:a=>a==null||Array.isArray(a)?null:"freezeFrames must be an array"})];for(const a of Ql)Dt(a);const Jl=jt({type:"keyframe/setAll",paramKey:"keyframes",field:"keyframes",validateValue:a=>a==null||Array.isArray(a)?null:"keyframes must be an array"}),Zl={type:"effect/setOrder",validate(a,e){const t=a.params,o=[],i=typeof t.clipId=="string"?Ge(e,t.clipId):void 0;if(!i)o.push({code:"CLIP_NOT_FOUND",message:`Clip not found: ${String(t.clipId)}`});else if(!Array.isArray(t.effectIds))o.push({code:"INVALID_PARAMS",message:"effectIds must be an array"});else{const r=new Set(i.effects.map(s=>s.id));t.effectIds.length===i.effects.length&&t.effectIds.every(s=>typeof s=="string"&&r.has(s))||o.push({code:"INVALID_PARAMS",message:"effectIds must be a permutation of the clip's effect ids"})}return{valid:o.length===0,errors:o}},apply(a,e){const t=a.params,o=Ge(e,t.clipId);if(!o)return;const i=new Map(o.effects.map(n=>[n.id,n])),r=t.effectIds.map(n=>i.get(n)).filter(n=>n!==void 0);oo(e,t.clipId,{effects:r})},invert(a,e){const t=a.params,o=Ge(e,t.clipId);return o?{type:"effect/setOrder",id:`inverse-${a.id}`,timestamp:Date.now(),params:{clipId:t.clipId,effectIds:o.effects.map(i=>i.id)}}:null}},ec={type:"effect/setStack",validate(a,e){const t=a.params,o=[];return(typeof t.clipId!="string"||!Ge(e,t.clipId))&&o.push({code:"CLIP_NOT_FOUND",message:`Clip not found: ${String(t.clipId)}`}),Array.isArray(t.effects)||o.push({code:"INVALID_PARAMS",message:"effects must be an array"}),{valid:o.length===0,errors:o}},apply(a,e){const t=a.params;oo(e,t.clipId,{effects:structuredClone(t.effects)})},invert(a,e){const t=a.params,o=Ge(e,t.clipId);return o?{type:"effect/setStack",id:`inverse-${a.id}`,timestamp:Date.now(),params:{clipId:t.clipId,effects:structuredClone(o.effects)}}:null}};function Ur(a,e){return a.timeline.subtitles.find(t=>t.id===e)}const tc={type:"subtitle/replace",validate(a,e){const t=a.params,o=[];return(typeof t.subtitleId!="string"||!Ur(e,t.subtitleId))&&o.push({code:"INVALID_PARAMS",message:`Subtitle not found: ${String(t.subtitleId)}`}),{valid:o.length===0,errors:o}},apply(a,e){const t=a.params,o=e.timeline;o.subtitles=o.subtitles.map(i=>i.id===t.subtitleId?t.subtitle:i)},invert(a,e){const t=a.params,o=Ur(e,t.subtitleId);return o?{type:"subtitle/replace",id:`inverse-${a.id}`,timestamp:Date.now(),params:{subtitleId:t.subtitleId,subtitle:{...o}}}:null}},ac={type:"subtitle/setAll",validate(){return{valid:!0,errors:[]}},apply(a,e){const t=a.params;e.timeline.subtitles=t.subtitles??[]},invert(a,e){return{type:"subtitle/setAll",id:`inverse-${a.id}`,timestamp:Date.now(),params:{subtitles:e.timeline.subtitles.map(t=>({...t}))}}}},oc={type:"adjustment/setAll",validate(){return{valid:!0,errors:[]}},apply(a,e){const t=a.params;e.adjustmentLayers=t.layers??[]},invert(a,e){const t=e.adjustmentLayers??[];return{type:"adjustment/setAll",id:`inverse-${a.id}`,timestamp:Date.now(),params:{layers:t.map(o=>({...o}))}}}},ic={type:"mask/setAll",validate(){return{valid:!0,errors:[]}},apply(a,e){const t=a.params;e.masks=t.masks??[],e.modifiedAt=Date.now()},invert(a,e){const t=e.masks??[];return{type:"mask/setAll",id:`inverse-${a.id}`,timestamp:Date.now(),params:{masks:t.map(o=>({...o}))}}}},rc={type:"multicam/setAll",validate(){return{valid:!0,errors:[]}},apply(a,e){const t=a.params;e.multicamGroups=t.groups??[]},invert(a,e){const t=e.multicamGroups??[];return{type:"multicam/setAll",id:`inverse-${a.id}`,timestamp:Date.now(),params:{groups:t.map(o=>({...o}))}}}},nc={type:"nested/setAll",validate(){return{valid:!0,errors:[]}},apply(a,e){const t=a.params,o=e;o.compoundClips=t.compoundClips??[],o.nestedInstances=t.instances??[]},invert(a,e){const t=e;return{type:"nested/setAll",id:`inverse-${a.id}`,timestamp:Date.now(),params:{compoundClips:(t.compoundClips??[]).map(o=>({...o})),instances:(t.nestedInstances??[]).map(o=>({...o}))}}}};for(const a of[Jl,Zl,ec,tc,ac,oc,ic,rc,nc])Dt(a);function Et(a,e){return a[e]??[]}function Zo(a,e,t){a[e]=t}function ei(){return{valid:!0,errors:[]}}function ti(a){return{valid:!1,errors:[{code:"INVALID_PARAMS",message:a}]}}function sc(a,e){const t={type:`${a}/create`,validate(r){const n=r.params.clip;return n&&typeof n.id=="string"?ei():ti(`${a}/create requires a clip with an id`)},apply(r,n){const s=r.params.clip;Zo(n,e,[...Et(n,e),s])},invert(r){const n=r.params.clip;return{type:`${a}/remove`,id:`inverse-${r.id}`,timestamp:Date.now(),params:{clipId:n.id}}}},o={type:`${a}/update`,validate(r,n){const s=r.params.clipId;return Et(n,e).some(l=>l.id===s)?ei():ti(`${a} clip not found: ${String(s)}`)},apply(r,n){const{clipId:s,updates:l}=r.params;Zo(n,e,Et(n,e).map(c=>c.id===s?{...c,...l}:c))},invert(r,n){const s=r.params.clipId,l=Et(n,e).find(c=>c.id===s);return l?{type:`${a}/update`,id:`inverse-${r.id}`,timestamp:Date.now(),params:{clipId:s,updates:{...l}}}:null}},i={type:`${a}/remove`,validate(r,n){const s=r.params.clipId;return Et(n,e).some(l=>l.id===s)?ei():ti(`${a} clip not found: ${String(s)}`)},apply(r,n){const s=r.params.clipId;Zo(n,e,Et(n,e).filter(l=>l.id!==s))},invert(r,n){const s=r.params.clipId,l=Et(n,e).find(c=>c.id===s);return l?{type:`${a}/create`,id:`inverse-${r.id}`,timestamp:Date.now(),params:{clip:{...l}}}:null}};return[t,o,i]}const lc=[{prefix:"text",field:"textClips"},{prefix:"shape",field:"shapeClips"},{prefix:"svg",field:"svgClips"},{prefix:"sticker",field:"stickerClips"}];for(const a of lc)for(const e of sc(a.prefix,a.field))Dt(e);const En={fill:{type:"solid",color:"#3b82f6",opacity:1},stroke:{color:"#1d4ed8",width:2,opacity:1}},Ir={position:{x:.5,y:.5},scale:{x:1,y:1},rotation:0,anchor:{x:.5,y:.5},opacity:1},wi={position:{x:960,y:540,z:0},scale:{x:1,y:1},rotation:0,rotation3d:{x:0,y:0},anchor:{x:.5,y:.5},opacity:1,perspective:1e3,transformStyle:"flat"},cc={position:{x:0,y:0},scale:{x:1,y:1},rotation:0,anchor:{x:.5,y:.5},opacity:1,fitMode:"contain"},Ln={fit:"contain",scale:1,rotation:0,offsetX:0,offsetY:0,originX:.5,originY:.5,worldWidth:0,worldHeight:0},uc={fit:"none",scale:1,rotation:0,offsetX:0,offsetY:0,originX:.5,originY:.5,worldWidth:0,worldHeight:0},fc={none:0,contain:1,cover:2},G=`
#define TWO_PI 6.28318530718
#define PI 3.14159265358979323846
`,ge=`
vec2 rotate(vec2 uv, float th) {
  return mat2(cos(th), sin(th), -sin(th), cos(th)) * uv;
}
`,$o=`
  float hash11(float p) {
    p = fract(p * 0.3183099) + 0.1;
    p *= p + 19.19;
    return fract(p * p);
  }
`,zt=`
  float hash21(vec2 p) {
    p = fract(p * vec2(0.3183099, 0.3678794)) + 0.1;
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
  }
`,Oa=`
  float randomR(vec2 p) {
    vec2 uv = floor(p) / 100. + .5;
    return texture(u_noiseTexture, fract(uv)).r;
  }
`,Zi=`
  vec2 randomGB(vec2 p) {
    vec2 uv = floor(p) / 100. + .5;
    return texture(u_noiseTexture, fract(uv)).gb;
  }
`,Ye=`
  color += 1. / 256. * (fract(sin(dot(.014 * gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453123) - .5);
`,Ft=`
vec3 permute(vec3 x) { return mod(((x * 34.0) + 1.0) * x, 289.0); }
float snoise(vec2 v) {
  const vec4 C = vec4(0.211324865405187, 0.366025403784439,
    -0.577350269189626, 0.024390243902439);
  vec2 i = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1;
  i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);
  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
    + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy),
      dot(x12.zw, x12.zw)), 0.0);
  m = m * m;
  m = m * m;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
  vec3 g;
  g.x = a0.x * x0.x + h.x * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}
`,pc=`
float fiberRandom(vec2 p) {
  vec2 uv = floor(p) / 100.;
  return texture(u_noiseTexture, fract(uv)).b;
}

float fiberValueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = fiberRandom(i);
  float b = fiberRandom(i + vec2(1.0, 0.0));
  float c = fiberRandom(i + vec2(0.0, 1.0));
  float d = fiberRandom(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

float fiberNoiseFbm(in vec2 n, vec2 seedOffset) {
  float total = 0.0, amplitude = 1.;
  for (int i = 0; i < 4; i++) {
    n = rotate(n, .7);
    total += fiberValueNoise(n + seedOffset) * amplitude;
    n *= 2.;
    amplitude *= 0.6;
  }
  return total;
}

float fiberNoise(vec2 uv, vec2 seedOffset) {
  float epsilon = 0.001;
  float n1 = fiberNoiseFbm(uv + vec2(epsilon, 0.0), seedOffset);
  float n2 = fiberNoiseFbm(uv - vec2(epsilon, 0.0), seedOffset);
  float n3 = fiberNoiseFbm(uv + vec2(0.0, epsilon), seedOffset);
  float n4 = fiberNoiseFbm(uv - vec2(0.0, epsilon), seedOffset);
  return length(vec2(n1 - n2, n3 - n4)) / (2.0 * epsilon);
}
`,Ar={maxColorCount:10},dc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform vec4 u_colors[${Ar.maxColorCount}];
uniform float u_colorsCount;

uniform float u_distortion;
uniform float u_swirl;
uniform float u_grainMixer;
uniform float u_grainOverlay;

in vec2 v_objectUV;
out vec4 fragColor;

${G}
${ge}
${zt}

float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

float noise(vec2 n, vec2 seedOffset) {
  return valueNoise(n + seedOffset);
}

vec2 getPosition(int i, float t) {
  float a = float(i) * .37;
  float b = .6 + fract(float(i) / 3.) * .9;
  float c = .8 + fract(float(i + 1) / 4.);

  float x = sin(t * b + a);
  float y = cos(t * c + a * 1.5);

  return .5 + .5 * vec2(x, y);
}

void main() {
  vec2 uv = v_objectUV;
  uv += .5;
  vec2 grainUV = uv * 1000.;

  float grain = noise(grainUV, vec2(0.));
  float mixerGrain = .4 * u_grainMixer * (grain - .5);

  const float firstFrameOffset = 41.5;
  float t = .5 * (u_time + firstFrameOffset);

  float radius = smoothstep(0., 1., length(uv - .5));
  float center = 1. - radius;
  for (float i = 1.; i <= 2.; i++) {
    uv.x += u_distortion * center / i * sin(t + i * .4 * smoothstep(.0, 1., uv.y)) * cos(.2 * t + i * 2.4 * smoothstep(.0, 1., uv.y));
    uv.y += u_distortion * center / i * cos(t + i * 2. * smoothstep(.0, 1., uv.x));
  }

  vec2 uvRotated = uv;
  uvRotated -= vec2(.5);
  float angle = 3. * u_swirl * radius;
  uvRotated = rotate(uvRotated, -angle);
  uvRotated += vec2(.5);

  vec3 color = vec3(0.);
  float opacity = 0.;
  float totalWeight = 0.;

  for (int i = 0; i < ${Ar.maxColorCount}; i++) {
    if (i >= int(u_colorsCount)) break;

    vec2 pos = getPosition(i, t) + mixerGrain;
    vec3 colorFraction = u_colors[i].rgb * u_colors[i].a;
    float opacityFraction = u_colors[i].a;

    float dist = length(uvRotated - pos);

    dist = pow(dist, 3.5);
    float weight = 1. / (dist + 1e-3);
    color += colorFraction * weight;
    opacity += opacityFraction * weight;
    totalWeight += weight;
  }

  color /= max(1e-4, totalWeight);
  opacity /= max(1e-4, totalWeight);

  float grainOverlay = valueNoise(rotate(grainUV, 1.) + vec2(3.));
  grainOverlay = mix(grainOverlay, valueNoise(rotate(grainUV, 2.) + vec2(-1.)), .5);
  grainOverlay = pow(grainOverlay, 1.3);

  float grainOverlayV = grainOverlay * 2. - 1.;
  vec3 grainOverlayColor = vec3(step(0., grainOverlayV));
  float grainOverlayStrength = u_grainOverlay * abs(grainOverlayV);
  grainOverlayStrength = pow(grainOverlayStrength, .8);
  color = mix(color, grainOverlayColor, .35 * grainOverlayStrength);

  opacity += .5 * grainOverlayStrength;
  opacity = clamp(opacity, 0., 1.);

  fragColor = vec4(color, opacity);
}
`,ai={maxColorCount:10,maxNoiseIterations:8},mc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform sampler2D u_noiseTexture;

uniform vec4 u_colorBack;
uniform vec4 u_colors[${ai.maxColorCount}];
uniform float u_colorsCount;

uniform float u_thickness;
uniform float u_radius;
uniform float u_innerShape;
uniform float u_noiseScale;
uniform float u_noiseIterations;

in vec2 v_objectUV;

out vec4 fragColor;

${G}
${Oa}
float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = randomR(i);
  float b = randomR(i + vec2(1.0, 0.0));
  float c = randomR(i + vec2(0.0, 1.0));
  float d = randomR(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}
vec2 fbm(vec2 n0, vec2 n1) {
  vec2 total = vec2(0.0);
  float amplitude = .4;
  for (int i = 0; i < ${ai.maxNoiseIterations}; i++) {
    if (i >= int(u_noiseIterations)) break;
    total.x += valueNoise(n0) * amplitude;
    total.y += valueNoise(n1) * amplitude;
    n0 *= 1.99;
    n1 *= 1.99;
    amplitude *= 0.65;
  }
  return total;
}

float getNoise(vec2 uv, vec2 pUv, float t) {
  vec2 pUvLeft = pUv + .03 * t;
  float period = max(abs(u_noiseScale * TWO_PI), 1e-6);
  vec2 pUvRight = vec2(fract(pUv.x / period) * period, pUv.y) + .03 * t;
  vec2 noise = fbm(pUvLeft, pUvRight);
  return mix(noise.y, noise.x, smoothstep(-.25, .25, uv.x));
}

float getRingShape(vec2 uv) {
  float radius = u_radius;
  float thickness = u_thickness;

  float distance = length(uv);
  float ringValue = 1. - smoothstep(radius, radius + thickness, distance);
  ringValue *= smoothstep(radius - pow(u_innerShape, 3.) * thickness, radius, distance);

  return ringValue;
}

void main() {
  vec2 shape_uv = v_objectUV;

  float t = u_time;

  float cycleDuration = 3.;
  float period2 = 2.0 * cycleDuration;
  float localTime1 = fract((0.1 * t + cycleDuration) / period2) * period2;
  float localTime2 = fract((0.1 * t) / period2) * period2;
  float timeBlend = .5 + .5 * sin(.1 * t * PI / cycleDuration - .5 * PI);

  float atg = atan(shape_uv.y, shape_uv.x) + .001;
  float l = length(shape_uv);
  float radialOffset = .5 * l - inversesqrt(max(1e-4, l));
  vec2 polar_uv1 = vec2(atg, localTime1 - radialOffset) * u_noiseScale;
  vec2 polar_uv2 = vec2(atg, localTime2 - radialOffset) * u_noiseScale;
  
  float noise1 = getNoise(shape_uv, polar_uv1, t);
  float noise2 = getNoise(shape_uv, polar_uv2, t);

  float noise = mix(noise1, noise2, timeBlend);

  shape_uv *= (.8 + 1.2 * noise);

  float ringShape = getRingShape(shape_uv);

  float mixer = ringShape * ringShape * (u_colorsCount - 1.);
  int idxLast = int(u_colorsCount) - 1;
  vec4 gradient = u_colors[idxLast];
  gradient.rgb *= gradient.a;
  for (int i = ${ai.maxColorCount} - 2; i >= 0; i--) {
    float localT = clamp(mixer - float(idxLast - i - 1), 0., 1.);
    vec4 c = u_colors[i];
    c.rgb *= c.a;
    gradient = mix(gradient, c, localT);
  }

  vec3 color = gradient.rgb * ringShape;
  float opacity = gradient.a * ringShape;

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1. - opacity);
  opacity = opacity + u_colorBack.a * (1. - opacity);

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,hc=`#version 300 es
precision mediump float;

uniform float u_time;
uniform vec2 u_resolution;
uniform float u_pixelRatio;

uniform vec4 u_colorFront;
uniform vec4 u_colorMid;
uniform vec4 u_colorBack;
uniform float u_brightness;
uniform float u_contrast;

in vec2 v_patternUV;

out vec4 fragColor;

${ge}

float neuroShape(vec2 uv, float t) {
  vec2 sine_acc = vec2(0.);
  vec2 res = vec2(0.);
  float scale = 8.;

  for (int j = 0; j < 15; j++) {
    uv = rotate(uv, 1.);
    sine_acc = rotate(sine_acc, 1.);
    vec2 layer = uv * scale + float(j) + sine_acc - t;
    sine_acc += sin(layer);
    res += (.5 + .5 * cos(layer)) / scale;
    scale *= (1.2);
  }
  return res.x + res.y;
}

void main() {
  vec2 shape_uv = v_patternUV;
  shape_uv *= .13;

  float t = .5 * u_time;

  float noise = neuroShape(shape_uv, t);

  noise = (1. + u_brightness) * noise * noise;
  noise = pow(noise, .7 + 6. * u_contrast);
  noise = min(1.4, noise);

  float blend = smoothstep(0.7, 1.4, noise);

  vec4 frontC = u_colorFront;
  frontC.rgb *= frontC.a;
  vec4 midC = u_colorMid;
  midC.rgb *= midC.a;
  vec4 blendFront = mix(midC, frontC, blend);

  float safeNoise = max(noise, 0.0);
  vec3 color = blendFront.rgb * safeNoise;
  float opacity = clamp(blendFront.a * safeNoise, 0., 1.);

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1. - opacity);
  opacity = opacity + u_colorBack.a * (1. - opacity);

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,Mr={maxColorCount:10},gc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform sampler2D u_noiseTexture;

uniform vec4 u_colorBack;
uniform vec4 u_colors[${Mr.maxColorCount}];
uniform float u_colorsCount;
uniform float u_stepsPerColor;
uniform float u_size;
uniform float u_sizeRange;
uniform float u_spreading;

in vec2 v_patternUV;

out vec4 fragColor;

${G}
${ge}
${Oa}
${Zi}


vec3 voronoiShape(vec2 uv, float time) {
  vec2 i_uv = floor(uv);
  vec2 f_uv = fract(uv);

  float spreading = .25 * clamp(u_spreading, 0., 1.);

  float minDist = 1.;
  vec2 randomizer = vec2(0.);
  for (int y = -1; y <= 1; y++) {
    for (int x = -1; x <= 1; x++) {
      vec2 tileOffset = vec2(float(x), float(y));
      vec2 rand = randomGB(i_uv + tileOffset);
      vec2 cellCenter = vec2(.5 + 1e-4);
      cellCenter += spreading * cos(time + TWO_PI * rand);
      cellCenter -= .5;
      cellCenter = rotate(cellCenter, randomR(vec2(rand.x, rand.y)) + .1 * time);
      cellCenter += .5;
      float dist = length(tileOffset + cellCenter - f_uv);
      if (dist < minDist) {
        minDist = dist;
        randomizer = rand;
      }
    }
  }

  return vec3(minDist, randomizer);
}

void main() {

  vec2 shape_uv = v_patternUV;
  shape_uv *= 1.5;

  const float firstFrameOffset = -10.;
  float t = u_time + firstFrameOffset;

  vec3 voronoi = voronoiShape(shape_uv, t) + 1e-4;

  float radius = .25 * clamp(u_size, 0., 1.) - .5 * clamp(u_sizeRange, 0., 1.) * voronoi[2];
  float dist = voronoi[0];
  float edgeWidth = fwidth(dist);
  float dots = 1. - smoothstep(radius - edgeWidth, radius + edgeWidth, dist);

  float shape = voronoi[1];

  float mixer = shape * (u_colorsCount - 1.);
  mixer = (shape - .5 / u_colorsCount) * u_colorsCount;
  float steps = max(1., u_stepsPerColor);

  vec4 gradient = u_colors[0];
  gradient.rgb *= gradient.a;
  for (int i = 1; i < ${Mr.maxColorCount}; i++) {
    if (i >= int(u_colorsCount)) break;
    float localT = clamp(mixer - float(i - 1), 0.0, 1.0);
    localT = round(localT * steps) / steps;
    vec4 c = u_colors[i];
    c.rgb *= c.a;
    gradient = mix(gradient, c, localT);
  }

  if ((mixer < 0.) || (mixer > (u_colorsCount - 1.))) {
    float localT = mixer + 1.;
    if (mixer > (u_colorsCount - 1.)) {
      localT = mixer - (u_colorsCount - 1.);
    }
    localT = round(localT * steps) / steps;
    vec4 cFst = u_colors[0];
    cFst.rgb *= cFst.a;
    vec4 cLast = u_colors[int(u_colorsCount - 1.)];
    cLast.rgb *= cLast.a;
    gradient = mix(cLast, cFst, localT);
  }

  vec3 color = gradient.rgb * dots;
  float opacity = gradient.a * dots;

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1. - opacity);
  opacity = opacity + u_colorBack.a * (1. - opacity);

  fragColor = vec4(color, opacity);
}
`,vc=`#version 300 es
precision mediump float;

uniform vec4 u_colorBack;
uniform vec4 u_colorFill;
uniform vec4 u_colorStroke;
uniform float u_dotSize;
uniform float u_gapX;
uniform float u_gapY;
uniform float u_strokeWidth;
uniform float u_sizeRange;
uniform float u_opacityRange;
uniform float u_shape;

in vec2 v_patternUV;

out vec4 fragColor;

${G}
${Ft}

float polygon(vec2 p, float N, float rot) {
  float a = atan(p.x, p.y) + rot;
  float r = TWO_PI / float(N);

  return cos(floor(.5 + a / r) * r - a) * length(p);
}

void main() {

  // x100 is a default multiplier between vertex and fragmant shaders
  // we use it to avoid UV presision issues
  vec2 shape_uv = 100. * v_patternUV;

  vec2 gap = max(abs(vec2(u_gapX, u_gapY)), vec2(1e-6));
  vec2 grid = fract(shape_uv / gap) + 1e-4;
  vec2 grid_idx = floor(shape_uv / gap);
  float sizeRandomizer = .5 + .8 * snoise(2. * vec2(grid_idx.x * 100., grid_idx.y));
  float opacity_randomizer = .5 + .7 * snoise(2. * vec2(grid_idx.y, grid_idx.x));

  vec2 center = vec2(0.5) - 1e-3;
  vec2 p = (grid - center) * vec2(u_gapX, u_gapY);

  float baseSize = u_dotSize * (1. - sizeRandomizer * u_sizeRange);
  float strokeWidth = u_strokeWidth * (1. - sizeRandomizer * u_sizeRange);

  float dist;
  if (u_shape < 0.5) {
    // Circle
    dist = length(p);
  } else if (u_shape < 1.5) {
    // Diamond
    strokeWidth *= 1.5;
    dist = polygon(1.5 * p, 4., .25 * PI);
  } else if (u_shape < 2.5) {
    // Square
    dist = polygon(1.03 * p, 4., 1e-3);
  } else {
    // Triangle
    strokeWidth *= 1.5;
    p = p * 2. - 1.;
    p *= .9;
    p.y = 1. - p.y;
    p.y -= .75 * baseSize;
    dist = polygon(p, 3., 1e-3);
  }

  float edgeWidth = fwidth(dist);
  float shapeOuter = 1. - smoothstep(baseSize - edgeWidth, baseSize + edgeWidth, dist - strokeWidth);
  float shapeInner = 1. - smoothstep(baseSize - edgeWidth, baseSize + edgeWidth, dist);
  float stroke = shapeOuter - shapeInner;

  float dotOpacity = max(0., 1. - opacity_randomizer * u_opacityRange);
  stroke *= dotOpacity;
  shapeInner *= dotOpacity;

  stroke *= u_colorStroke.a;
  shapeInner *= u_colorFill.a;

  vec3 color = vec3(0.);
  color += stroke * u_colorStroke.rgb;
  color += shapeInner * u_colorFill.rgb;
  color += (1. - shapeInner - stroke) * u_colorBack.rgb * u_colorBack.a;

  float opacity = 0.;
  opacity += stroke;
  opacity += shapeInner;
  opacity += (1. - opacity) * u_colorBack.a;

  fragColor = vec4(color, opacity);
}
`,Br={maxColorCount:10},yc=`#version 300 es
precision mediump float;

uniform float u_time;
uniform float u_scale;

uniform vec4 u_colors[${Br.maxColorCount}];
uniform float u_colorsCount;
uniform float u_stepsPerColor;
uniform float u_softness;

in vec2 v_patternUV;

out vec4 fragColor;

${Ft}

float getNoise(vec2 uv, float t) {
  float noise = .5 * snoise(uv - vec2(0., .3 * t));
  noise += .5 * snoise(2. * uv + vec2(0., .32 * t));

  return noise;
}

float steppedSmooth(float m, float steps, float softness) {
  float stepT = floor(m * steps) / steps;
  float f = m * steps - floor(m * steps);
  float fw = steps * fwidth(m);
  float smoothed = smoothstep(.5 - softness, min(1., .5 + softness + fw), f);
  return stepT + smoothed / steps;
}

void main() {
  vec2 shape_uv = v_patternUV;
  shape_uv *= .1;

  float t = .2 * u_time;

  float shape = .5 + .5 * getNoise(shape_uv, t);

  bool u_extraSides = true;

  float mixer = shape * (u_colorsCount - 1.);
  if (u_extraSides == true) {
    mixer = (shape - .5 / u_colorsCount) * u_colorsCount;
  }

  float steps = max(1., u_stepsPerColor);

  vec4 gradient = u_colors[0];
  gradient.rgb *= gradient.a;
  for (int i = 1; i < ${Br.maxColorCount}; i++) {
    if (i >= int(u_colorsCount)) break;

    float localM = clamp(mixer - float(i - 1), 0., 1.);
    localM = steppedSmooth(localM, steps, .5 * u_softness);

    vec4 c = u_colors[i];
    c.rgb *= c.a;
    gradient = mix(gradient, c, localM);
  }

  if (u_extraSides == true) {
    if ((mixer < 0.) || (mixer > (u_colorsCount - 1.))) {
      float localM = mixer + 1.;
      if (mixer > (u_colorsCount - 1.)) {
        localM = mixer - (u_colorsCount - 1.);
      }
      localM = steppedSmooth(localM, steps, .5 * u_softness);
      vec4 cFst = u_colors[0];
      cFst.rgb *= cFst.a;
      vec4 cLast = u_colors[int(u_colorsCount - 1.)];
      cLast.rgb *= cLast.a;
      gradient = mix(cLast, cFst, localM);
    }
  }

  vec3 color = gradient.rgb;
  float opacity = gradient.a;

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,oi={maxColorCount:8,maxBallsCount:20},_c=`#version 300 es
precision mediump float;

uniform float u_time;

uniform sampler2D u_noiseTexture;

uniform vec4 u_colorBack;
uniform vec4 u_colors[${oi.maxColorCount}];
uniform float u_colorsCount;
uniform float u_size;
uniform float u_sizeRange;
uniform float u_count;

in vec2 v_objectUV;

out vec4 fragColor;

${G}
${Oa}
float noise(float x) {
  float i = floor(x);
  float f = fract(x);
  float u = f * f * (3.0 - 2.0 * f);
  vec2 p0 = vec2(i, 0.0);
  vec2 p1 = vec2(i + 1.0, 0.0);
  return mix(randomR(p0), randomR(p1), u);
}

float getBallShape(vec2 uv, vec2 c, float p) {
  float s = .5 * length(uv - c);
  s = 1. - clamp(s, 0., 1.);
  s = pow(s, p);
  return s;
}

void main() {
  vec2 shape_uv = v_objectUV;

  shape_uv += .5;

  const float firstFrameOffset = 2503.4;
  float t = .2 * (u_time + firstFrameOffset);

  vec3 totalColor = vec3(0.);
  float totalShape = 0.;
  float totalOpacity = 0.;

  for (int i = 0; i < ${oi.maxBallsCount}; i++) {
    if (i >= int(ceil(u_count))) break;

    float idxFract = float(i) / float(${oi.maxBallsCount});
    float angle = TWO_PI * idxFract;

    float speed = 1. - .2 * idxFract;
    float noiseX = noise(angle * 10. + float(i) + t * speed);
    float noiseY = noise(angle * 20. + float(i) - t * speed);

    vec2 pos = vec2(.5) + 1e-4 + .9 * (vec2(noiseX, noiseY) - .5);

    int safeIndex = i % int(u_colorsCount + 0.5);
    vec4 ballColor = u_colors[safeIndex];
    ballColor.rgb *= ballColor.a;

    float sizeFrac = 1.;
    if (float(i) > floor(u_count - 1.)) {
      sizeFrac *= fract(u_count);
    }

    float shape = getBallShape(shape_uv, pos, 45. - 30. * u_size * sizeFrac);
    shape *= pow(u_size, .2);
    shape = smoothstep(0., 1., shape);

    totalColor += ballColor.rgb * shape;
    totalShape += shape;
    totalOpacity += ballColor.a * shape;
  }

  totalColor /= max(totalShape, 1e-4);
  totalOpacity /= max(totalShape, 1e-4);

  float edge_width = fwidth(totalShape);
  float finalShape = smoothstep(.4, .4 + edge_width, totalShape);

  vec3 color = totalColor * finalShape;
  float opacity = totalOpacity * finalShape;

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1. - opacity);
  opacity = opacity + u_colorBack.a * (1. - opacity);

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,xc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform vec4 u_colorFront;
uniform vec4 u_colorBack;
uniform float u_proportion;
uniform float u_softness;
uniform float u_octaveCount;
uniform float u_persistence;
uniform float u_lacunarity;

in vec2 v_patternUV;

out vec4 fragColor;

${G}
${$o}
${zt}

float hash31(vec3 p) {
  p = fract(p * 0.3183099) + 0.1;
  p += dot(p, p.yzx + 19.19);
  return fract(p.x * (p.y + p.z));
}

vec3 gradientPredefined(float hash) {
  int idx = int(hash * 12.0) % 12;

  if (idx == 0) return vec3(1, 1, 0);
  if (idx == 1) return vec3(-1, 1, 0);
  if (idx == 2) return vec3(1, -1, 0);
  if (idx == 3) return vec3(-1, -1, 0);
  if (idx == 4) return vec3(1, 0, 1);
  if (idx == 5) return vec3(-1, 0, 1);
  if (idx == 6) return vec3(1, 0, -1);
  if (idx == 7) return vec3(-1, 0, -1);
  if (idx == 8) return vec3(0, 1, 1);
  if (idx == 9) return vec3(0, -1, 1);
  if (idx == 10) return vec3(0, 1, -1);
  return vec3(0, -1, -1);// idx == 11
}

float interpolateSafe(float v000, float v001, float v010, float v011,
float v100, float v101, float v110, float v111, vec3 t) {
  t = clamp(t, 0.0, 1.0);

  float v00 = mix(v000, v100, t.x);
  float v01 = mix(v001, v101, t.x);
  float v10 = mix(v010, v110, t.x);
  float v11 = mix(v011, v111, t.x);

  float v0 = mix(v00, v10, t.y);
  float v1 = mix(v01, v11, t.y);

  return mix(v0, v1, t.z);
}

vec3 fade(vec3 t) {
  return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}

float perlinNoise(vec3 position, float seed) {
  position += vec3(seed * 127.1, seed * 311.7, seed * 74.7);

  vec3 i = floor(position);
  vec3 f = fract(position);
  float h000 = hash31(i);
  float h001 = hash31(i + vec3(0, 0, 1));
  float h010 = hash31(i + vec3(0, 1, 0));
  float h011 = hash31(i + vec3(0, 1, 1));
  float h100 = hash31(i + vec3(1, 0, 0));
  float h101 = hash31(i + vec3(1, 0, 1));
  float h110 = hash31(i + vec3(1, 1, 0));
  float h111 = hash31(i + vec3(1, 1, 1));
  vec3 g000 = gradientPredefined(h000);
  vec3 g001 = gradientPredefined(h001);
  vec3 g010 = gradientPredefined(h010);
  vec3 g011 = gradientPredefined(h011);
  vec3 g100 = gradientPredefined(h100);
  vec3 g101 = gradientPredefined(h101);
  vec3 g110 = gradientPredefined(h110);
  vec3 g111 = gradientPredefined(h111);
  float v000 = dot(g000, f - vec3(0, 0, 0));
  float v001 = dot(g001, f - vec3(0, 0, 1));
  float v010 = dot(g010, f - vec3(0, 1, 0));
  float v011 = dot(g011, f - vec3(0, 1, 1));
  float v100 = dot(g100, f - vec3(1, 0, 0));
  float v101 = dot(g101, f - vec3(1, 0, 1));
  float v110 = dot(g110, f - vec3(1, 1, 0));
  float v111 = dot(g111, f - vec3(1, 1, 1));

  vec3 u = fade(f);
  return interpolateSafe(v000, v001, v010, v011, v100, v101, v110, v111, u);
}

float p_noise(vec3 position, int octaveCount, float persistence, float lacunarity) {
  float value = 0.0;
  float amplitude = 1.0;
  float frequency = 10.0;
  float maxValue = 0.0;
  octaveCount = clamp(octaveCount, 1, 8);

  for (int i = 0; i < octaveCount; i++) {
    float seed = float(i) * 0.7319;
    value += perlinNoise(position * frequency, seed) * amplitude;
    maxValue += amplitude;
    amplitude *= persistence;
    frequency *= lacunarity;
  }
  return value;
}

float get_max_amp(float persistence, float octaveCount) {
  persistence = clamp(persistence * 0.999, 0.0, 0.999);
  octaveCount = clamp(octaveCount, 1.0, 8.0);

  if (abs(persistence - 1.0) < 0.001) {
    return octaveCount;
  }

  return (1.0 - pow(persistence, octaveCount)) / max(1e-4, (1.0 - persistence));
}

void main() {
  vec2 uv = v_patternUV;
  uv *= .5;

  float t = .2 * u_time;

  vec3 p = vec3(uv, t);

  float octCount = floor(u_octaveCount);
  float noise = p_noise(p, int(octCount), u_persistence, u_lacunarity);

  float max_amp = get_max_amp(u_persistence, octCount);
  float noise_normalized = clamp((noise + max_amp) / max(1e-4, (2. * max_amp)) + (u_proportion - .5), 0.0, 1.0);
  float sharpness = clamp(u_softness, 0., 1.);
  float smooth_w = 0.5 * max(fwidth(noise_normalized), 0.001);
  float res = smoothstep(
  .5 - .5 * sharpness - smooth_w,
  .5 + .5 * sharpness + smooth_w,
  noise_normalized
  );

  vec3 fgColor = u_colorFront.rgb * u_colorFront.a;
  float fgOpacity = u_colorFront.a;
  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  float bgOpacity = u_colorBack.a;

  vec3 color = fgColor * res;
  float opacity = fgOpacity * res;

  color += bgColor * (1. - opacity);
  opacity += bgOpacity * (1. - opacity);

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,Vr={maxColorCount:5},bc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform float u_scale;

uniform sampler2D u_noiseTexture;

uniform vec4 u_colors[${Vr.maxColorCount}];
uniform float u_colorsCount;

uniform float u_stepsPerColor;
uniform vec4 u_colorGlow;
uniform vec4 u_colorGap;
uniform float u_distortion;
uniform float u_gap;
uniform float u_glow;

in vec2 v_patternUV;

out vec4 fragColor;

${G}
${Zi}

vec4 voronoi(vec2 x, float t) {
  vec2 ip = floor(x);
  vec2 fp = fract(x);

  vec2 mg, mr;
  float md = 8.;
  float rand = 0.;

  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      vec2 g = vec2(float(i), float(j));
      vec2 o = randomGB(ip + g);
      float raw_hash = o.x;
      o = .5 + u_distortion * sin(t + TWO_PI * o);
      vec2 r = g + o - fp;
      float d = dot(r, r);

      if (d < md) {
        md = d;
        mr = r;
        mg = g;
        rand = raw_hash;
      }
    }
  }

  md = 8.;
  for (int j = -2; j <= 2; j++) {
    for (int i = -2; i <= 2; i++) {
      vec2 g = mg + vec2(float(i), float(j));
      vec2 o = randomGB(ip + g);
      o = .5 + u_distortion * sin(t + TWO_PI * o);
      vec2 r = g + o - fp;
      if (dot(mr - r, mr - r) > .00001) {
        md = min(md, dot(.5 * (mr + r), normalize(r - mr)));
      }
    }
  }

  return vec4(md, mr, rand);
}

void main() {
  vec2 shape_uv = v_patternUV;
  shape_uv *= 1.25;

  float t = u_time;

  vec4 voronoiRes = voronoi(shape_uv, t);

  float shape = clamp(voronoiRes.w, 0., 1.);
  float mixer = shape * (u_colorsCount - 1.);
  mixer = (shape - .5 / u_colorsCount) * u_colorsCount;
  float steps = max(1., u_stepsPerColor);

  vec4 gradient = u_colors[0];
  gradient.rgb *= gradient.a;
  for (int i = 1; i < ${Vr.maxColorCount}; i++) {
    if (i >= int(u_colorsCount)) break;
    float localT = clamp(mixer - float(i - 1), 0.0, 1.0);
    localT = round(localT * steps) / steps;
    vec4 c = u_colors[i];
    c.rgb *= c.a;
    gradient = mix(gradient, c, localT);
  }

  if ((mixer < 0.) || (mixer > (u_colorsCount - 1.))) {
    float localT = mixer + 1.;
    if (mixer > (u_colorsCount - 1.)) {
      localT = mixer - (u_colorsCount - 1.);
    }
    localT = round(localT * steps) / steps;
    vec4 cFst = u_colors[0];
    cFst.rgb *= cFst.a;
    vec4 cLast = u_colors[int(u_colorsCount - 1.)];
    cLast.rgb *= cLast.a;
    gradient = mix(cLast, cFst, localT);
  }

  vec3 cellColor = gradient.rgb;
  float cellOpacity = gradient.a;

  float glows = length(voronoiRes.yz * u_glow);
  glows = pow(glows, 1.5);

  vec3 color = mix(cellColor, u_colorGlow.rgb * u_colorGlow.a, u_colorGlow.a * glows);
  float opacity = cellOpacity + u_colorGlow.a * glows;

  float edge = voronoiRes.x;
  float smoothEdge = .02 / (2. * u_scale) * (1. + .5 * u_gap);
  edge = smoothstep(u_gap - smoothEdge, u_gap + smoothEdge, edge);

  color = mix(u_colorGap.rgb * u_colorGap.a, color, edge);
  opacity = mix(u_colorGap.a, opacity, edge);

  fragColor = vec4(color, opacity);
}
`,wc=`#version 300 es
precision mediump float;

uniform vec4 u_colorFront;
uniform vec4 u_colorBack;
uniform float u_shape;
uniform float u_frequency;
uniform float u_amplitude;
uniform float u_spacing;
uniform float u_proportion;
uniform float u_softness;

in vec2 v_patternUV;

out vec4 fragColor;

${G}

void main() {
  vec2 shape_uv = v_patternUV;
  shape_uv *= 4.;

  float wave = .5 * cos(shape_uv.x * u_frequency * TWO_PI);
  float zigzag = 2. * abs(fract(shape_uv.x * u_frequency) - .5);
  float irregular = sin(shape_uv.x * .25 * u_frequency * TWO_PI) * cos(shape_uv.x * u_frequency * TWO_PI);
  float irregular2 = .75 * (sin(shape_uv.x * u_frequency * TWO_PI) + .5 * cos(shape_uv.x * .5 * u_frequency * TWO_PI));

  float offset = mix(zigzag, wave, smoothstep(0., 1., u_shape));
  offset = mix(offset, irregular, smoothstep(1., 2., u_shape));
  offset = mix(offset, irregular2, smoothstep(2., 3., u_shape));
  offset *= 2. * u_amplitude;

  float spacing = (.001 + u_spacing);
  float shape = .5 + .5 * sin((shape_uv.y + offset) * PI / spacing);

  float aa = .0001 + fwidth(shape);
  float dc = 1. - clamp(u_proportion, 0., 1.);
  float e0 = dc - u_softness - aa;
  float e1 = dc + u_softness + aa;
  float res = smoothstep(min(e0, e1), max(e0, e1), shape);

  vec3 fgColor = u_colorFront.rgb * u_colorFront.a;
  float fgOpacity = u_colorFront.a;
  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  float bgOpacity = u_colorBack.a;

  vec3 color = fgColor * res;
  float opacity = fgOpacity * res;

  color += bgColor * (1. - opacity);
  opacity += bgOpacity * (1. - opacity);

  fragColor = vec4(color, opacity);
}
`,Rr={maxColorCount:10},Sc=`#version 300 es
precision mediump float;

uniform float u_time;
uniform float u_scale;

uniform sampler2D u_noiseTexture;

uniform vec4 u_colors[${Rr.maxColorCount}];
uniform float u_colorsCount;
uniform float u_proportion;
uniform float u_softness;
uniform float u_shape;
uniform float u_shapeScale;
uniform float u_distortion;
uniform float u_swirl;
uniform float u_swirlIterations;

in vec2 v_patternUV;

out vec4 fragColor;

${G}
${ge}
float randomG(vec2 p) {
  vec2 uv = floor(p) / 100. + .5;
  return texture(u_noiseTexture, fract(uv)).g;
}
float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = randomG(i);
  float b = randomG(i + vec2(1.0, 0.0));
  float c = randomG(i + vec2(0.0, 1.0));
  float d = randomG(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}


void main() {
  vec2 uv = v_patternUV;
  uv *= .5;

  const float firstFrameOffset = 118.;
  float t = 0.0625 * (u_time + firstFrameOffset);

  float n1 = valueNoise(uv * 1. + t);
  float n2 = valueNoise(uv * 2. - t);
  float angle = n1 * TWO_PI;
  uv.x += 4. * u_distortion * n2 * cos(angle);
  uv.y += 4. * u_distortion * n2 * sin(angle);

  float swirl = u_swirl;
  for (int i = 1; i <= 20; i++) {
    if (i >= int(u_swirlIterations)) break;
    float iFloat = float(i);
    //    swirl *= (1. - smoothstep(.0, .25, length(fwidth(uv))));
    uv.x += swirl / iFloat * cos(t + iFloat * 1.5 * uv.y);
    uv.y += swirl / iFloat * cos(t + iFloat * 1. * uv.x);
  }

  float proportion = clamp(u_proportion, 0., 1.);

  float shape = 0.;
  if (u_shape < .5) {
    vec2 checksShape_uv = uv * (.5 + 3.5 * u_shapeScale);
    shape = .5 + .5 * sin(checksShape_uv.x) * cos(checksShape_uv.y);
    shape += .48 * sign(proportion - .5) * pow(abs(proportion - .5), .5);
  } else if (u_shape < 1.5) {
    vec2 stripesShape_uv = uv * (2. * u_shapeScale);
    float f = fract(stripesShape_uv.y);
    shape = smoothstep(.0, .55, f) * (1.0 - smoothstep(.45, 1., f));
    shape += .48 * sign(proportion - .5) * pow(abs(proportion - .5), .5);
  } else {
    float shapeScaling = 5. * (1. - u_shapeScale);
    float e0 = 0.45 - shapeScaling;
    float e1 = 0.55 + shapeScaling;
    shape = smoothstep(min(e0, e1), max(e0, e1), 1.0 - uv.y + 0.3 * (proportion - 0.5));
  }

  float mixer = shape * (u_colorsCount - 1.);
  vec4 gradient = u_colors[0];
  gradient.rgb *= gradient.a;
  float aa = fwidth(shape);
  for (int i = 1; i < ${Rr.maxColorCount}; i++) {
    if (i >= int(u_colorsCount)) break;
    float m = clamp(mixer - float(i - 1), 0.0, 1.0);

    float localMixerStart = floor(m);
    float softness = .5 * u_softness + fwidth(m);
    float smoothed = smoothstep(max(0., .5 - softness - aa), min(1., .5 + softness + aa), m - localMixerStart);
    float stepped = localMixerStart + smoothed;

    m = mix(stepped, m, u_softness);

    vec4 c = u_colors[i];
    c.rgb *= c.a;
    gradient = mix(gradient, c, m);
  }

  vec3 color = gradient.rgb;
  float opacity = gradient.a;

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,Pr={maxColorCount:5},kc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform sampler2D u_noiseTexture;

uniform vec4 u_colorBack;
uniform vec4 u_colorBloom;
uniform vec4 u_colors[${Pr.maxColorCount}];
uniform float u_colorsCount;

uniform float u_density;
uniform float u_spotty;
uniform float u_midSize;
uniform float u_midIntensity;
uniform float u_intensity;
uniform float u_bloom;

in vec2 v_objectUV;

out vec4 fragColor;

${G}
${ge}
${Oa}
float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = randomR(i);
  float b = randomR(i + vec2(1.0, 0.0));
  float c = randomR(i + vec2(0.0, 1.0));
  float d = randomR(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

${$o}

float raysShape(vec2 uv, float r, float freq, float intensity, float radius) {
  float a = atan(uv.y, uv.x);
  vec2 left = vec2(a * freq, r);
  vec2 right = vec2(fract(a / TWO_PI) * TWO_PI * freq, r);
  float n_left = pow(valueNoise(left), intensity);
  float n_right = pow(valueNoise(right), intensity);
  float shape = mix(n_right, n_left, smoothstep(-.15, .15, uv.x));
  return shape;
}

void main() {
  vec2 shape_uv = v_objectUV;

  float t = .2 * u_time;

  float radius = length(shape_uv);
  float spots = 6.5 * abs(u_spotty);

  float intensity = 4. - 3. * clamp(u_intensity, 0., 1.);

  float delta = 1. - smoothstep(0., 1., radius);

  float midSize = 10. * abs(u_midSize);
  float ms_lo = 0.02 * midSize;
  float ms_hi = max(midSize, 1e-6);
  float middleShape = pow(u_midIntensity, 0.3) * (1. - smoothstep(ms_lo, ms_hi, 3.0 * radius));
  middleShape = pow(middleShape, 5.0);

  vec3 accumColor = vec3(0.0);
  float accumAlpha = 0.0;

  for (int i = 0; i < ${Pr.maxColorCount}; i++) {
    if (i >= int(u_colorsCount)) break;

    vec2 rotatedUV = rotate(shape_uv, float(i) + 1.0);

    float r1 = radius * (1.0 + 0.4 * float(i)) - 3.0 * t;
    float r2 = 0.5 * radius * (1.0 + spots) - 2.0 * t;
    float density = 6. * u_density + step(.5, u_density) * pow(4.5 * (u_density - .5), 4.);
    float f = mix(1.0, 3.0 + 0.5 * float(i), hash11(float(i) * 15.)) * density;

    float ray = raysShape(rotatedUV, r1, 5.0 * f, intensity, radius);
    ray *= raysShape(rotatedUV, r2, 4.0 * f, intensity, radius);
    ray += (1. + 4. * ray) * middleShape;
    ray = clamp(ray, 0.0, 1.0);

    float srcAlpha = u_colors[i].a * ray;
    vec3 srcColor = u_colors[i].rgb * srcAlpha;

    vec3 alphaBlendColor = accumColor + (1.0 - accumAlpha) * srcColor;
    float alphaBlendAlpha = accumAlpha + (1.0 - accumAlpha) * srcAlpha;

    vec3 addBlendColor = accumColor + srcColor;
    float addBlendAlpha = accumAlpha + srcAlpha;

    accumColor = mix(alphaBlendColor, addBlendColor, u_bloom);
    accumAlpha = mix(alphaBlendAlpha, addBlendAlpha, u_bloom);
  }

  float overlayAlpha = u_colorBloom.a;
  vec3 overlayColor = u_colorBloom.rgb * overlayAlpha;

  vec3 colorWithOverlay = accumColor + accumAlpha * overlayColor;
  accumColor = mix(accumColor, colorWithOverlay, u_bloom);

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;

  vec3 color = accumColor + (1. - accumAlpha) * bgColor;
  float opacity = accumAlpha + (1. - accumAlpha) * u_colorBack.a;
  color = clamp(color, 0., 1.);
  opacity = clamp(opacity, 0., 1.);

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,Cc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform vec4 u_colorBack;
uniform vec4 u_colorFront;
uniform float u_density;
uniform float u_distortion;
uniform float u_strokeWidth;
uniform float u_strokeCap;
uniform float u_strokeTaper;
uniform float u_noise;
uniform float u_noiseFrequency;
uniform float u_softness;

in vec2 v_patternUV;

out vec4 fragColor;

${G}
${Ft}

void main() {
  vec2 uv = 2. * v_patternUV;

  float t = u_time;
  float l = length(uv);
  float density = clamp(u_density, 0., 1.);
  l = pow(max(l, 1e-6), density);
  float angle = atan(uv.y, uv.x) - t;
  float angleNormalised = angle / TWO_PI;

  angleNormalised += .125 * u_noise * snoise(16. * pow(u_noiseFrequency, 3.) * uv);

  float offset = l + angleNormalised;
  offset -= u_distortion * (sin(4. * l - .5 * t) * cos(PI + l + .5 * t));
  float stripe = fract(offset);

  float shape = 2. * abs(stripe - .5);
  float width = 1. - clamp(u_strokeWidth, .005 * u_strokeTaper, 1.);


  float wCap = mix(width, (1. - stripe) * (1. - step(.5, stripe)), (1. - clamp(l, 0., 1.)));
  width = mix(width, wCap, u_strokeCap);
  width *= (1. - clamp(u_strokeTaper, 0., 1.) * l);

  float fw = fwidth(offset);
  float fwMult = 4. - 3. * (smoothstep(.05, .4, 2. * u_strokeWidth) * smoothstep(.05, .4, 2. * (1. - u_strokeWidth)));
  float pixelSize = mix(fwMult * fw, fwidth(shape), clamp(fw, 0., 1.));
  pixelSize = mix(pixelSize, .002, u_strokeCap * (1. - clamp(l, 0., 1.)));

  float res = smoothstep(width - pixelSize - u_softness, width + pixelSize + u_softness, shape);

  vec3 fgColor = u_colorFront.rgb * u_colorFront.a;
  float fgOpacity = u_colorFront.a;
  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  float bgOpacity = u_colorBack.a;

  vec3 color = fgColor * res;
  float opacity = fgOpacity * res;

  color += bgColor * (1. - opacity);
  opacity += bgOpacity * (1. - opacity);

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,Dr={maxColorCount:10},Oc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform vec4 u_colorBack;
uniform vec4 u_colors[${Dr.maxColorCount}];
uniform float u_colorsCount;
uniform float u_bandCount;
uniform float u_twist;
uniform float u_center;
uniform float u_proportion;
uniform float u_softness;
uniform float u_noise;
uniform float u_noiseFrequency;

in vec2 v_objectUV;

out vec4 fragColor;

${G}
${Ft}
${ge}

void main() {
  vec2 shape_uv = v_objectUV;

  float l = length(shape_uv);
  l = max(1e-4, l);

  float t = u_time;

  float angle = ceil(u_bandCount) * atan(shape_uv.y, shape_uv.x) + t;
  float angle_norm = angle / TWO_PI;

  float twist = 3. * clamp(u_twist, 0., 1.);
  float offset = pow(l, -twist) + angle_norm;

  float shape = fract(offset);
  shape = 1. - abs(2. * shape - 1.);
  shape += u_noise * snoise(15. * pow(u_noiseFrequency, 2.) * shape_uv);

  float mid = smoothstep(.2, .2 + .8 * u_center, pow(l, twist));
  shape = mix(0., shape, mid);

  float proportion = clamp(u_proportion, 0., 1.);
  float exponent = mix(.25, 1., proportion * 2.);
  exponent = mix(exponent, 10., max(0., proportion * 2. - 1.));
  shape = pow(shape, exponent);

  float mixer = shape * u_colorsCount;
  vec4 gradient = u_colors[0];
  gradient.rgb *= gradient.a;

  float outerShape = 0.;
  for (int i = 1; i < ${Dr.maxColorCount+1}; i++) {
    if (i > int(u_colorsCount)) break;

    float m = clamp(mixer - float(i - 1), 0., 1.);
    float aa = fwidth(m);
    m = smoothstep(.5 - .5 * u_softness - aa, .5 + .5 * u_softness + aa, m);

    if (i == 1) {
      outerShape = m;
    }

    vec4 c = u_colors[i - 1];
    c.rgb *= c.a;
    gradient = mix(gradient, c, m);
  }

  float midAA = .1 * fwidth(pow(l, -twist));
  float outerMid = smoothstep(.2, .2 + midAA, pow(l, twist));
  outerShape = mix(0., outerShape, outerMid);

  vec3 color = gradient.rgb * outerShape;
  float opacity = gradient.a * outerShape;

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1.0 - opacity);
  opacity = opacity + u_colorBack.a * (1.0 - opacity);

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,Tc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform vec2 u_resolution;
uniform float u_pixelRatio;
uniform float u_originX;
uniform float u_originY;
uniform float u_worldWidth;
uniform float u_worldHeight;
uniform float u_fit;
uniform float u_scale;
uniform float u_rotation;
uniform float u_offsetX;
uniform float u_offsetY;

uniform float u_pxSize;
uniform vec4 u_colorBack;
uniform vec4 u_colorFront;
uniform float u_shape;
uniform float u_type;

out vec4 fragColor;

${Ft}
${G}
${$o}
${zt}

float getSimplexNoise(vec2 uv, float t) {
  float noise = .5 * snoise(uv - vec2(0., .3 * t));
  noise += .5 * snoise(2. * uv + vec2(0., .32 * t));

  return noise;
}

const int bayer2x2[4] = int[4](0, 2, 3, 1);
const int bayer4x4[16] = int[16](
0, 8, 2, 10,
12, 4, 14, 6,
3, 11, 1, 9,
15, 7, 13, 5
);

const int bayer8x8[64] = int[64](
0, 32, 8, 40, 2, 34, 10, 42,
48, 16, 56, 24, 50, 18, 58, 26,
12, 44, 4, 36, 14, 46, 6, 38,
60, 28, 52, 20, 62, 30, 54, 22,
3, 35, 11, 43, 1, 33, 9, 41,
51, 19, 59, 27, 49, 17, 57, 25,
15, 47, 7, 39, 13, 45, 5, 37,
63, 31, 55, 23, 61, 29, 53, 21
);

float getBayerValue(vec2 uv, int size) {
  ivec2 pos = ivec2(fract(uv / float(size)) * float(size));
  int index = pos.y * size + pos.x;

  if (size == 2) {
    return float(bayer2x2[index]) / 4.0;
  } else if (size == 4) {
    return float(bayer4x4[index]) / 16.0;
  } else if (size == 8) {
    return float(bayer8x8[index]) / 64.0;
  }
  return 0.0;
}


void main() {
  float t = .5 * u_time;

  float pxSize = u_pxSize * u_pixelRatio;
  vec2 pxSizeUV = gl_FragCoord.xy - .5 * u_resolution;
  pxSizeUV /= pxSize;
  vec2 canvasPixelizedUV = (floor(pxSizeUV) + .5) * pxSize;
  vec2 normalizedUV = canvasPixelizedUV / u_resolution;

  vec2 ditheringNoiseUV = canvasPixelizedUV;
  vec2 shapeUV = normalizedUV;

  vec2 boxOrigin = vec2(.5 - u_originX, u_originY - .5);
  vec2 givenBoxSize = vec2(u_worldWidth, u_worldHeight);
  givenBoxSize = max(givenBoxSize, vec2(1.)) * u_pixelRatio;
  float r = u_rotation * PI / 180.;
  mat2 graphicRotation = mat2(cos(r), sin(r), -sin(r), cos(r));
  vec2 graphicOffset = vec2(-u_offsetX, u_offsetY);

  float patternBoxRatio = givenBoxSize.x / givenBoxSize.y;
  vec2 boxSize = vec2(
  (u_worldWidth == 0.) ? u_resolution.x : givenBoxSize.x,
  (u_worldHeight == 0.) ? u_resolution.y : givenBoxSize.y
  );
  
  if (u_shape > 3.5) {
    vec2 objectBoxSize = vec2(0.);
    // fit = none
    objectBoxSize.x = min(boxSize.x, boxSize.y);
    if (u_fit == 1.) { // fit = contain
      objectBoxSize.x = min(u_resolution.x, u_resolution.y);
    } else if (u_fit == 2.) { // fit = cover
      objectBoxSize.x = max(u_resolution.x, u_resolution.y);
    }
    objectBoxSize.y = objectBoxSize.x;
    vec2 objectWorldScale = u_resolution.xy / objectBoxSize;

    shapeUV *= objectWorldScale;
    shapeUV += boxOrigin * (objectWorldScale - 1.);
    shapeUV += vec2(-u_offsetX, u_offsetY);
    shapeUV /= u_scale;
    shapeUV = graphicRotation * shapeUV;
  } else {
    vec2 patternBoxSize = vec2(0.);
    // fit = none
    patternBoxSize.x = patternBoxRatio * min(boxSize.x / patternBoxRatio, boxSize.y);
    float patternWorldNoFitBoxWidth = patternBoxSize.x;
    if (u_fit == 1.) { // fit = contain
      patternBoxSize.x = patternBoxRatio * min(u_resolution.x / patternBoxRatio, u_resolution.y);
    } else if (u_fit == 2.) { // fit = cover
      patternBoxSize.x = patternBoxRatio * max(u_resolution.x / patternBoxRatio, u_resolution.y);
    }
    patternBoxSize.y = patternBoxSize.x / patternBoxRatio;
    vec2 patternWorldScale = u_resolution.xy / patternBoxSize;

    shapeUV += vec2(-u_offsetX, u_offsetY) / patternWorldScale;
    shapeUV += boxOrigin;
    shapeUV -= boxOrigin / patternWorldScale;
    shapeUV *= u_resolution.xy;
    shapeUV /= u_pixelRatio;
    if (u_fit > 0.) {
      shapeUV *= (patternWorldNoFitBoxWidth / patternBoxSize.x);
    }
    shapeUV /= u_scale;
    shapeUV = graphicRotation * shapeUV;
    shapeUV += boxOrigin / patternWorldScale;
    shapeUV -= boxOrigin;
    shapeUV += .5;
  }

  float shape = 0.;
  if (u_shape < 1.5) {
    // Simplex noise
    shapeUV *= .001;

    shape = 0.5 + 0.5 * getSimplexNoise(shapeUV, t);
    shape = smoothstep(0.3, 0.9, shape);

  } else if (u_shape < 2.5) {
    // Warp
    shapeUV *= .003;

    for (float i = 1.0; i < 6.0; i++) {
      shapeUV.x += 0.6 / i * cos(i * 2.5 * shapeUV.y + t);
      shapeUV.y += 0.6 / i * cos(i * 1.5 * shapeUV.x + t);
    }

    shape = .15 / max(0.001, abs(sin(t - shapeUV.y - shapeUV.x)));
    shape = smoothstep(0.02, 1., shape);

  } else if (u_shape < 3.5) {
    // Dots
    shapeUV *= .05;

    float stripeIdx = floor(2. * shapeUV.x / TWO_PI);
    float rand = hash11(stripeIdx * 10.);
    rand = sign(rand - .5) * pow(.1 + abs(rand), .4);
    shape = sin(shapeUV.x) * cos(shapeUV.y - 5. * rand * t);
    shape = pow(abs(shape), 6.);

  } else if (u_shape < 4.5) {
    // Sine wave
    shapeUV *= 4.;

    float wave = cos(.5 * shapeUV.x - 2. * t) * sin(1.5 * shapeUV.x + t) * (.75 + .25 * cos(3. * t));
    shape = 1. - smoothstep(-1., 1., shapeUV.y + wave);

  } else if (u_shape < 5.5) {
    // Ripple

    float dist = length(shapeUV);
    float waves = sin(pow(dist, 1.7) * 7. - 3. * t) * .5 + .5;
    shape = waves;

  } else if (u_shape < 6.5) {
    // Swirl

    float l = length(shapeUV);
    float angle = 6. * atan(shapeUV.y, shapeUV.x) + 4. * t;
    float twist = 1.2;
    float offset = 1. / pow(max(l, 1e-6), twist) + angle / TWO_PI;
    float mid = smoothstep(0., 1., pow(l, twist));
    shape = mix(0., fract(offset), mid);

  } else {
    // Sphere
    shapeUV *= 2.;

    float d = 1. - pow(length(shapeUV), 2.);
    vec3 pos = vec3(shapeUV, sqrt(max(0., d)));
    vec3 lightPos = normalize(vec3(cos(1.5 * t), .8, sin(1.25 * t)));
    shape = .5 + .5 * dot(lightPos, pos);
    shape *= step(0., d);
  }


  int type = int(floor(u_type));
  float dithering = 0.0;

  switch (type) {
    case 1: {
      dithering = step(hash21(ditheringNoiseUV), shape);
    } break;
    case 2:
    dithering = getBayerValue(pxSizeUV, 2);
    break;
    case 3:
    dithering = getBayerValue(pxSizeUV, 4);
    break;
    default :
    dithering = getBayerValue(pxSizeUV, 8);
    break;
  }

  dithering -= .5;
  float res = step(.5, shape + dithering);

  vec3 fgColor = u_colorFront.rgb * u_colorFront.a;
  float fgOpacity = u_colorFront.a;
  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  float bgOpacity = u_colorBack.a;

  vec3 color = fgColor * res;
  float opacity = fgOpacity * res;

  color += bgColor * (1. - opacity);
  opacity += bgOpacity * (1. - opacity);

  fragColor = vec4(color, opacity);
}
`,zr={maxColorCount:7},Uc=`#version 300 es
precision lowp float;

uniform mediump float u_time;
uniform mediump vec2 u_resolution;
uniform mediump float u_pixelRatio;

uniform sampler2D u_noiseTexture;

uniform vec4 u_colorBack;
uniform vec4 u_colors[${zr.maxColorCount}];
uniform float u_colorsCount;
uniform float u_softness;
uniform float u_intensity;
uniform float u_noise;
uniform float u_shape;

uniform mediump float u_originX;
uniform mediump float u_originY;
uniform mediump float u_worldWidth;
uniform mediump float u_worldHeight;
uniform mediump float u_fit;

uniform mediump float u_scale;
uniform mediump float u_rotation;
uniform mediump float u_offsetX;
uniform mediump float u_offsetY;

in vec2 v_objectUV;
in vec2 v_patternUV;
in vec2 v_objectBoxSize;
in vec2 v_patternBoxSize;

out vec4 fragColor;

${G}
${Ft}
${ge}
${Oa}

float valueNoiseR(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = randomR(i);
  float b = randomR(i + vec2(1.0, 0.0));
  float c = randomR(i + vec2(0.0, 1.0));
  float d = randomR(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}
vec4 fbmR(vec2 n0, vec2 n1, vec2 n2, vec2 n3) {
  float amplitude = 0.2;
  vec4 total = vec4(0.);
  for (int i = 0; i < 3; i++) {
    n0 = rotate(n0, 0.3);
    n1 = rotate(n1, 0.3);
    n2 = rotate(n2, 0.3);
    n3 = rotate(n3, 0.3);
    total.x += valueNoiseR(n0) * amplitude;
    total.y += valueNoiseR(n1) * amplitude;
    total.z += valueNoiseR(n2) * amplitude;
    total.z += valueNoiseR(n3) * amplitude;
    n0 *= 1.99;
    n1 *= 1.99;
    n2 *= 1.99;
    n3 *= 1.99;
    amplitude *= 0.6;
  }
  return total;
}

${$o}

vec2 truchet(vec2 uv, float idx){
  idx = fract(((idx - .5) * 2.));
  if (idx > 0.75) {
    uv = vec2(1.0) - uv;
  } else if (idx > 0.5) {
    uv = vec2(1.0 - uv.x, uv.y);
  } else if (idx > 0.25) {
    uv = 1.0 - vec2(1.0 - uv.x, uv.y);
  }
  return uv;
}

void main() {

  const float firstFrameOffset = 7.;
  float t = .1 * (u_time + firstFrameOffset);

  vec2 shape_uv = vec2(0.);
  vec2 grain_uv = vec2(0.);

  float r = u_rotation * PI / 180.;
  float cr = cos(r);
  float sr = sin(r);
  mat2 graphicRotation = mat2(cr, sr, -sr, cr);
  vec2 graphicOffset = vec2(-u_offsetX, u_offsetY);

  if (u_shape > 3.5) {
    shape_uv = v_objectUV;
    grain_uv = shape_uv;

    // apply inverse transform to grain_uv so it respects the originXY
    grain_uv = transpose(graphicRotation) * grain_uv;
    grain_uv *= u_scale;
    grain_uv -= graphicOffset;
    grain_uv *= v_objectBoxSize;
    grain_uv *= .7;
  } else {
    shape_uv = .5 * v_patternUV;
    grain_uv = 100. * v_patternUV;

    // apply inverse transform to grain_uv so it respects the originXY
    grain_uv = transpose(graphicRotation) * grain_uv;
    grain_uv *= u_scale;
    if (u_fit > 0.) {
      vec2 givenBoxSize = vec2(u_worldWidth, u_worldHeight);
      givenBoxSize = max(givenBoxSize, vec2(1.)) * u_pixelRatio;
      float patternBoxRatio = givenBoxSize.x / givenBoxSize.y;
      vec2 patternBoxGivenSize = vec2(
      (u_worldWidth == 0.) ? u_resolution.x : givenBoxSize.x,
      (u_worldHeight == 0.) ? u_resolution.y : givenBoxSize.y
      );
      patternBoxRatio = patternBoxGivenSize.x / patternBoxGivenSize.y;
      float patternBoxNoFitBoxWidth = patternBoxRatio * min(patternBoxGivenSize.x / patternBoxRatio, patternBoxGivenSize.y);
      grain_uv /= (patternBoxNoFitBoxWidth / v_patternBoxSize.x);
    }
    vec2 patternBoxScale = u_resolution.xy / v_patternBoxSize;
    grain_uv -= graphicOffset / patternBoxScale;
    grain_uv *= 1.6;
  }


  float shape = 0.;

  if (u_shape < 1.5) {
    // Sine wave

    float wave = cos(.5 * shape_uv.x - 4. * t) * sin(1.5 * shape_uv.x + 2. * t) * (.75 + .25 * cos(6. * t));
    shape = 1. - smoothstep(-1., 1., shape_uv.y + wave);

  } else if (u_shape < 2.5) {
    // Grid (dots)

    float stripeIdx = floor(2. * shape_uv.x / TWO_PI);
    float rand = hash11(stripeIdx * 100.);
    rand = sign(rand - .5) * pow(4. * abs(rand), .3);
    shape = sin(shape_uv.x) * cos(shape_uv.y - 5. * rand * t);
    shape = pow(abs(shape), 4.);

  } else if (u_shape < 3.5) {
    // Truchet pattern

    float n2 = valueNoiseR(shape_uv * .4 - 3.75 * t);
    shape_uv.x += 10.;
    shape_uv *= .6;

    vec2 tile = truchet(fract(shape_uv), randomR(floor(shape_uv)));

    float distance1 = length(tile);
    float distance2 = length(tile - vec2(1.));

    n2 -= .5;
    n2 *= .1;
    shape = smoothstep(.2, .55, distance1 + n2) * (1. - smoothstep(.45, .8, distance1 - n2));
    shape += smoothstep(.2, .55, distance2 + n2) * (1. - smoothstep(.45, .8, distance2 - n2));

    shape = pow(shape, 1.5);

  } else if (u_shape < 4.5) {
    // Corners

    shape_uv *= .6;
    vec2 outer = vec2(.5);

    vec2 bl = smoothstep(vec2(0.), outer, shape_uv + vec2(.1 + .1 * sin(3. * t), .2 - .1 * sin(5.25 * t)));
    vec2 tr = smoothstep(vec2(0.), outer, 1. - shape_uv);
    shape = 1. - bl.x * bl.y * tr.x * tr.y;

    shape_uv = -shape_uv;
    bl = smoothstep(vec2(0.), outer, shape_uv + vec2(.1 + .1 * sin(3. * t), .2 - .1 * cos(5.25 * t)));
    tr = smoothstep(vec2(0.), outer, 1. - shape_uv);
    shape -= bl.x * bl.y * tr.x * tr.y;

    shape = 1. - smoothstep(0., 1., shape);

  } else if (u_shape < 5.5) {
    // Ripple

    shape_uv *= 2.;
    float dist = length(.4 * shape_uv);
    float waves = sin(pow(dist, 1.2) * 5. - 3. * t) * .5 + .5;
    shape = waves;

  } else if (u_shape < 6.5) {
    // Blob

    t *= 2.;

    vec2 f1_traj = .25 * vec2(1.3 * sin(t), .2 + 1.3 * cos(.6 * t + 4.));
    vec2 f2_traj = .2 * vec2(1.2 * sin(-t), 1.3 * sin(1.6 * t));
    vec2 f3_traj = .25 * vec2(1.7 * cos(-.6 * t), cos(-1.6 * t));
    vec2 f4_traj = .3 * vec2(1.4 * cos(.8 * t), 1.2 * sin(-.6 * t - 3.));

    shape = .5 * pow(1. - clamp(0., 1., length(shape_uv + f1_traj)), 5.);
    shape += .5 * pow(1. - clamp(0., 1., length(shape_uv + f2_traj)), 5.);
    shape += .5 * pow(1. - clamp(0., 1., length(shape_uv + f3_traj)), 5.);
    shape += .5 * pow(1. - clamp(0., 1., length(shape_uv + f4_traj)), 5.);

    shape = smoothstep(.0, .9, shape);
    float edge = smoothstep(.25, .3, shape);
    shape = mix(.0, shape, edge);

  } else {
    // Sphere

    shape_uv *= 2.;
    float d = 1. - pow(length(shape_uv), 2.);
    vec3 pos = vec3(shape_uv, sqrt(max(d, 0.)));
    vec3 lightPos = normalize(vec3(cos(1.5 * t), .8, sin(1.25 * t)));
    shape = .5 + .5 * dot(lightPos, pos);
    shape *= step(0., d);
  }

  float baseNoise = snoise(grain_uv * .5);
  vec4 fbmVals = fbmR(
  .002 * grain_uv + 10.,
  .003 * grain_uv,
  .001 * grain_uv,
  rotate(.4 * grain_uv, 2.)
  );
  float grainDist = baseNoise * snoise(grain_uv * .2) - fbmVals.x - fbmVals.y;
  float rawNoise = .75 * baseNoise - fbmVals.w - fbmVals.z;
  float noise = clamp(rawNoise, 0., 1.);

  shape += u_intensity * 2. / u_colorsCount * (grainDist + .5);
  shape += u_noise * 10. / u_colorsCount * noise;

  float aa = fwidth(shape);

  shape = clamp(shape - .5 / u_colorsCount, 0., 1.);
  float totalShape = smoothstep(0., u_softness + 2. * aa, clamp(shape * u_colorsCount, 0., 1.));
  float mixer = shape * (u_colorsCount - 1.);

  int cntStop = int(u_colorsCount) - 1;
  vec4 gradient = u_colors[0];
  gradient.rgb *= gradient.a;
  for (int i = 1; i < ${zr.maxColorCount}; i++) {
    if (i > cntStop) break;

    float localT = clamp(mixer - float(i - 1), 0., 1.);
    localT = smoothstep(.5 - .5 * u_softness - aa, .5 + .5 * u_softness + aa, localT);

    vec4 c = u_colors[i];
    c.rgb *= c.a;
    gradient = mix(gradient, c, localT);
  }

  vec3 color = gradient.rgb * totalShape;
  float opacity = gradient.a * totalShape;

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1.0 - opacity);
  opacity = opacity + u_colorBack.a * (1.0 - opacity);

  fragColor = vec4(color, opacity);
}
`,ii={maxColorCount:5,maxSpots:4},Ic=`#version 300 es
precision lowp float;

uniform float u_time;

uniform vec4 u_colorBack;
uniform vec4 u_colors[${ii.maxColorCount}];
uniform float u_colorsCount;
uniform float u_roundness;
uniform float u_thickness;
uniform float u_marginLeft;
uniform float u_marginRight;
uniform float u_marginTop;
uniform float u_marginBottom;
uniform float u_aspectRatio;
uniform float u_softness;
uniform float u_intensity;
uniform float u_bloom;
uniform float u_spotSize;
uniform float u_spots;
uniform float u_pulse;
uniform float u_smoke;
uniform float u_smokeSize;

uniform sampler2D u_noiseTexture;

in vec2 v_responsiveUV;
in vec2 v_responsiveBoxGivenSize;
in vec2 v_patternUV;

out vec4 fragColor;

${G}

float beat(float time) {
  float first = pow(abs(sin(time * TWO_PI)), 10.);
  float second = pow(abs(sin((time - .15) * TWO_PI)), 10.);

  return clamp(first + 0.6 * second, 0.0, 1.0);
}

float sst(float edge0, float edge1, float x) {
  return smoothstep(edge0, edge1, x);
}

float roundedBox(vec2 uv, vec2 halfSize, float distance, float cornerDistance, float thickness, float softness) {
  float borderDistance = abs(distance);
  float aa = 2. * fwidth(distance);
  float border = 1. - sst(min(mix(thickness, -thickness, softness), thickness + aa), max(mix(thickness, -thickness, softness), thickness + aa), borderDistance);
  float cornerFadeCircles = 0.;
  cornerFadeCircles = mix(1., cornerFadeCircles, sst(0., 1., length((uv + halfSize) / thickness)));
  cornerFadeCircles = mix(1., cornerFadeCircles, sst(0., 1., length((uv - vec2(-halfSize.x, halfSize.y)) / thickness)));
  cornerFadeCircles = mix(1., cornerFadeCircles, sst(0., 1., length((uv - vec2(halfSize.x, -halfSize.y)) / thickness)));
  cornerFadeCircles = mix(1., cornerFadeCircles, sst(0., 1., length((uv - halfSize) / thickness)));
  aa = fwidth(cornerDistance);
  float cornerFade = sst(0., mix(aa, thickness, softness), cornerDistance);
  cornerFade *= cornerFadeCircles;
  border += cornerFade;
  return border;
}

${Zi}

float randomG(vec2 p) {
  vec2 uv = floor(p) / 100. + .5;
  return texture(u_noiseTexture, fract(uv)).g;
}
float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = randomG(i);
  float b = randomG(i + vec2(1.0, 0.0));
  float c = randomG(i + vec2(0.0, 1.0));
  float d = randomG(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

void main() {
  const float firstFrameOffset = 109.;
  float t = 1.2 * (u_time + firstFrameOffset);

  vec2 borderUV = v_responsiveUV;
  float pulse = u_pulse * beat(.18 * u_time);

  float canvasRatio = v_responsiveBoxGivenSize.x / v_responsiveBoxGivenSize.y;
  vec2 halfSize = vec2(.5);
  borderUV.x *= max(canvasRatio, 1.);
  borderUV.y /= min(canvasRatio, 1.);
  halfSize.x *= max(canvasRatio, 1.);
  halfSize.y /= min(canvasRatio, 1.);

  float mL = u_marginLeft;
  float mR = u_marginRight;
  float mT = u_marginTop;
  float mB = u_marginBottom;
  float mX = mL + mR;
  float mY = mT + mB;

  if (u_aspectRatio > 0.) {
    float shapeRatio = canvasRatio * (1. - mX) / max(1. - mY, 1e-6);
    float freeX = shapeRatio > 1. ? (1. - mX) * (1. - 1. / max(abs(shapeRatio), 1e-6)) : 0.;
    float freeY = shapeRatio < 1. ? (1. - mY) * (1. - shapeRatio) : 0.;
    mL += freeX * 0.5;
    mR += freeX * 0.5;
    mT += freeY * 0.5;
    mB += freeY * 0.5;
    mX = mL + mR;
    mY = mT + mB;
  }

  float thickness = .5 * u_thickness * min(halfSize.x, halfSize.y);

  halfSize.x *= (1. - mX);
  halfSize.y *= (1. - mY);

  vec2 centerShift = vec2(
  (mL - mR) * max(canvasRatio, 1.) * 0.5,
  (mB - mT) / min(canvasRatio, 1.) * 0.5
  );

  borderUV -= centerShift;
  halfSize -= mix(thickness, 0., u_softness);

  float radius = mix(0., min(halfSize.x, halfSize.y), u_roundness);
  vec2 d = abs(borderUV) - halfSize + radius;
  float outsideDistance = length(max(d, .0001)) - radius;
  float insideDistance = min(max(d.x, d.y), .0001);
  float cornerDistance = abs(min(max(d.x, d.y) - .45 * radius, .0));
  float distance = outsideDistance + insideDistance;

  float borderThickness = mix(thickness, 3. * thickness, u_softness);
  float border = roundedBox(borderUV, halfSize, distance, cornerDistance, borderThickness, u_softness);
  border = pow(border, 1. + u_softness);

  vec2 smokeUV = .3 * u_smokeSize * v_patternUV;
  float smoke = clamp(3. * valueNoise(2.7 * smokeUV + .5 * t), 0., 1.);
  smoke -= valueNoise(3.4 * smokeUV - .5 * t);
  float smokeThickness = thickness + .2;
  smokeThickness = min(.4, max(smokeThickness, .1));
  smoke *= roundedBox(borderUV, halfSize, distance, cornerDistance, smokeThickness, 1.);
  smoke = 30. * smoke * smoke;
  smoke *= mix(0., .5, pow(u_smoke, 2.));
  smoke *= mix(1., pulse, u_pulse);
  smoke = clamp(smoke, 0., 1.);
  border += smoke;

  border = clamp(border, 0., 1.);

  vec3 blendColor = vec3(0.);
  float blendAlpha = 0.;
  vec3 addColor = vec3(0.);
  float addAlpha = 0.;

  float bloom = 4. * u_bloom;
  float intensity = 1. + (1. + 4. * u_softness) * u_intensity;

  float angle = atan(borderUV.y, borderUV.x) / TWO_PI;

  for (int colorIdx = 0; colorIdx < ${ii.maxColorCount}; colorIdx++) {
    if (colorIdx >= int(u_colorsCount)) break;
    float colorIdxF = float(colorIdx);

    vec3 c = u_colors[colorIdx].rgb * u_colors[colorIdx].a;
    float a = u_colors[colorIdx].a;

    for (int spotIdx = 0; spotIdx < ${ii.maxSpots}; spotIdx++) {
      if (spotIdx >= int(u_spots)) break;
      float spotIdxF = float(spotIdx);

      vec2 randVal = randomGB(vec2(spotIdxF * 10. + 2., 40. + colorIdxF));

      float time = (.1 + .15 * abs(sin(spotIdxF * (2. + colorIdxF)) * cos(spotIdxF * (2. + 2.5 * colorIdxF)))) * t + randVal.x * 3.;
      time *= mix(1., -1., step(.5, randVal.y));

      float mask = .5 + .5 * mix(
      sin(t + spotIdxF * (5. - 1.5 * colorIdxF)),
      cos(t + spotIdxF * (3. + 1.3 * colorIdxF)),
      step(mod(colorIdxF, 2.), .5)
      );

      float p = clamp(2. * u_pulse - randVal.x, 0., 1.);
      mask = mix(mask, pulse, p);

      float atg1 = fract(angle + time);
      float spotSize = .05 + .6 * pow(u_spotSize, 2.) + .05 * randVal.x;
      spotSize = mix(spotSize, .1, p);
      float sector = sst(.5 - spotSize, .5, atg1) * (1. - sst(.5, .5 + spotSize, atg1));

      sector *= mask;
      sector *= border;
      sector *= intensity;
      sector = clamp(sector, 0., 1.);

      vec3 srcColor = c * sector;
      float srcAlpha = a * sector;

      blendColor += ((1. - blendAlpha) * srcColor);
      blendAlpha = blendAlpha + (1. - blendAlpha) * srcAlpha;
      addColor += srcColor;
      addAlpha += srcAlpha;
    }
  }

  vec3 accumColor = mix(blendColor, addColor, bloom);
  float accumAlpha = mix(blendAlpha, addAlpha, bloom);
  accumAlpha = clamp(accumAlpha, 0., 1.);

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  vec3 color = accumColor + (1. - accumAlpha) * bgColor;
  float opacity = accumAlpha + (1. - accumAlpha) * u_colorBack.a;

  ${Ye}

  fragColor = vec4(color, opacity);
}`,ri={maxColorCount:7},Ac=`#version 300 es
precision lowp float;

uniform float u_time;
uniform mediump float u_scale;

uniform vec4 u_colors[${ri.maxColorCount}];
uniform float u_colorsCount;
uniform vec4 u_colorBack;
uniform float u_density;
uniform float u_angle1;
uniform float u_angle2;
uniform float u_length;
uniform bool u_edges;
uniform float u_blur;
uniform float u_fadeIn;
uniform float u_fadeOut;
uniform float u_gradient;

in vec2 v_objectUV;

out vec4 fragColor;

${G}

const float zLimit = .5;

vec2 getPanel(float angle, vec2 uv, float invLength, float aa) {
  float sinA = sin(angle);
  float cosA = cos(angle);

  float denom = sinA - uv.y * cosA;
  if (abs(denom) < .01) return vec2(0.);

  float z = uv.y / denom;

  if (z <= 0. || z > zLimit) return vec2(0.);

  float zRatio = z / zLimit;
  float panelMap = 1. - zRatio;
  float x = uv.x * (cosA * z + 1.) * invLength;

  float zOffset = zRatio - .5;
  float left = -.5 + zOffset * u_angle1;
  float right = .5 - zOffset * u_angle2;
  float blurX = aa + 2. * panelMap * u_blur;

  float leftEdge1 = left - blurX;
  float leftEdge2 = left + .25 * blurX;
  float rightEdge1 = right - .25 * blurX;
  float rightEdge2 = right + blurX;

  float panel = smoothstep(leftEdge1, leftEdge2, x) * (1.0 - smoothstep(rightEdge1, rightEdge2, x));
  panel *= mix(0., panel, smoothstep(0., .01 / max(u_scale, 1e-6), panelMap));

  float midScreen = abs(sinA);
  if (u_edges == true) {
    panelMap = mix(.99, panelMap, panel * clamp(panelMap / (.15 * (1. - pow(midScreen, .1))), 0.0, 1.0));
  } else if (midScreen < .07) {
    panel *= (midScreen * 15.);
  }

  return vec2(panel, panelMap);
}

vec4 blendColor(vec4 colorA, float panelMask, float panelMap) {
  float fade = 1. - smoothstep(.97 - .97 * u_fadeIn, 1., panelMap);

  fade *= smoothstep(-.2 * (1. - u_fadeOut), u_fadeOut, panelMap);

  vec3 blendedRGB = mix(vec3(0.), colorA.rgb, fade);
  float blendedAlpha = mix(0., colorA.a, fade);

  return vec4(blendedRGB, blendedAlpha) * panelMask;
}

void main() {
  vec2 uv = v_objectUV;
  uv *= 1.25;

  float t = .02 * u_time;
  t = fract(t);
  bool reverseTime = (t < 0.5);

  vec3 color = vec3(0.);
  float opacity = 0.;

  float aa = .005 / u_scale;
  int colorsCount = int(u_colorsCount);

  vec4 premultipliedColors[${ri.maxColorCount}];
  for (int i = 0; i < ${ri.maxColorCount}; i++) {
    if (i >= colorsCount) break;
    vec4 c = u_colors[i];
    c.rgb *= c.a;
    premultipliedColors[i] = c;
  }

  float invLength = 1.5 / max(u_length, .001);

  float totalColorWeight = 0.;
  int panelsNumber = 12;

  float densityNormalizer = 1.;
  if (colorsCount == 4) {
    panelsNumber = 16;
    densityNormalizer = 1.34;
  } else if (colorsCount == 5) {
    panelsNumber = 20;
    densityNormalizer = 1.67;
  } else if (colorsCount == 7) {
    panelsNumber = 14;
    densityNormalizer = 1.17;
  }

  float fPanelsNumber = float(panelsNumber);

  float totalPanelsShape = 0.;
  float panelGrad = 1. - clamp(u_gradient, 0., 1.);

  for (int set = 0; set < 2; set++) {
    bool isForward = (set == 0 && !reverseTime) || (set == 1 && reverseTime);
    if (!isForward) continue;

    for (int i = 0; i <= 20; i++) {
      if (i >= panelsNumber) break;

      int idx = panelsNumber - 1 - i;

      float offset = float(idx) / fPanelsNumber;
      if (set == 1) {
        offset += .5;
      }

      float densityFract = densityNormalizer * fract(t + offset);
      float angleNorm = densityFract / u_density;
      if (densityFract >= .5 || angleNorm >= .3) continue;

      float smoothDensity = clamp((.5 - densityFract) / .1, 0., 1.) * clamp(densityFract / .01, 0., 1.);
      float smoothAngle = clamp((.3 - angleNorm) / .05, 0., 1.);
      if (smoothDensity * smoothAngle < .001) continue;

      if (angleNorm > .5) {
        angleNorm = 0.5;
      }
      vec2 panel = getPanel(angleNorm * TWO_PI + PI, uv, invLength, aa);
      if (panel[0] <= .001) continue;
      float panelMask = panel[0] * smoothDensity * smoothAngle;
      float panelMap = panel[1];

      int colorIdx = idx % colorsCount;
      int nextColorIdx = (idx + 1) % colorsCount;

      vec4 colorA = premultipliedColors[colorIdx];
      vec4 colorB = premultipliedColors[nextColorIdx];

      colorA = mix(colorA, colorB, max(0., smoothstep(.0, .45, panelMap) - panelGrad));
      vec4 blended = blendColor(colorA, panelMask, panelMap);
      color = blended.rgb + color * (1. - blended.a);
      opacity = blended.a + opacity * (1. - blended.a);
    }


    for (int i = 0; i <= 20; i++) {
      if (i >= panelsNumber) break;

      int idx = panelsNumber - 1 - i;

      float offset = float(idx) / fPanelsNumber;
      if (set == 0) {
        offset += .5;
      }

      float densityFract = densityNormalizer * fract(-t + offset);
      float angleNorm = -densityFract / u_density;
      if (densityFract >= .5 || angleNorm < -.3) continue;

      float smoothDensity = clamp((.5 - densityFract) / .1, 0., 1.) * clamp(densityFract / .01, 0., 1.);
      float smoothAngle = clamp((angleNorm + .3) / .05, 0., 1.);
      if (smoothDensity * smoothAngle < .001) continue;

      vec2 panel = getPanel(angleNorm * TWO_PI + PI, uv, invLength, aa);
      float panelMask = panel[0] * smoothDensity * smoothAngle;
      if (panelMask <= .001) continue;
      float panelMap = panel[1];

      int colorIdx = (colorsCount - (idx % colorsCount)) % colorsCount;
      if (colorIdx < 0) colorIdx += colorsCount;
      int nextColorIdx = (colorIdx + 1) % colorsCount;

      vec4 colorA = premultipliedColors[colorIdx];
      vec4 colorB = premultipliedColors[nextColorIdx];

      colorA = mix(colorA, colorB, max(0., smoothstep(.0, .45, panelMap) - panelGrad));
      vec4 blended = blendColor(colorA, panelMask, panelMap);
      color = blended.rgb + color * (1. - blended.a);
      opacity = blended.a + opacity * (1. - blended.a);
    }
  }

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1.0 - opacity);
  opacity = opacity + u_colorBack.a * (1.0 - opacity);

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,Fr={maxColorCount:10},Mc=`#version 300 es
precision mediump float;

uniform vec4 u_colors[${Fr.maxColorCount}];
uniform float u_colorsCount;

uniform float u_positions;
uniform float u_waveX;
uniform float u_waveXShift;
uniform float u_waveY;
uniform float u_waveYShift;
uniform float u_mixing;
uniform float u_grainMixer;
uniform float u_grainOverlay;

in vec2 v_objectUV;
out vec4 fragColor;

${G}
${ge}
${zt}

float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

float noise(vec2 n, vec2 seedOffset) {
  return valueNoise(n + seedOffset);
}

vec2 getPosition(int i, float t) {
  float a = float(i) * .37;
  float b = .6 + mod(float(i), 3.) * .3;
  float c = .8 + mod(float(i + 1), 4.) * 0.25;

  float x = sin(t * b + a);
  float y = cos(t * c + a * 1.5);

  return .5 + .5 * vec2(x, y);
}

void main() {
  vec2 uv = v_objectUV;
  uv += .5;
  vec2 grainUV = uv * 1000.;

  float grain = noise(grainUV, vec2(0.));
  float mixerGrain = .4 * u_grainMixer * (grain - .5);

  float radius = smoothstep(0., 1., length(uv - .5));
  float center = 1. - radius;
  for (float i = 1.; i <= 2.; i++) {
    uv.x += u_waveX * center / i * cos(TWO_PI * u_waveXShift + i * 2. * smoothstep(.0, 1., uv.y));
    uv.y += u_waveY * center / i * cos(TWO_PI * u_waveYShift + i * 2. * smoothstep(.0, 1., uv.x));
  }

  vec3 color = vec3(0.);
  float opacity = 0.;
  float totalWeight = 0.;
  float positionSeed = 25. + .33 * u_positions;

  for (int i = 0; i < ${Fr.maxColorCount}; i++) {
    if (i >= int(u_colorsCount)) break;

    vec2 pos = getPosition(i, positionSeed) + mixerGrain;
    float dist = length(uv - pos);
    dist = length(uv - pos);

    vec3 colorFraction = u_colors[i].rgb * u_colors[i].a;
    float opacityFraction = u_colors[i].a;

    float mixing = pow(u_mixing, .7);
    float power = mix(2., 1., mixing);
    dist = pow(dist, power);

    float w = 1. / (dist + 1e-3);
    float baseSharpness = mix(.0, 8., clamp(w, 0., 1.));
    float sharpness = mix(baseSharpness, 1., mixing);
    w = pow(w, sharpness);
    color += colorFraction * w;
    opacity += opacityFraction * w;
    totalWeight += w;
  }

  color /= max(1e-4, totalWeight);
  opacity /= max(1e-4, totalWeight);

  float grainOverlay = valueNoise(rotate(grainUV, 1.) + vec2(3.));
  grainOverlay = mix(grainOverlay, valueNoise(rotate(grainUV, 2.) + vec2(-1.)), .5);
  grainOverlay = pow(grainOverlay, 1.3);

  float grainOverlayV = grainOverlay * 2. - 1.;
  vec3 grainOverlayColor = vec3(step(0., grainOverlayV));
  float grainOverlayStrength = u_grainOverlay * abs(grainOverlayV);
  grainOverlayStrength = pow(grainOverlayStrength, .8);
  color = mix(color, grainOverlayColor, .35 * grainOverlayStrength);

  opacity += .5 * grainOverlayStrength;
  opacity = clamp(opacity, 0., 1.);

  fragColor = vec4(color, opacity);
}
`,Nr={maxColorCount:10},Bc=`#version 300 es
precision mediump float;

uniform vec4 u_colorBack;
uniform vec4 u_colors[${Nr.maxColorCount}];
uniform float u_colorsCount;

uniform float u_radius;
uniform float u_focalDistance;
uniform float u_focalAngle;
uniform float u_falloff;
uniform float u_mixing;
uniform float u_distortion;
uniform float u_distortionShift;
uniform float u_distortionFreq;
uniform float u_grainMixer;
uniform float u_grainOverlay;

in vec2 v_objectUV;
out vec4 fragColor;

${G}
${ge}
${zt}

float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

float noise(vec2 n, vec2 seedOffset) {
  return valueNoise(n + seedOffset);
}

vec2 getPosition(int i, float t) {
  float a = float(i) * .37;
  float b = .6 + mod(float(i), 3.) * .3;
  float c = .8 + mod(float(i + 1), 4.) * 0.25;

  float x = sin(t * b + a);
  float y = cos(t * c + a * 1.5);

  return .5 + .5 * vec2(x, y);
}

void main() {
  vec2 uv = 2. * v_objectUV;
  vec2 grainUV = uv * 1000.;

  vec2 center = vec2(0.);
  float angleRad = -radians(u_focalAngle + 90.);
  vec2 focalPoint = vec2(cos(angleRad), sin(angleRad)) * u_focalDistance;
  float radius = u_radius;

  vec2 c_to_uv = uv - center;
  vec2 f_to_uv = uv - focalPoint;
  vec2 f_to_c = center - focalPoint;
  float r = length(c_to_uv);

  float fragAngle = atan(c_to_uv.y, c_to_uv.x);
  float angleDiff = fract((fragAngle - angleRad + PI) / TWO_PI) * TWO_PI - PI;

  float halfAngle = acos(clamp(radius / max(u_focalDistance, 1e-4), 0.0, 1.0));
  float e0 = 0.6 * PI, e1 = halfAngle;
  float lo = min(e0, e1), hi = max(e0, e1);
  float s  = smoothstep(lo, hi, abs(angleDiff));
  float isInSector = (e1 >= e0) ? (1.0 - s) : s;

  float a = dot(f_to_uv, f_to_uv);
  float b = -2.0 * dot(f_to_uv, f_to_c);
  float c = dot(f_to_c, f_to_c) - radius * radius;

  float discriminant = b * b - 4.0 * a * c;
  float t = 1.0;

  if (discriminant >= 0.0) {
    float sqrtD = sqrt(discriminant);
    float div = max(1e-4, 2.0 * a);
    float t0 = (-b - sqrtD) / div;
    float t1 = (-b + sqrtD) / div;
    t = max(t0, t1);
    if (t < 0.0) t = 0.0;
  }

  float dist = length(f_to_uv);
  float normalized = dist / max(1e-4, length(f_to_uv * t));
  float shape = clamp(normalized, 0.0, 1.0);

  float falloffMapped = mix(.2 + .8 * max(0., u_falloff + 1.), mix(1., 15., u_falloff * u_falloff), step(.0, u_falloff));

  float falloffExp = mix(falloffMapped, 1., shape);
  shape = pow(shape, falloffExp);
  shape = 1. - clamp(shape, 0., 1.);


  float outerMask = .002;
  float outer = 1.0 - smoothstep(radius - outerMask, radius + outerMask, r);
  outer = mix(outer, 1., isInSector);

  shape = mix(0., shape, outer);
  shape *= 1. - smoothstep(radius - .01, radius, r);

  float angle = atan(f_to_uv.y, f_to_uv.x);
  shape -= pow(u_distortion, 2.) * shape * pow(abs(sin(PI * clamp(length(f_to_uv) - 0.2 + u_distortionShift, 0.0, 1.0))), 4.0) * (sin(u_distortionFreq * angle) + cos(floor(0.65 * u_distortionFreq) * angle));

  float grain = noise(grainUV, vec2(0.));
  float mixerGrain = .4 * u_grainMixer * (grain - .5);

  float mixer = shape * u_colorsCount + mixerGrain;
  vec4 gradient = u_colors[0];
  gradient.rgb *= gradient.a;

  float outerShape = 0.;
  for (int i = 1; i < ${Nr.maxColorCount+1}; i++) {
    if (i > int(u_colorsCount)) break;
    float mLinear = clamp(mixer - float(i - 1), 0.0, 1.0);

    float aa = fwidth(mLinear);
    float width = min(u_mixing, 0.5);
    float t = clamp((mLinear - (0.5 - width - aa)) / (2. * width + 2. * aa), 0., 1.);
    float p = mix(2., 1., clamp((u_mixing - 0.5) * 2., 0., 1.));
    float m = t < 0.5
      ? 0.5 * pow(2. * t, p)
      : 1. - 0.5 * pow(2. * (1. - t), p);

    float quadBlend = clamp((u_mixing - 0.5) * 2., 0., 1.);
    m = mix(m, m * m, 0.5 * quadBlend);
    
    if (i == 1) {
      outerShape = m;
    }

    vec4 c = u_colors[i - 1];
    c.rgb *= c.a;
    gradient = mix(gradient, c, m);
  }

  vec3 color = gradient.rgb * outerShape;
  float opacity = gradient.a * outerShape;

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1.0 - opacity);
  opacity = opacity + u_colorBack.a * (1.0 - opacity);

  float grainOverlay = valueNoise(rotate(grainUV, 1.) + vec2(3.));
  grainOverlay = mix(grainOverlay, valueNoise(rotate(grainUV, 2.) + vec2(-1.)), .5);
  grainOverlay = pow(grainOverlay, 1.3);

  float grainOverlayV = grainOverlay * 2. - 1.;
  vec3 grainOverlayColor = vec3(step(0., grainOverlayV));
  float grainOverlayStrength = u_grainOverlay * abs(grainOverlayV);
  grainOverlayStrength = pow(grainOverlayStrength, .8);
  color = mix(color, grainOverlayColor, .35 * grainOverlayStrength);

  opacity += .5 * grainOverlayStrength;
  opacity = clamp(opacity, 0., 1.);

  fragColor = vec4(color, opacity);
}
`,Vc=`#version 300 es
precision mediump float;

uniform vec2 u_resolution;
uniform float u_pixelRatio;

uniform vec4 u_colorFront;
uniform vec4 u_colorBack;

uniform sampler2D u_image;
uniform float u_imageAspectRatio;

uniform float u_contrast;
uniform float u_roughness;
uniform float u_fiber;
uniform float u_fiberSize;
uniform float u_crumples;
uniform float u_crumpleSize;
uniform float u_folds;
uniform float u_foldCount;
uniform float u_drops;
uniform float u_seed;
uniform float u_fade;

uniform sampler2D u_noiseTexture;

in vec2 v_imageUV;

out vec4 fragColor;

float getUvFrame(vec2 uv) {
  float aax = 2. * fwidth(uv.x);
  float aay = 2. * fwidth(uv.y);

  float left   = smoothstep(0., aax, uv.x);
  float right = 1. - smoothstep(1. - aax, 1., uv.x);
  float bottom = smoothstep(0., aay, uv.y);
  float top = 1. - smoothstep(1. - aay, 1., uv.y);

  return left * right * bottom * top;
}

${G}
${ge}
${Oa}
float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = randomR(i);
  float b = randomR(i + vec2(1.0, 0.0));
  float c = randomR(i + vec2(0.0, 1.0));
  float d = randomR(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}
float fbm(vec2 n) {
  float total = 0.0, amplitude = .4;
  for (int i = 0; i < 3; i++) {
    total += valueNoise(n) * amplitude;
    n *= 1.99;
    amplitude *= 0.65;
  }
  return total;
}


float randomG(vec2 p) {
  vec2 uv = floor(p) / 50. + .5;
  return texture(u_noiseTexture, fract(uv)).g;
}
float roughness(vec2 p) {
  p *= .1;
  float o = 0.;
  for (float i = 0.; ++i < 4.; p *= 2.1) {
    vec4 w = vec4(floor(p), ceil(p));
    vec2 f = fract(p);
    o += mix(
    mix(randomG(w.xy), randomG(w.xw), f.y),
    mix(randomG(w.zy), randomG(w.zw), f.y),
    f.x);
    o += .2 / exp(2. * abs(sin(.2 * p.x + .5 * p.y)));
  }
  return o / 3.;
}

${pc}

vec2 randomGB(vec2 p) {
  vec2 uv = floor(p) / 50. + .5;
  return texture(u_noiseTexture, fract(uv)).gb;
}
float crumpledNoise(vec2 t, float pw) {
  vec2 p = floor(t);
  float wsum = 0.;
  float cl = 0.;
  for (int y = -1; y < 2; y += 1) {
    for (int x = -1; x < 2; x += 1) {
      vec2 b = vec2(float(x), float(y));
      vec2 q = b + p;
      vec2 q2 = q - floor(q / 8.) * 8.;
      vec2 c = q + randomGB(q2);
      vec2 r = c - t;
      float w = pow(smoothstep(0., 1., 1. - abs(r.x)), pw) * pow(smoothstep(0., 1., 1. - abs(r.y)), pw);
      cl += (.5 + .5 * sin((q2.x + q2.y * 5.) * 8.)) * w;
      wsum += w;
    }
  }
  return pow(wsum != 0.0 ? cl / wsum : 0.0, .5) * 2.;
}
float crumplesShape(vec2 uv) {
  return crumpledNoise(uv * .25, 16.) * crumpledNoise(uv * .5, 2.);
}


vec2 folds(vec2 uv) {
  vec3 pp = vec3(0.);
  float l = 9.;
  for (float i = 0.; i < 15.; i++) {
    if (i >= u_foldCount) break;
    vec2 rand = randomGB(vec2(i, i * u_seed));
    float an = rand.x * TWO_PI;
    vec2 p = vec2(cos(an), sin(an)) * rand.y;
    float dist = distance(uv, p);
    l = min(l, dist);

    if (l == dist) {
      pp.xy = (uv - p.xy);
      pp.z = dist;
    }
  }
  return mix(pp.xy, vec2(0.), pow(pp.z, .25));
}

float drops(vec2 uv) {
  vec2 iDropsUV = floor(uv);
  vec2 fDropsUV = fract(uv);
  float dropsMinDist = 1.;
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      vec2 neighbor = vec2(float(i), float(j));
      vec2 offset = randomGB(iDropsUV + neighbor);
      offset = .5 + .5 * sin(10. * u_seed + TWO_PI * offset);
      vec2 pos = neighbor + offset - fDropsUV;
      float dist = length(pos);
      dropsMinDist = min(dropsMinDist, dropsMinDist*dist);
    }
  }
  return 1. - smoothstep(.05, .09, pow(dropsMinDist, .5));
}

float lst(float edge0, float edge1, float x) {
  return clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0);
}

void main() {

  vec2 imageUV = v_imageUV;
  vec2 patternUV = v_imageUV - .5;
  patternUV = 5. * (patternUV * vec2(u_imageAspectRatio, 1.));

  vec2 roughnessUv = 1.5 * (gl_FragCoord.xy - .5 * u_resolution) / u_pixelRatio;
  float roughness = roughness(roughnessUv + vec2(1., 0.)) - roughness(roughnessUv - vec2(1., 0.));

  vec2 crumplesUV = fract(patternUV * .02 / u_crumpleSize - u_seed) * 32.;
  float crumples = u_crumples * (crumplesShape(crumplesUV + vec2(.05, 0.)) - crumplesShape(crumplesUV));

  vec2 fiberUV = 2. / u_fiberSize * patternUV;
  float fiber = fiberNoise(fiberUV, vec2(0.));
  fiber = .5 * u_fiber * (fiber - 1.);

  vec2 normal = vec2(0.);
  vec2 normalImage = vec2(0.);

  vec2 foldsUV = patternUV * .12;
  foldsUV = rotate(foldsUV, 4. * u_seed);
  vec2 w = folds(foldsUV);
  foldsUV = rotate(foldsUV + .007 * cos(u_seed), .01 * sin(u_seed));
  vec2 w2 = folds(foldsUV);

  float drops = u_drops * drops(patternUV * 2.);

  float fade = u_fade * fbm(.17 * patternUV + 10. * u_seed);
  fade = clamp(8. * fade * fade * fade, 0., 1.);

  w = mix(w, vec2(0.), fade);
  w2 = mix(w2, vec2(0.), fade);
  crumples = mix(crumples, 0., fade);
  drops = mix(drops, 0., fade);
  fiber *= mix(1., .5, fade);
  roughness *= mix(1., .5, fade);

  normal.xy += u_folds * min(5. * u_contrast, 1.) * 4. * max(vec2(0.), w + w2);
  normalImage.xy += u_folds * 2. * w;

  normal.xy += crumples;
  normalImage.xy += 1.5 * crumples;

  normal.xy += 3. * drops;
  normalImage.xy += .2 * drops;

  normal.xy += u_roughness * 1.5 * roughness;
  normal.xy += fiber;

  normalImage += u_roughness * .75 * roughness;
  normalImage += .2 * fiber;

  vec3 lightPos = vec3(1., 2., 1.);
  float res = dot(normalize(vec3(normal, 9.5 - 9. * pow(u_contrast, .1))), normalize(lightPos));

  vec3 fgColor = u_colorFront.rgb * u_colorFront.a;
  float fgOpacity = u_colorFront.a;
  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  float bgOpacity = u_colorBack.a;

  imageUV += .02 * normalImage;
  float frame = getUvFrame(imageUV);
  vec4 image = texture(u_image, imageUV);
  image.rgb += .6 * pow(u_contrast, .4) * (res - .7);

  frame *= image.a;

  vec3 color = fgColor * res;
  float opacity = fgOpacity * res;

  color += bgColor * (1. - opacity);
  opacity += bgOpacity * (1. - opacity);
  opacity = mix(opacity, 1., frame);

  color -= .007 * drops;

  color.rgb = mix(color, image.rgb, frame);

  fragColor = vec4(color, opacity);
}
`,Rc=`#version 300 es
precision mediump float;

uniform float u_time;

uniform vec4 u_colorBack;
uniform vec4 u_colorHighlight;

uniform sampler2D u_image;
uniform float u_imageAspectRatio;

uniform float u_size;
uniform float u_highlights;
uniform float u_layering;
uniform float u_edges;
uniform float u_caustic;
uniform float u_waves;

in vec2 v_imageUV;

out vec4 fragColor;

${G}
${ge}
${Ft}

float getUvFrame(vec2 uv) {
  float aax = 2. * fwidth(uv.x);
  float aay = 2. * fwidth(uv.y);

  float left   = smoothstep(0., aax, uv.x);
  float right = 1.0 - smoothstep(1. - aax, 1., uv.x);
  float bottom = smoothstep(0., aay, uv.y);
  float top = 1.0 - smoothstep(1. - aay, 1., uv.y);

  return left * right * bottom * top;
}

mat2 rotate2D(float r) {
  return mat2(cos(r), sin(r), -sin(r), cos(r));
}

float getCausticNoise(vec2 uv, float t, float scale) {
  vec2 n = vec2(.1);
  vec2 N = vec2(.1);
  mat2 m = rotate2D(.5);
  for (int j = 0; j < 6; j++) {
    uv *= m;
    n *= m;
    vec2 q = uv * scale + float(j) + n + (.5 + .5 * float(j)) * (mod(float(j), 2.) - 1.) * t;
    n += sin(q);
    N += cos(q) / scale;
    scale *= 1.1;
  }
  return (N.x + N.y + 1.);
}

void main() {
  vec2 imageUV = v_imageUV;
  vec2 patternUV = v_imageUV - .5;
  patternUV = (patternUV * vec2(u_imageAspectRatio, 1.));
  patternUV /= (.01 + .09 * u_size);

  float t = u_time;

  float wavesNoise = snoise((.3 + .1 * sin(t)) * .1 * patternUV + vec2(0., .4 * t));

  float causticNoise = getCausticNoise(patternUV + u_waves * vec2(1., -1.) * wavesNoise, 2. * t, 1.5);

  causticNoise += u_layering * getCausticNoise(patternUV + 2. * u_waves * vec2(1., -1.) * wavesNoise, 1.5 * t, 2.);
  causticNoise = causticNoise * causticNoise;

  float edgesDistortion = smoothstep(0., .1, imageUV.x);
  edgesDistortion *= smoothstep(0., .1, imageUV.y);
  edgesDistortion *= (smoothstep(1., 1.1, imageUV.x) + (1.0 - smoothstep(.8, .95, imageUV.x)));
  edgesDistortion *= (1.0 - smoothstep(.9, 1., imageUV.y));
  edgesDistortion = mix(edgesDistortion, 1., u_edges);

  float causticNoiseDistortion = .02 * causticNoise * edgesDistortion;

  float wavesDistortion = .1 * u_waves * wavesNoise;

  imageUV += vec2(wavesDistortion, -wavesDistortion);
  imageUV += (u_caustic * causticNoiseDistortion);

  float frame = getUvFrame(imageUV);

  vec4 image = texture(u_image, imageUV);
  vec4 backColor = u_colorBack;
  backColor.rgb *= backColor.a;

  vec3 color = mix(backColor.rgb, image.rgb, image.a * frame);
  float opacity = backColor.a + image.a * frame;

  causticNoise = max(-.2, causticNoise);

  float hightlight = .025 * u_highlights * causticNoise;
  hightlight *= u_colorHighlight.a;
  color = mix(color, u_colorHighlight.rgb, .05 * u_highlights * causticNoise);
  opacity += hightlight;

  color += hightlight * (.5 + .5 * wavesNoise);
  opacity += hightlight * (.5 + .5 * wavesNoise);

  opacity = clamp(opacity, 0., 1.);

  fragColor = vec4(color, opacity);
}
`,Pc=`#version 300 es
precision mediump float;

uniform vec2 u_resolution;
uniform float u_pixelRatio;
uniform float u_rotation;

uniform vec4 u_colorBack;
uniform vec4 u_colorShadow;
uniform vec4 u_colorHighlight;

uniform sampler2D u_image;
uniform float u_imageAspectRatio;

uniform float u_size;
uniform float u_shadows;
uniform float u_angle;
uniform float u_stretch;
uniform float u_shape;
uniform float u_distortion;
uniform float u_highlights;
uniform float u_distortionShape;
uniform float u_shift;
uniform float u_blur;
uniform float u_edges;
uniform float u_marginLeft;
uniform float u_marginRight;
uniform float u_marginTop;
uniform float u_marginBottom;
uniform float u_grainMixer;
uniform float u_grainOverlay;

in vec2 v_imageUV;

out vec4 fragColor;

${G}
${ge}
${zt}

float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

float getUvFrame(vec2 uv, float softness) {
  float aax = 2. * fwidth(uv.x);
  float aay = 2. * fwidth(uv.y);
  float left   = smoothstep(0., aax + softness, uv.x);
  float right  = 1. - smoothstep(1. - softness - aax, 1., uv.x);
  float bottom = smoothstep(0., aay + softness, uv.y);
  float top    = 1. - smoothstep(1. - softness - aay, 1., uv.y);
  return left * right * bottom * top;
}

const int MAX_RADIUS = 50;
vec4 samplePremultiplied(sampler2D tex, vec2 uv) {
  vec4 c = texture(tex, uv);
  c.rgb *= c.a;
  return c;
}
vec4 getBlur(sampler2D tex, vec2 uv, vec2 texelSize, vec2 dir, float sigma) {
  if (sigma <= .5) return texture(tex, uv);
  int radius = int(min(float(MAX_RADIUS), ceil(3.0 * sigma)));

  float twoSigma2 = 2.0 * sigma * sigma;
  float gaussianNorm = 1.0 / sqrt(TWO_PI * sigma * sigma);

  vec4 sum = samplePremultiplied(tex, uv) * gaussianNorm;
  float weightSum = gaussianNorm;

  for (int i = 1; i <= MAX_RADIUS; i++) {
    if (i > radius) break;

    float x = float(i);
    float w = exp(-(x * x) / twoSigma2) * gaussianNorm;

    vec2 offset = dir * texelSize * x;
    vec4 s1 = samplePremultiplied(tex, uv + offset);
    vec4 s2 = samplePremultiplied(tex, uv - offset);

    sum += (s1 + s2) * w;
    weightSum += 2.0 * w;
  }

  vec4 result = sum / weightSum;
  if (result.a > 0.) {
    result.rgb /= result.a;
  }

  return result;
}

vec2 rotateAspect(vec2 p, float a, float aspect) {
  p.x *= aspect;
  p = rotate(p, a);
  p.x /= aspect;
  return p;
}

float smoothFract(float x) {
  float f = fract(x);
  float w = fwidth(x);

  float edge = abs(f - 0.5) - 0.5;
  float band = smoothstep(-w, w, edge);

  return mix(f, 1.0 - f, band);
}

void main() {

  float patternRotation = -u_angle * PI / 180.;
  float patternSize = mix(200., 5., u_size);

  vec2 uv = v_imageUV;

  vec2 uvMask = gl_FragCoord.xy / u_resolution.xy;
  vec2 sw = vec2(.005);
  vec4 margins = vec4(u_marginLeft, u_marginTop, u_marginRight, u_marginBottom);
  float mask =
  smoothstep(margins[0], margins[0] + sw.x, uvMask.x + sw.x) *
  smoothstep(margins[2], margins[2] + sw.x, 1.0 - uvMask.x + sw.x) *
  smoothstep(margins[1], margins[1] + sw.y, uvMask.y + sw.y) *
  smoothstep(margins[3], margins[3] + sw.y, 1.0 - uvMask.y + sw.y);
  float maskOuter =
  smoothstep(margins[0] - sw.x, margins[0], uvMask.x + sw.x) *
  smoothstep(margins[2] - sw.x, margins[2], 1.0 - uvMask.x + sw.x) *
  smoothstep(margins[1] - sw.y, margins[1], uvMask.y + sw.y) *
  smoothstep(margins[3] - sw.y, margins[3], 1.0 - uvMask.y + sw.y);
  float maskStroke = maskOuter - mask;
  float maskInner =
  smoothstep(margins[0] - 2. * sw.x, margins[0], uvMask.x) *
  smoothstep(margins[2] - 2. * sw.x, margins[2], 1.0 - uvMask.x) *
  smoothstep(margins[1] - 2. * sw.y, margins[1], uvMask.y) *
  smoothstep(margins[3] - 2. * sw.y, margins[3], 1.0 - uvMask.y);
  float maskStrokeInner = maskInner - mask;

  uv -= .5;
  uv *= patternSize;
  uv = rotateAspect(uv, patternRotation, u_imageAspectRatio);

  float curve = 0.;
  float patternY = uv.y / u_imageAspectRatio;
  if (u_shape > 4.5) {
    // pattern
    curve = .5 + .5 * sin(.5 * PI * uv.x) * cos(.5 * PI * patternY);
  } else if (u_shape > 3.5) {
    // zigzag
    curve = 10. * abs(fract(.1 * patternY) - .5);
  } else if (u_shape > 2.5) {
    // wave
    curve = 4. * sin(.23 * patternY);
  } else if (u_shape > 1.5) {
    // lines irregular
    curve = .5 + .5 * sin(.5 * uv.x) * sin(1.7 * uv.x);
  } else {
    // lines
  }

  vec2 UvToFract = uv + curve;
  vec2 fractOrigUV = fract(uv);
  vec2 floorOrigUV = floor(uv);

  float x = smoothFract(UvToFract.x);
  float xNonSmooth = fract(UvToFract.x) + .0001;

  float highlightsWidth = 2. * max(.001, fwidth(UvToFract.x));
  highlightsWidth += 2. * maskStrokeInner;
  float highlights = smoothstep(0., highlightsWidth, xNonSmooth);
  highlights *= smoothstep(1., 1. - highlightsWidth, xNonSmooth);
  highlights = 1. - highlights;
  highlights *= u_highlights;
  highlights = clamp(highlights, 0., 1.);
  highlights *= mask;

  float shadows = pow(x, 1.3);
  float distortion = 0.;
  float fadeX = 1.;
  float frameFade = 0.;

  float aa = fwidth(xNonSmooth);
  aa = max(aa, fwidth(uv.x));
  aa = max(aa, fwidth(UvToFract.x));
  aa = max(aa, .0001);

  if (u_distortionShape == 1.) {
    distortion = -pow(1.5 * x, 3.);
    distortion += (.5 - u_shift);

    frameFade = pow(1.5 * x, 3.);
    aa = max(.2, aa);
    aa += mix(.2, 0., u_size);
    fadeX = smoothstep(0., aa, xNonSmooth) * smoothstep(1., 1. - aa, xNonSmooth);
    distortion = mix(.5, distortion, fadeX);
  } else if (u_distortionShape == 2.) {
    distortion = 2. * pow(x, 2.);
    distortion -= (.5 + u_shift);

    frameFade = pow(abs(x - .5), 4.);
    aa = max(.2, aa);
    aa += mix(.2, 0., u_size);
    fadeX = smoothstep(0., aa, xNonSmooth) * smoothstep(1., 1. - aa, xNonSmooth);
    distortion = mix(.5, distortion, fadeX);
    frameFade = mix(1., frameFade, .5 * fadeX);
  } else if (u_distortionShape == 3.) {
    distortion = pow(2. * (xNonSmooth - .5), 6.);
    distortion -= .25;
    distortion -= u_shift;

    frameFade = 1. - 2. * pow(abs(x - .4), 2.);
    aa = .15;
    aa += mix(.1, 0., u_size);
    fadeX = smoothstep(0., aa, xNonSmooth) * smoothstep(1., 1. - aa, xNonSmooth);
    frameFade = mix(1., frameFade, fadeX);

  } else if (u_distortionShape == 4.) {
    x = xNonSmooth;
    distortion = sin((x + .25) * TWO_PI);
    shadows = .5 + .5 * asin(distortion) / (.5 * PI);
    distortion *= .5;
    distortion -= u_shift;
    frameFade = .5 + .5 * sin(x * TWO_PI);
  } else if (u_distortionShape == 5.) {
    distortion -= pow(abs(x), .2) * x;
    distortion += .33;
    distortion -= 3. * u_shift;
    distortion *= .33;

    frameFade = .3 * (smoothstep(.0, 1., x));
    shadows = pow(x, 2.5);

    aa = max(.1, aa);
    aa += mix(.1, 0., u_size);
    fadeX = smoothstep(0., aa, xNonSmooth) * smoothstep(1., 1. - aa, xNonSmooth);
    distortion *= fadeX;
  }

  vec2 dudx = dFdx(v_imageUV);
  vec2 dudy = dFdy(v_imageUV);
  vec2 grainUV = v_imageUV - .5;
  grainUV *= (.8 / vec2(length(dudx), length(dudy)));
  grainUV += .5;
  float grain = valueNoise(grainUV);
  grain = smoothstep(.4, .7, grain);
  grain *= u_grainMixer;
  distortion = mix(distortion, 0., grain);

  shadows = min(shadows, 1.);
  shadows += maskStrokeInner;
  shadows *= mask;
  shadows = min(shadows, 1.);
  shadows *= pow(u_shadows, 2.);
  shadows = clamp(shadows, 0., 1.);

  distortion *= 3. * u_distortion;
  frameFade *= u_distortion;

  fractOrigUV.x += distortion;
  floorOrigUV = rotateAspect(floorOrigUV, -patternRotation, u_imageAspectRatio);
  fractOrigUV = rotateAspect(fractOrigUV, -patternRotation, u_imageAspectRatio);

  uv = (floorOrigUV + fractOrigUV) / patternSize;
  uv += pow(maskStroke, 4.);

  uv += vec2(.5);

  uv = mix(v_imageUV, uv, smoothstep(0., .7, mask));
  float blur = mix(0., 50., u_blur);
  blur = mix(0., blur, smoothstep(.5, 1., mask));

  float edgeDistortion = mix(.0, .04, u_edges);
  edgeDistortion += .06 * frameFade * u_edges;
  edgeDistortion *= mask;
  float frame = getUvFrame(uv, edgeDistortion);

  float stretch = 1. - smoothstep(0., .5, xNonSmooth) * smoothstep(1., 1. - .5, xNonSmooth);
  stretch = pow(stretch, 2.);
  stretch *= mask;
  stretch *= getUvFrame(uv, .1 + .05 * mask * frameFade);
  uv.y = mix(uv.y, .5, u_stretch * stretch);

  vec4 image = getBlur(u_image, uv, 1. / u_resolution / u_pixelRatio, vec2(0., 1.), blur);
  image.rgb *= image.a;
  vec4 backColor = u_colorBack;
  backColor.rgb *= backColor.a;
  vec4 highlightColor = u_colorHighlight;
  highlightColor.rgb *= highlightColor.a;
  vec4 shadowColor = u_colorShadow;

  vec3 color = highlightColor.rgb * highlights;
  float opacity = highlightColor.a * highlights;

  shadows = mix(shadows * shadowColor.a, 0., highlights);
  color = mix(color, shadowColor.rgb * shadowColor.a, .5 * shadows);
  color += .5 * pow(shadows, .5) * shadowColor.rgb;
  opacity += shadows;
  color = clamp(color, vec3(0.), vec3(1.));
  opacity = clamp(opacity, 0., 1.);

  color += image.rgb * (1. - opacity) * frame;
  opacity += image.a * (1. - opacity) * frame;

  color += backColor.rgb * (1. - opacity);
  opacity += backColor.a * (1. - opacity);

  float grainOverlay = valueNoise(rotate(grainUV, 1.) + vec2(3.));
  grainOverlay = mix(grainOverlay, valueNoise(rotate(grainUV, 2.) + vec2(-1.)), .5);
  grainOverlay = pow(grainOverlay, 1.3);

  float grainOverlayV = grainOverlay * 2. - 1.;
  vec3 grainOverlayColor = vec3(step(0., grainOverlayV));
  float grainOverlayStrength = u_grainOverlay * abs(grainOverlayV);
  grainOverlayStrength = pow(grainOverlayStrength, .8);
  grainOverlayStrength *= mask;
  color = mix(color, grainOverlayColor, .35 * grainOverlayStrength);

  opacity += .5 * grainOverlayStrength;
  opacity = clamp(opacity, 0., 1.);

  fragColor = vec4(color, opacity);
}
`,Dc=`#version 300 es
precision mediump float;

uniform vec2 u_resolution;
uniform float u_pixelRatio;
uniform float u_originX;
uniform float u_originY;
uniform float u_worldWidth;
uniform float u_worldHeight;
uniform float u_fit;

uniform float u_scale;
uniform float u_rotation;
uniform float u_offsetX;
uniform float u_offsetY;

uniform vec4 u_colorFront;
uniform vec4 u_colorBack;
uniform vec4 u_colorHighlight;

uniform sampler2D u_image;
uniform float u_imageAspectRatio;

uniform float u_type;
uniform float u_pxSize;
uniform bool u_originalColors;
uniform bool u_inverted;
uniform float u_colorSteps;

out vec4 fragColor;


${zt}
${G}

float getUvFrame(vec2 uv, vec2 pad) {
  float aa = 0.0001;

  float left   = smoothstep(-pad.x, -pad.x + aa, uv.x);
  float right  = smoothstep(1.0 + pad.x, 1.0 + pad.x - aa, uv.x);
  float bottom = smoothstep(-pad.y, -pad.y + aa, uv.y);
  float top    = smoothstep(1.0 + pad.y, 1.0 + pad.y - aa, uv.y);

  return left * right * bottom * top;
}

vec2 getImageUV(vec2 uv) {
  vec2 boxOrigin = vec2(.5 - u_originX, u_originY - .5);
  float r = u_rotation * PI / 180.;
  mat2 graphicRotation = mat2(cos(r), sin(r), -sin(r), cos(r));
  vec2 graphicOffset = vec2(-u_offsetX, u_offsetY);

  vec2 imageBoxSize;
  if (u_fit == 1.) { // contain
    imageBoxSize.x = min(u_resolution.x / u_imageAspectRatio, u_resolution.y) * u_imageAspectRatio;
  } else if (u_fit == 2.) { // cover
    imageBoxSize.x = max(u_resolution.x / u_imageAspectRatio, u_resolution.y) * u_imageAspectRatio;
  } else {
    imageBoxSize.x = min(10.0, 10.0 / u_imageAspectRatio * u_imageAspectRatio);
  }
  imageBoxSize.y = imageBoxSize.x / u_imageAspectRatio;
  vec2 imageBoxScale = u_resolution.xy / imageBoxSize;

  vec2 imageUV = uv;
  imageUV *= imageBoxScale;
  imageUV += boxOrigin * (imageBoxScale - 1.);
  imageUV += graphicOffset;
  imageUV /= u_scale;
  imageUV.x *= u_imageAspectRatio;
  imageUV = graphicRotation * imageUV;
  imageUV.x /= u_imageAspectRatio;

  imageUV += .5;
  imageUV.y = 1. - imageUV.y;

  return imageUV;
}

const int bayer2x2[4] = int[4](0, 2, 3, 1);
const int bayer4x4[16] = int[16](
0, 8, 2, 10,
12, 4, 14, 6,
3, 11, 1, 9,
15, 7, 13, 5
);

const int bayer8x8[64] = int[64](
0, 32, 8, 40, 2, 34, 10, 42,
48, 16, 56, 24, 50, 18, 58, 26,
12, 44, 4, 36, 14, 46, 6, 38,
60, 28, 52, 20, 62, 30, 54, 22,
3, 35, 11, 43, 1, 33, 9, 41,
51, 19, 59, 27, 49, 17, 57, 25,
15, 47, 7, 39, 13, 45, 5, 37,
63, 31, 55, 23, 61, 29, 53, 21
);

float getBayerValue(vec2 uv, int size) {
  ivec2 pos = ivec2(fract(uv / float(size)) * float(size));
  int index = pos.y * size + pos.x;

  if (size == 2) {
    return float(bayer2x2[index]) / 4.0;
  } else if (size == 4) {
    return float(bayer4x4[index]) / 16.0;
  } else if (size == 8) {
    return float(bayer8x8[index]) / 64.0;
  }
  return 0.0;
}


void main() {

  float pxSize = u_pxSize * u_pixelRatio;
  vec2 pxSizeUV = gl_FragCoord.xy - .5 * u_resolution;
  pxSizeUV /= pxSize;
  vec2 canvasPixelizedUV = (floor(pxSizeUV) + .5) * pxSize;
  vec2 normalizedUV = canvasPixelizedUV / u_resolution;

  vec2 imageUV = getImageUV(normalizedUV);
  vec2 ditheringNoiseUV = canvasPixelizedUV;
  vec4 image = texture(u_image, imageUV);
  float frame = getUvFrame(imageUV, pxSize / u_resolution);

  int type = int(floor(u_type));
  float dithering = 0.0;

  float lum = dot(vec3(.2126, .7152, .0722), image.rgb);
  lum = u_inverted ? (1. - lum) : lum;

  switch (type) {
    case 1: {
      dithering = step(hash21(ditheringNoiseUV), lum);
    } break;
    case 2:
    dithering = getBayerValue(pxSizeUV, 2);
    break;
    case 3:
    dithering = getBayerValue(pxSizeUV, 4);
    break;
    default :
    dithering = getBayerValue(pxSizeUV, 8);
    break;
  }

  float colorSteps = max(floor(u_colorSteps), 1.);
  vec3 color = vec3(0.0);
  float opacity = 1.;

  dithering -= .5;
  float brightness = clamp(lum + dithering / colorSteps, 0.0, 1.0);
  brightness = mix(0.0, brightness, frame);
  brightness = mix(0.0, brightness, image.a);
  float quantLum = floor(brightness * colorSteps + 0.5) / colorSteps;
  quantLum = mix(0.0, quantLum, frame);

  if (u_originalColors == true) {
    vec3 normColor = image.rgb / max(lum, 0.001);
    color = normColor * quantLum;

    float quantAlpha = floor(image.a * colorSteps + 0.5) / colorSteps;
    opacity = mix(quantLum, 1., quantAlpha);
  } else {
    vec3 fgColor = u_colorFront.rgb * u_colorFront.a;
    float fgOpacity = u_colorFront.a;
    vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
    float bgOpacity = u_colorBack.a;
    vec3 hlColor = u_colorHighlight.rgb * u_colorHighlight.a;
    float hlOpacity = u_colorHighlight.a;

    fgColor = mix(fgColor, hlColor, step(1.02 - .02 * u_colorSteps, brightness));
    fgOpacity = mix(fgOpacity, hlOpacity, step(1.02 - .02 * u_colorSteps, brightness));

    color = fgColor * quantLum;
    opacity = fgOpacity * quantLum;
    color += bgColor * (1.0 - opacity);
    opacity += bgOpacity * (1.0 - opacity);
  }

  fragColor = vec4(color, opacity);
}
`,Er={maxColorCount:10},zc=`#version 300 es
precision highp float;

in mediump vec2 v_imageUV;
in mediump vec2 v_objectUV;
out vec4 fragColor;

uniform sampler2D u_image;
uniform float u_time;
uniform mediump float u_imageAspectRatio;

uniform vec4 u_colorBack;
uniform vec4 u_colors[${Er.maxColorCount}];
uniform float u_colorsCount;

uniform float u_angle;
uniform float u_noise;
uniform float u_innerGlow;
uniform float u_outerGlow;
uniform float u_contour;

#define TWO_PI 6.28318530718
#define PI 3.14159265358979323846

float getImgFrame(vec2 uv, float th) {
  float frame = 1.;
  frame *= smoothstep(0., th, uv.y);
  frame *= 1. - smoothstep(1. - th, 1., uv.y);
  frame *= smoothstep(0., th, uv.x);
  frame *= 1. - smoothstep(1. - th, 1., uv.x);
  return frame;
}

float circle(vec2 uv, vec2 c, vec2 r) {
  return 1. - smoothstep(r[0], r[1], length(uv - c));
}

float lst(float edge0, float edge1, float x) {
  return clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0);
}

float sst(float edge0, float edge1, float x) {
  return smoothstep(edge0, edge1, x);
}

float shadowShape(vec2 uv, float t, float contour) {
  vec2 scaledUV = uv;

  // base shape tranjectory
  float posY = mix(-1., 2., t);

  // scaleX when it's moving down
  scaledUV.y -= .5;
  float mainCircleScale = sst(0., .8, posY) * lst(1.4, .9, posY);
  scaledUV *= vec2(1., 1. + 1.5 * mainCircleScale);
  scaledUV.y += .5;

  // base shape
  float innerR = .4;
  float outerR = 1. - .3 * (sst(.1, .2, t) * (1. - sst(.2, .5, t)));
  float s = circle(scaledUV, vec2(.5, posY - .2), vec2(innerR, outerR));
  float shapeSizing = sst(.2, .3, t) * sst(.6, .3, t);
  s = pow(s, 1.4);
  s *= 1.2;

  // flat gradient to take over the shadow shape
  float topFlattener = 0.;
  {
    float pos = posY - uv.y;
    float edge = 1.2;
    topFlattener = lst(-.4, 0., pos) * (1. - sst(.0, edge, pos));
    topFlattener = pow(topFlattener, 3.);
    float topFlattenerMixer = (1. - sst(.0, .3, pos));
    s = mix(topFlattener, s, topFlattenerMixer);
  }

  // apple right circle
  {
    float visibility = sst(.6, .7, t) * (1. - sst(.8, .9, t));
    float angle = -2. -t * TWO_PI;
    float rightCircle = circle(uv, vec2(.95 - .2 * cos(angle), .4 - .1 * sin(angle)), vec2(.15, .3));
    rightCircle *= visibility;
    s = mix(s, 0., rightCircle);
  }

  // apple top circle
  {
    float topCircle = circle(uv, vec2(.5, .19), vec2(.05, .25));
    topCircle += 2. * contour * circle(uv, vec2(.5, .19), vec2(.2, .5));
    float visibility = .55 * sst(.2, .3, t) * (1. - sst(.3, .45, t));
    topCircle *= visibility;
    s = mix(s, 0., topCircle);
  }

  float leafMask = circle(uv, vec2(.53, .13), vec2(.08, .19));
  leafMask = mix(leafMask, 0., 1. - sst(.4, .54, uv.x));
  leafMask = mix(0., leafMask, sst(.0, .2, uv.y));
  leafMask *= (sst(.5, 1.1, posY) * sst(1.5, 1.3, posY));
  s += leafMask;

  // apple bottom circle
  {
    float visibility = sst(.0, .4, t) * (1. - sst(.6, .8, t));
    s = mix(s, 0., visibility * circle(uv, vec2(.52, .92), vec2(.09, .25)));
  }

  // random balls that are invisible if apple logo is selected
  {
    float pos = sst(.0, .6, t) * (1. - sst(.6, 1., t));
    s = mix(s, .5, circle(uv, vec2(.0, 1.2 - .5 * pos), vec2(.1, .3)));
    s = mix(s, .0, circle(uv, vec2(1., .5 + .5 * pos), vec2(.1, .3)));

    s = mix(s, 1., circle(uv, vec2(.95, .2 + .2 * sst(.3, .4, t) * sst(.7, .5, t)), vec2(.07, .22)));
    s = mix(s, 1., circle(uv, vec2(.95, .2 + .2 * sst(.3, .4, t) * (1. - sst(.5, .7, t))), vec2(.07, .22)));
    s /= max(1e-4, sst(1., .85, uv.y));
  }

  s = clamp(0., 1., s);
  return s;
}

float blurEdge3x3(sampler2D tex, vec2 uv, vec2 dudx, vec2 dudy, float radius, float centerSample) {
  vec2 texel = 1.0 / vec2(textureSize(tex, 0));
  vec2 r = radius * texel;

  float w1 = 1.0, w2 = 2.0, w4 = 4.0;
  float norm = 16.0;
  float sum = w4 * centerSample;

  sum += w2 * textureGrad(tex, uv + vec2(0.0, -r.y), dudx, dudy).g;
  sum += w2 * textureGrad(tex, uv + vec2(0.0, r.y), dudx, dudy).g;
  sum += w2 * textureGrad(tex, uv + vec2(-r.x, 0.0), dudx, dudy).g;
  sum += w2 * textureGrad(tex, uv + vec2(r.x, 0.0), dudx, dudy).g;

  sum += w1 * textureGrad(tex, uv + vec2(-r.x, -r.y), dudx, dudy).g;
  sum += w1 * textureGrad(tex, uv + vec2(r.x, -r.y), dudx, dudy).g;
  sum += w1 * textureGrad(tex, uv + vec2(-r.x, r.y), dudx, dudy).g;
  sum += w1 * textureGrad(tex, uv + vec2(r.x, r.y), dudx, dudy).g;

  return sum / norm;
}

void main() {
  vec2 uv = v_objectUV + .5;
  uv.y = 1. - uv.y;

  vec2 imgUV = v_imageUV;
  imgUV -= .5;
  imgUV *= 0.5714285714285714;
  imgUV += .5;
  float imgSoftFrame = getImgFrame(imgUV, .03);

  vec4 img = texture(u_image, imgUV);
  vec2 dudx = dFdx(imgUV);
  vec2 dudy = dFdy(imgUV);

  if (img.a == 0.) {
    fragColor = u_colorBack;
    return;
  }

  float t = .1 * u_time;
  t -= .3;

  float tCopy = t + 1. / 3.;
  float tCopy2 = t + 2. / 3.;

  t = mod(t, 1.);
  tCopy = mod(tCopy, 1.);
  tCopy2 = mod(tCopy2, 1.);

  vec2 animationUV = imgUV - vec2(.5);
  float angle = -u_angle * PI / 180.;
  float cosA = cos(angle);
  float sinA = sin(angle);
  animationUV = vec2(
  animationUV.x * cosA - animationUV.y * sinA,
  animationUV.x * sinA + animationUV.y * cosA
  ) + vec2(.5);

  float shape = img[0];

  img[1] = blurEdge3x3(u_image, imgUV, dudx, dudy, 8., img[1]);

  float outerBlur = 1. - mix(1., img[1], shape);
  float innerBlur = mix(img[1], 0., shape);
  float contour = mix(img[2], 0., shape);

  outerBlur *= imgSoftFrame;

  float shadow = shadowShape(animationUV, t, innerBlur);
  float shadowCopy = shadowShape(animationUV, tCopy, innerBlur);
  float shadowCopy2 = shadowShape(animationUV, tCopy2, innerBlur);

  float inner = .8 + .8 * innerBlur;
  inner = mix(inner, 0., shadow);
  inner = mix(inner, 0., shadowCopy);
  inner = mix(inner, 0., shadowCopy2);

  inner *= mix(0., 2., u_innerGlow);

  inner += (u_contour * 2.) * contour;
  inner = min(1., inner);
  inner *= (1. - shape);

  float outer = 0.;
  {
    t *= 3.;
    t = mod(t - .1, 1.);

    outer = .9 * pow(outerBlur, .8);
    float y = mod(animationUV.y - t, 1.);
    float animatedMask = sst(.3, .65, y) * (1. - sst(.65, 1., y));
    animatedMask = .5 + animatedMask;
    outer *= animatedMask;
    outer *= mix(0., 5., pow(u_outerGlow, 2.));
    outer *= imgSoftFrame;
  }

  inner = pow(inner, 1.2);
  float heat = clamp(inner + outer, 0., 1.);

  heat += (.005 + .35 * u_noise) * (fract(sin(dot(uv, vec2(12.9898, 78.233))) * 43758.5453123) - .5);

  float mixer = heat * u_colorsCount;
  vec4 gradient = u_colors[0];
  gradient.rgb *= gradient.a;
  float outerShape = 0.;
  for (int i = 1; i < ${Er.maxColorCount+1}; i++) {
    if (i > int(u_colorsCount)) break;
    float m = clamp(mixer - float(i - 1), 0., 1.);
    if (i == 1) {
      outerShape = m;
    }
    vec4 c = u_colors[i - 1];
    c.rgb *= c.a;
    gradient = mix(gradient, c, m);
  }

  vec3 color = gradient.rgb * outerShape;
  float opacity = gradient.a * outerShape;

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1.0 - opacity);
  opacity = opacity + u_colorBack.a * (1.0 - opacity);

  color += .02 * (fract(sin(dot(uv + 1., vec2(12.9898, 78.233))) * 43758.5453123) - .5);

  fragColor = vec4(color, opacity);
}
`,Fc=`#version 300 es
precision mediump float;

uniform sampler2D u_image;
uniform float u_imageAspectRatio;

uniform vec2 u_resolution;
uniform float u_time;

uniform vec4 u_colorBack;
uniform vec4 u_colorTint;

uniform float u_softness;
uniform float u_repetition;
uniform float u_shiftRed;
uniform float u_shiftBlue;
uniform float u_distortion;
uniform float u_contour;
uniform float u_angle;

uniform float u_shape;
uniform bool u_isImage;

in vec2 v_objectUV;
in vec2 v_responsiveUV;
in vec2 v_responsiveBoxGivenSize;
in vec2 v_imageUV;

out vec4 fragColor;

${G}
${ge}
${Ft}

float getColorChanges(float c1, float c2, float stripe_p, vec3 w, float blur, float bump, float tint) {

  float ch = mix(c2, c1, smoothstep(.0, 2. * blur, stripe_p));

  float border = w[0];
  ch = mix(ch, c2, smoothstep(border, border + 2. * blur, stripe_p));

  if (u_isImage == true) {
    bump = smoothstep(.2, .8, bump);
  }
  border = w[0] + .4 * (1. - bump) * w[1];
  ch = mix(ch, c1, smoothstep(border, border + 2. * blur, stripe_p));

  border = w[0] + .5 * (1. - bump) * w[1];
  ch = mix(ch, c2, smoothstep(border, border + 2. * blur, stripe_p));

  border = w[0] + w[1];
  ch = mix(ch, c1, smoothstep(border, border + 2. * blur, stripe_p));

  float gradient_t = (stripe_p - w[0] - w[1]) / w[2];
  float gradient = mix(c1, c2, smoothstep(0., 1., gradient_t));
  ch = mix(ch, gradient, smoothstep(border, border + .5 * blur, stripe_p));

  // Tint color is applied with color burn blending
  ch = mix(ch, 1. - min(1., (1. - ch) / max(tint, 0.0001)), u_colorTint.a);
  return ch;
}

float getImgFrame(vec2 uv, float th) {
  float frame = 1.;
  frame *= smoothstep(0., th, uv.y);
  frame *= 1.0 - smoothstep(1. - th, 1., uv.y);
  frame *= smoothstep(0., th, uv.x);
  frame *= 1.0 - smoothstep(1. - th, 1., uv.x);
  return frame;
}

float blurEdge3x3(sampler2D tex, vec2 uv, vec2 dudx, vec2 dudy, float radius, float centerSample) {
  vec2 texel = 1.0 / vec2(textureSize(tex, 0));
  vec2 r = radius * texel;

  float w1 = 1.0, w2 = 2.0, w4 = 4.0;
  float norm = 16.0;
  float sum = w4 * centerSample;

  sum += w2 * textureGrad(tex, uv + vec2(0.0, -r.y), dudx, dudy).r;
  sum += w2 * textureGrad(tex, uv + vec2(0.0, r.y), dudx, dudy).r;
  sum += w2 * textureGrad(tex, uv + vec2(-r.x, 0.0), dudx, dudy).r;
  sum += w2 * textureGrad(tex, uv + vec2(r.x, 0.0), dudx, dudy).r;

  sum += w1 * textureGrad(tex, uv + vec2(-r.x, -r.y), dudx, dudy).r;
  sum += w1 * textureGrad(tex, uv + vec2(r.x, -r.y), dudx, dudy).r;
  sum += w1 * textureGrad(tex, uv + vec2(-r.x, r.y), dudx, dudy).r;
  sum += w1 * textureGrad(tex, uv + vec2(r.x, r.y), dudx, dudy).r;

  return sum / norm;
}

float lst(float edge0, float edge1, float x) {
  return clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0);
}

void main() {

  const float firstFrameOffset = 2.8;
  float t = .3 * (u_time + firstFrameOffset);

  vec2 uv = v_imageUV;
  vec2 dudx = dFdx(v_imageUV);
  vec2 dudy = dFdy(v_imageUV);
  vec4 img = textureGrad(u_image, uv, dudx, dudy);

  if (u_isImage == false) {
    uv = v_objectUV + .5;
    uv.y = 1. - uv.y;
  }

  float cycleWidth = u_repetition;
  float edge = 0.;
  float contOffset = 1.;

  vec2 rotatedUV = uv - vec2(.5);
  float angle = (-u_angle + 70.) * PI / 180.;
  float cosA = cos(angle);
  float sinA = sin(angle);
  rotatedUV = vec2(
  rotatedUV.x * cosA - rotatedUV.y * sinA,
  rotatedUV.x * sinA + rotatedUV.y * cosA
  ) + vec2(.5);

  if (u_isImage == true) {
    float edgeRaw = img.r;
    edge = blurEdge3x3(u_image, uv, dudx, dudy, 6., edgeRaw);
    edge = pow(edge, 1.6);
    edge *= mix(0.0, 1.0, smoothstep(0.0, 0.4, u_contour));
  } else {
    if (u_shape < 1.) {
      // full-fill on canvas
      vec2 borderUV = v_responsiveUV + .5;
      float ratio = v_responsiveBoxGivenSize.x / v_responsiveBoxGivenSize.y;
      vec2 mask = min(borderUV, 1. - borderUV);
      vec2 pixel_thickness = min(250. / v_responsiveBoxGivenSize, vec2(.5));
      float maskX = smoothstep(0.0, pixel_thickness.x, mask.x);
      float maskY = smoothstep(0.0, pixel_thickness.y, mask.y);
      maskX = pow(maskX, .25);
      maskY = pow(maskY, .25);
      edge = clamp(1. - maskX * maskY, 0., 1.);

      uv = v_responsiveUV;
      if (ratio > 1.) {
        uv.y /= ratio;
      } else {
        uv.x *= ratio;
      }
      uv += .5;
      uv.y = 1. - uv.y;

      cycleWidth *= 2.;
      contOffset = 1.5;

    } else if (u_shape < 2.) {
      // circle
      vec2 shapeUV = uv - .5;
      shapeUV *= .67;
      edge = pow(clamp(3. * length(shapeUV), 0., 1.), 18.);
    } else if (u_shape < 3.) {
      // daisy
      vec2 shapeUV = uv - .5;
      shapeUV *= 1.68;

      float r = length(shapeUV) * 2.;
      float a = atan(shapeUV.y, shapeUV.x) + .2;
      r *= (1. + .05 * sin(3. * a + 2. * t));
      float f = abs(cos(a * 3.));
      edge = smoothstep(f, f + .7, r);
      edge *= edge;

      uv *= .8;
      cycleWidth *= 1.6;

    } else if (u_shape < 4.) {
      // diamond
      vec2 shapeUV = uv - .5;
      shapeUV = rotate(shapeUV, .25 * PI);
      shapeUV *= 1.42;
      shapeUV += .5;
      vec2 mask = min(shapeUV, 1. - shapeUV);
      vec2 pixel_thickness = vec2(.15);
      float maskX = smoothstep(0.0, pixel_thickness.x, mask.x);
      float maskY = smoothstep(0.0, pixel_thickness.y, mask.y);
      maskX = pow(maskX, .25);
      maskY = pow(maskY, .25);
      edge = clamp(1. - maskX * maskY, 0., 1.);
    } else if (u_shape < 5.) {
      // metaballs
      vec2 shapeUV = uv - .5;
      shapeUV *= 1.3;
      edge = 0.;
      for (int i = 0; i < 5; i++) {
        float fi = float(i);
        float speed = 1.5 + 2./3. * sin(fi * 12.345);
        float angle = -fi * 1.5;
        vec2 dir1 = vec2(cos(angle), sin(angle));
        vec2 dir2 = vec2(cos(angle + 1.57), sin(angle + 1.));
        vec2 traj = .4 * (dir1 * sin(t * speed + fi * 1.23) + dir2 * cos(t * (speed * 0.7) + fi * 2.17));
        float d = length(shapeUV + traj);
        edge += pow(1.0 - clamp(d, 0.0, 1.0), 4.0);
      }
      edge = 1. - smoothstep(.65, .9, edge);
      edge = pow(edge, 4.);
    }

    edge = mix(smoothstep(.9 - 2. * fwidth(edge), .9, edge), edge, smoothstep(0.0, 0.4, u_contour));

  }

  float opacity = 0.;
  if (u_isImage == true) {
    opacity = img.g;
    float frame = getImgFrame(v_imageUV, 0.);
    opacity *= frame;
  } else {
    opacity = 1. - smoothstep(.9 - 2. * fwidth(edge), .9, edge);
    if (u_shape < 2.) {
      edge = 1.2 * edge;
    } else if (u_shape < 5.) {
      edge = 1.8 * pow(edge, 1.5);
    }
  }

  float diagBLtoTR = rotatedUV.x - rotatedUV.y;
  float diagTLtoBR = rotatedUV.x + rotatedUV.y;

  vec3 color = vec3(0.);
  vec3 color1 = vec3(.98, 0.98, 1.);
  vec3 color2 = vec3(.1, .1, .1 + .1 * smoothstep(.7, 1.3, diagTLtoBR));

  vec2 grad_uv = uv - .5;

  float dist = length(grad_uv + vec2(0., .2 * diagBLtoTR));
  grad_uv = rotate(grad_uv, (.25 - .2 * diagBLtoTR) * PI);
  float direction = grad_uv.x;

  float bump = pow(1.8 * dist, 1.2);
  bump = 1. - bump;
  bump *= pow(uv.y, .3);


  float thin_strip_1_ratio = .12 / cycleWidth * (1. - .4 * bump);
  float thin_strip_2_ratio = .07 / cycleWidth * (1. + .4 * bump);
  float wide_strip_ratio = (1. - thin_strip_1_ratio - thin_strip_2_ratio);

  float thin_strip_1_width = cycleWidth * thin_strip_1_ratio;
  float thin_strip_2_width = cycleWidth * thin_strip_2_ratio;

  float noise = snoise(uv - t);

  edge += (1. - edge) * u_distortion * noise;

  direction += diagBLtoTR;
  float contour = 0.;
  direction -= 2. * noise * diagBLtoTR * (smoothstep(0., 1., edge) * (1.0 - smoothstep(0., 1., edge)));
  direction *= mix(1., 1. - edge, smoothstep(.5, 1., u_contour));
  direction -= 1.7 * edge * smoothstep(.5, 1., u_contour);
  direction += .2 * pow(u_contour, 4.) * (1.0 - smoothstep(0., 1., edge));

  bump *= clamp(pow(uv.y, .1), .3, 1.);
  direction *= (.1 + (1.1 - edge) * bump);

  direction *= (.4 + .6 * (1.0 - smoothstep(.5, 1., edge)));
  direction += .18 * (smoothstep(.1, .2, uv.y) * (1.0 - smoothstep(.2, .4, uv.y)));
  direction += .03 * (smoothstep(.1, .2, 1. - uv.y) * (1.0 - smoothstep(.2, .4, 1. - uv.y)));

  direction *= (.5 + .5 * pow(uv.y, 2.));
  direction *= cycleWidth;
  direction -= t;


  float colorDispersion = (1. - bump);
  colorDispersion = clamp(colorDispersion, 0., 1.);
  float dispersionRed = colorDispersion;
  dispersionRed += .03 * bump * noise;
  dispersionRed += 5. * (smoothstep(-.1, .2, uv.y) * (1.0 - smoothstep(.1, .5, uv.y))) * (smoothstep(.4, .6, bump) * (1.0 - smoothstep(.4, 1., bump)));
  dispersionRed -= diagBLtoTR;

  float dispersionBlue = colorDispersion;
  dispersionBlue *= 1.3;
  dispersionBlue += (smoothstep(0., .4, uv.y) * (1.0 - smoothstep(.1, .8, uv.y))) * (smoothstep(.4, .6, bump) * (1.0 - smoothstep(.4, .8, bump)));
  dispersionBlue -= .2 * edge;

  dispersionRed *= (u_shiftRed / 20.);
  dispersionBlue *= (u_shiftBlue / 20.);

  float blur = 0.;
  float rExtraBlur = 0.;
  float gExtraBlur = 0.;
  if (u_isImage == true) {
    float softness = 0.05 * u_softness;
    blur = softness + .5 * smoothstep(1., 10., u_repetition) * smoothstep(.0, 1., edge);
    float smallCanvasT = 1.0 - smoothstep(100., 500., min(u_resolution.x, u_resolution.y));
    blur += smallCanvasT * smoothstep(.0, 1., edge);
    rExtraBlur = softness * (0.05 + .1 * (u_shiftRed / 20.) * bump);
    gExtraBlur = softness * 0.05 / max(0.001, abs(1. - diagBLtoTR));
  } else {
    blur = u_softness / 15. + .3 * contour;
  }

  vec3 w = vec3(thin_strip_1_width, thin_strip_2_width, wide_strip_ratio);
  w[1] -= .02 * smoothstep(.0, 1., edge + bump);
  float stripe_r = fract(direction + dispersionRed);
  float r = getColorChanges(color1.r, color2.r, stripe_r, w, blur + fwidth(stripe_r) + rExtraBlur, bump, u_colorTint.r);
  float stripe_g = fract(direction);
  float g = getColorChanges(color1.g, color2.g, stripe_g, w, blur + fwidth(stripe_g) + gExtraBlur, bump, u_colorTint.g);
  float stripe_b = fract(direction - dispersionBlue);
  float b = getColorChanges(color1.b, color2.b, stripe_b, w, blur + fwidth(stripe_b), bump, u_colorTint.b);

  color = vec3(r, g, b);
  color *= opacity;

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1. - opacity);
  opacity = opacity + u_colorBack.a * (1. - opacity);

  ${Ye}

  fragColor = vec4(color, opacity);
}
`,Nc=`#version 300 es
precision mediump float;

uniform float u_rotation;

uniform float u_time;

uniform vec4 u_colorFront;
uniform vec4 u_colorBack;
uniform float u_radius;
uniform float u_contrast;

uniform sampler2D u_image;
uniform float u_imageAspectRatio;

uniform float u_size;
uniform float u_grainMixer;
uniform float u_grainOverlay;
uniform float u_grainSize;
uniform float u_grid;
uniform bool u_originalColors;
uniform bool u_inverted;
uniform float u_type;

in vec2 v_imageUV;

out vec4 fragColor;

${G}
${ge}
${zt}

float valueNoise(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  float x1 = mix(a, b, u.x);
  float x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

float lst(float edge0, float edge1, float x) {
  return clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0);
}

float sst(float edge0, float edge1, float x) {
  return smoothstep(edge0, edge1, x);
}

float getCircle(vec2 uv, float r, float baseR) {
  r = mix(.25 * baseR, 0., r);
  float d = length(uv - .5);
  float aa = fwidth(d);
  return 1. - smoothstep(r - aa, r + aa, d);
}

float getCell(vec2 uv) {
  float insideX = step(0.0, uv.x) * (1.0 - step(1.0, uv.x));
  float insideY = step(0.0, uv.y) * (1.0 - step(1.0, uv.y));
  return insideX * insideY;
}

float getCircleWithHole(vec2 uv, float r, float baseR) {
  float cell = getCell(uv);

  r = mix(.75 * baseR, 0., r);
  float rMod = mod(r, .5);

  float d = length(uv - .5);
  float aa = fwidth(d);
  float circle = 1. - smoothstep(rMod - aa, rMod + aa, d);
  if (r < .5) {
    return circle;
  } else {
    return cell - circle;
  }
}

float getGooeyBall(vec2 uv, float r, float baseR) {
  float d = length(uv - .5);
  float sizeRadius = .3;
  if (u_grid == 1.) {
    sizeRadius = .42;
  }
  sizeRadius = mix(sizeRadius * baseR, 0., r);
  d = 1. - sst(0., sizeRadius, d);

  d = pow(d, 2. + baseR);
  return d;
}

float getSoftBall(vec2 uv, float r, float baseR) {
  float d = length(uv - .5);
  float sizeRadius = clamp(baseR, 0., 1.);
  sizeRadius = mix(.5 * sizeRadius, 0., r);
  d = 1. - lst(0., sizeRadius, d);
  float powRadius = 1. - lst(0., 2., baseR);
  d = pow(d, 4. + 3. * powRadius);
  return d;
}

float getUvFrame(vec2 uv, vec2 pad) {
  float aa = 0.0001;

  float left   = smoothstep(-pad.x, -pad.x + aa, uv.x);
  float right  = smoothstep(1.0 + pad.x, 1.0 + pad.x - aa, uv.x);
  float bottom = smoothstep(-pad.y, -pad.y + aa, uv.y);
  float top    = smoothstep(1.0 + pad.y, 1.0 + pad.y - aa, uv.y);

  return left * right * bottom * top;
}

float sigmoid(float x, float k) {
  return 1.0 / (1.0 + exp(-k * (x - 0.5)));
}

float getLumAtPx(vec2 uv, float contrast) {
  vec4 tex = texture(u_image, uv);
  vec3 color = vec3(
  sigmoid(tex.r, contrast),
  sigmoid(tex.g, contrast),
  sigmoid(tex.b, contrast)
  );
  float lum = dot(vec3(0.2126, 0.7152, 0.0722), color);
  lum = mix(1., lum, tex.a);
  lum = u_inverted ? (1. - lum) : lum;
  return lum;
}

float getLumBall(vec2 p, vec2 pad, vec2 inCellOffset, float contrast, float baseR, float stepSize, out vec4 ballColor) {
  p += inCellOffset;
  vec2 uv_i = floor(p);
  vec2 uv_f = fract(p);
  vec2 samplingUV = (uv_i + .5 - inCellOffset) * pad + vec2(.5);
  float outOfFrame = getUvFrame(samplingUV, pad * stepSize);

  float lum = getLumAtPx(samplingUV, contrast);
  ballColor = texture(u_image, samplingUV);
  ballColor.rgb *= ballColor.a;
  ballColor *= outOfFrame;

  float ball = 0.;
  if (u_type == 0.) {
    // classic
    ball = getCircle(uv_f, lum, baseR);
  } else if (u_type == 1.) {
    // gooey
    ball = getGooeyBall(uv_f, lum, baseR);
  } else if (u_type == 2.) {
    // holes
    ball = getCircleWithHole(uv_f, lum, baseR);
  } else if (u_type == 3.) {
    // soft
    ball = getSoftBall(uv_f, lum, baseR);
  }

  return ball * outOfFrame;
}


void main() {

  float stepMultiplier = 1.;
  if (u_type == 0.) {
    // classic
    stepMultiplier = 2.;
  } else if (u_type == 1. || u_type == 3.) {
    // gooey & soft
    stepMultiplier = 6.;
  }

  float cellsPerSide = mix(300., 7., pow(u_size, .7));
  cellsPerSide /= stepMultiplier;
  float cellSizeY = 1. / cellsPerSide;
  vec2 pad = cellSizeY * vec2(1. / u_imageAspectRatio, 1.);
  if (u_type == 1. && u_grid == 1.) {
    // gooey diagonal grid works differently
    pad *= .7;
  }

  vec2 uv = v_imageUV;
  uv -= vec2(.5);
  uv /= pad;

  float contrast = mix(0., 15., pow(u_contrast, 1.5));
  float baseRadius = u_radius;
  if (u_originalColors == true) {
    contrast = mix(.1, 4., pow(u_contrast, 2.));
    baseRadius = 2. * pow(.5 * u_radius, .3);
  }

  float totalShape = 0.;
  vec3 totalColor = vec3(0.);
  float totalOpacity = 0.;

  vec4 ballColor;
  float shape;
  float stepSize = 1. / stepMultiplier;
  for (float x = -0.5; x < 0.5; x += stepSize) {
    for (float y = -0.5; y < 0.5; y += stepSize) {
      vec2 offset = vec2(x, y);

      if (u_grid == 1.) {
        float rowIndex = floor((y + .5) / stepSize);
        float colIndex = floor((x + .5) / stepSize);
        if (stepSize == 1.) {
          rowIndex = floor(uv.y + y + 1.);
          if (u_type == 1.) {
            colIndex = floor(uv.x + x + 1.);
          }
        }
        if (u_type == 1.) {
          if (mod(rowIndex + colIndex, 2.) == 1.) {
            continue;
          }
        } else {
          if (mod(rowIndex, 2.) == 1.) {
            offset.x += .5 * stepSize;
          }
        }
      }

      shape = getLumBall(uv, pad, offset, contrast, baseRadius, stepSize, ballColor);
      totalColor   += ballColor.rgb * shape;
      totalShape   += shape;
      totalOpacity += shape;
    }
  }

  const float eps = 1e-4;

  totalColor /= max(totalShape, eps);
  totalOpacity /= max(totalShape, eps);

  float finalShape = 0.;
  if (u_type == 0.) {
    finalShape = min(1., totalShape);
  } else if (u_type == 1.) {
    float aa = fwidth(totalShape);
    float th = .5;
    finalShape = smoothstep(th - aa, th + aa, totalShape);
  } else if (u_type == 2.) {
    finalShape = min(1., totalShape);
  } else if (u_type == 3.) {
    finalShape = totalShape;
  }

  vec2 grainSize = mix(2000., 200., u_grainSize) * vec2(1., 1. / u_imageAspectRatio);
  vec2 grainUV = v_imageUV - .5;
  grainUV *= grainSize;
  grainUV += .5;
  float grain = valueNoise(grainUV);
  grain = smoothstep(.55, .7 + .2 * u_grainMixer, grain);
  grain *= u_grainMixer;
  finalShape = mix(finalShape, 0., grain);

  vec3 color = vec3(0.);
  float opacity = 0.;

  if (u_originalColors == true) {
    color = totalColor * finalShape;
    opacity = totalOpacity * finalShape;

    vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
    color = color + bgColor * (1. - opacity);
    opacity = opacity + u_colorBack.a * (1. - opacity);
  } else {
    vec3 fgColor = u_colorFront.rgb * u_colorFront.a;
    float fgOpacity = u_colorFront.a;
    vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
    float bgOpacity = u_colorBack.a;

    color = fgColor * finalShape;
    opacity = fgOpacity * finalShape;
    color += bgColor * (1. - opacity);
    opacity += bgOpacity * (1. - opacity);
  }

  float grainOverlay = valueNoise(rotate(grainUV, 1.) + vec2(3.));
  grainOverlay = mix(grainOverlay, valueNoise(rotate(grainUV, 2.) + vec2(-1.)), .5);
  grainOverlay = pow(grainOverlay, 1.3);

  float grainOverlayV = grainOverlay * 2. - 1.;
  vec3 grainOverlayColor = vec3(step(0., grainOverlayV));
  float grainOverlayStrength = u_grainOverlay * abs(grainOverlayV);
  grainOverlayStrength = pow(grainOverlayStrength, .8);
  color = mix(color, grainOverlayColor, .5 * grainOverlayStrength);

  opacity += .5 * grainOverlayStrength;
  opacity = clamp(opacity, 0., 1.);

  fragColor = vec4(color, opacity);
}
`,Ec=`#version 300 es
precision mediump float;

uniform sampler2D u_image;
uniform float u_imageAspectRatio;

uniform vec4 u_colorBack;
uniform vec4 u_colorC;
uniform vec4 u_colorM;
uniform vec4 u_colorY;
uniform vec4 u_colorK;
uniform float u_size;
uniform float u_minDot;
uniform float u_contrast;
uniform float u_grainSize;
uniform float u_grainMixer;
uniform float u_grainOverlay;
uniform float u_gridNoise;
uniform float u_softness;
uniform float u_floodC;
uniform float u_floodM;
uniform float u_floodY;
uniform float u_floodK;
uniform float u_gainC;
uniform float u_gainM;
uniform float u_gainY;
uniform float u_gainK;
uniform float u_type;
uniform sampler2D u_noiseTexture;

in vec2 v_imageUV;
out vec4 fragColor;

const float shiftC = -.5;
const float shiftM = -.25;
const float shiftY = .2;
const float shiftK = 0.;

// Precomputed sin/cos for rotation angles (15°, 75°, 0°, 45°)
const float cosC = 0.9659258;  const float sinC = 0.2588190;   // 15°
const float cosM = 0.2588190;  const float sinM = 0.9659258;   // 75°
const float cosY = 1.0;        const float sinY = 0.0;         // 0°
const float cosK = 0.7071068;  const float sinK = 0.7071068;   // 45°

${G}

vec2 randomRG(vec2 p) {
  vec2 uv = floor(p) / 100. + .5;
  return texture(u_noiseTexture, fract(uv)).rg;
}
vec3 hash23(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * vec3(0.3183099, 0.3678794, 0.3141592)) + 0.1;
  p3 += dot(p3, p3.yzx + 19.19);
  return fract(vec3(p3.x * p3.y, p3.y * p3.z, p3.z * p3.x));
}

float sst(float edge0, float edge1, float x) {
  return smoothstep(edge0, edge1, x);
}

vec3 valueNoise3(vec2 st) {
  vec2 i = floor(st);
  vec2 f = fract(st);
  vec3 a = hash23(i);
  vec3 b = hash23(i + vec2(1.0, 0.0));
  vec3 c = hash23(i + vec2(0.0, 1.0));
  vec3 d = hash23(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  vec3 x1 = mix(a, b, u.x);
  vec3 x2 = mix(c, d, u.x);
  return mix(x1, x2, u.y);
}

float getUvFrame(vec2 uv, vec2 pad) {
  float left   = smoothstep(-pad.x, 0., uv.x);
  float right  = smoothstep(1. + pad.x, 1., uv.x);
  float bottom = smoothstep(-pad.y, 0., uv.y);
  float top    = smoothstep(1. + pad.y, 1., uv.y);

  return left * right * bottom * top;
}

vec4 RGBAtoCMYK(vec4 rgba) {
  float k = 1. - max(max(rgba.r, rgba.g), rgba.b);
  float denom = 1. - k;
  vec3 cmy = vec3(0.);
  if (denom > 1e-5) {
    cmy = (1. - rgba.rgb - vec3(k)) / denom;
  }
  return vec4(cmy, k) * rgba.a;
}

vec3 applyContrast(vec3 rgb) {
  return clamp((rgb - 0.5) * u_contrast + 0.5, 0.0, 1.0);
}

// Single-component CMYK extractors with contrast built-in, alpha-aware
float getCyan(vec4 rgba) {
  vec3 c = clamp((rgba.rgb - 0.5) * u_contrast + 0.5, 0.0, 1.0);
  float maxRGB = max(max(c.r, c.g), c.b);
  return (maxRGB > 1e-5 ? (maxRGB - c.r) / maxRGB : 0.) * rgba.a;
}
float getMagenta(vec4 rgba) {
  vec3 c = clamp((rgba.rgb - 0.5) * u_contrast + 0.5, 0.0, 1.0);
  float maxRGB = max(max(c.r, c.g), c.b);
  return (maxRGB > 1e-5 ? (maxRGB - c.g) / maxRGB : 0.) * rgba.a;
}
float getYellow(vec4 rgba) {
  vec3 c = clamp((rgba.rgb - 0.5) * u_contrast + 0.5, 0.0, 1.0);
  float maxRGB = max(max(c.r, c.g), c.b);
  return (maxRGB > 1e-5 ? (maxRGB - c.b) / maxRGB : 0.) * rgba.a;
}
float getBlack(vec4 rgba) {
  vec3 c = clamp((rgba.rgb - 0.5) * u_contrast + 0.5, 0.0, 1.0);
  return (1. - max(max(c.r, c.g), c.b)) * rgba.a;
}

vec2 cellCenterPos(vec2 uv, vec2 cellOffset, float channelIdx) {
  vec2 cellCenter = floor(uv) + .5 + cellOffset;
  return cellCenter + (randomRG(cellCenter + channelIdx * 50.) - .5) * u_gridNoise;
}

vec2 gridToImageUV(vec2 cellCenter, float cosA, float sinA, float shift, vec2 pad) {
  vec2 uvGrid = mat2(cosA, -sinA, sinA, cosA) * (cellCenter - shift);
  return uvGrid * pad + 0.5;
}

void colorMask(vec2 pos, vec2 cellCenter, float rad, float transparency, float grain, float channelAddon, float channelgain, float generalComp, bool isJoined, inout float outMask) {
  float dist = length(pos - cellCenter);

  float radius = rad;
  radius *= (1. + generalComp);
  radius += (.15 + channelgain * radius);
  radius = max(0., radius);
  radius = mix(0., radius, transparency);
  radius += channelAddon;
  radius *= (1. - grain);

  float mask = 1. - sst(0., radius, dist);
  if (isJoined) {
    // ink or sharp (joined)
    mask = pow(mask, 1.2);
  } else {
    // dots (separate)
    mask = sst(.5 - .5 * u_softness, .51 + .49 * u_softness, mask);
  }

  mask *= mix(1., mix(.5, 1., 1.5 * radius), u_softness);
  outMask += mask;
}

vec3 applyInk(vec3 paper, vec3 inkColor, float cov) {
  vec3 inkEffect = mix(vec3(1.0), inkColor, clamp(cov, 0.0, 1.0));
  return paper * inkEffect;
}

void main() {
  vec2 uv = v_imageUV;

  float cellsPerSide = mix(400.0, 7.0, pow(u_size, 0.7));
  float cellSizeY = 1.0 / cellsPerSide;
  vec2 pad = cellSizeY * vec2(1.0 / u_imageAspectRatio, 1.0);
  vec2 uvGrid = (uv - .5) / pad;
  float insideImageBox = getUvFrame(uv, pad);

  float generalComp = .1 * u_softness + .1 * u_gridNoise + .1 * (1. - step(0.5, u_type)) * (1.5 - u_softness);

  vec2 uvC = mat2(cosC, sinC, -sinC, cosC) * uvGrid + shiftC;
  vec2 uvM = mat2(cosM, sinM, -sinM, cosM) * uvGrid + shiftM;
  vec2 uvY = mat2(cosY, sinY, -sinY, cosY) * uvGrid + shiftY;
  vec2 uvK = mat2(cosK, sinK, -sinK, cosK) * uvGrid + shiftK;

  vec2 grainSize = mix(2000., 200., u_grainSize) * vec2(1., 1. / u_imageAspectRatio);
  vec2 grainUV = (v_imageUV - .5) * grainSize + .5;
  vec3 noiseValues = valueNoise3(grainUV);
  float grain = sst(.55, 1., noiseValues.r);
  grain *= u_grainMixer;

  vec4 outMask = vec4(0.);
  bool isJoined = u_type > 0.5;

  if (u_type < 1.5) {
    // dots or ink: per-cell color sampling
    for (int dy = -1; dy <= 1; dy++) {
      for (int dx = -1; dx <= 1; dx++) {
        vec2 cellOffset = vec2(float(dx), float(dy));

        vec2 cellCenterC = cellCenterPos(uvC, cellOffset, 0.);
        vec4 texC = texture(u_image, gridToImageUV(cellCenterC, cosC, sinC, shiftC, pad));
        colorMask(uvC, cellCenterC, getCyan(texC), insideImageBox * texC.a, grain, u_floodC, u_gainC, generalComp, isJoined, outMask[0]);

        vec2 cellCenterM = cellCenterPos(uvM, cellOffset, 1.);
        vec4 texM = texture(u_image, gridToImageUV(cellCenterM, cosM, sinM, shiftM, pad));
        colorMask(uvM, cellCenterM, getMagenta(texM), insideImageBox * texM.a, grain, u_floodM, u_gainM, generalComp, isJoined, outMask[1]);

        vec2 cellCenterY = cellCenterPos(uvY, cellOffset, 2.);
        vec4 texY = texture(u_image, gridToImageUV(cellCenterY, cosY, sinY, shiftY, pad));
        colorMask(uvY, cellCenterY, getYellow(texY), insideImageBox * texY.a, grain, u_floodY, u_gainY, generalComp, isJoined, outMask[2]);

        vec2 cellCenterK = cellCenterPos(uvK, cellOffset, 3.);
        vec4 texK = texture(u_image, gridToImageUV(cellCenterK, cosK, sinK, shiftK, pad));
        colorMask(uvK, cellCenterK, getBlack(texK), insideImageBox * texK.a, grain, u_floodK, u_gainK, generalComp, isJoined, outMask[3]);
      }
    }
  } else {
    // sharp: direct px color sampling
    vec4 tex = texture(u_image, uv);
    tex.rgb = applyContrast(tex.rgb);
    insideImageBox *= tex.a;
    vec4 cmykOriginal = RGBAtoCMYK(tex);
    for (int dy = -1; dy <= 1; dy++) {
      for (int dx = -1; dx <= 1; dx++) {
        vec2 cellOffset = vec2(float(dx), float(dy));

        colorMask(uvC, cellCenterPos(uvC, cellOffset, 0.), cmykOriginal.x, insideImageBox, grain, u_floodC, u_gainC, generalComp, isJoined, outMask[0]);
        colorMask(uvM, cellCenterPos(uvM, cellOffset, 1.), cmykOriginal.y, insideImageBox, grain, u_floodM, u_gainM, generalComp, isJoined, outMask[1]);
        colorMask(uvY, cellCenterPos(uvY, cellOffset, 2.), cmykOriginal.z, insideImageBox, grain, u_floodY, u_gainY, generalComp, isJoined, outMask[2]);
        colorMask(uvK, cellCenterPos(uvK, cellOffset, 3.), cmykOriginal.w, insideImageBox, grain, u_floodK, u_gainK, generalComp, isJoined, outMask[3]);
      }
    }
  }

  float shape;

  float C = outMask[0];
  float M = outMask[1];
  float Y = outMask[2];
  float K = outMask[3];

  if (isJoined) {
    // ink or sharp: apply threshold for joined dots
    float th = .5;
    float sLeft = th * u_softness;
    float sRight = (1. - th) * u_softness + .01;
    C = smoothstep(th - sLeft - fwidth(C), th + sRight, C);
    M = smoothstep(th - sLeft - fwidth(M), th + sRight, M);
    Y = smoothstep(th - sLeft - fwidth(Y), th + sRight, Y);
    K = smoothstep(th - sLeft - fwidth(K), th + sRight, K);
  }

  C *= u_colorC.a;
  M *= u_colorM.a;
  Y *= u_colorY.a;
  K *= u_colorK.a;

  vec3 ink = vec3(1.);
  ink = applyInk(ink, u_colorK.rgb, K);
  ink = applyInk(ink, u_colorC.rgb, C);
  ink = applyInk(ink, u_colorM.rgb, M);
  ink = applyInk(ink, u_colorY.rgb, Y);

  shape = clamp(max(max(C, M), max(Y, K)), 0., 1.);

  vec3 color = u_colorBack.rgb * u_colorBack.a;

  float opacity = u_colorBack.a;
  color = mix(color, ink, shape);
  opacity += shape;
  opacity = clamp(opacity, 0., 1.);

  float grainOverlay = mix(noiseValues.g, noiseValues.b, .5);
  grainOverlay = pow(grainOverlay, 1.3);

  float grainOverlayV = grainOverlay * 2. - 1.;
  vec3 grainOverlayColor = vec3(step(0., grainOverlayV));
  float grainOverlayStrength = u_grainOverlay * abs(grainOverlayV);
  grainOverlayStrength = pow(grainOverlayStrength, .8);
  color = mix(color, grainOverlayColor, .5 * grainOverlayStrength);

  opacity += .5 * grainOverlayStrength;
  opacity = clamp(opacity, 0., 1.);

  fragColor = vec4(color, opacity);
}
`,Lr={maxColorCount:6},Lc=`#version 300 es
precision mediump float;

in mediump vec2 v_imageUV;
in mediump vec2 v_objectUV;
in mediump vec2 v_responsiveUV;
in mediump vec2 v_responsiveBoxGivenSize;
out vec4 fragColor;

// Image
uniform sampler2D u_image;
uniform float u_imageAspectRatio;

// Canvas
uniform vec2 u_resolution;
uniform float u_time;

// Colors
uniform vec4 u_colors[${Lr.maxColorCount}];
uniform float u_colorsCount;
uniform vec4 u_colorBack;
uniform vec4 u_colorInner;

// Effect controls
uniform float u_innerDistortion;
uniform float u_outerDistortion;
uniform float u_outerGlow;
uniform float u_innerGlow;
uniform float u_offset;
uniform float u_angle;
uniform float u_size;

// Shape controls
uniform float u_shape;
uniform bool u_isImage;

${G}
${ge}

// 9x9 Gaussian blur on R and G channels
vec2 gaussBlur9x9RG(sampler2D tex, vec2 uv, vec2 dudx, vec2 dudy, float radius) {
  vec2 texel = 1.0 / vec2(textureSize(tex, 0));
  vec2 r = max(radius, 0.0) * texel;
  // Pascal's row 8: sum = 256, 2D norm = 65536
  const float k[9] = float[9](1.0, 8.0, 28.0, 56.0, 70.0, 56.0, 28.0, 8.0, 1.0);
  vec2 sum = vec2(0.0);

  for (int j = -4; j <= 4; ++j) {
    float wy = k[j + 4];
    for (int i = -4; i <= 4; ++i) {
      float w = k[i + 4] * wy;
      vec2 off = vec2(float(i) * r.x, float(j) * r.y);
      sum += w * texture(tex, uv + off).rg;
    }
  }

  return sum / 65536.0;
}

float sst(float a, float b, float x) {
  return smoothstep(a, b, x);
}

void main() {
  float time = u_time;

  float roundness = 0.;
  float imgAlpha = 0.;

  if (u_isImage == true) {
    // Image sampling (UV scaled inward to account for padding)
    vec2 imageUV = v_imageUV;
    imageUV -= .5;
    imageUV *= .95;
    imageUV += .5;

    vec2 dudx = dFdx(v_imageUV);
    vec2 dudy = dFdy(v_imageUV);

    // Blurred image: x = roundness, y = alpha
    vec2 blurred = gaussBlur9x9RG(u_image, imageUV, dudx, dudy, 10.);
    roundness = 1. - blurred.x;
    vec2 texelA = 1.0 / vec2(textureSize(u_image, 0));
    const float k3[3] = float[3](1.0, 2.0, 1.0);
    for (int j = -1; j <= 1; ++j) {
      for (int i = -1; i <= 1; ++i) {
        imgAlpha += k3[i + 1] * k3[j + 1] * texture(u_image, imageUV + vec2(float(i) * texelA.x, float(j) * texelA.y)).g;
      }
    }
    imgAlpha /= 16.0;
  } else {
    vec2 uv = v_objectUV + .5;
    uv.y = 1. - uv.y;
    float edge = 0.;

    if (u_shape < 1.) {
      // full-fill on canvas
      vec2 borderUV = v_responsiveUV + .5;
      vec2 mask = min(borderUV, 1. - borderUV);
      vec2 pixel_thickness = min(250. / v_responsiveBoxGivenSize, vec2(.5));
      float maskX = smoothstep(0.0, pixel_thickness.x, mask.x);
      float maskY = smoothstep(0.0, pixel_thickness.y, mask.y);
      maskX = pow(maskX, .25);
      maskY = pow(maskY, .25);
      edge = clamp(1. - maskX * maskY, 0., 1.);
    } else if (u_shape < 2.) {
      // circle
      vec2 shapeUV = uv - .5;
      shapeUV *= .67;
      edge = pow(clamp(3. * length(shapeUV), 0., 1.), 18.);
    } else if (u_shape < 3.) {
      // daisy
      vec2 shapeUV = uv - .5;
      shapeUV *= 1.68;

      float r = length(shapeUV) * 2.;
      float a = atan(shapeUV.y, shapeUV.x) + .2;
      r *= (1. + .05 * sin(3. * a + 2. * time));
      float f = abs(cos(a * 3.));
      edge = smoothstep(f, f + .7, r);
      edge *= edge;
    } else if (u_shape < 4.) {
      // diamond
      vec2 shapeUV = uv - .5;
      shapeUV = rotate(shapeUV, .25 * PI);
      shapeUV *= 1.42;
      shapeUV += .5;
      vec2 mask = min(shapeUV, 1. - shapeUV);
      vec2 pixel_thickness = vec2(.15);
      float maskX = smoothstep(0.0, pixel_thickness.x, mask.x);
      float maskY = smoothstep(0.0, pixel_thickness.y, mask.y);
      maskX = pow(maskX, .25);
      maskY = pow(maskY, .25);
      edge = clamp(1. - maskX * maskY, 0., 1.);
    } else if (u_shape < 5.) {
      // metaballs
      vec2 shapeUV = uv - .5;
      shapeUV *= 1.3;
      edge = 0.;
      for (int i = 0; i < 5; i++) {
        float fi = float(i);
        float speed = 1.5 + 2./3. * sin(fi * 12.345);
        float angle = -fi * 1.5;
        vec2 dir1 = vec2(cos(angle), sin(angle));
        vec2 dir2 = vec2(cos(angle + 1.57), sin(angle + 1.));
        vec2 traj = .4 * (dir1 * sin(time * speed + fi * 1.23) + dir2 * cos(time * (speed * 0.7) + fi * 2.17));
        float d = length(shapeUV + traj);
        edge += pow(1.0 - clamp(d, 0.0, 1.0), 4.0);
      }
      edge = 1. - smoothstep(.65, .9, edge);
      edge = pow(edge, 4.);
    }

    imgAlpha = 1. - smoothstep(.9 - 2. * fwidth(edge), .9, edge);
    roundness = 1. - edge;
  }

// Smoke UV setup
  vec2 smokeUV = v_objectUV;
  smokeUV = rotate(smokeUV, u_angle * PI / 180.);
  smokeUV *= mix(4., 1., u_size);

  // Two swirl paths: inner (shape-masked) and outer (free), each with independent distortion
  vec2 innerUV = smokeUV;
  vec2 outerUV = smokeUV;

  // Vertical displacement — applied independently to inner and outer
  innerUV.y += u_innerDistortion * (1. - sst(0., 1., length(.4 * innerUV)));
  innerUV.y -= .4 * u_innerDistortion;
  innerUV.y += .7 * u_offset * roundness;

  outerUV.y += u_outerDistortion * (1. - sst(0., 1., length(.4 * outerUV)));
  outerUV.y -= .4 * u_outerDistortion;

  float innerSwirl = u_innerDistortion * roundness;
  float outerSwirl = u_outerDistortion;

  for (int i = 1; i < 5; i++) {
    float fi = float(i);

    float stretchIn = max(length(dFdx(innerUV)), length(dFdy(innerUV)));
    float dampenIn = 1. / (1. + stretchIn * 8.);
    float sIn = innerSwirl * dampenIn;
    innerUV.x += sIn / fi * cos(time + fi * 2.9 * innerUV.y);
    innerUV.y += sIn / fi * cos(time + fi * 1.5 * innerUV.x);

    float stretchOut = max(length(dFdx(outerUV)), length(dFdy(outerUV)));
    float dampenOut = 1. / (1. + stretchOut * 8.);
    float sOut = outerSwirl * dampenOut;
    outerUV.x += sOut / fi * cos(time + fi * 2.9 * outerUV.y);
    outerUV.y += sOut / fi * cos(time + fi * 1.5 * outerUV.x);
  }

  // Smoke shapes from swirl fields
  float innerShape = exp(-1.5 * dot(innerUV, innerUV));
  float outerShape = exp(-1.5 * dot(outerUV, outerUV));

  // Visibility masks
  float outerMask = pow(u_outerGlow, 2.) * (1. - imgAlpha);
  float innerMask = (.01 + .99 * u_innerGlow) * imgAlpha;

  innerShape *= innerMask;
  outerShape *= outerMask;

  // Color gradient
  float mixer = (innerShape + outerShape) * u_colorsCount;
  vec4 gradient = u_colors[0];
  gradient.rgb *= gradient.a;

  float smokeMask = 0.;
  for (int i = 1; i < ${Lr.maxColorCount+1}; i++) {
    if (i > int(u_colorsCount)) break;

    float m = sst(0., 1., clamp(mixer - float(i - 1), 0., 1.));
    if (i == 1) smokeMask = m;

    vec4 c = u_colors[i - 1];
    c.rgb *= c.a;
    gradient = mix(gradient, c, m);
  }

  // Compositing (premultiplied alpha, front-to-back)
  vec3 color = gradient.rgb * smokeMask;
  float opacity = gradient.a * smokeMask;

  float innerOpacity = u_colorInner.a * imgAlpha;
  vec3 innerColor = u_colorInner.rgb * innerOpacity;
  color += innerColor * (1.0 - opacity);
  opacity += innerOpacity * (1.0 - opacity);

  vec3 backColor = u_colorBack.rgb * u_colorBack.a;
  color += backColor * (1.0 - opacity);
  opacity += u_colorBack.a * (1.0 - opacity);

  fragColor = vec4(color, opacity);
}
`,$c=`#version 300 es
precision mediump float;

layout(location = 0) in vec4 a_position;

uniform vec2 u_resolution;
uniform float u_pixelRatio;
uniform float u_imageAspectRatio;
uniform float u_originX;
uniform float u_originY;
uniform float u_worldWidth;
uniform float u_worldHeight;
uniform float u_fit;
uniform float u_scale;
uniform float u_rotation;
uniform float u_offsetX;
uniform float u_offsetY;

out vec2 v_objectUV;
out vec2 v_objectBoxSize;
out vec2 v_responsiveUV;
out vec2 v_responsiveBoxGivenSize;
out vec2 v_patternUV;
out vec2 v_patternBoxSize;
out vec2 v_imageUV;

vec3 getBoxSize(float boxRatio, vec2 givenBoxSize) {
  vec2 box = vec2(0.);
  box.x = boxRatio * min(givenBoxSize.x / boxRatio, givenBoxSize.y);
  float noFitBoxWidth = box.x;
  if (u_fit == 1.) {
    box.x = boxRatio * min(u_resolution.x / boxRatio, u_resolution.y);
  } else if (u_fit == 2.) {
    box.x = boxRatio * max(u_resolution.x / boxRatio, u_resolution.y);
  }
  box.y = box.x / boxRatio;
  return vec3(box, noFitBoxWidth);
}

void main() {
  gl_Position = a_position;

  vec2 uv = gl_Position.xy * .5;
  vec2 boxOrigin = vec2(.5 - u_originX, u_originY - .5);
  vec2 givenBoxSize = vec2(u_worldWidth, u_worldHeight);
  givenBoxSize = max(givenBoxSize, vec2(1.)) * u_pixelRatio;
  float r = u_rotation * 3.14159265358979323846 / 180.;
  mat2 graphicRotation = mat2(cos(r), sin(r), -sin(r), cos(r));
  vec2 graphicOffset = vec2(-u_offsetX, u_offsetY);

  float fixedRatio = 1.;
  vec2 fixedRatioBoxGivenSize = vec2(
  (u_worldWidth == 0.) ? u_resolution.x : givenBoxSize.x,
  (u_worldHeight == 0.) ? u_resolution.y : givenBoxSize.y
  );

  v_objectBoxSize = getBoxSize(fixedRatio, fixedRatioBoxGivenSize).xy;
  vec2 objectWorldScale = u_resolution.xy / v_objectBoxSize;

  v_objectUV = uv;
  v_objectUV *= objectWorldScale;
  v_objectUV += boxOrigin * (objectWorldScale - 1.);
  v_objectUV += graphicOffset;
  v_objectUV /= u_scale;
  v_objectUV = graphicRotation * v_objectUV;

  v_responsiveBoxGivenSize = vec2(
  (u_worldWidth == 0.) ? u_resolution.x : givenBoxSize.x,
  (u_worldHeight == 0.) ? u_resolution.y : givenBoxSize.y
  );
  float responsiveRatio = v_responsiveBoxGivenSize.x / v_responsiveBoxGivenSize.y;
  vec2 responsiveBoxSize = getBoxSize(responsiveRatio, v_responsiveBoxGivenSize).xy;
  vec2 responsiveBoxScale = u_resolution.xy / responsiveBoxSize;

  #ifdef ADD_HELPERS
  v_responsiveHelperBox = uv;
  v_responsiveHelperBox *= responsiveBoxScale;
  v_responsiveHelperBox += boxOrigin * (responsiveBoxScale - 1.);
  #endif

  v_responsiveUV = uv;
  v_responsiveUV *= responsiveBoxScale;
  v_responsiveUV += boxOrigin * (responsiveBoxScale - 1.);
  v_responsiveUV += graphicOffset;
  v_responsiveUV /= u_scale;
  v_responsiveUV.x *= responsiveRatio;
  v_responsiveUV = graphicRotation * v_responsiveUV;
  v_responsiveUV.x /= responsiveRatio;

  float patternBoxRatio = givenBoxSize.x / givenBoxSize.y;
  vec2 patternBoxGivenSize = vec2(
  (u_worldWidth == 0.) ? u_resolution.x : givenBoxSize.x,
  (u_worldHeight == 0.) ? u_resolution.y : givenBoxSize.y
  );
  patternBoxRatio = patternBoxGivenSize.x / patternBoxGivenSize.y;

  vec3 boxSizeData = getBoxSize(patternBoxRatio, patternBoxGivenSize);
  v_patternBoxSize = boxSizeData.xy;
  float patternBoxNoFitBoxWidth = boxSizeData.z;
  vec2 patternBoxScale = u_resolution.xy / v_patternBoxSize;

  v_patternUV = uv;
  v_patternUV += graphicOffset / patternBoxScale;
  v_patternUV += boxOrigin;
  v_patternUV -= boxOrigin / patternBoxScale;
  v_patternUV *= u_resolution.xy;
  v_patternUV /= u_pixelRatio;
  if (u_fit > 0.) {
    v_patternUV *= (patternBoxNoFitBoxWidth / v_patternBoxSize.x);
  }
  v_patternUV /= u_scale;
  v_patternUV = graphicRotation * v_patternUV;
  v_patternUV += boxOrigin / patternBoxScale;
  v_patternUV -= boxOrigin;
  v_patternUV *= .01;

  vec2 imageBoxSize;
  if (u_fit == 1.) {
    imageBoxSize.x = min(u_resolution.x / u_imageAspectRatio, u_resolution.y) * u_imageAspectRatio;
  } else if (u_fit == 2.) {
    imageBoxSize.x = max(u_resolution.x / u_imageAspectRatio, u_resolution.y) * u_imageAspectRatio;
  } else {
    imageBoxSize.x = min(10.0, 10.0 / u_imageAspectRatio * u_imageAspectRatio);
  }
  imageBoxSize.y = imageBoxSize.x / u_imageAspectRatio;
  vec2 imageBoxScale = u_resolution.xy / imageBoxSize;

  v_imageUV = uv;
  v_imageUV *= imageBoxScale;
  v_imageUV += boxOrigin * (imageBoxScale - 1.);
  v_imageUV += graphicOffset;
  v_imageUV /= u_scale;
  v_imageUV.x *= u_imageAspectRatio;
  v_imageUV = graphicRotation * v_imageUV;
  v_imageUV.x /= u_imageAspectRatio;

  v_imageUV += .5;
  v_imageUV.y = 1. - v_imageUV.y;
}
`;function er(a,e){return{u_pixelRatio:1,u_imageAspectRatio:e,u_originX:a.originX,u_originY:a.originY,u_worldWidth:a.worldWidth,u_worldHeight:a.worldHeight,u_fit:fc[a.fit],u_scale:a.scale,u_rotation:a.rotation,u_offsetX:a.offsetX,u_offsetY:a.offsetY}}const Je=er(uc,1),Ze=er(Ln,1),lt={...er(Ln,1),u_isImage:1};function O(a,e,t,o,i,r){return{name:a,label:e,type:"number",default:t,min:o,max:i,step:r}}function P(a,e,t){return{name:a,label:e,type:"color",default:t,min:0,max:1,step:1}}function ce(a){return a.map((e,t)=>P(`color${t+1}`,`Color ${t+1}`,e))}function kt(a,e,t){return{uniform:a,countUniform:e,max:t}}const et="u_noiseTexture",ct="u_image",ut=kt("u_colors","u_colorsCount",10),jc=[{id:"paper-mesh-gradient",name:"Mesh Gradient",category:"fill",glsl:dc,staticUniforms:Ze,colorArrayParams:ut,params:[...ce(["#e0eaff","#241d9a","#f75092","#9f50d3"]),O("distortion","Distortion",.8,0,1,.01),O("swirl","Swirl",.6,0,1,.01),O("grainOverlay","Grain",0,0,1,.01)]},{id:"paper-static-mesh-gradient",name:"Static Mesh Gradient",category:"fill",glsl:Mc,staticUniforms:Ze,colorArrayParams:ut,params:[...ce(["#ffad0a","#6200ff","#e2a3ff","#ff99fd"]),O("positions","Positions",3,0,8,.1),O("waveX","Wave X",.5,0,1,.01),O("waveY","Wave Y",.5,0,1,.01)]},{id:"paper-static-radial-gradient",name:"Static Radial Gradient",category:"fill",glsl:Bc,staticUniforms:Ze,colorArrayParams:ut,params:[...ce(["#00bbff","#00ffe1","#ffffff"]),P("colorBack","Background","#000000"),O("radius","Radius",.5,0,2,.01),O("falloff","Falloff",0,-1,1,.01),O("mixing","Mixing",.5,0,1,.01)]},{id:"paper-smoke-ring",name:"Smoke Ring",category:"fill",glsl:mc,staticUniforms:Ze,colorArrayParams:ut,needsNoiseTexture:et,params:[...ce(["#ffffff","#ffca0a","#fc6203"]),P("colorBack","Background","#000000"),O("radius","Radius",.5,0,1,.01),O("thickness","Thickness",.5,0,1,.01),O("noiseScale","Noise Scale",1.6,0,4,.01)]},{id:"paper-neuro-noise",name:"Neuro Noise",category:"fill",glsl:hc,staticUniforms:Je,params:[P("colorFront","Front","#ffffff"),P("colorMid","Mid","#47a6ff"),P("colorBack","Background","#000000"),O("brightness","Brightness",1.3,0,3,.01),O("contrast","Contrast",1,0,3,.01)]},{id:"paper-metaballs",name:"Metaballs",category:"fill",glsl:_c,staticUniforms:Ze,colorArrayParams:kt("u_colors","u_colorsCount",8),needsNoiseTexture:et,params:[...ce(["#6e33cc","#ff5500","#ffc105"]),P("colorBack","Background","#000000"),O("count","Count",6,1,8,1),O("size","Size",1,0,1,.01),O("sizeRange","Size Range",.5,0,1,.01)]},{id:"paper-god-rays",name:"God Rays",category:"fill",glsl:kc,staticUniforms:Ze,colorArrayParams:kt("u_colors","u_colorsCount",5),needsNoiseTexture:et,params:[...ce(["#a600ff","#6200ff","#33fff5"]),P("colorBack","Background","#000000"),O("intensity","Intensity",1,0,2,.01),O("density","Density",.4,0,1,.01),O("spotty","Spotty",.3,0,1,.01)]},{id:"paper-spiral",name:"Spiral",category:"fill",glsl:Cc,staticUniforms:Je,params:[P("colorFront","Front","#79d1ff"),P("colorBack","Background","#001429"),O("density","Density",.5,0,1,.01),O("distortion","Distortion",.2,0,1,.01),O("strokeWidth","Stroke Width",.5,0,1,.01)]},{id:"paper-swirl",name:"Swirl",category:"fill",glsl:Oc,staticUniforms:Ze,colorArrayParams:ut,params:[...ce(["#ffd1d1","#ff8a8a","#660000"]),P("colorBack","Background","#330000"),O("bandCount","Bands",4,1,12,1),O("twist","Twist",.3,0,1,.01),O("proportion","Proportion",.5,0,1,.01)]},{id:"paper-warp",name:"Warp",category:"fill",glsl:Sc,staticUniforms:Je,colorArrayParams:ut,needsNoiseTexture:et,params:[...ce(["#121212","#9470ff","#8838ff"]),O("proportion","Proportion",.5,0,1,.01),O("distortion","Distortion",.25,0,1,.01),O("swirl","Swirl",.8,0,1,.01),O("softness","Softness",1,0,1,.01)]},{id:"paper-voronoi",name:"Voronoi",category:"fill",glsl:bc,staticUniforms:Je,colorArrayParams:kt("u_colors","u_colorsCount",5),needsNoiseTexture:et,params:[...ce(["#ff8247","#ffe53d","#83c9fb"]),P("colorGap","Gap","#2e0000"),O("scale","Zoom",1,.1,4,.01),O("distortion","Distortion",.3,0,1,.01),O("gap","Gap Width",.05,0,.5,.01)]},{id:"paper-simplex-noise",name:"Simplex Noise",category:"fill",glsl:yc,staticUniforms:Je,colorArrayParams:ut,params:[...ce(["#4449cf","#ffd1e0","#f94446"]),O("scale","Zoom",1,.1,4,.01),O("softness","Softness",.5,0,1,.01),O("stepsPerColor","Steps",1,1,8,1)]},{id:"paper-perlin-noise",name:"Perlin Noise",category:"fill",glsl:xc,staticUniforms:Je,params:[P("colorFront","Front","#fccff7"),P("colorBack","Background","#632ad5"),O("proportion","Proportion",.5,0,1,.01),O("softness","Softness",.5,0,1,.01),O("octaveCount","Octaves",2,1,8,1)]},{id:"paper-grain-gradient",name:"Grain Gradient",category:"fill",glsl:Uc,staticUniforms:Ze,colorArrayParams:kt("u_colors","u_colorsCount",7),needsNoiseTexture:et,params:[...ce(["#7300ff","#eba8ff","#00bfff"]),P("colorBack","Background","#000000"),O("softness","Softness",.5,0,1,.01),O("intensity","Grain",.5,0,1,.01),O("noise","Noise",.5,0,1,.01)]},{id:"paper-pulsing-border",name:"Pulsing Border",category:"fill",glsl:Ic,staticUniforms:Ze,colorArrayParams:kt("u_colors","u_colorsCount",5),needsNoiseTexture:et,params:[...ce(["#0dc1fd","#d915ef","#ff3f2e"]),P("colorBack","Background","#000000"),O("thickness","Thickness",.1,0,1,.01),O("intensity","Intensity",.5,0,1,.01),O("pulse","Pulse",0,0,1,.01)]},{id:"paper-dot-orbit",name:"Dot Orbit",category:"fill",glsl:gc,staticUniforms:Je,colorArrayParams:ut,needsNoiseTexture:et,params:[...ce(["#ffc96b","#ff6200","#ff2f00"]),P("colorBack","Background","#000000"),O("size","Size",.5,0,1,.01),O("sizeRange","Size Range",.5,0,1,.01),O("spreading","Spreading",.5,0,1,.01)]},{id:"paper-dot-grid",name:"Dot Grid",category:"fill",glsl:vc,staticUniforms:Je,params:[P("colorFill","Fill","#ffffff"),P("colorBack","Background","#000000"),O("dotSize","Dot Size",2,.5,20,.1),O("gapX","Gap X",32,4,128,1),O("gapY","Gap Y",32,4,128,1)]},{id:"paper-waves",name:"Waves",category:"fill",glsl:wc,staticUniforms:Je,params:[P("colorFront","Front","#ffbb00"),P("colorBack","Background","#000000"),O("amplitude","Amplitude",.5,0,1,.01),O("frequency","Frequency",.5,0,1,.01),O("spacing","Spacing",.5,0,1,.01)]},{id:"paper-color-panels",name:"Color Panels",category:"fill",glsl:Ac,staticUniforms:Ze,colorArrayParams:kt("u_colors","u_colorsCount",7),params:[...ce(["#ff9d00","#fd4f30","#809bff"]),P("colorBack","Background","#000000"),O("density","Density",.5,0,1,.01),O("angle1","Angle 1",0,-1,1,.01),O("blur","Blur",.2,0,1,.01)]},{id:"paper-dithering",name:"Dithering",category:"fill",glsl:Tc,staticUniforms:Je,params:[P("colorFront","Front","#00b2ff"),P("colorBack","Background","#000000"),O("pxSize","Pixel Size",2,1,16,.5),O("shape","Shape",1,0,3,1),O("type","Type",1,0,4,1)]},{id:"paper-water",name:"Water",category:"effect",glsl:Rc,staticUniforms:lt,inputUniform:ct,params:[P("colorHighlight","Highlight","#ffffff"),O("size","Size",.5,0,1,.01),O("waves","Waves",.5,0,1,.01),O("highlights","Highlights",.5,0,1,.01),O("caustic","Caustic",.5,0,1,.01)]},{id:"paper-paper-texture",name:"Paper Texture",category:"effect",glsl:Vc,staticUniforms:{...lt,u_contrast:.3,u_fiberSize:.2,u_crumpleSize:.35,u_foldCount:5,u_drops:.2,u_seed:5.8},inputUniform:ct,needsNoiseTexture:et,params:[P("colorFront","Texture Color","#9fadbc"),P("colorBack","Paper Color","#ffffff"),O("roughness","Roughness",.4,0,1,.01),O("crumples","Crumples",.3,0,1,.01),O("folds","Folds",.65,0,1,.01),O("fiber","Fiber",.3,0,1,.01),O("fade","Fade",0,0,1,.01)]},{id:"paper-fluted-glass",name:"Fluted Glass",category:"effect",glsl:Pc,staticUniforms:lt,inputUniform:ct,params:[O("size","Size",.5,0,1,.01),O("distortion","Distortion",.5,0,1,.01),O("shift","Shift",.5,0,1,.01),O("blur","Blur",.2,0,1,.01),O("highlights","Highlights",.5,0,1,.01)]},{id:"paper-image-dithering",name:"Image Dithering",category:"effect",glsl:Dc,staticUniforms:lt,inputUniform:ct,params:[P("colorFront","Front","#94ffaf"),P("colorBack","Background","#000c38"),O("pxSize","Pixel Size",2,1,16,.5),O("type","Type",1,0,4,1),O("colorSteps","Color Steps",2,1,8,1)]},{id:"paper-halftone-dots",name:"Halftone Dots",category:"effect",glsl:Nc,staticUniforms:lt,inputUniform:ct,params:[P("colorFront","Front","#2b2b2b"),P("colorBack","Background","#f2f1e8"),O("size","Size",.5,0,1,.01),O("radius","Radius",.5,0,1,.01),O("contrast","Contrast",.5,0,1,.01)]},{id:"paper-halftone-cmyk",name:"Halftone CMYK",category:"effect",glsl:Ec,staticUniforms:{...lt,u_type:1,u_grainSize:.5,u_grainMixer:0,u_grainOverlay:0,u_gridNoise:.2,u_floodC:.15,u_floodM:0,u_floodY:0,u_floodK:0,u_gainC:.3,u_gainM:0,u_gainY:.2,u_gainK:0},inputUniform:ct,needsNoiseTexture:et,params:[P("colorBack","Paper","#fbfaf5"),P("colorC","Cyan","#00b4ff"),P("colorM","Magenta","#fc519f"),P("colorY","Yellow","#ffd800"),P("colorK","Key","#231f20"),O("size","Size",.2,0,1,.01),O("contrast","Contrast",1,0,1,.01),O("softness","Softness",1,0,1,.01),O("minDot","Min Dot",.1,0,1,.01)]},{id:"paper-heatmap",name:"Heatmap",category:"effect",glsl:zc,staticUniforms:lt,inputUniform:ct,colorArrayParams:ut,params:[...ce(["#11206a","#6bd7ff","#ff4c00"]),O("contour","Contour",.5,0,1,.01),O("innerGlow","Inner Glow",.5,0,1,.01),O("outerGlow","Outer Glow",.5,0,1,.01)]},{id:"paper-liquid-metal",name:"Liquid Metal",category:"effect",glsl:Fc,staticUniforms:lt,inputUniform:ct,params:[P("colorTint","Tint","#ffffff"),O("repetition","Repetition",3,1,8,1),O("softness","Softness",.5,0,1,.01),O("shiftRed","Shift Red",.3,0,1,.01),O("distortion","Distortion",.2,0,1,.01)]},{id:"paper-gem-smoke",name:"Gem Smoke",category:"effect",glsl:Lc,staticUniforms:lt,inputUniform:ct,colorArrayParams:kt("u_colors","u_colorsCount",6),params:[...ce(["#333333","#e7e6df","#fafaf5"]),O("size","Size",.5,0,1,.01),O("innerGlow","Inner Glow",.5,0,1,.01),O("outerGlow","Outer Glow",.5,0,1,.01)]}],Wc=[],Gc=new Set(Wc);jc.filter(a=>!Gc.has(a.id)).map(a=>({id:a.id,name:a.name,category:a.category,glsl:a.glsl,params:a.params,origin:"builtin",collection:"Paper",vertexShader:$c,staticUniforms:a.staticUniforms,...a.colorArrayParams?{colorArrayParams:a.colorArrayParams}:{},...a.needsNoiseTexture?{needsNoiseTexture:a.needsNoiseTexture}:{},...a.inputUniform?{inputUniform:a.inputUniform}:{}}));const oa=()=>`motion-text-anim-${Date.now()}-${Math.random().toString(36).slice(2,9)}`,$n=[{id:"text-reveal-up",name:"Reveal Up",description:"Staggers characters upward from transparent to fully visible.",create:(a=oa())=>({id:a,name:"Reveal Up",enabled:!0,selector:{basedOn:"characters",start:0,end:100,offset:0},timing:{startTime:0,duration:.45,stagger:.035,direction:"forward",easing:"ease-out"},properties:{position:{x:0,y:36},scale:{x:.96,y:.96},rotation:0,opacity:0}})},{id:"text-type-on",name:"Type On",description:"Reveals text one unit at a time without spatial movement.",create:(a=oa())=>({id:a,name:"Type On",enabled:!0,selector:{basedOn:"characters",start:0,end:100,offset:0},timing:{startTime:0,duration:.18,stagger:.045,direction:"forward",easing:"linear"},properties:{position:{x:0,y:0},scale:{x:1,y:1},rotation:0,opacity:0}})},{id:"text-scale-in",name:"Scale In",description:"Pops each character up from zero scale with a springy reveal.",create:(a=oa())=>({id:a,name:"Scale In",enabled:!0,selector:{basedOn:"characters",start:0,end:100,offset:0},timing:{startTime:0,duration:.4,stagger:.04,direction:"forward",easing:"ease-out"},properties:{position:{x:0,y:0},scale:{x:0,y:0},rotation:0,opacity:0}})},{id:"text-reveal-down",name:"Reveal Down",description:"Drops characters in from above with a staggered fade.",create:(a=oa())=>({id:a,name:"Reveal Down",enabled:!0,selector:{basedOn:"characters",start:0,end:100,offset:0},timing:{startTime:0,duration:.45,stagger:.035,direction:"forward",easing:"ease-out"},properties:{position:{x:0,y:-36},scale:{x:.96,y:.96},rotation:0,opacity:0}})},{id:"text-slide-left",name:"Slide In Left",description:"Slides characters in from the left edge in sequence.",create:(a=oa())=>({id:a,name:"Slide In Left",enabled:!0,selector:{basedOn:"words",start:0,end:100,offset:0},timing:{startTime:0,duration:.5,stagger:.06,direction:"forward",easing:"ease-out"},properties:{position:{x:-72,y:0},scale:{x:1,y:1},rotation:0,opacity:0}})},{id:"text-spin-in",name:"Spin In",description:"Tumbles each character in with rotation and scale for kinetic titles.",create:(a=oa())=>({id:a,name:"Spin In",enabled:!0,selector:{basedOn:"characters",start:0,end:100,offset:0},timing:{startTime:0,duration:.5,stagger:.05,direction:"forward",easing:"ease-out"},properties:{position:{x:0,y:18},scale:{x:.7,y:.7},rotation:-120,opacity:0}})}];function Yc(a="text-reveal-up",e){const t=$n.find(o=>o.id===a);if(!t)throw new Error(`Unsupported motion text animator preset: ${a}`);return t.create(e)}const Ne=a=>`${a}-${Date.now()}-${Math.random().toString(36).slice(2,9)}`;class qc{createComposition(e={}){const t=Date.now(),o=e.width??1920,i=e.height??1080;return{id:Ne("motion"),name:e.name??"Untitled Motion Scene",width:o,height:i,frameRate:e.frameRate??30,duration:e.duration??5,backgroundColor:e.backgroundColor??"transparent",layers:[],assets:[],variables:[],markers:[],guides:[],createdAt:t,modifiedAt:t}}createStarterComposition(e={}){const t=this.createComposition(e),o={id:Ne("motion-layer"),type:"text",name:"Headline",startTime:0,duration:t.duration,visible:!0,locked:!1,transform:{...wi,position:{x:t.width/2,y:t.height/2}},keyframes:[{id:Ne("motion-kf"),time:0,property:"transform.opacity",value:0,easing:"ease-out"},{id:Ne("motion-kf"),time:.6,property:"transform.opacity",value:1,easing:"ease-out"},{id:Ne("motion-kf"),time:t.duration-.5,property:"transform.opacity",value:1,easing:"ease-in"},{id:Ne("motion-kf"),time:t.duration,property:"transform.opacity",value:0,easing:"ease-in"}],text:"Motion Scene",textAnimators:[Yc("text-reveal-up",Ne("motion-text-anim"))],style:{fontFamily:"Inter",fontSize:112,fontWeight:800,color:"#ffffff",align:"center",lineHeight:1.05}};return{...t,layers:[{id:Ne("motion-layer"),type:"shape",name:"Accent Bar",startTime:0,duration:t.duration,visible:!0,locked:!1,transform:{...wi,position:{x:t.width/2,y:t.height*.65},scale:{x:1,y:1}},keyframes:[{id:Ne("motion-kf"),time:0,property:"transform.scale.x",value:0,easing:"ease-out"},{id:Ne("motion-kf"),time:.7,property:"transform.scale.x",value:1,easing:"ease-out"}],shapeType:"rectangle",width:560,height:18,style:{...En,fill:{type:"solid",color:"#14b8a6",opacity:1},stroke:{color:"#14b8a6",width:0,opacity:0},cornerRadius:9}},o]}}upsertComposition(e,t){const o=e.motionCompositions??[],i=o.some(r=>r.id===t.id)?o.map(r=>r.id===t.id?t:r):[...o,t];return{...e,motionCompositions:i,modifiedAt:Date.now()}}addLayer(e,t){return{...e,layers:[...e.layers,t],modifiedAt:Date.now()}}createInstance(e,t={}){return{id:Ne("motion-instance"),compositionId:e.id,name:t.name??e.name,trackId:t.trackId,startTime:t.startTime??0,duration:t.duration??e.duration,transform:cc,opacity:1}}insertInstance(e,t){const{track:o,tracks:i}=Xc(e,t.trackId),r=o.id,n={...t,trackId:r},s=Hc(n),l=i.map(u=>{if(u.id!==o.id)return u;const f=u.clips.some(d=>d.metadata?.motionInstanceId===t.id)?u.clips.map(d=>d.metadata?.motionInstanceId===t.id?s:d):[...u.clips,s];return{...u,clips:f}}),c=(e.motionInstances??[]).some(u=>u.id===t.id)?(e.motionInstances??[]).map(u=>u.id===t.id?n:u):[...e.motionInstances??[],n];return{...e,motionInstances:c,timeline:{...e.timeline,tracks:l,duration:Math.max(e.timeline.duration,n.startTime+n.duration)},modifiedAt:Date.now()}}}function Hc(a){return{id:`motion-clip-${a.id}`,mediaId:`motion-${a.id}`,trackId:a.trackId??"track-motion",startTime:a.startTime,duration:a.duration,inPoint:0,outPoint:a.duration,effects:[],audioEffects:[],transform:a.transform,blendMode:a.blendMode,blendOpacity:a.opacity,volume:1,keyframes:[],metadata:{motionInstanceId:a.id,motionCompositionId:a.compositionId,motionClip:!0}}}function Xc(a,e){if(e){const i=a.timeline.tracks.find(r=>r.id===e);if(i)return{track:i,tracks:a.timeline.tracks}}const t=a.timeline.tracks.find(i=>i.type==="graphics"&&i.name==="Motion");if(t)return{track:t,tracks:a.timeline.tracks};const o={id:e??Ne("track-motion"),type:"graphics",name:"Motion",clips:[],transitions:[],locked:!1,hidden:!1,muted:!1,solo:!1};return{track:o,tracks:[...a.timeline.tracks,o]}}const jo=new qc;function io(){return{valid:!0,errors:[]}}function xa(a){return{valid:!1,errors:[{code:"INVALID_PARAMS",message:a}]}}function ro(a,e){Object.assign(a,e)}function jn(a,e){const t=(a.motionInstances??[]).filter(r=>r.id!==e),o=a.timeline.tracks.map(r=>({...r,clips:r.clips.filter(n=>n.metadata?.motionInstanceId!==e)})),i=o.reduce((r,n)=>n.clips.reduce((s,l)=>Math.max(s,l.startTime+l.duration),r),0);return{...a,motionInstances:t,timeline:{...a.timeline,tracks:o,duration:i},modifiedAt:Date.now()}}const Kc={type:"motion/createComposition",validate(a){const e=a.params.composition;return e&&typeof e.id=="string"?io():xa("motion/createComposition requires a composition with an id")},apply(a,e){const t=a.params.composition;ro(e,jo.upsertComposition(e,t))},invert(a){const e=a.params.composition;return{type:"motion/removeComposition",id:`inverse-${a.id}`,timestamp:Date.now(),params:{compositionId:e.id}}}},Qc={type:"motion/upsertComposition",validate(a){const e=a.params.composition;return e&&typeof e.id=="string"?io():xa("motion/upsertComposition requires a composition with an id")},apply(a,e){const t=a.params.composition;ro(e,jo.upsertComposition(e,t))},invert(a,e){const t=a.params.composition,o=(e.motionCompositions??[]).find(i=>i.id===t.id);return{type:o?"motion/upsertComposition":"motion/removeComposition",id:`inverse-${a.id}`,timestamp:Date.now(),params:o?{composition:o}:{compositionId:t.id}}}},Jc={type:"motion/removeComposition",validate(a,e){const t=a.params.compositionId;return(e.motionCompositions??[]).some(o=>o.id===t)?io():xa(`Motion composition not found: ${String(t)}`)},apply(a,e){const t=a.params.compositionId,o=(e.motionInstances??[]).filter(r=>r.compositionId===t).map(r=>r.id);let i={...e,motionCompositions:(e.motionCompositions??[]).filter(r=>r.id!==t),modifiedAt:Date.now()};for(const r of o)i=jn(i,r);ro(e,i)},invert(a,e){const t=a.params.compositionId,o=(e.motionCompositions??[]).find(i=>i.id===t);return o?{type:"motion/createComposition",id:`inverse-${a.id}`,timestamp:Date.now(),params:{composition:o}}:null}},Zc={type:"motion/insertInstance",validate(a,e){const t=a.params.instance;return!t||typeof t.id!="string"?xa("motion/insertInstance requires an instance with an id"):(e.motionCompositions??[]).some(o=>o.id===t.compositionId)?io():xa(`Motion composition not found: ${t.compositionId}`)},apply(a,e){const t=a.params.instance;ro(e,jo.insertInstance(e,t))},invert(a){const e=a.params.instance;return{type:"motion/removeInstance",id:`inverse-${a.id}`,timestamp:Date.now(),params:{instanceId:e.id}}}},eu={type:"motion/removeInstance",validate(a,e){const t=a.params.instanceId;return(e.motionInstances??[]).some(o=>o.id===t)?io():xa(`Motion instance not found: ${String(t)}`)},apply(a,e){const t=a.params.instanceId;ro(e,jn(e,t))},invert(a,e){const t=a.params.instanceId,o=(e.motionInstances??[]).find(i=>i.id===t);return o?{type:"motion/insertInstance",id:`inverse-${a.id}`,timestamp:Date.now(),params:{instance:o}}:null}};for(const a of[Kc,Qc,Jc,Zc,eu])Dt(a);const Wn="0.1.0";function $r(a={}){return{version:a.version??Wn,assets:[],scenes:[],activeSceneId:a.activeSceneId,operationHistory:[]}}function tu(a,e,t){return t<=0?a.operationHistory:[...a.operationHistory,e].slice(-t)}function Ta(a,e){return{...a,modifiedAt:e}}function ta(a,e){const t=a.scenes.find(o=>o.id===e);if(!t)throw new Error(`Creation scene not found: ${e}`);return t}function no(a,e){return a.findIndex(o=>o.id===e.id)<0?[...a,e]:a.map(o=>o.id===e.id?e:o)}function au(a,e){return a.filter(t=>t.id!==e)}function ou(a,e){return{...a,assets:no(a.assets,e)}}function iu(a,e){return{...a,assets:au(a.assets,e),scenes:a.scenes.map(t=>({...t,objects:t.objects.filter(o=>o.assetId!==e)}))}}function ru(a,e){return{...a,scenes:no(a.scenes,e),activeSceneId:a.activeSceneId??e.id}}function nu(a,e){return ta(a,e),{...a,activeSceneId:e}}function su(a,e,t,o=!1,i=Date.now()){return ta(a,e),{...a,scenes:a.scenes.map(r=>r.id===e?Ta({...r,cameras:no(r.cameras,t),activeCameraId:o||!r.activeCameraId?t.id:r.activeCameraId},i):r)}}function lu(a,e,t,o=Date.now()){return ta(a,e),{...a,scenes:a.scenes.map(i=>i.id===e?Ta({...i,objects:no(i.objects,t)},o):i)}}function cu(a,e,t,o,i=Date.now()){if(!ta(a,e).objects.some(n=>n.id===t))throw new Error(`Creation scene object not found: ${t}`);return{...a,scenes:a.scenes.map(n=>n.id===e?Ta({...n,objects:n.objects.map(s=>s.id===t?{...s,transform:o}:s)},i):n)}}function uu(a,e,t,o,i=Date.now()){if(!ta(a,e).objects.some(n=>n.id===t))throw new Error(`Creation scene object not found: ${t}`);return{...a,scenes:a.scenes.map(n=>n.id===e?Ta({...n,objects:n.objects.map(s=>s.id===t?{...s,materialId:o}:s)},i):n)}}function fu(a,e,t,o=Date.now()){return ta(a,e),{...a,scenes:a.scenes.map(i=>i.id===e?Ta({...i,objects:i.objects.filter(r=>r.id!==t).map(r=>r.parentId===t?{...r,parentId:void 0}:r),animations:i.animations.map(r=>({...r,tracks:r.tracks.filter(n=>n.targetId!==t)}))},o):i)}}function pu(a,e,t,o=Date.now()){return ta(a,e),{...a,scenes:a.scenes.map(i=>i.id===e?Ta({...i,animations:no(i.animations,t)},o):i)}}function jr(a,e,t={}){const o=t.maxHistory??200;let i;switch(e.type){case"asset/upsert":i=ou(a,e.asset);break;case"asset/remove":i=iu(a,e.assetId);break;case"scene/upsert":i=ru(a,e.scene);break;case"scene/set-active":i=nu(a,e.sceneId);break;case"camera/upsert":i=su(a,e.sceneId,e.camera,e.active,e.timestamp);break;case"scene-object/upsert":i=lu(a,e.sceneId,e.object,e.timestamp);break;case"scene-object/update-transform":i=cu(a,e.sceneId,e.objectId,e.transform,e.timestamp);break;case"scene-object/update-material":i=uu(a,e.sceneId,e.objectId,e.materialId,e.timestamp);break;case"scene-object/remove":i=fu(a,e.sceneId,e.objectId,e.timestamp);break;case"animation/upsert-clip":i=pu(a,e.sceneId,e.clip,e.timestamp);break}return{...i,operationHistory:tu(i,e,o)}}function Si(a){if(a)return{version:typeof a.version=="string"?a.version:Wn,assets:Array.isArray(a.assets)?a.assets:[],scenes:Array.isArray(a.scenes)?a.scenes.map(e=>({...e,objects:Array.isArray(e.objects)?e.objects:[],cameras:Array.isArray(e.cameras)?e.cameras:[],lights:Array.isArray(e.lights)?e.lights:[],animations:Array.isArray(e.animations)?e.animations:[],renderBindings:Array.isArray(e.renderBindings)?e.renderBindings:[]})):[],activeSceneId:typeof a.activeSceneId=="string"?a.activeSceneId:void 0,operationHistory:Array.isArray(a.operationHistory)?a.operationHistory:[]}}function qe(a,e,t,o,i){a.push({code:e,message:t,severity:o,path:i})}function ni(a){const e=new Set,t=new Set;for(const o of a)e.has(o.id)&&t.add(o.id),e.add(o.id);return[...t]}function du(a){const e=[],t=new Set(a.assets.map(r=>r.id)),o=new Map(a.assets.map(r=>[r.id,r])),i=new Set(a.scenes.map(r=>r.id));for(const r of ni(a.assets))qe(e,"DUPLICATE_ASSET_ID",`Duplicate asset id: ${r}`,"error","assets");for(const r of ni(a.scenes))qe(e,"DUPLICATE_SCENE_ID",`Duplicate scene id: ${r}`,"error","scenes");a.activeSceneId&&!i.has(a.activeSceneId)&&qe(e,"ACTIVE_SCENE_NOT_FOUND",`Active creation scene does not exist: ${a.activeSceneId}`,"error","activeSceneId");for(const[r,n]of a.scenes.entries()){const s=`scenes[${r}]`,l=new Set(n.objects.map(u=>u.id)),c=new Set(n.cameras.map(u=>u.id));for(const u of ni(n.objects))qe(e,"DUPLICATE_OBJECT_ID",`Duplicate object id in scene ${n.id}: ${u}`,"error",`${s}.objects`);for(const u of n.objects){const f=o.get(u.assetId);t.has(u.assetId)||qe(e,"OBJECT_ASSET_NOT_FOUND",`Object ${u.id} references missing asset ${u.assetId}`,"error",`${s}.objects.${u.id}.assetId`),u.materialId&&f&&!f.materials.some(d=>d.id===u.materialId)&&qe(e,"OBJECT_MATERIAL_NOT_FOUND",`Object ${u.id} references missing material ${u.materialId}`,"error",`${s}.objects.${u.id}.materialId`),u.parentId&&!l.has(u.parentId)&&qe(e,"OBJECT_PARENT_NOT_FOUND",`Object ${u.id} references missing parent ${u.parentId}`,"error",`${s}.objects.${u.id}.parentId`)}n.activeCameraId&&!c.has(n.activeCameraId)&&qe(e,"ACTIVE_CAMERA_NOT_FOUND",`Scene ${n.id} active camera does not exist: ${n.activeCameraId}`,"error",`${s}.activeCameraId`);for(const u of n.renderBindings)for(const f of u.objectBindings)l.has(f.sceneObjectId)||qe(e,"RENDER_BINDING_OBJECT_NOT_FOUND",`Render binding ${u.id} references missing scene object ${f.sceneObjectId}`,"error",`${s}.renderBindings.${u.id}.objectBindings`);for(const u of n.animations)for(const f of u.tracks){(f.channel.startsWith("camera.")?c.has(f.targetId):l.has(f.targetId))||qe(e,"ANIMATION_TARGET_NOT_FOUND",`Animation track ${f.id} references missing target ${f.targetId}`,"error",`${s}.animations.${u.id}.${f.id}`);for(let h=1;h<f.keyframes.length;h+=1){const p=f.keyframes[h-1],g=f.keyframes[h];if(p&&g&&g.time<p.time){qe(e,"KEYFRAMES_NOT_SORTED",`Track ${f.id} keyframes must be sorted by time`,"warning",`${s}.animations.${u.id}.${f.id}.keyframes`);break}}}}return e}function Wr(){return{valid:!0,errors:[]}}function Gr(a){return{valid:!1,errors:[{code:"INVALID_PARAMS",message:a}]}}function mu(a,e){Object.assign(a,e)}function hu(a){return!!a&&typeof a=="object"&&!Array.isArray(a)}function Yr(a){const e=a.params.operation;if(hu(e)&&!(typeof e.id!="string"||typeof e.type!="string")&&!(typeof e.timestamp!="number"||!Number.isFinite(e.timestamp))&&!(e.source!=="agent"&&e.source!=="user"&&e.source!=="system"))return e}function qr(a){if(!(a.params.state===null||a.params.state===void 0))return Si(a.params.state)}function Gn(a){if(!a)return Wr();const e=du(a).filter(t=>t.severity==="error");return e.length===0?Wr():{valid:!1,errors:e.map(t=>({code:t.code,message:t.message,path:t.path}))}}function Yn(a,e){mu(a,{...a,creation:e,modifiedAt:Date.now()})}const gu={type:"creation/replaceState",validate(a){return Gn(qr(a))},apply(a,e){Yn(e,qr(a))},invert(a,e){return{type:"creation/replaceState",id:`inverse-${a.id}`,timestamp:Date.now(),params:{state:e.creation??null}}}},vu={type:"creation/applyOperation",validate(a,e){const t=Yr(a);if(!t)return Gr("creation/applyOperation requires a valid operation");try{const o=Si(e.creation)??$r(),i=jr(o,t);return Gn(i)}catch(o){return Gr(o instanceof Error?o.message:"Invalid creation operation")}},apply(a,e){const t=Yr(a);if(!t)throw new Error("creation/applyOperation requires a valid operation");const o=Si(e.creation)??$r();Yn(e,jr(o,t))},invert(a,e){return{type:"creation/replaceState",id:`inverse-${a.id}`,timestamp:Date.now(),params:{state:e.creation??null}}}};Dt(gu);Dt(vu);function ki(a){return a.outputTracks??(a.outputTrack?[a.outputTrack]:[])}function na(a){return{valid:!1,errors:[{code:"INVALID_PARAMS",message:a}]}}function yu(a,e){const t=ki(e),o=new Set(t.map(l=>l.id)),i=new Set(e.sourceTrackIds),r=a.timeline.tracks.filter(l=>!o.has(l.id)).map(l=>i.has(l.id)?{...l,hidden:!0,muted:!0}:l),n=Math.max(0,Math.min(e.outputTrackPosition??0,r.length)),s=[...r];s.splice(n,0,...structuredClone(t)),Object.assign(a.timeline,{tracks:s}),Object.assign(a,{multicamGroups:structuredClone(e.groups)})}const _u={type:"multicam/applyEdit",validate(a,e){const t=a.params,o=ki(t);if(!o.length||o.some(n=>typeof n.id!="string"))return na("multicam/applyEdit requires at least one output track");if(o.some(n=>n.type!=="video"))return na("multicam outputs must be video tracks");if(o.some(n=>!Array.isArray(n.clips)||n.clips.some(s=>s.trackId!==n.id)))return na("every multicam clip must target the output track");if(!Array.isArray(t.sourceTrackIds)||!Array.isArray(t.groups))return na("multicam/applyEdit requires source tracks and groups");const i=new Set(e.timeline.tracks.map(n=>n.id)),r=t.sourceTrackIds.find(n=>!i.has(n));return r?na(`multicam source track not found: ${r}`):{valid:!0,errors:[]}},apply(a,e){yu(e,a.params)},invert(a,e){const t=a.params,o=ki(t).map(r=>r.id),i=e.timeline.tracks.flatMap((r,n)=>o.includes(r.id)?[{track:structuredClone(r),position:n}]:[]);return{type:"multicam/restoreEdit",id:`inverse-${a.id}`,timestamp:Date.now(),params:{outputTrackIds:o,priorOutputTracks:i,sourceTrackStates:t.sourceTrackIds.flatMap(r=>{const n=e.timeline.tracks.find(s=>s.id===r);return n?[{trackId:r,hidden:n.hidden,muted:n.muted}]:[]}),groups:structuredClone(e.multicamGroups??[])}}}},xu={type:"multicam/restoreEdit",validate(a){const e=a.params;return Array.isArray(e.outputTrackIds)&&Array.isArray(e.groups)?{valid:!0,errors:[]}:na("multicam/restoreEdit requires a prior edit snapshot")},apply(a,e){const t=a.params,o=new Map(t.sourceTrackStates.map(r=>[r.trackId,r])),i=e.timeline.tracks.filter(r=>!t.outputTrackIds.includes(r.id)).map(r=>{const n=o.get(r.id);return n?{...r,hidden:n.hidden,muted:n.muted}:r});for(const r of[...t.priorOutputTracks].sort((n,s)=>n.position-s.position))i.splice(Math.max(0,Math.min(r.position,i.length)),0,structuredClone(r.track));Object.assign(e.timeline,{tracks:i}),Object.assign(e,{multicamGroups:structuredClone(t.groups)})},invert(){return null}};Dt(_u);Dt(xu);const bu=["normal","multiply","screen","overlay","darken","lighten","color-dodge","color-burn","hard-light","soft-light","difference","exclusion","hue","saturation","color","luminosity","add","linear-dodge"],wu=[{id:"cinematic-teal-orange",name:"Teal & Orange",category:"cinematic",description:"Classic Hollywood color grade",effects:[{type:"contrast",params:{value:1.15}},{type:"saturation",params:{value:1.1}},{type:"vignette",params:{amount:.25,midpoint:.5,roundness:.5,feather:.8}}]},{id:"cinematic-noir",name:"Film Noir",category:"cinematic",description:"High contrast black & white",effects:[{type:"saturation",params:{value:0}},{type:"contrast",params:{value:1.4}},{type:"brightness",params:{value:-.05}},{type:"vignette",params:{amount:.4,midpoint:.4,roundness:.5,feather:.6}},{type:"grain",params:{amount:.15,size:1.5,roughness:.5,colored:!1}}]},{id:"cinematic-blockbuster",name:"Blockbuster",category:"cinematic",description:"Bold, punchy Hollywood look",effects:[{type:"contrast",params:{value:1.2}},{type:"saturation",params:{value:1.15}},{type:"brightness",params:{value:.05}},{type:"sharpen",params:{amount:.3,radius:1,threshold:10}}]},{id:"vintage-70s",name:"70s Retro",category:"vintage",description:"Warm, faded 1970s aesthetic",effects:[{type:"saturation",params:{value:.85}},{type:"contrast",params:{value:.9}},{type:"brightness",params:{value:.05}},{type:"grain",params:{amount:.2,size:2,roughness:.6,colored:!0}}]},{id:"vintage-polaroid",name:"Polaroid",category:"vintage",description:"Classic instant photo look",effects:[{type:"contrast",params:{value:1.1}},{type:"saturation",params:{value:.9}},{type:"vignette",params:{amount:.3,midpoint:.5,roundness:.3,feather:.85}}]},{id:"vintage-vhs",name:"VHS",category:"vintage",description:"Nostalgic VHS tape effect",effects:[{type:"saturation",params:{value:.8}},{type:"contrast",params:{value:1.15}},{type:"blur",params:{radius:.5,type:"gaussian"}},{type:"grain",params:{amount:.25,size:2.5,roughness:.7,colored:!0}}]},{id:"vintage-sepia",name:"Sepia",category:"vintage",description:"Classic sepia tone",effects:[{type:"saturation",params:{value:.3}},{type:"contrast",params:{value:1.05}},{type:"brightness",params:{value:.1}}]},{id:"mood-dreamy",name:"Dreamy",category:"mood",description:"Soft, ethereal atmosphere",effects:[{type:"brightness",params:{value:.1}},{type:"saturation",params:{value:.85}},{type:"blur",params:{radius:1,type:"gaussian"}},{type:"contrast",params:{value:.9}}]},{id:"mood-moody",name:"Moody",category:"mood",description:"Dark, atmospheric feel",effects:[{type:"brightness",params:{value:-.15}},{type:"contrast",params:{value:1.25}},{type:"saturation",params:{value:.75}},{type:"vignette",params:{amount:.35,midpoint:.4,roundness:.5,feather:.7}}]},{id:"mood-golden-hour",name:"Golden Hour",category:"mood",description:"Warm sunset lighting",effects:[{type:"brightness",params:{value:.1}},{type:"saturation",params:{value:1.2}},{type:"contrast",params:{value:1.05}}]},{id:"mood-cold",name:"Cold Blue",category:"mood",description:"Cool, icy atmosphere",effects:[{type:"saturation",params:{value:.9}},{type:"brightness",params:{value:.05}},{type:"contrast",params:{value:1.1}}]},{id:"color-vibrant",name:"Vibrant",category:"color",description:"Punchy, saturated colors",effects:[{type:"saturation",params:{value:1.4}},{type:"contrast",params:{value:1.15}},{type:"brightness",params:{value:.05}}]},{id:"color-muted",name:"Muted",category:"color",description:"Soft, desaturated palette",effects:[{type:"saturation",params:{value:.6}},{type:"contrast",params:{value:.95}},{type:"brightness",params:{value:.05}}]},{id:"color-bw-classic",name:"B&W Classic",category:"color",description:"Timeless black & white",effects:[{type:"saturation",params:{value:0}},{type:"contrast",params:{value:1.1}}]},{id:"color-bw-high-contrast",name:"B&W High Contrast",category:"color",description:"Dramatic black & white",effects:[{type:"saturation",params:{value:0}},{type:"contrast",params:{value:1.5}},{type:"brightness",params:{value:-.05}}]},{id:"stylized-cyberpunk",name:"Cyberpunk",category:"stylized",description:"Neon-lit futuristic look",effects:[{type:"saturation",params:{value:1.3}},{type:"contrast",params:{value:1.3}},{type:"vignette",params:{amount:.3,midpoint:.45,roundness:.5,feather:.75}}]},{id:"stylized-comic",name:"Comic Book",category:"stylized",description:"Bold, graphic novel style",effects:[{type:"contrast",params:{value:1.5}},{type:"saturation",params:{value:1.4}},{type:"sharpen",params:{amount:.5,radius:1.5,threshold:5}}]},{id:"stylized-soft-glow",name:"Soft Glow",category:"stylized",description:"Romantic soft focus effect",effects:[{type:"brightness",params:{value:.15}},{type:"blur",params:{radius:1.5,type:"gaussian"}},{type:"contrast",params:{value:.85}},{type:"saturation",params:{value:.9}}]},{id:"cinematic-bleach-bypass",name:"Bleach Bypass",category:"cinematic",description:"Gritty, desaturated high contrast",effects:[{type:"saturation",params:{value:.45}},{type:"contrast",params:{value:1.35}},{type:"sharpen",params:{amount:.35,radius:1,threshold:8}},{type:"vignette",params:{amount:.3,midpoint:.5,roundness:.5,feather:.7}}]},{id:"cinematic-day-for-night",name:"Day for Night",category:"cinematic",description:"Cool moonlit night look",effects:[{type:"brightness",params:{value:-.18}},{type:"contrast",params:{value:1.2}},{type:"saturation",params:{value:.7}},{type:"hue",params:{rotation:210}},{type:"vignette",params:{amount:.45,midpoint:.4,roundness:.5,feather:.6}}]},{id:"vintage-faded-film",name:"Faded Film",category:"vintage",description:"Washed-out lifted blacks",effects:[{type:"contrast",params:{value:.82}},{type:"saturation",params:{value:.8}},{type:"brightness",params:{value:.08}},{type:"grain",params:{amount:.12,size:1.4,roughness:.5,colored:!1}},{type:"vignette",params:{amount:.2,midpoint:.5,roundness:.5,feather:.8}}]},{id:"vintage-super8",name:"Super 8",category:"vintage",description:"Warm grainy home-movie feel",effects:[{type:"hue",params:{rotation:18}},{type:"saturation",params:{value:1.1}},{type:"contrast",params:{value:1.08}},{type:"grain",params:{amount:.22,size:1.8,roughness:.6,colored:!0}},{type:"vignette",params:{amount:.35,midpoint:.45,roundness:.5,feather:.7}}]},{id:"mood-sunset",name:"Sunset",category:"mood",description:"Warm golden glow",effects:[{type:"hue",params:{rotation:20}},{type:"saturation",params:{value:1.2}},{type:"brightness",params:{value:.06}},{type:"contrast",params:{value:1.08}},{type:"vignette",params:{amount:.2,midpoint:.55,roundness:.6,feather:.85}}]},{id:"mood-winter-chill",name:"Winter Chill",category:"mood",description:"Cold, crisp blue tone",effects:[{type:"hue",params:{rotation:200}},{type:"saturation",params:{value:.78}},{type:"brightness",params:{value:.1}},{type:"contrast",params:{value:1.1}}]},{id:"mood-dramatic",name:"Dramatic",category:"mood",description:"Moody high-contrast with vignette",effects:[{type:"contrast",params:{value:1.3}},{type:"saturation",params:{value:.85}},{type:"brightness",params:{value:-.06}},{type:"vignette",params:{amount:.5,midpoint:.4,roundness:.5,feather:.6}}]},{id:"color-pop",name:"Pop",category:"color",description:"Vivid, punchy colors",effects:[{type:"saturation",params:{value:1.45}},{type:"contrast",params:{value:1.18}},{type:"sharpen",params:{amount:.25,radius:1,threshold:10}}]},{id:"color-pastel",name:"Pastel",category:"color",description:"Soft, airy low-contrast tones",effects:[{type:"contrast",params:{value:.82}},{type:"saturation",params:{value:.82}},{type:"brightness",params:{value:.14}}]},{id:"stylized-dreamscape",name:"Dreamscape",category:"stylized",description:"Hazy, glowing dream look",effects:[{type:"blur",params:{radius:2.5,type:"gaussian"}},{type:"brightness",params:{value:.18}},{type:"saturation",params:{value:1.15}},{type:"contrast",params:{value:.9}}]},{id:"stylized-hdr",name:"Crisp HDR",category:"stylized",description:"Hyper-detailed punchy clarity",effects:[{type:"contrast",params:{value:1.25}},{type:"saturation",params:{value:1.2}},{type:"sharpen",params:{amount:.6,radius:1.5,threshold:4}}]},{id:"stylized-matrix",name:"Matrix",category:"stylized",description:"Green-tinted digital dystopia",effects:[{type:"hue",params:{rotation:95}},{type:"saturation",params:{value:1.1}},{type:"contrast",params:{value:1.2}},{type:"brightness",params:{value:-.05}}]}],Na=Math.PI,To=1.70158,co=To*1.525,Hr=To+1,qn=2*Na/3,Xr=2*Na/4.5,wt=a=>a<1/2.75?7.5625*a*a:a<2/2.75?7.5625*(a-=1.5/2.75)*a+.75:a<2.5/2.75?7.5625*(a-=2.25/2.75)*a+.9375:7.5625*(a-=2.625/2.75)*a+.984375,Kr=a=>a===0?0:a===1?1:-Math.pow(2,10*a-10)*Math.sin((a*10-10.75)*qn),Qr=a=>a===0?0:a===1?1:Math.pow(2,-10*a)*Math.sin((a*10-.75)*qn)+1,Jr=a=>a===0?0:a===1?1:a<.5?-(Math.pow(2,20*a-10)*Math.sin((20*a-11.125)*Xr))/2:Math.pow(2,-20*a+10)*Math.sin((20*a-11.125)*Xr)/2+1,mt={linear:a=>a,ease:uo(.25,.1,.25,1),"ease-in":a=>a*a,"ease-out":a=>1-(1-a)*(1-a),"ease-in-out":a=>a<.5?2*a*a:1-Math.pow(-2*a+2,2)/2,hold:a=>a>=1?1:0,bezier:uo(.25,.1,.25,1),smoothstep:a=>a*a*(3-2*a),smootherstep:a=>a*a*a*(a*(a*6-15)+10),snappy:uo(.19,1,.22,1),smooth:uo(.4,0,.2,1),easeInQuad:a=>a*a,easeOutQuad:a=>1-(1-a)*(1-a),easeInOutQuad:a=>a<.5?2*a*a:1-Math.pow(-2*a+2,2)/2,easeInCubic:a=>a*a*a,easeOutCubic:a=>1-Math.pow(1-a,3),easeInOutCubic:a=>a<.5?4*a*a*a:1-Math.pow(-2*a+2,3)/2,easeInQuart:a=>a*a*a*a,easeOutQuart:a=>1-Math.pow(1-a,4),easeInOutQuart:a=>a<.5?8*a*a*a*a:1-Math.pow(-2*a+2,4)/2,easeInQuint:a=>a*a*a*a*a,easeOutQuint:a=>1-Math.pow(1-a,5),easeInOutQuint:a=>a<.5?16*a*a*a*a*a:1-Math.pow(-2*a+2,5)/2,easeInSine:a=>1-Math.cos(a*Na/2),easeOutSine:a=>Math.sin(a*Na/2),easeInOutSine:a=>-(Math.cos(Na*a)-1)/2,easeInExpo:a=>a===0?0:Math.pow(2,10*a-10),easeOutExpo:a=>a===1?1:1-Math.pow(2,-10*a),easeInOutExpo:a=>a===0?0:a===1?1:a<.5?Math.pow(2,20*a-10)/2:(2-Math.pow(2,-20*a+10))/2,easeInCirc:a=>1-Math.sqrt(1-Math.pow(a,2)),easeOutCirc:a=>Math.sqrt(1-Math.pow(a-1,2)),easeInOutCirc:a=>a<.5?(1-Math.sqrt(1-Math.pow(2*a,2)))/2:(Math.sqrt(1-Math.pow(-2*a+2,2))+1)/2,easeInBack:a=>Hr*a*a*a-To*a*a,easeOutBack:a=>1+Hr*Math.pow(a-1,3)+To*Math.pow(a-1,2),easeInOutBack:a=>a<.5?Math.pow(2*a,2)*((co+1)*2*a-co)/2:(Math.pow(2*a-2,2)*((co+1)*(a*2-2)+co)+2)/2,easeInBackStrong:a=>(2.70158+1)*a*a*a-2.70158*a*a,easeOutBackStrong:a=>1+(2.70158+1)*Math.pow(a-1,3)+2.70158*Math.pow(a-1,2),easeInOutBackStrong:a=>{const e=4.1199094999999994;return a<.5?Math.pow(2*a,2)*((e+1)*2*a-e)/2:(Math.pow(2*a-2,2)*((e+1)*(a*2-2)+e)+2)/2},easeInElastic:Kr,easeOutElastic:Qr,easeInOutElastic:Jr,easeInElasticSoft:a=>a+(Kr(a)-a)*.65,easeOutElasticSoft:a=>a+(Qr(a)-a)*.65,easeInOutElasticSoft:a=>a+(Jr(a)-a)*.65,easeInBounce:a=>1-wt(1-a),easeOutBounce:wt,easeInOutBounce:a=>a<.5?(1-wt(1-2*a))/2:(1+wt(2*a-1))/2,easeInBounceSmall:a=>a+(1-wt(1-a)-a)*.82,easeOutBounceSmall:a=>a+(wt(a)-a)*.82,easeInOutBounceSmall:a=>{const e=a<.5?(1-wt(1-2*a))/2:(1+wt(2*a-1))/2;return a+(e-a)*.82}};function uo(a,e,t,o){const i=3*a,r=3*(t-a)-i,n=1-i-r,s=3*e,l=3*(o-e)-s,c=1-s-l,u=h=>((n*h+r)*h+i)*h,f=h=>((c*h+l)*h+s)*h,d=h=>(3*n*h+2*r)*h+i,m=h=>{let p=h;for(let y=0;y<8;y++){const v=u(p)-h;if(Math.abs(v)<1e-6)return p;const b=d(p);if(Math.abs(b)<1e-6)break;p=p-v/b}let g=0,_=1;for(p=h;g<_;){const y=u(p);if(Math.abs(y-h)<1e-6)return p;h>y?g=p:_=p,p=(_-g)*.5+g}return p};return h=>f(m(h))}const Su=[{id:"flash",name:"Flash",description:"Quick burst of speed in the middle",keyframes:[{time:0,speed:.5,easing:"easeInQuad"},{time:.3,speed:4,easing:"easeOutQuad"},{time:.7,speed:4,easing:"easeInQuad"},{time:1,speed:.5,easing:"linear"}]},{id:"smooth-slow-mo",name:"Smooth Slow-Mo",description:"Gradual slow down and speed up",keyframes:[{time:0,speed:1,easing:"easeInOutCubic"},{time:.3,speed:.3,easing:"linear"},{time:.7,speed:.3,easing:"easeInOutCubic"},{time:1,speed:1,easing:"linear"}]},{id:"jump-cut",name:"Jump Cut",description:"Alternating fast and normal speed",keyframes:[{time:0,speed:1,easing:"linear"},{time:.2,speed:3,easing:"linear"},{time:.4,speed:1,easing:"linear"},{time:.6,speed:3,easing:"linear"},{time:.8,speed:1,easing:"linear"},{time:1,speed:3,easing:"linear"}]},{id:"montage",name:"Montage",description:"Gradual acceleration throughout",keyframes:[{time:0,speed:1,easing:"easeInQuart"},{time:.5,speed:1.5,easing:"easeInQuart"},{time:1,speed:3,easing:"linear"}]},{id:"hero-moment",name:"Hero Moment",description:"Dramatic slow-down at the peak",keyframes:[{time:0,speed:1.5,easing:"easeInCubic"},{time:.35,speed:.2,easing:"linear"},{time:.65,speed:.2,easing:"easeOutCubic"},{time:1,speed:1.5,easing:"linear"}]},{id:"bullet-time",name:"Bullet Time",description:"Near freeze in the center",keyframes:[{time:0,speed:2,easing:"easeInExpo"},{time:.4,speed:.1,easing:"linear"},{time:.6,speed:.1,easing:"easeOutExpo"},{time:1,speed:2,easing:"linear"}]}],xt=a=>!a||a==="linear"?t=>t:a==="ease-in"?mt.easeInQuad:a==="ease-out"?mt.easeOutQuad:a==="ease-in-out"?mt.easeInOutQuad:a==="bezier"?mt.easeInOutCubic:mt[a]||(t=>t),J={opacity:1,scale:{x:1,y:1},rotation:0,offsetX:0,offsetY:0,blur:0},ku=a=>{const{unit:e,progress:t,isIn:o}=a,i=a.animation.stagger||.05,r=e.index*i,n=a.animation.inDuration-(e.totalUnits-1)*i;let s;return o?s=Math.max(0,Math.min(1,(t*a.animation.inDuration-r)/n)):s=1-Math.max(0,Math.min(1,(t*a.animation.outDuration-r)/n)),{...J,opacity:s>=.5?1:0}},Cu=a=>{const{unit:e,progress:t,isIn:o,animation:i}=a,r=i.params,n=i.stagger||.03,s=xt(r.easing||"easeOutQuad"),l=e.index*n,c=o?i.inDuration:i.outDuration,u=Math.max(.1,c-(e.totalUnits-1)*n);let f=Math.max(0,Math.min(1,(t*c-l)/u));o||(f=1-f);const d=s(f),m=r.fadeOpacity?.start??0,h=r.fadeOpacity?.end??1,p=m+(h-m)*d;return{...J,opacity:p}},fo=a=>e=>{const{unit:t,progress:o,isIn:i,animation:r}=e,n=r.params,s=r.stagger||.03,l=xt(n.easing||"easeOutCubic"),c=n.slideDistance||50,u=t.index*s,f=i?r.inDuration:r.outDuration,d=Math.max(.1,f-(t.totalUnits-1)*s);let m=Math.max(0,Math.min(1,(o*f-u)/d));i||(m=1-m);const h=l(m);let p=0,g=0;const _=c*(1-h);switch(a){case"left":p=-_;break;case"right":p=_;break;case"up":g=-_;break;case"down":g=_;break}return{...J,opacity:h,offsetX:p,offsetY:g}},Ou=a=>{const{unit:e,progress:t,isIn:o,animation:i}=a,r=i.params,n=i.stagger||.03,s=xt(r.easing||"easeOutBack"),l=r.scaleFrom??0,c=r.scaleTo??1,u=e.index*n,f=o?i.inDuration:i.outDuration,d=Math.max(.1,f-(e.totalUnits-1)*n);let m=Math.max(0,Math.min(1,(t*f-u)/d));o||(m=1-m);const h=s(m),p=l+(c-l)*h;return{...J,opacity:h,scale:{x:p,y:p}}},Tu=a=>{const{unit:e,progress:t,isIn:o,animation:i}=a,r=i.params,n=i.stagger||.03,s=xt(r.easing||"easeOutQuad"),l=r.blurAmount??10,c=e.index*n,u=o?i.inDuration:i.outDuration,f=Math.max(.1,u-(e.totalUnits-1)*n);let d=Math.max(0,Math.min(1,(t*u-c)/f));o||(d=1-d);const m=s(d),h=l*(1-m);return{...J,opacity:m,blur:h}},Uu=a=>{const{unit:e,progress:t,isIn:o,animation:i}=a,r=i.params,n=i.stagger||.05,s=r.bounceHeight??30,l=e.index*n,c=o?i.inDuration:i.outDuration,u=Math.max(.1,c-(e.totalUnits-1)*n);let f=Math.max(0,Math.min(1,(t*c-l)/u));o||(f=1-f);const d=mt.easeOutBounce(f),m=-s*(1-d);return{...J,opacity:f>0?1:0,offsetY:m}},Iu=a=>{const{unit:e,progress:t,isIn:o,animation:i}=a,r=i.params,n=i.stagger||.03,s=xt(r.easing||"easeOutBack"),l=r.rotateAngle??180,c=e.index*n,u=o?i.inDuration:i.outDuration,f=Math.max(.1,u-(e.totalUnits-1)*n);let d=Math.max(0,Math.min(1,(t*u-c)/f));o||(d=1-d);const m=s(d),h=l*(1-m);return{...J,opacity:m,rotation:h,scale:{x:m,y:m}}},Au=a=>{const{unit:e,progress:t,animation:o}=a,i=o.params,r=i.waveAmplitude??10,n=i.waveFrequency??2,s=e.index/e.totalUnits*Math.PI*2,l=Math.sin(t*Math.PI*2*n+s)*r;return{...J,offsetY:l}},Mu=a=>{const{progress:e,animation:t}=a,o=t.params,i=o.shakeIntensity??5,r=o.shakeSpeed??20,n=Math.sin(e*Math.PI*2*r)*i,s=Math.cos(e*Math.PI*2*r*1.3)*i*.5;return{...J,offsetX:n,offsetY:s}},Bu=a=>{const{unit:e,progress:t,isIn:o,animation:i}=a,r=i.params,n=i.stagger||.05,s=r.popOvershoot??1.2,l=e.index*n,c=o?i.inDuration:i.outDuration,u=Math.max(.1,c-(e.totalUnits-1)*n);let f=Math.max(0,Math.min(1,(t*c-l)/u));o||(f=1-f);const d=mt.easeOutBack(f),m=f>0?d*(f<.5?s:1):0;return{...J,opacity:f>0?1:0,scale:{x:Math.max(0,m),y:Math.max(0,m)}}},Vu=a=>{const{unit:e,progress:t,animation:o}=a,i=o.params,r=i.glitchIntensity??10,n=i.glitchSpeed??10,s=t*n,l=Math.floor(s)+e.index*.3,c=Math.sin(l*12.9898)*43758.5453,u=c-Math.floor(c),f=u>.7,d=f?(u-.5)*r*2:0,m=f?(u-.5)*5:0;return{...J,offsetX:d,skewX:m,color:f&&u>.85?`hsl(${u*360}, 100%, 50%)`:void 0}},Ru=a=>{const{unit:e,progress:t,isIn:o,animation:i}=a,r=i.params,n=i.stagger||.03,s=xt(r.easing||"easeOutCubic"),l=r.splitDirection||"horizontal",c=e.index*n,u=o?i.inDuration:i.outDuration,f=Math.max(.1,u-(e.totalUnits-1)*n);let d=Math.max(0,Math.min(1,(t*u-c)/f));o||(d=1-d);const m=s(d),h=(e.totalUnits-1)/2,_=100*(e.index-h)*(1-m)/h;return{...J,opacity:m,offsetX:l==="horizontal"?_:0,offsetY:l==="vertical"?_:0}},Pu=a=>{const{unit:e,progress:t,isIn:o,animation:i}=a,r=i.params,n=i.stagger||.05,s=xt(r.easing||"easeOutBack"),l=r.flipAxis||"y",c=e.index*n,u=o?i.inDuration:i.outDuration,f=Math.max(.1,u-(e.totalUnits-1)*n);let d=Math.max(0,Math.min(1,(t*u-c)/f));o||(d=1-d);const m=s(d),h=90*(1-m),p=Math.cos(h*Math.PI/180);return{...J,opacity:m>.1?1:0,scale:l==="x"?{x:p,y:1}:{x:1,y:p},rotation:0}},Du=a=>{const{unit:e,progress:t,isIn:o,animation:i}=a,r=i.params,n=r.wordDelay??.2,s=xt(r.easing||"easeOutQuad"),l=e.index*n,c=o?i.inDuration:i.outDuration;let f=Math.max(0,Math.min(1,(t*c-l)/.3));o||(f=1-f);const d=s(f);return{...J,opacity:d,offsetY:20*(1-d),scale:{x:.8+.2*d,y:.8+.2*d}}},zu=a=>{const{unit:e,progress:t,animation:o}=a,r=o.params.rainbowSpeed??1,n=(e.index/e.totalUnits*360+t*360*r)%360;return{...J,color:`hsl(${n}, 80%, 60%)`}},Ua=(a,e,t)=>{const{unit:o,animation:i,isIn:r,progress:n}=a,s=i.stagger??e,l=r?i.inDuration:i.outDuration,c=o.index*s,u=Math.max(.1,l-(o.totalUnits-1)*s);let f=Math.max(0,Math.min(1,(n*l-c)/u));r||(f=1-f);const d=xt(a.animation.params.easing||t);return{raw:f,eased:d(f)}},Fu=a=>{const{raw:e,eased:t}=Ua(a,.08,"easeOutCubic"),o=a.animation.params.slideDistance??36,i=a.animation.params.blurAmount??8;return{...J,opacity:e,offsetY:o*(1-t),blur:Math.max(0,i*(1-e)),scale:{x:.88+t*.12,y:.88+t*.12}}},Nu=a=>{const{raw:e}=Ua(a,.045,"easeOutBounceSmall"),t=mt.easeOutBounceSmall(e),o=a.animation.params.slideDistance??60,i=a.animation.params.rotateAngle??10,r=a.unit.index%2===0?-1:1;return{...J,opacity:e>0?1:0,offsetY:-o*(1-t),rotation:r*i*(1-t)}},Eu=a=>{const{raw:e}=Ua(a,.08,"easeOutElasticSoft"),t=mt.easeOutElasticSoft(e),o=a.animation.params.scaleFrom??.15,i=o+(1-o)*t;return{...J,opacity:e>0?1:0,scale:{x:Math.max(0,i),y:Math.max(0,i)}}},Lu=a=>{const{raw:e,eased:t}=Ua(a,.09,"easeOutBack"),o=a.animation.params.rotateAngle??28,i=a.animation.params.slideDistance??20,r=a.unit.index%2===0?-1:1;return{...J,opacity:e,offsetY:-i*(1-e),rotation:r*o*(1-t)}},$u=a=>{const{raw:e,eased:t}=Ua(a,.06,"easeOutExpo"),o=a.animation.params.scaleFrom??1.65,i=a.animation.params.blurAmount??14,r=o+(1-o)*t;return{...J,opacity:e,scale:{x:r,y:r},blur:Math.max(0,i*(1-e))}},ju=a=>{const{raw:e,eased:t}=Ua(a,.035,"easeOutCubic"),o=a.animation.params.slideDistance??48,i=a.animation.params.rotateAngle??8,r=a.unit.index%2===0?-1:1;return{...J,opacity:e,offsetX:r*o*.35*(1-t),offsetY:o*(1-t),rotation:r*i*(1-t),scale:{x:.9+t*.1,y:.9+t*.1}}},Wu={none:()=>J,typewriter:ku,fade:Cu,"slide-left":fo("left"),"slide-right":fo("right"),"slide-up":fo("up"),"slide-down":fo("down"),scale:Ou,blur:Tu,bounce:Uu,rotate:Iu,wave:Au,shake:Mu,pop:Bu,glitch:Vu,split:Ru,flip:Pu,"word-by-word":Du,rainbow:zu,rise:Fu,drop:Nu,elastic:Eu,swing:Lu,"zoom-blur":$u,cascade:ju};function si(a){const e=Wu[a.animation.preset];return e?e(a):J}const Gu=[{id:"none",name:"None",description:"No animation",category:"entrance",defaultParams:{},defaultUnit:"character",defaultStagger:0,defaultInDuration:0,defaultOutDuration:0},{id:"typewriter",name:"Typewriter",description:"Characters appear one by one",category:"entrance",defaultParams:{},defaultUnit:"character",defaultStagger:.05,defaultInDuration:1,defaultOutDuration:.5},{id:"fade",name:"Fade In",description:"Smooth opacity transition",category:"entrance",defaultParams:{fadeOpacity:{start:0,end:1},easing:"easeOutQuad"},defaultUnit:"character",defaultStagger:.03,defaultInDuration:.5,defaultOutDuration:.3},{id:"slide-up",name:"Slide Up",description:"Slides in from below",category:"entrance",defaultParams:{slideDistance:50,easing:"easeOutCubic"},defaultUnit:"word",defaultStagger:.1,defaultInDuration:.5,defaultOutDuration:.3},{id:"slide-down",name:"Slide Down",description:"Slides in from above",category:"entrance",defaultParams:{slideDistance:50,easing:"easeOutCubic"},defaultUnit:"word",defaultStagger:.1,defaultInDuration:.5,defaultOutDuration:.3},{id:"slide-left",name:"Slide Left",description:"Slides in from the right",category:"entrance",defaultParams:{slideDistance:50,easing:"easeOutCubic"},defaultUnit:"character",defaultStagger:.02,defaultInDuration:.5,defaultOutDuration:.3},{id:"slide-right",name:"Slide Right",description:"Slides in from the left",category:"entrance",defaultParams:{slideDistance:50,easing:"easeOutCubic"},defaultUnit:"character",defaultStagger:.02,defaultInDuration:.5,defaultOutDuration:.3},{id:"scale",name:"Scale In",description:"Grows from small to full size",category:"entrance",defaultParams:{scaleFrom:0,scaleTo:1,easing:"easeOutBack"},defaultUnit:"character",defaultStagger:.03,defaultInDuration:.5,defaultOutDuration:.3},{id:"blur",name:"Blur In",description:"Fades in while unblurring",category:"entrance",defaultParams:{blurAmount:10,easing:"easeOutQuad"},defaultUnit:"word",defaultStagger:.1,defaultInDuration:.5,defaultOutDuration:.3},{id:"bounce",name:"Bounce",description:"Bounces into place",category:"entrance",defaultParams:{bounceHeight:30},defaultUnit:"character",defaultStagger:.05,defaultInDuration:.8,defaultOutDuration:.3},{id:"rotate",name:"Rotate In",description:"Spins while appearing",category:"entrance",defaultParams:{rotateAngle:180,easing:"easeOutBack"},defaultUnit:"character",defaultStagger:.05,defaultInDuration:.6,defaultOutDuration:.3},{id:"pop",name:"Pop",description:"Pops in with overshoot",category:"entrance",defaultParams:{popOvershoot:1.2},defaultUnit:"character",defaultStagger:.05,defaultInDuration:.5,defaultOutDuration:.3},{id:"flip",name:"Flip",description:"Flips into view",category:"entrance",defaultParams:{flipAxis:"y",easing:"easeOutBack"},defaultUnit:"character",defaultStagger:.05,defaultInDuration:.6,defaultOutDuration:.3},{id:"split",name:"Split",description:"Characters split from center",category:"entrance",defaultParams:{splitDirection:"horizontal",easing:"easeOutCubic"},defaultUnit:"character",defaultStagger:0,defaultInDuration:.5,defaultOutDuration:.3},{id:"word-by-word",name:"Word by Word",description:"Words appear one at a time",category:"entrance",defaultParams:{wordDelay:.2,easing:"easeOutQuad"},defaultUnit:"word",defaultStagger:.2,defaultInDuration:1,defaultOutDuration:.5},{id:"rise",name:"Rise",description:"Soft blurred rise with a subtle scale settle",category:"entrance",defaultParams:{slideDistance:36,blurAmount:8,easing:"easeOutCubic"},defaultUnit:"word",defaultStagger:.08,defaultInDuration:.65,defaultOutDuration:.35},{id:"drop",name:"Drop",description:"Characters drop in and land with a soft bounce",category:"entrance",defaultParams:{slideDistance:60,rotateAngle:10,easing:"easeOutBounceSmall"},defaultUnit:"character",defaultStagger:.045,defaultInDuration:.8,defaultOutDuration:.35},{id:"elastic",name:"Elastic",description:"Springy scale entrance with a controlled overshoot",category:"entrance",defaultParams:{scaleFrom:.15,popOvershoot:1.25,easing:"easeOutElasticSoft"},defaultUnit:"word",defaultStagger:.08,defaultInDuration:.9,defaultOutDuration:.4},{id:"swing",name:"Swing",description:"Alternating hinged letters swing into place",category:"entrance",defaultParams:{rotateAngle:28,slideDistance:20,easing:"easeOutBack"},defaultUnit:"character",defaultStagger:.09,defaultInDuration:.75,defaultOutDuration:.4},{id:"zoom-blur",name:"Zoom Blur",description:"Sharpens from a cinematic forward zoom",category:"entrance",defaultParams:{scaleFrom:1.65,blurAmount:14,easing:"easeOutExpo"},defaultUnit:"word",defaultStagger:.06,defaultInDuration:.65,defaultOutDuration:.35},{id:"cascade",name:"Cascade",description:"Staggered diagonal character entrance",category:"entrance",defaultParams:{slideDistance:48,rotateAngle:8,easing:"easeOutCubic"},defaultUnit:"character",defaultStagger:.035,defaultInDuration:.85,defaultOutDuration:.4},{id:"wave",name:"Wave",description:"Continuous wave motion",category:"continuous",defaultParams:{waveAmplitude:10,waveFrequency:2},defaultUnit:"character",defaultStagger:0,defaultInDuration:0,defaultOutDuration:0},{id:"shake",name:"Shake",description:"Continuous shaking",category:"continuous",defaultParams:{shakeIntensity:5,shakeSpeed:20},defaultUnit:"character",defaultStagger:0,defaultInDuration:0,defaultOutDuration:0},{id:"glitch",name:"Glitch",description:"Digital glitch effect",category:"emphasis",defaultParams:{glitchIntensity:10,glitchSpeed:10},defaultUnit:"character",defaultStagger:0,defaultInDuration:0,defaultOutDuration:0},{id:"rainbow",name:"Rainbow",description:"Cycling rainbow colors",category:"continuous",defaultParams:{rainbowSpeed:1},defaultUnit:"character",defaultStagger:0,defaultInDuration:0,defaultOutDuration:0}],Ya=a=>`${a}-${Date.now()}-${Math.random().toString(36).slice(2,9)}`,Zr=[{id:"motion-ad-card",name:"Ad Card",category:"ads",description:"A clean animated headline scene for short product ads.",variables:[L("headline","Headline","Launch faster"),L("subheadline","Subheadline","Turn product moments into polished ads."),ue("brand-color","Brand color","#14b8a6")],create:()=>St({name:"Ad Card",duration:6,backgroundColor:"#111827",variables:[L("headline","Headline","Launch faster"),L("subheadline","Subheadline","Turn product moments into polished ads."),ue("brand-color","Brand color","#14b8a6")],layers:a=>[re(a,{id:"ad-bg-wash",name:"Brand Wash",x:a.width*.5,y:a.height*.5,width:a.width*1.25,height:a.height*.95,color:"#1f2937",opacity:.9,cornerRadius:0,keyframes:Aa(0,.7,.96,1)}),re(a,{id:"ad-accent-bar",name:"Accent Bar",x:a.width*.5,y:a.height*.68,width:620,height:18,color:"#14b8a6",cornerRadius:999,variableBindings:[{variableId:"brand-color",target:"shape.fill.color"}],keyframes:[Y("transform.scale.x",0,0,"ease-out"),Y("transform.scale.x",.8,1,"ease-out")]}),he(a,{id:"ad-headline",name:"Headline",text:"Launch faster",x:a.width*.5,y:a.height*.46,fontSize:112,fontWeight:850,color:"#ffffff",variableBindings:[{variableId:"headline",target:"text.content"}],keyframes:Fe("y",0,.75,a.height*.46,80,0,1)}),he(a,{id:"ad-subheadline",name:"Subheadline",text:"Turn product moments into polished ads.",x:a.width*.5,y:a.height*.57,fontSize:42,fontWeight:500,color:"#d1d5db",variableBindings:[{variableId:"subheadline",target:"text.content"}],keyframes:ze(.35,1)})]})},{id:"motion-app-ui-demo",name:"App UI Demo",category:"app-ui-demos",description:"Animated interface cards for product launch walkthroughs.",variables:[L("headline","Headline","Your workflow, automated"),ue("brand-color","Brand color","#60a5fa")],create:()=>St({name:"App UI Demo",duration:8,backgroundColor:"#0b1020",variables:[L("headline","Headline","Your workflow, automated"),ue("brand-color","Brand color","#60a5fa")],layers:a=>[re(a,{id:"ui-window",name:"App Window",x:a.width*.5,y:a.height*.55,width:1060,height:620,color:"#f8fafc",cornerRadius:28,keyframes:Fe("y",.15,.8,a.height*.55,90,0,1)}),re(a,{id:"ui-sidebar",name:"Sidebar",x:a.width*.29,y:a.height*.55,width:250,height:560,color:"#e2e8f0",cornerRadius:18,keyframes:ze(.35,.9)}),re(a,{id:"ui-primary-card",name:"Primary Card",x:a.width*.58,y:a.height*.48,width:560,height:210,color:"#60a5fa",cornerRadius:24,variableBindings:[{variableId:"brand-color",target:"shape.fill.color"}],keyframes:Fe("x",.55,1.15,a.width*.58,-90,0,1)}),re(a,{id:"ui-cursor",name:"Cursor",x:a.width*.68,y:a.height*.48,width:42,height:42,shapeType:"triangle",color:"#111827",keyframes:[Y("transform.position.x",1.15,a.width*.68,"ease"),Y("transform.position.y",1.15,a.height*.48,"ease"),Y("transform.position.x",2.2,a.width*.54,"ease-in-out"),Y("transform.position.y",2.2,a.height*.63,"ease-in-out")]}),he(a,{id:"ui-headline",name:"Headline",text:"Your workflow, automated",x:a.width*.5,y:a.height*.17,fontSize:66,fontWeight:800,color:"#ffffff",variableBindings:[{variableId:"headline",target:"text.content"}],keyframes:ze(0,.65)})]})},{id:"motion-lower-third",name:"Lower Third",category:"lower-thirds",description:"A reusable animated lower-third composition.",variables:[L("name","Name","Avery Stone"),L("title","Title","Creative Director"),ue("brand-color","Brand color","#14b8a6")],create:()=>St({name:"Lower Third",duration:4,backgroundColor:"transparent",variables:[L("name","Name","Avery Stone"),L("title","Title","Creative Director"),ue("brand-color","Brand color","#14b8a6")],layers:a=>[re(a,{id:"lt-panel",name:"Name Plate",x:a.width*.32,y:a.height*.78,width:720,height:138,color:"#0f172a",opacity:.92,cornerRadius:18,keyframes:Fe("x",0,.55,a.width*.32,-120,0,1)}),re(a,{id:"lt-accent",name:"Accent",x:a.width*.14,y:a.height*.78,width:18,height:120,color:"#14b8a6",cornerRadius:999,variableBindings:[{variableId:"brand-color",target:"shape.fill.color"}],keyframes:ze(.15,.45)}),he(a,{id:"lt-name",name:"Name",text:"Avery Stone",x:a.width*.34,y:a.height*.75,fontSize:52,fontWeight:800,color:"#ffffff",align:"left",variableBindings:[{variableId:"name",target:"text.content"}],keyframes:Fe("x",.12,.55,a.width*.34,-80,0,1)}),he(a,{id:"lt-title",name:"Title",text:"Creative Director",x:a.width*.34,y:a.height*.82,fontSize:28,fontWeight:500,color:"#cbd5e1",align:"left",variableBindings:[{variableId:"title",target:"text.content"}],keyframes:ze(.32,.65)})]})},{id:"motion-product-shot",name:"Product Shot",category:"product-shots",description:"Hero product frame with feature callouts and brand controls.",variables:[L("headline","Headline","Meet the new dashboard"),L("badge","Badge","New"),ue("brand-color","Brand color","#f59e0b")],create:()=>St({name:"Product Shot",duration:7,backgroundColor:"#111827",variables:[L("headline","Headline","Meet the new dashboard"),L("badge","Badge","New"),ue("brand-color","Brand color","#f59e0b")],layers:a=>[re(a,{id:"product-card",name:"Product Frame",x:a.width*.5,y:a.height*.56,width:920,height:520,color:"#f8fafc",cornerRadius:34,keyframes:Aa(.18,.9,.88,1)}),re(a,{id:"product-screen",name:"Media Placeholder",x:a.width*.5,y:a.height*.57,width:820,height:405,color:"#cbd5e1",cornerRadius:24,keyframes:ze(.45,.9)}),re(a,{id:"product-badge-pill",name:"Badge Pill",x:a.width*.29,y:a.height*.2,width:148,height:54,color:"#f59e0b",cornerRadius:999,variableBindings:[{variableId:"brand-color",target:"shape.fill.color"}],keyframes:Fe("y",0,.55,a.height*.2,-30,0,1)}),he(a,{id:"product-badge",name:"Badge",text:"New",x:a.width*.29,y:a.height*.203,fontSize:28,fontWeight:800,color:"#111827",variableBindings:[{variableId:"badge",target:"text.content"}],keyframes:ze(.05,.55)}),he(a,{id:"product-headline",name:"Headline",text:"Meet the new dashboard",x:a.width*.5,y:a.height*.14,fontSize:72,fontWeight:850,color:"#ffffff",variableBindings:[{variableId:"headline",target:"text.content"}],keyframes:ze(.2,.8)})]})},{id:"motion-social-hook",name:"Social Hook",category:"social-hooks",description:"Vertical short-form opener with progress and punchy text.",variables:[L("hook","Hook","Stop scrolling"),L("subhook","Subhook","This saves hours every week."),ue("brand-color","Brand color","#f43f5e")],create:()=>St({name:"Social Hook",width:1080,height:1920,duration:5,backgroundColor:"#111827",variables:[L("hook","Hook","Stop scrolling"),L("subhook","Subhook","This saves hours every week."),ue("brand-color","Brand color","#f43f5e")],layers:a=>[re(a,{id:"social-swipe",name:"Color Swipe",x:a.width*.5,y:a.height*.5,width:a.width,height:a.height,color:"#f43f5e",variableBindings:[{variableId:"brand-color",target:"shape.fill.color"}],keyframes:[Y("transform.scale.y",0,0,"ease-out"),Y("transform.scale.y",.55,1,"ease-out"),Y("transform.opacity",1.15,.28,"ease")]}),he(a,{id:"social-hook",name:"Hook",text:"Stop scrolling",x:a.width*.5,y:a.height*.42,fontSize:118,fontWeight:900,color:"#ffffff",variableBindings:[{variableId:"hook",target:"text.content"}],keyframes:Fe("y",.1,.55,a.height*.42,100,0,1)}),he(a,{id:"social-subhook",name:"Subhook",text:"This saves hours every week.",x:a.width*.5,y:a.height*.54,fontSize:48,fontWeight:650,color:"#f8fafc",variableBindings:[{variableId:"subhook",target:"text.content"}],keyframes:ze(.42,.9)}),re(a,{id:"social-progress",name:"Progress",x:a.width*.5,y:a.height*.91,width:a.width*.82,height:12,color:"#ffffff",cornerRadius:999,keyframes:[Y("transform.scale.x",0,0,"linear"),Y("transform.scale.x",a.duration,1,"linear")]})]})},{id:"motion-kinetic-title",name:"Kinetic Title",category:"kinetic-typography",description:"A staggered animated headline for launches, hooks, and ads.",variables:[L("word-1","Word 1","Design"),L("word-2","Word 2","Moves"),L("word-3","Word 3","People"),ue("brand-color","Brand color","#38bdf8")],create:()=>St({name:"Kinetic Title",duration:5,backgroundColor:"#0f172a",variables:[L("word-1","Word 1","Design"),L("word-2","Word 2","Moves"),L("word-3","Word 3","People"),ue("brand-color","Brand color","#38bdf8")],layers:a=>[he(a,{id:"kinetic-word-1",name:"Word 1",text:"Design",x:a.width*.34,y:a.height*.4,fontSize:126,fontWeight:900,color:"#ffffff",variableBindings:[{variableId:"word-1",target:"text.content"}],keyframes:Fe("x",0,.45,a.width*.34,-120,0,1)}),he(a,{id:"kinetic-word-2",name:"Word 2",text:"Moves",x:a.width*.58,y:a.height*.52,fontSize:146,fontWeight:900,color:"#38bdf8",variableBindings:[{variableId:"word-2",target:"text.content"},{variableId:"brand-color",target:"text.color"}],keyframes:Fe("x",.18,.58,a.width*.58,120,0,1)}),he(a,{id:"kinetic-word-3",name:"Word 3",text:"People",x:a.width*.5,y:a.height*.66,fontSize:112,fontWeight:800,color:"#e2e8f0",variableBindings:[{variableId:"word-3",target:"text.content"}],keyframes:Fe("y",.36,.76,a.height*.66,110,0,1)})]})},{id:"motion-logo-reveal",name:"Logo Reveal",category:"logo-reveals",description:"A simple reveal scene ready for logo or SVG replacement.",variables:[L("brand-name","Brand name","OpenReel"),ue("brand-color","Brand color","#14b8a6")],create:()=>St({name:"Logo Reveal",duration:5,backgroundColor:"transparent",variables:[L("brand-name","Brand name","OpenReel"),ue("brand-color","Brand color","#14b8a6")],layers:a=>[re(a,{id:"logo-ring",name:"Logo Ring",x:a.width*.5,y:a.height*.43,width:230,height:230,shapeType:"ellipse",color:"#14b8a6",opacity:.18,variableBindings:[{variableId:"brand-color",target:"shape.fill.color"}],keyframes:Aa(0,.9,.35,1)}),re(a,{id:"logo-mark",name:"Logo Mark Placeholder",x:a.width*.5,y:a.height*.43,width:132,height:132,color:"#14b8a6",cornerRadius:30,variableBindings:[{variableId:"brand-color",target:"shape.fill.color"}],keyframes:[...Aa(.18,.78,.65,1),Y("transform.rotation",.18,-18,"ease-out"),Y("transform.rotation",.78,0,"ease-out")]}),he(a,{id:"logo-name",name:"Brand Name",text:"OpenReel",x:a.width*.5,y:a.height*.61,fontSize:74,fontWeight:850,color:"#ffffff",variableBindings:[{variableId:"brand-name",target:"text.content"}],keyframes:ze(.62,1.15)})]})},{id:"motion-end-screen",name:"End Screen",category:"end-screens",description:"Outro card with two placeholders and a strong call to action.",variables:[L("headline","Headline","Keep watching"),L("cta","CTA","Subscribe for more"),ue("brand-color","Brand color","#a78bfa")],create:()=>St({name:"End Screen",duration:6,backgroundColor:"#111827",variables:[L("headline","Headline","Keep watching"),L("cta","CTA","Subscribe for more"),ue("brand-color","Brand color","#a78bfa")],layers:a=>[he(a,{id:"end-headline",name:"Headline",text:"Keep watching",x:a.width*.5,y:a.height*.18,fontSize:82,fontWeight:850,color:"#ffffff",variableBindings:[{variableId:"headline",target:"text.content"}],keyframes:ze(0,.5)}),re(a,{id:"end-card-left",name:"Video Placeholder Left",x:a.width*.33,y:a.height*.52,width:520,height:300,color:"#1f2937",cornerRadius:24,keyframes:Fe("x",.22,.8,a.width*.33,-90,0,1)}),re(a,{id:"end-card-right",name:"Video Placeholder Right",x:a.width*.67,y:a.height*.52,width:520,height:300,color:"#1f2937",cornerRadius:24,keyframes:Fe("x",.34,.92,a.width*.67,90,0,1)}),re(a,{id:"end-cta-pill",name:"CTA Pill",x:a.width*.5,y:a.height*.8,width:430,height:72,color:"#a78bfa",cornerRadius:999,variableBindings:[{variableId:"brand-color",target:"shape.fill.color"}],keyframes:Aa(.55,1.05,.82,1)}),he(a,{id:"end-cta",name:"CTA",text:"Subscribe for more",x:a.width*.5,y:a.height*.805,fontSize:34,fontWeight:800,color:"#111827",variableBindings:[{variableId:"cta",target:"text.content"}],keyframes:ze(.68,1.12)})]})}];function St(a){const e=jo.createComposition({name:a.name,width:a.width,height:a.height,duration:a.duration,backgroundColor:a.backgroundColor});return{...e,variables:Yu(a.variables),layers:a.layers(e),modifiedAt:Date.now()}}function L(a,e,t){return{id:a,label:e,type:"text",defaultValue:t}}function ue(a,e,t){return{id:a,label:e,type:"color",defaultValue:t}}function Yu(a){return a.map(e=>({id:e.id,name:e.label,type:e.type,value:e.defaultValue}))}function he(a,e){return{id:Ya(e.id),type:"text",name:e.name,startTime:0,duration:a.duration,visible:!0,locked:!1,transform:Hn(e.x,e.y),keyframes:e.keyframes??[],variableBindings:e.variableBindings?.map(t=>({id:Ya("motion-binding"),variableId:t.variableId,target:t.target})),text:e.text,style:{fontFamily:"Inter",fontSize:e.fontSize,fontWeight:e.fontWeight,color:e.color,align:e.align??"center",lineHeight:1.05}}}function re(a,e){return{id:Ya(e.id),type:"shape",name:e.name,startTime:0,duration:a.duration,visible:!0,locked:!1,transform:Hn(e.x,e.y,e.opacity??1),keyframes:e.keyframes??[],variableBindings:e.variableBindings?.map(t=>({id:Ya("motion-binding"),variableId:t.variableId,target:t.target})),shapeType:e.shapeType??"rectangle",width:e.width,height:e.height,style:{...En,fill:{type:"solid",color:e.color,opacity:1},stroke:{color:e.color,width:0,opacity:0},cornerRadius:e.cornerRadius??0}}}function Hn(a,e,t=1){return{...wi,position:{x:a,y:e},opacity:t}}function ze(a,e){return[Y("transform.opacity",a,0,"ease-out"),Y("transform.opacity",e,1,"ease-out")]}function Aa(a,e,t,o){return[Y("transform.scale.x",a,t,"ease-out"),Y("transform.scale.y",a,t,"ease-out"),Y("transform.opacity",a,0,"ease-out"),Y("transform.scale.x",e,o,"ease-out"),Y("transform.scale.y",e,o,"ease-out"),Y("transform.opacity",e,1,"ease-out")]}function Fe(a,e,t,o,i,r,n){const s=`transform.position.${a}`;return[Y("transform.opacity",e,r,"ease-out"),Y(s,e,o+i,"ease-out"),Y("transform.opacity",t,n,"ease-out"),Y(s,t,o,"ease-out")]}function Y(a,e,t,o){return{id:Ya("motion-kf"),property:a,time:e,value:t,easing:o}}const qu={"transform.position.x":{property:"transform.position.x",label:"Position X",family:"transform",min:-4e3,max:4e3,step:1,unit:"px",defaultValue:0},"transform.position.y":{property:"transform.position.y",label:"Position Y",family:"transform",min:-4e3,max:4e3,step:1,unit:"px",defaultValue:0},"transform.position.z":{property:"transform.position.z",label:"Position Z",family:"transform",min:-4e3,max:4e3,step:1,unit:"px",defaultValue:0},"transform.scale.x":{property:"transform.scale.x",label:"Scale X",family:"transform",min:0,max:10,step:.01,unit:"%",defaultValue:1,displayScale:100},"transform.scale.y":{property:"transform.scale.y",label:"Scale Y",family:"transform",min:0,max:10,step:.01,unit:"%",defaultValue:1,displayScale:100},"transform.rotation":{property:"transform.rotation",label:"Rotation Z",family:"transform",min:-360,max:360,step:1,unit:"deg",defaultValue:0},"transform.rotation.x":{property:"transform.rotation.x",label:"Rotation X",family:"transform",min:-360,max:360,step:1,unit:"deg",defaultValue:0},"transform.rotation.y":{property:"transform.rotation.y",label:"Rotation Y",family:"transform",min:-360,max:360,step:1,unit:"deg",defaultValue:0},"transform.perspective":{property:"transform.perspective",label:"Perspective",family:"transform",min:100,max:5e3,step:25,unit:"px",defaultValue:1e3},"transform.opacity":{property:"transform.opacity",label:"Opacity",family:"transform",min:0,max:1,step:.01,unit:"%",defaultValue:1,displayScale:100},"transform.anchor.x":{property:"transform.anchor.x",label:"Anchor X",family:"transform",min:0,max:1,step:.01,defaultValue:.5},"transform.anchor.y":{property:"transform.anchor.y",label:"Anchor Y",family:"transform",min:0,max:1,step:.01,defaultValue:.5},"transform.borderRadius":{property:"transform.borderRadius",label:"Border Radius",family:"transform",min:0,max:240,step:1,unit:"px",defaultValue:0},"transform.crop.x":{property:"transform.crop.x",label:"Crop X",family:"crop",min:0,max:1,step:.001,defaultValue:0},"transform.crop.y":{property:"transform.crop.y",label:"Crop Y",family:"crop",min:0,max:1,step:.001,defaultValue:0},"transform.crop.width":{property:"transform.crop.width",label:"Crop Width",family:"crop",min:0,max:1,step:.001,defaultValue:1},"transform.crop.height":{property:"transform.crop.height",label:"Crop Height",family:"crop",min:0,max:1,step:.001,defaultValue:1},"audio.volume":{property:"audio.volume",label:"Volume",family:"audio",min:0,max:2,step:.01,defaultValue:1},"audio.pan":{property:"audio.pan",label:"Pan",family:"audio",min:-1,max:1,step:.01,defaultValue:0},"colorGrade.temperature":{property:"colorGrade.temperature",label:"Temperature",family:"colorGrade",min:-100,max:100,step:1,defaultValue:0},"colorGrade.tint":{property:"colorGrade.tint",label:"Tint",family:"colorGrade",min:-100,max:100,step:1,defaultValue:0}};function Hu(a){return qu[a]}class Bt{constructor(e,t){this.next=null,this.key=e,this.data=t,this.left=null,this.right=null}}function Xu(a,e){return a>e?1:a<e?-1:0}function Ct(a,e,t){const o=new Bt(null,null);let i=o,r=o;for(;;){const n=t(a,e.key);if(n<0){if(e.left===null)break;if(t(a,e.left.key)<0){const s=e.left;if(e.left=s.right,s.right=e,e=s,e.left===null)break}r.left=e,r=e,e=e.left}else if(n>0){if(e.right===null)break;if(t(a,e.right.key)>0){const s=e.right;if(e.right=s.left,s.left=e,e=s,e.right===null)break}i.right=e,i=e,e=e.right}else break}return i.right=e.left,r.left=e.right,e.left=o.right,e.right=o.left,e}function li(a,e,t,o){const i=new Bt(a,e);if(t===null)return i.left=i.right=null,i;t=Ct(a,t,o);const r=o(a,t.key);return r<0?(i.left=t.left,i.right=t,t.left=null):r>=0&&(i.right=t.right,i.left=t,t.right=null),i}function en(a,e,t){let o=null,i=null;if(e){e=Ct(a,e,t);const r=t(e.key,a);r===0?(o=e.left,i=e.right):r<0?(i=e.right,e.right=null,o=e):(o=e.left,e.left=null,i=e)}return{left:o,right:i}}function Ku(a,e,t){return e===null?a:(a===null||(e=Ct(a.key,e,t),e.left=a),e)}function Ci(a,e,t,o,i){if(a){o(`${e}${t?"└── ":"├── "}${i(a)}
`);const r=e+(t?"    ":"│   ");a.left&&Ci(a.left,r,!1,o,i),a.right&&Ci(a.right,r,!0,o,i)}}class Qu{constructor(e=Xu){this._root=null,this._size=0,this._comparator=e}insert(e,t){return this._size++,this._root=li(e,t,this._root,this._comparator)}add(e,t){const o=new Bt(e,t);this._root===null&&(o.left=o.right=null,this._size++,this._root=o);const i=this._comparator,r=Ct(e,this._root,i),n=i(e,r.key);return n===0?this._root=r:(n<0?(o.left=r.left,o.right=r,r.left=null):n>0&&(o.right=r.right,o.left=r,r.right=null),this._size++,this._root=o),this._root}remove(e){this._root=this._remove(e,this._root,this._comparator)}_remove(e,t,o){let i;return t===null?null:(t=Ct(e,t,o),o(e,t.key)===0?(t.left===null?i=t.right:(i=Ct(e,t.left,o),i.right=t.right),this._size--,i):t)}pop(){let e=this._root;if(e){for(;e.left;)e=e.left;return this._root=Ct(e.key,this._root,this._comparator),this._root=this._remove(e.key,this._root,this._comparator),{key:e.key,data:e.data}}return null}findStatic(e){let t=this._root;const o=this._comparator;for(;t;){const i=o(e,t.key);if(i===0)return t;i<0?t=t.left:t=t.right}return null}find(e){return this._root&&(this._root=Ct(e,this._root,this._comparator),this._comparator(e,this._root.key)!==0)?null:this._root}contains(e){let t=this._root;const o=this._comparator;for(;t;){const i=o(e,t.key);if(i===0)return!0;i<0?t=t.left:t=t.right}return!1}forEach(e,t){let o=this._root;const i=[];let r=!1;for(;!r;)o!==null?(i.push(o),o=o.left):i.length!==0?(o=i.pop(),e.call(t,o),o=o.right):r=!0;return this}range(e,t,o,i){const r=[],n=this._comparator;let s=this._root,l;for(;r.length!==0||s;)if(s)r.push(s),s=s.left;else{if(s=r.pop(),l=n(s.key,t),l>0)break;if(n(s.key,e)>=0&&o.call(i,s))return this;s=s.right}return this}keys(){const e=[];return this.forEach(({key:t})=>{e.push(t)}),e}values(){const e=[];return this.forEach(({data:t})=>{e.push(t)}),e}min(){return this._root?this.minNode(this._root).key:null}max(){return this._root?this.maxNode(this._root).key:null}minNode(e=this._root){if(e)for(;e.left;)e=e.left;return e}maxNode(e=this._root){if(e)for(;e.right;)e=e.right;return e}at(e){let t=this._root,o=!1,i=0;const r=[];for(;!o;)if(t)r.push(t),t=t.left;else if(r.length>0){if(t=r.pop(),i===e)return t;i++,t=t.right}else o=!0;return null}next(e){let t=this._root,o=null;if(e.right){for(o=e.right;o.left;)o=o.left;return o}const i=this._comparator;for(;t;){const r=i(e.key,t.key);if(r===0)break;r<0?(o=t,t=t.left):t=t.right}return o}prev(e){let t=this._root,o=null;if(e.left!==null){for(o=e.left;o.right;)o=o.right;return o}const i=this._comparator;for(;t;){const r=i(e.key,t.key);if(r===0)break;r<0?t=t.left:(o=t,t=t.right)}return o}clear(){return this._root=null,this._size=0,this}toList(){return Zu(this._root)}load(e,t=[],o=!1){let i=e.length;const r=this._comparator;if(o&&Ui(e,t,0,i-1,r),this._root===null)this._root=Oi(e,t,0,i),this._size=i;else{const n=ef(this.toList(),Ju(e,t),r);i=this._size+i,this._root=Ti({head:n},0,i)}return this}isEmpty(){return this._root===null}get size(){return this._size}get root(){return this._root}toString(e=t=>String(t.key)){const t=[];return Ci(this._root,"",!0,o=>t.push(o),e),t.join("")}update(e,t,o){const i=this._comparator;let{left:r,right:n}=en(e,this._root,i);i(e,t)<0?n=li(t,o,n,i):r=li(t,o,r,i),this._root=Ku(r,n,i)}split(e){return en(e,this._root,this._comparator)}*[Symbol.iterator](){let e=this._root;const t=[];let o=!1;for(;!o;)e!==null?(t.push(e),e=e.left):t.length!==0?(e=t.pop(),yield e,e=e.right):o=!0}}function Oi(a,e,t,o){const i=o-t;if(i>0){const r=t+Math.floor(i/2),n=a[r],s=e[r],l=new Bt(n,s);return l.left=Oi(a,e,t,r),l.right=Oi(a,e,r+1,o),l}return null}function Ju(a,e){const t=new Bt(null,null);let o=t;for(let i=0;i<a.length;i++)o=o.next=new Bt(a[i],e[i]);return o.next=null,t.next}function Zu(a){let e=a;const t=[];let o=!1;const i=new Bt(null,null);let r=i;for(;!o;)e?(t.push(e),e=e.left):t.length>0?(e=r=r.next=t.pop(),e=e.right):o=!0;return r.next=null,i.next}function Ti(a,e,t){const o=t-e;if(o>0){const i=e+Math.floor(o/2),r=Ti(a,e,i),n=a.head;return n.left=r,a.head=a.head.next,n.right=Ti(a,i+1,t),n}return null}function ef(a,e,t){const o=new Bt(null,null);let i=o,r=a,n=e;for(;r!==null&&n!==null;)t(r.key,n.key)<0?(i.next=r,r=r.next):(i.next=n,n=n.next),i=i.next;return r!==null?i.next=r:n!==null&&(i.next=n),o.next}function Ui(a,e,t,o,i){if(t>=o)return;const r=a[t+o>>1];let n=t-1,s=o+1;for(;;){do n++;while(i(a[n],r)<0);do s--;while(i(a[s],r)>0);if(n>=s)break;let l=a[n];a[n]=a[s],a[s]=l,l=e[n],e[n]=e[s],e[s]=l}Ui(a,e,t,s,i),Ui(a,e,s+1,o,i)}let Ot=Number.EPSILON;Ot===void 0&&(Ot=Math.pow(2,-52));const tf=Ot*Ot,tn=(a,e)=>{if(-Ot<a&&a<Ot&&-Ot<e&&e<Ot)return 0;const t=a-e;return t*t<tf*a*e?0:a<e?-1:1};class af{constructor(){this.reset()}reset(){this.xRounder=new an,this.yRounder=new an}round(e,t){return{x:this.xRounder.round(e),y:this.yRounder.round(t)}}}class an{constructor(){this.tree=new Qu,this.round(0)}round(e){const t=this.tree.add(e),o=this.tree.prev(t);if(o!==null&&tn(t.key,o.key)===0)return this.tree.remove(e),o.key;const i=this.tree.next(t);return i!==null&&tn(t.key,i.key)===0?(this.tree.remove(e),i.key):e}}new af;const ft=()=>`motion-expr-${Date.now()}-${Math.random().toString(36).slice(2,9)}`,of=[{type:"sine",name:"Sine Wave",description:"Oscillates around the keyed value with smooth periodic motion.",create:(a,e=ft())=>({id:e,property:a,type:"sine",name:"Sine Wave",enabled:!0,amplitude:24,frequency:1,phase:0,seed:1,decay:3})},{type:"wiggle",name:"Wiggle",description:"Adds deterministic organic variation for handheld or lively motion.",create:(a,e=ft())=>({id:e,property:a,type:"wiggle",name:"Wiggle",enabled:!0,amplitude:18,frequency:2,phase:0,seed:7,decay:3})},{type:"drift",name:"Drift",description:"Moves continuously over time without manual keyframes.",create:(a,e=ft())=>({id:e,property:a,type:"drift",name:"Drift",enabled:!0,amplitude:30,frequency:1,phase:0,seed:1,decay:3})},{type:"spring",name:"Spring",description:"Adds a damped bounce around the keyed value.",create:(a,e=ft())=>({id:e,property:a,type:"spring",name:"Spring",enabled:!0,amplitude:30,frequency:2,phase:0,seed:1,decay:3})},{type:"loop",name:"Loop Keyframes",description:"Repeats this property's keyframed motion after the final key.",create:(a,e=ft())=>({id:e,property:a,type:"loop",name:"Loop Keyframes",enabled:!0,amplitude:0,frequency:1,phase:0,seed:1,decay:3})},{type:"ping-pong",name:"Ping-Pong Keyframes",description:"Repeats keyframes forward and backward for seamless oscillation.",create:(a,e=ft())=>({id:e,property:a,type:"ping-pong",name:"Ping-Pong Keyframes",enabled:!0,amplitude:0,frequency:1,phase:0,seed:1,decay:3})},{type:"random",name:"Random Jitter",description:"Adds deterministic stepped random offsets for punchy movement.",create:(a,e=ft())=>({id:e,property:a,type:"random",name:"Random Jitter",enabled:!0,amplitude:18,frequency:8,phase:0,seed:13,decay:3})},{type:"posterize",name:"Posterize Time",description:"Samples this property at a lower rate for stop-motion timing.",create:(a,e=ft())=>({id:e,property:a,type:"posterize",name:"Posterize Time",enabled:!0,amplitude:0,frequency:12,phase:0,seed:1,decay:3})},{type:"expression",name:"Expression",description:"Write a JavaScript expression. Available: value, time, wiggle(freq, amp), loopOut(), linear(), ease(), clamp(), random(), Math.",create:(a,e=ft())=>({id:e,property:a,type:"expression",name:"Expression",enabled:!0,amplitude:0,frequency:1,phase:0,seed:1,decay:3,code:"value + wiggle(2, 20)"})}];function Ma(a){return{emissionRate:at(He(a?.emissionRate,48),0,1e3),maxParticles:Math.round(at(He(a?.maxParticles,240),0,5e3)),lifetime:at(He(a?.lifetime,2.4),.01,60),speed:at(He(a?.speed,220),0,5e3),spread:at(He(a?.spread,120),0,360),gravity:at(He(a?.gravity,120),-5e3,5e3),size:at(He(a?.size,10),.1,1e3),sizeRandomness:at(He(a?.sizeRandomness,.55),0,1),opacityStart:rn(He(a?.opacityStart,1)),opacityEnd:rn(He(a?.opacityEnd,0)),colorStart:on(a?.colorStart,"#ffffff"),colorEnd:on(a?.colorEnd,"#14b8a6"),seed:Math.round(at(He(a?.seed,1337),-1e6,1e6)),shape:rf(a?.shape)}}function on(a,e){if(typeof a!="string")return e;const t=a.trim(),o=/^#([0-9a-f]{3})$/i.exec(t);return o?`#${o[1].split("").map(i=>`${i}${i}`).join("")}`.toLowerCase():/^#[0-9a-f]{6}$/i.test(t)?t.toLowerCase():e}function rf(a){return a==="square"?"square":"circle"}function He(a,e){return typeof a=="number"&&Number.isFinite(a)?a:e}function rn(a){return at(a,0,1)}function at(a,e,t){return Math.min(t,Math.max(e,Number.isFinite(a)?a:e))}const nf=["transform.position.x","transform.position.y","transform.position.z","transform.scale.x","transform.scale.y","transform.rotation","transform.rotation.x","transform.rotation.y","transform.rotation.z","transform.opacity","transform.anchor.x","transform.anchor.y","transform.perspective"],sf=[...nf.map(a=>{const e=Hu(a);return{property:a,label:e?.label??a,family:"motion",group:"Transform",min:e?.min??0,max:e?.max??1,step:e?.step??.01,unit:e?.unit,defaultValue:e?.defaultValue??0,displayScale:e?.displayScale}}),{property:"shape.width",label:"Shape Width",family:"motion",group:"Shape",min:1,max:4e3,step:1,unit:"px",defaultValue:100},{property:"shape.height",label:"Shape Height",family:"motion",group:"Shape",min:1,max:4e3,step:1,unit:"px",defaultValue:100},{property:"shape.cornerRadius",label:"Corner Radius",family:"motion",group:"Shape",min:0,max:500,step:1,unit:"px",defaultValue:0},{property:"shape.fill.opacity",label:"Fill Opacity",family:"motion",group:"Shape",min:0,max:1,step:.01,unit:"%",defaultValue:1,displayScale:100},{property:"shape.stroke.width",label:"Stroke Width",family:"motion",group:"Shape",min:0,max:500,step:1,unit:"px",defaultValue:0},{property:"shape.stroke.opacity",label:"Stroke Opacity",family:"motion",group:"Shape",min:0,max:1,step:.01,unit:"%",defaultValue:1,displayScale:100},{property:"shape.stroke.dashOffset",label:"Dash Offset",family:"motion",group:"Shape",min:-1e3,max:1e3,step:1,unit:"px",defaultValue:0},{property:"shape.gradient.angle",label:"Gradient Angle",family:"motion",group:"Shape",min:-360,max:360,step:1,unit:"deg",defaultValue:0},{property:"composition.time",label:"Source Time",family:"motion",group:"Precomp",min:0,max:60,step:.05,unit:"s",defaultValue:0},{property:"particle.emissionRate",label:"Emission Rate",family:"motion",group:"Particles",min:0,max:1e3,step:1,unit:"/s",defaultValue:48},{property:"particle.maxParticles",label:"Max Particles",family:"motion",group:"Particles",min:0,max:5e3,step:1,defaultValue:240},{property:"particle.lifetime",label:"Lifetime",family:"motion",group:"Particles",min:.01,max:60,step:.05,unit:"s",defaultValue:2.4},{property:"particle.speed",label:"Speed",family:"motion",group:"Particles",min:0,max:5e3,step:10,defaultValue:220},{property:"particle.spread",label:"Spread",family:"motion",group:"Particles",min:0,max:360,step:1,unit:"deg",defaultValue:120},{property:"particle.gravity",label:"Gravity",family:"motion",group:"Particles",min:-5e3,max:5e3,step:10,defaultValue:120},{property:"particle.size",label:"Particle Size",family:"motion",group:"Particles",min:.1,max:1e3,step:1,unit:"px",defaultValue:10},{property:"particle.sizeRandomness",label:"Size Randomness",family:"motion",group:"Particles",min:0,max:1,step:.01,unit:"%",defaultValue:.55,displayScale:100},{property:"particle.opacityStart",label:"Start Opacity",family:"motion",group:"Particles",min:0,max:1,step:.01,unit:"%",defaultValue:1,displayScale:100},{property:"particle.opacityEnd",label:"End Opacity",family:"motion",group:"Particles",min:0,max:1,step:.01,unit:"%",defaultValue:0,displayScale:100}],lf=[{id:"sparks",name:"Sparks",description:"Fast warm bursts with gravity for logo and product reveals.",emitter:Ma({emissionRate:72,maxParticles:180,lifetime:1.1,speed:480,spread:70,gravity:540,size:5,sizeRandomness:.65,opacityStart:1,opacityEnd:0,colorStart:"#fef3c7",colorEnd:"#f97316",seed:2818,shape:"circle"})},{id:"confetti",name:"Confetti",description:"Square celebratory pieces for promos, launches, and wins.",emitter:Ma({emissionRate:54,maxParticles:260,lifetime:3.2,speed:260,spread:150,gravity:320,size:13,sizeRandomness:.75,opacityStart:1,opacityEnd:.15,colorStart:"#f43f5e",colorEnd:"#facc15",seed:9301,shape:"square"})},{id:"snow",name:"Snow",description:"Slow falling soft particles for seasonal or dreamy scenes.",emitter:Ma({emissionRate:36,maxParticles:360,lifetime:6,speed:34,spread:360,gravity:36,size:7,sizeRandomness:.8,opacityStart:.9,opacityEnd:.25,colorStart:"#ffffff",colorEnd:"#bfdbfe",seed:4922,shape:"circle"})},{id:"dust",name:"Dust",description:"Subtle atmospheric motion for depth and product polish.",emitter:Ma({emissionRate:24,maxParticles:160,lifetime:4.5,speed:42,spread:360,gravity:-8,size:6,sizeRandomness:.9,opacityStart:.45,opacityEnd:0,colorStart:"#f8fafc",colorEnd:"#94a3b8",seed:6174,shape:"circle"})},{id:"ui-burst",name:"UI Burst",description:"Tight energetic accent particles for clicks and app demos.",emitter:Ma({emissionRate:96,maxParticles:160,lifetime:.85,speed:340,spread:360,gravity:40,size:7,sizeRandomness:.45,opacityStart:1,opacityEnd:0,colorStart:"#67e8f9",colorEnd:"#14b8a6",seed:1447,shape:"circle"})}],U=(a,e)=>Number((a.startTime+a.duration*e).toFixed(4)),tt=(a,e)=>Number((a*e).toFixed(4)),ca=a=>a.type==="shape",cf=a=>{if(a.shapeType==="circle"||a.shapeType==="ellipse"){const e=Math.max(1,a.width/2),t=Math.max(1,a.height/2);return Number((Math.PI*(3*(e+t)-Math.sqrt((3*e+t)*(e+3*t)))).toFixed(2))}return Number((Math.max(1,a.width)*2+Math.max(1,a.height)*2).toFixed(2))},nn=(a,e)=>{if(!ca(a))return a;const t=cf(a);return{...a,style:{...a.style,stroke:{...a.style.stroke,width:a.style.stroke.width>0?a.style.stroke.width:Math.max(2,Number((4*Math.max(.5,e.intensity)).toFixed(2))),opacity:a.style.stroke.opacity>0?a.style.stroke.opacity:1,dashArray:a.style.stroke.dashArray&&a.style.stroke.dashArray.length>0?a.style.stroke.dashArray:[t],dashOffset:a.style.stroke.dashOffset&&a.style.stroke.dashOffset>0?a.style.stroke.dashOffset:t,lineCap:a.style.stroke.lineCap??"round",lineJoin:a.style.stroke.lineJoin??"round"}}}},uf=a=>{if(!ca(a)||a.style.fill.type==="gradient")return a;const e=a.style.fill.color??"#14b8a6";return{...a,style:{...a.style,fill:{type:"gradient",opacity:a.style.fill.opacity,color:e,gradient:{type:"linear",angle:0,stops:[{offset:0,color:e},{offset:1,color:"#ffffff"}]}}}}},ff=[{id:"fade-in",name:"Fade In",category:"entrance",description:"Brings the layer in with a clean opacity ramp.",defaultDuration:.45,properties:["transform.opacity"],keyframes:a=>[{property:"transform.opacity",time:U(a,0),value:0,easing:"ease-out"},{property:"transform.opacity",time:U(a,1),value:a.value("transform.opacity"),easing:"ease-out"}]},{id:"fade-out",name:"Fade Out",category:"exit",description:"Fades the selected layer out over the preset duration.",defaultDuration:.45,properties:["transform.opacity"],keyframes:a=>[{property:"transform.opacity",time:U(a,0),value:a.value("transform.opacity"),easing:"ease-in"},{property:"transform.opacity",time:U(a,1),value:0,easing:"ease-in"}]},{id:"click-press",name:"Click Press",category:"emphasis",description:"Quick button-press feedback — scale down then spring back.",defaultDuration:.24,properties:["transform.scale.x","transform.scale.y"],keyframes:a=>[{property:"transform.scale.x",time:U(a,0),value:a.value("transform.scale.x"),easing:"ease-out"},{property:"transform.scale.y",time:U(a,0),value:a.value("transform.scale.y"),easing:"ease-out"},{property:"transform.scale.x",time:U(a,.45),value:tt(a.value("transform.scale.x"),.93),easing:"ease-out"},{property:"transform.scale.y",time:U(a,.45),value:tt(a.value("transform.scale.y"),.93),easing:"ease-out"},{property:"transform.scale.x",time:U(a,1),value:a.value("transform.scale.x"),easing:"ease-out"},{property:"transform.scale.y",time:U(a,1),value:a.value("transform.scale.y"),easing:"ease-out"}]},{id:"lift-to-3d",name:"Lift to 3D",category:"emphasis",description:"Tilts the layer back and lifts it off the plane in 3D.",defaultDuration:.6,properties:["transform.rotation.x","transform.position.z","transform.scale.x","transform.scale.y"],keyframes:a=>[{property:"transform.rotation.x",time:U(a,0),value:a.value("transform.rotation.x"),easing:"easeOutCubic"},{property:"transform.position.z",time:U(a,0),value:a.value("transform.position.z"),easing:"easeOutCubic"},{property:"transform.scale.x",time:U(a,0),value:a.value("transform.scale.x"),easing:"easeOutCubic"},{property:"transform.scale.y",time:U(a,0),value:a.value("transform.scale.y"),easing:"easeOutCubic"},{property:"transform.rotation.x",time:U(a,1),value:Number((-24*Math.max(.4,a.intensity)).toFixed(2)),easing:"easeOutCubic"},{property:"transform.position.z",time:U(a,1),value:Number((a.value("transform.position.z")+140).toFixed(2)),easing:"easeOutCubic"},{property:"transform.scale.x",time:U(a,1),value:tt(a.value("transform.scale.x"),1.06),easing:"easeOutCubic"},{property:"transform.scale.y",time:U(a,1),value:tt(a.value("transform.scale.y"),1.06),easing:"easeOutCubic"}]},{id:"flip-in-3d",name:"Flip In (3D)",category:"entrance",description:"Card-flips the layer in around its vertical axis.",defaultDuration:.55,properties:["transform.rotation.y","transform.opacity"],keyframes:a=>[{property:"transform.rotation.y",time:U(a,0),value:-90,easing:"easeOutCubic"},{property:"transform.opacity",time:U(a,0),value:0,easing:"easeOutCubic"},{property:"transform.rotation.y",time:U(a,1),value:a.value("transform.rotation.y"),easing:"easeOutCubic"},{property:"transform.opacity",time:U(a,1),value:a.value("transform.opacity"),easing:"easeOutCubic"}]},{id:"slide-up-in",name:"Slide Up In",category:"entrance",description:"Moves the layer upward into place while fading in.",defaultDuration:.6,properties:["transform.position.y","transform.opacity"],keyframes:a=>[{property:"transform.position.y",time:U(a,0),value:a.value("transform.position.y")+a.distance,easing:"easeOutCubic"},{property:"transform.opacity",time:U(a,0),value:0,easing:"easeOutCubic"},{property:"transform.position.y",time:U(a,1),value:a.value("transform.position.y"),easing:"easeOutCubic"},{property:"transform.opacity",time:U(a,1),value:a.value("transform.opacity"),easing:"easeOutCubic"}]},{id:"slide-left-in",name:"Slide Left In",category:"entrance",description:"Slides the layer horizontally into position.",defaultDuration:.6,properties:["transform.position.x","transform.opacity"],keyframes:a=>[{property:"transform.position.x",time:U(a,0),value:a.value("transform.position.x")+a.distance,easing:"easeOutCubic"},{property:"transform.opacity",time:U(a,0),value:0,easing:"easeOutCubic"},{property:"transform.position.x",time:U(a,1),value:a.value("transform.position.x"),easing:"easeOutCubic"},{property:"transform.opacity",time:U(a,1),value:a.value("transform.opacity"),easing:"easeOutCubic"}]},{id:"scale-pop",name:"Scale Pop",category:"entrance",description:"Pops the layer on with a subtle overshoot.",defaultDuration:.55,properties:["transform.scale.x","transform.scale.y","transform.opacity"],keyframes:a=>{const e=1+.08*a.intensity;return[{property:"transform.scale.x",time:U(a,0),value:tt(a.value("transform.scale.x"),.82),easing:"easeOutBack"},{property:"transform.scale.y",time:U(a,0),value:tt(a.value("transform.scale.y"),.82),easing:"easeOutBack"},{property:"transform.opacity",time:U(a,0),value:0,easing:"ease-out"},{property:"transform.scale.x",time:U(a,.62),value:tt(a.value("transform.scale.x"),e),easing:"easeOutBack"},{property:"transform.scale.y",time:U(a,.62),value:tt(a.value("transform.scale.y"),e),easing:"easeOutBack"},{property:"transform.opacity",time:U(a,.62),value:a.value("transform.opacity"),easing:"ease-out"},{property:"transform.scale.x",time:U(a,1),value:a.value("transform.scale.x"),easing:"easeOutBack"},{property:"transform.scale.y",time:U(a,1),value:a.value("transform.scale.y"),easing:"easeOutBack"}]}},{id:"rotate-in",name:"Rotate In",category:"entrance",description:"Adds a small rotational settle as the layer appears.",defaultDuration:.55,properties:["transform.rotation","transform.opacity"],keyframes:a=>[{property:"transform.rotation",time:U(a,0),value:a.value("transform.rotation")-12*a.intensity,easing:"easeOutBack"},{property:"transform.opacity",time:U(a,0),value:0,easing:"ease-out"},{property:"transform.rotation",time:U(a,1),value:a.value("transform.rotation"),easing:"easeOutBack"},{property:"transform.opacity",time:U(a,1),value:a.value("transform.opacity"),easing:"ease-out"}]},{id:"pulse",name:"Pulse",category:"emphasis",description:"Adds a quick scale pulse for beat accents and CTAs.",defaultDuration:.5,properties:["transform.scale.x","transform.scale.y"],keyframes:a=>{const e=1+.08*a.intensity;return[{property:"transform.scale.x",time:U(a,0),value:a.value("transform.scale.x"),easing:"easeOutQuad"},{property:"transform.scale.y",time:U(a,0),value:a.value("transform.scale.y"),easing:"easeOutQuad"},{property:"transform.scale.x",time:U(a,.5),value:tt(a.value("transform.scale.x"),e),easing:"easeOutBack"},{property:"transform.scale.y",time:U(a,.5),value:tt(a.value("transform.scale.y"),e),easing:"easeOutBack"},{property:"transform.scale.x",time:U(a,1),value:a.value("transform.scale.x"),easing:"easeInOutQuad"},{property:"transform.scale.y",time:U(a,1),value:a.value("transform.scale.y"),easing:"easeInOutQuad"}]}},{id:"float-loop",name:"Float Loop",category:"loop",description:"Creates a seamless vertical float cycle.",defaultDuration:2,properties:["transform.position.y"],keyframes:a=>[{property:"transform.position.y",time:U(a,0),value:a.value("transform.position.y"),easing:"easeInOutSine"},{property:"transform.position.y",time:U(a,.5),value:a.value("transform.position.y")-a.distance*.28,easing:"easeInOutSine"},{property:"transform.position.y",time:U(a,1),value:a.value("transform.position.y"),easing:"easeInOutSine"}]},{id:"stroke-draw-on",name:"Stroke Draw On",category:"shape",description:"Prepares a dashed stroke and reveals it like a vector logo.",defaultDuration:.8,properties:["shape.stroke.dashOffset","shape.stroke.opacity"],supportsLayer:ca,prepareLayer:nn,keyframes:a=>[{property:"shape.stroke.dashOffset",time:U(a,0),value:a.value("shape.stroke.dashOffset"),easing:"easeOutCubic"},{property:"shape.stroke.opacity",time:U(a,0),value:0,easing:"ease-out"},{property:"shape.stroke.dashOffset",time:U(a,1),value:0,easing:"easeOutCubic"},{property:"shape.stroke.opacity",time:U(a,1),value:a.value("shape.stroke.opacity"),easing:"ease-out"}]},{id:"stroke-pop",name:"Stroke Pop",category:"shape",description:"Adds a quick outline accent for cards and product callouts.",defaultDuration:.45,properties:["shape.stroke.width","shape.stroke.opacity"],supportsLayer:ca,prepareLayer:nn,keyframes:a=>{const e=Math.max(1,a.value("shape.stroke.width")),t=Number((e+5*a.intensity).toFixed(4));return[{property:"shape.stroke.width",time:U(a,0),value:e,easing:"easeOutQuad"},{property:"shape.stroke.opacity",time:U(a,0),value:0,easing:"easeOutQuad"},{property:"shape.stroke.width",time:U(a,.5),value:t,easing:"easeOutBack"},{property:"shape.stroke.opacity",time:U(a,.5),value:a.value("shape.stroke.opacity"),easing:"easeOutBack"},{property:"shape.stroke.width",time:U(a,1),value:e,easing:"easeInOutQuad"}]}},{id:"gradient-sweep",name:"Gradient Sweep",category:"shape",description:"Turns the fill into an editable gradient and sweeps its angle.",defaultDuration:.9,properties:["shape.gradient.angle"],supportsLayer:ca,prepareLayer:uf,keyframes:a=>{const e=a.value("shape.gradient.angle"),t=90*Math.max(.25,a.intensity);return[{property:"shape.gradient.angle",time:U(a,0),value:Number((e-t/2).toFixed(4)),easing:"easeInOutSine"},{property:"shape.gradient.angle",time:U(a,1),value:Number((e+t/2).toFixed(4)),easing:"easeInOutSine"}]}},{id:"corner-bloom",name:"Corner Bloom",category:"shape",description:"Animates rectangle radius for soft UI-card transitions.",defaultDuration:.55,properties:["shape.cornerRadius"],supportsLayer:ca,keyframes:a=>{const e=a.value("shape.cornerRadius"),t=Number((e+a.distance*.16*a.intensity).toFixed(4));return[{property:"shape.cornerRadius",time:U(a,0),value:e,easing:"easeOutQuad"},{property:"shape.cornerRadius",time:U(a,.58),value:t,easing:"easeOutBack"},{property:"shape.cornerRadius",time:U(a,1),value:e,easing:"easeInOutQuad"}]}}];Zr.map(a=>({id:a.id,name:a.name,category:a.category})),[...new Set(Zr.map(a=>a.category))],sf.map(a=>({property:a.property,label:a.label,group:a.group})),of.map(a=>({id:a.type,name:a.name})),$n.map(a=>({id:a.id,name:a.name})),lf.map(a=>({id:a.id,name:a.name})),ff.map(a=>({id:a.id,name:a.name,category:a.category}));wu.map(a=>({id:a.id,name:a.name,category:a.category})),Gu.map(a=>({id:a.id,name:a.name,category:a.category})),Su.map(a=>({id:a.id,name:a.name}));const sn=new Map;let Ii=0,ia=null;async function Xn(){if(ia)return ia;try{return ia=await import("./index-dWOTc-AL.js"),ia}catch{try{return ia=await import("https://esm.sh/mediabunny@1.25.3"),ia}catch{return null}}}async function pf(a,e,t,o){const i=sn.get(a);if(i)return i;try{const r=await Xn();if(!r)return null;const{Input:n,ALL_FORMATS:s,BlobSource:l,CanvasSink:c}=r,u=new n({source:new l(e),formats:s}),f=await u.getPrimaryVideoTrack();if(!f)return null;const d=new c(f,{width:t,height:o,fit:"contain"}),m={input:u,sink:d,videoTrack:f,blobUrl:URL.createObjectURL(e)};return sn.set(a,m),m}catch(r){return console.error(`[DecodeWorker ${Ii}] Failed to create resources for ${a}:`,r),null}}async function df(a){const{requestId:e,clipId:t,blob:o,time:i,width:r,height:n}=a;try{const s=await pf(t,o,r,n);if(!s)return{type:"decoded",requestId:e,clipId:t,bitmap:null,time:i,error:"Failed to create decode resources"};const c=await s.sink.getCanvas(i);if(!c?.canvas)return{type:"decoded",requestId:e,clipId:t,bitmap:null,time:i,error:"No frame at requested time"};const u=await createImageBitmap(c.canvas);return{type:"decoded",requestId:e,clipId:t,bitmap:u,time:i}}catch(s){return{type:"decoded",requestId:e,clipId:t,bitmap:null,time:i,error:s instanceof Error?s.message:"Unknown decode error"}}}const po=self;po.onmessage=async a=>{const e=a.data;switch(e.type){case"init":Ii=Math.floor(Math.random()*1e4),await Xn();const t={type:"ready",workerId:Ii};po.postMessage(t);break;case"decode":const o=await df(e);o.bitmap?po.postMessage(o,{transfer:[o.bitmap]}):po.postMessage(o);break}};bu.map(a=>({id:a,name:mf(a)}));function mf(a){return a.split("-").map(e=>e.charAt(0).toUpperCase()+e.slice(1)).join(" ")}class hf{size;cosTable;sinTable;reverseTable;constructor(e){if(e<=0||e&e-1)throw new Error("FFT size must be a power of 2");this.size=e,this.cosTable=new Float32Array(e/2),this.sinTable=new Float32Array(e/2),this.reverseTable=new Uint32Array(e);for(let o=0;o<e/2;o++){const i=-2*Math.PI*o/e;this.cosTable[o]=Math.cos(i),this.sinTable[o]=Math.sin(i)}const t=Math.log2(e);for(let o=0;o<e;o++){let i=0;for(let r=0;r<t;r++)i=i<<1|o>>r&1;this.reverseTable[o]=i}}getSize(){return this.size}forward(e){const t=this.size,o=new Float32Array(t),i=new Float32Array(t);for(let r=0;r<t;r++)o[this.reverseTable[r]]=e[r]||0;for(let r=2;r<=t;r*=2){const n=r/2,s=t/r;for(let l=0;l<t;l+=r)for(let c=0;c<n;c++){const u=c*s,f=this.cosTable[u],d=this.sinTable[u],m=l+c,h=l+c+n,p=o[h]*f-i[h]*d,g=o[h]*d+i[h]*f;o[h]=o[m]-p,i[h]=i[m]-g,o[m]=o[m]+p,i[m]=i[m]+g}}return{real:o,imag:i}}inverse(e,t){const o=this.size,i=new Float32Array(o),r=new Float32Array(o);for(let s=0;s<o;s++)i[this.reverseTable[s]]=e[s],r[this.reverseTable[s]]=-t[s];for(let s=2;s<=o;s*=2){const l=s/2,c=o/s;for(let u=0;u<o;u+=s)for(let f=0;f<l;f++){const d=f*c,m=this.cosTable[d],h=this.sinTable[d],p=u+f,g=u+f+l,_=i[g]*m-r[g]*h,y=i[g]*h+r[g]*m;i[g]=i[p]-_,r[g]=r[p]-y,i[p]=i[p]+_,r[p]=r[p]+y}}const n=new Float32Array(o);for(let s=0;s<o;s++)n[s]=i[s]/o;return n}getMagnitude(e,t){const o=this.size/2,i=new Float32Array(o);for(let r=0;r<o;r++)i[r]=Math.sqrt(e[r]*e[r]+t[r]*t[r]);return i}getPower(e,t){const o=this.size/2,i=new Float32Array(o);for(let r=0;r<o;r++)i[r]=e[r]*e[r]+t[r]*t[r];return i}getMagnitudeAndPhase(e,t){const o=this.size/2,i=new Float32Array(o),r=new Float32Array(o);for(let n=0;n<o;n++)i[n]=Math.sqrt(e[n]*e[n]+t[n]*t[n]),r[n]=Math.atan2(t[n],e[n]);return{magnitudes:i,phases:r}}fromMagnitudeAndPhase(e,t){const o=this.size,i=e.length,r=new Float32Array(o),n=new Float32Array(o);for(let s=0;s<i;s++)r[s]=e[s]*Math.cos(t[s]),n[s]=e[s]*Math.sin(t[s]);for(let s=1;s<i;s++)r[o-s]=r[s],n[o-s]=-n[s];return{real:r,imag:n}}applyHannWindow(e){const t=new Float32Array(e.length),o=e.length;for(let i=0;i<o;i++){const r=.5*(1-Math.cos(2*Math.PI*i/(o-1)));t[i]=e[i]*r}return t}applySynthesisWindow(e){const t=new Float32Array(e.length),o=e.length;for(let i=0;i<o;i++){const r=.5*(1-Math.cos(2*Math.PI*i/(o-1)));t[i]=e[i]*r}return t}}class gf{measureCtx=null;constructor(){if(typeof OffscreenCanvas<"u"){const e=new OffscreenCanvas(1,1);this.measureCtx=e.getContext("2d")}else if(typeof document<"u"){const e=document.createElement("canvas");this.measureCtx=e.getContext("2d")}}measureText(e,t,o,i,r,n){if(!this.measureCtx)return this.createFallbackLayout(e,o,n);const s=this.measureCtx;s.font=`${i} ${o}px ${t}`;const l=e.split(`
`),c=[],u=[],f=[];let d=0,m=0,h=0;const p=o*n;for(let y=0;y<l.length;y++){const v=l[y],b=[],C=s.measureText(v).width+(v.length-1)*r;let w=0;const k=v.split(/(\s+)/);let S=0;for(const A of k){if(!A)continue;const M=/^\s+$/.test(A),V=[],N=w;for(let F=0;F<A.length;F++){const D=A[F],ae=s.measureText(D).width,Re={char:D,x:w,y:h,width:ae,height:o,lineIndex:y,charIndexInLine:V.length,globalIndex:d};V.push(Re),u.push(Re),d++,w+=ae+r}if(!M&&V.length>0){const F=w-N-r,D={word:A,chars:V,x:N,y:h,width:F,height:o,lineIndex:y,wordIndexInLine:S,globalIndex:m};b.push(D),f.push(D),m++,S++}}const T={text:v,words:b,x:0,y:h,width:C,height:p,lineIndex:y};c.push(T),h+=p}const g=Math.max(...c.map(y=>y.width),0);return{characters:u,words:f,lines:c,totalWidth:g,totalHeight:h}}createFallbackLayout(e,t,o){const i=t*.6,r=e.split(`
`),n=[],s=[],l=[];let c=0,u=0,f=0;const d=t*o;for(let m=0;m<r.length;m++){const h=r[m],p=[];let g=0;const _=h.split(/(\s+)/);for(const v of _){if(!v)continue;const b=/^\s+$/.test(v),x=[],C=g;for(let w=0;w<v.length;w++){const k=v[w],S=i,T={char:k,x:g,y:f,width:S,height:t,lineIndex:m,charIndexInLine:x.length,globalIndex:c};x.push(T),s.push(T),c++,g+=S}if(!b&&x.length>0){const w=g-C,k={word:v,chars:x,x:C,y:f,width:w,height:t,lineIndex:m,wordIndexInLine:p.length,globalIndex:u};p.push(k),l.push(k),u++}}const y={text:h,words:p,x:0,y:f,width:g,height:d,lineIndex:m};n.push(y),f+=d}return{characters:s,words:l,lines:n,totalWidth:Math.max(...n.map(m=>m.width),0),totalHeight:f}}calculateAnimatedLayout(e,t){const o=e.animation;if(!o||o.preset==="none")return this.createStaticLayout(e);const i=this.measureText(e.text,e.style.fontFamily,e.style.fontSize,String(e.style.fontWeight),e.style.letterSpacing,e.style.lineHeight),r=t-e.startTime,n=e.duration,s=r<=o.inDuration,l=r>=n-o.outDuration,c=!s&&!l;let u,f;if(s)u=o.inDuration>0?r/o.inDuration:1,f=!0;else if(l){const h=n-o.outDuration;u=o.outDuration>0?(r-h)/o.outDuration:0,f=!1}else u=1,f=!0;const d=o.unit||"character",m=[];for(const h of i.lines){const p=[];for(const v of h.words){const b=[];for(const k of v.chars){let S,T;d==="character"?(S={text:k.char,index:k.globalIndex,totalUnits:i.characters.length,x:k.x,y:k.y,width:k.width,height:k.height},T=i.characters.length):d==="word"?(S={text:v.word,index:v.globalIndex,totalUnits:i.words.length,x:v.x,y:v.y,width:v.width,height:v.height},T=i.words.length):(S={text:h.text,index:h.lineIndex,totalUnits:i.lines.length,x:h.x,y:h.y,width:h.width,height:h.height},T=i.lines.length);const A={unit:{...S,totalUnits:T},progress:c?1:u,isIn:f,animation:o,totalDuration:n},M=si(A);b.push({...k,state:M})}const C={unit:{text:v.word,index:v.globalIndex,totalUnits:i.words.length,x:v.x,y:v.y,width:v.width,height:v.height},progress:c?1:u,isIn:f,animation:o,totalDuration:n},w=d==="word"||d==="line"?si(C):{opacity:1,scale:{x:1,y:1},rotation:0,offsetX:0,offsetY:0,blur:0};p.push({...v,state:w,animatedChars:b})}const _={unit:{text:h.text,index:h.lineIndex,totalUnits:i.lines.length,x:h.x,y:h.y,width:h.width,height:h.height},progress:c?1:u,isIn:f,animation:o,totalDuration:n},y=d==="line"?si(_):{opacity:1,scale:{x:1,y:1},rotation:0,offsetX:0,offsetY:0,blur:0};m.push({...h,state:y,animatedWords:p})}return{lines:m,totalWidth:i.totalWidth,totalHeight:i.totalHeight}}createStaticLayout(e){const t=this.measureText(e.text,e.style.fontFamily,e.style.fontSize,String(e.style.fontWeight),e.style.letterSpacing,e.style.lineHeight),o={opacity:1,scale:{x:1,y:1},rotation:0,offsetX:0,offsetY:0,blur:0};return{lines:t.lines.map(r=>({...r,state:o,animatedWords:r.words.map(n=>({...n,state:o,animatedChars:n.chars.map(s=>({...s,state:o}))}))})),totalWidth:t.totalWidth,totalHeight:t.totalHeight}}}new gf;const vf=[{id:"smileys",name:"Smileys & Emotion",emojis:[{id:"grinning",emoji:"😀",name:"Grinning Face",category:"smileys"},{id:"joy",emoji:"😂",name:"Face with Tears of Joy",category:"smileys"},{id:"heart_eyes",emoji:"😍",name:"Smiling Face with Heart-Eyes",category:"smileys"},{id:"thinking",emoji:"🤔",name:"Thinking Face",category:"smileys"},{id:"sunglasses",emoji:"😎",name:"Smiling Face with Sunglasses",category:"smileys"},{id:"wink",emoji:"😉",name:"Winking Face",category:"smileys"},{id:"thumbsup",emoji:"👍",name:"Thumbs Up",category:"smileys"},{id:"clap",emoji:"👏",name:"Clapping Hands",category:"smileys"},{id:"fire",emoji:"🔥",name:"Fire",category:"smileys"},{id:"heart",emoji:"❤️",name:"Red Heart",category:"smileys"},{id:"star",emoji:"⭐",name:"Star",category:"smileys"},{id:"sparkles",emoji:"✨",name:"Sparkles",category:"smileys"}]},{id:"gestures",name:"Gestures",emojis:[{id:"wave",emoji:"👋",name:"Waving Hand",category:"gestures"},{id:"ok_hand",emoji:"👌",name:"OK Hand",category:"gestures"},{id:"point_up",emoji:"☝️",name:"Index Pointing Up",category:"gestures"},{id:"point_right",emoji:"👉",name:"Backhand Index Pointing Right",category:"gestures"},{id:"raised_hands",emoji:"🙌",name:"Raising Hands",category:"gestures"},{id:"pray",emoji:"🙏",name:"Folded Hands",category:"gestures"},{id:"muscle",emoji:"💪",name:"Flexed Biceps",category:"gestures"},{id:"v",emoji:"✌️",name:"Victory Hand",category:"gestures"}]},{id:"objects",name:"Objects",emojis:[{id:"camera",emoji:"📷",name:"Camera",category:"objects"},{id:"video_camera",emoji:"📹",name:"Video Camera",category:"objects"},{id:"microphone",emoji:"🎤",name:"Microphone",category:"objects"},{id:"headphones",emoji:"🎧",name:"Headphones",category:"objects"},{id:"movie_camera",emoji:"🎥",name:"Movie Camera",category:"objects"},{id:"clapper",emoji:"🎬",name:"Clapper Board",category:"objects"},{id:"trophy",emoji:"🏆",name:"Trophy",category:"objects"},{id:"medal",emoji:"🏅",name:"Sports Medal",category:"objects"},{id:"bell",emoji:"🔔",name:"Bell",category:"objects"},{id:"megaphone",emoji:"📣",name:"Megaphone",category:"objects"}]},{id:"symbols",name:"Symbols",emojis:[{id:"check",emoji:"✅",name:"Check Mark",category:"symbols"},{id:"x",emoji:"❌",name:"Cross Mark",category:"symbols"},{id:"question",emoji:"❓",name:"Question Mark",category:"symbols"},{id:"exclamation",emoji:"❗",name:"Exclamation Mark",category:"symbols"},{id:"100",emoji:"💯",name:"Hundred Points",category:"symbols"},{id:"arrow_right",emoji:"➡️",name:"Right Arrow",category:"symbols"},{id:"arrow_left",emoji:"⬅️",name:"Left Arrow",category:"symbols"},{id:"arrow_up",emoji:"⬆️",name:"Up Arrow",category:"symbols"},{id:"arrow_down",emoji:"⬇️",name:"Down Arrow",category:"symbols"},{id:"new",emoji:"🆕",name:"New",category:"symbols"},{id:"free",emoji:"🆓",name:"Free",category:"symbols"}]},{id:"nature",name:"Nature",emojis:[{id:"sun",emoji:"☀️",name:"Sun",category:"nature"},{id:"moon",emoji:"🌙",name:"Crescent Moon",category:"nature"},{id:"cloud",emoji:"☁️",name:"Cloud",category:"nature"},{id:"rainbow",emoji:"🌈",name:"Rainbow",category:"nature"},{id:"snowflake",emoji:"❄️",name:"Snowflake",category:"nature"},{id:"lightning",emoji:"⚡",name:"Lightning",category:"nature"},{id:"flower",emoji:"🌸",name:"Cherry Blossom",category:"nature"},{id:"tree",emoji:"🌳",name:"Deciduous Tree",category:"nature"}]}];class yf{stickers=new Map;categories=new Map;emojiCategories=vf;constructor(){this.initializeDefaultCategories()}initializeDefaultCategories(){const e=[{id:"arrows",name:"Arrows",icon:"➡️"},{id:"badges",name:"Badges",icon:"🏷️"},{id:"banners",name:"Banners",icon:"🎗️"},{id:"callouts",name:"Callouts",icon:"💬"},{id:"social",name:"Social Media",icon:"📱"},{id:"custom",name:"Custom",icon:"✨"}];for(const t of e)this.categories.set(t.id,t)}addSticker(e){this.stickers.set(e.id,e)}removeSticker(e){return this.stickers.delete(e)}getSticker(e){return this.stickers.get(e)}getAllStickers(){return Array.from(this.stickers.values())}getStickersByCategory(e){return Array.from(this.stickers.values()).filter(t=>t.category===e)}searchStickers(e){const t=e.toLowerCase();return Array.from(this.stickers.values()).filter(o=>o.name.toLowerCase().includes(t)||o.tags?.some(i=>i.toLowerCase().includes(t)))}addCategory(e){this.categories.set(e.id,e)}getCategories(){return Array.from(this.categories.values())}getCategory(e){return this.categories.get(e)}getEmojiCategories(){return this.emojiCategories}getEmojisByCategory(e){return this.emojiCategories.find(o=>o.id===e)?.emojis||[]}getAllEmojis(){return this.emojiCategories.flatMap(e=>e.emojis)}searchEmojis(e){const t=e.toLowerCase();return this.getAllEmojis().filter(o=>o.name.toLowerCase().includes(t))}getEmoji(e){return this.getAllEmojis().find(t=>t.id===e)}createStickerClip(e,t,o,i){return{id:`sticker_${Date.now()}_${Math.random().toString(36).slice(2,11)}`,trackId:t,startTime:o,duration:i,type:"sticker",imageUrl:e.imageUrl,category:e.category,name:e.name,transform:{...Ir},keyframes:[]}}createEmojiClip(e,t,o,i){const r=this.emojiToDataUrl(e.emoji);return{id:`emoji_${Date.now()}_${Math.random().toString(36).slice(2,11)}`,trackId:t,startTime:o,duration:i,type:"emoji",imageUrl:r,category:e.category,name:e.name,transform:{...Ir},keyframes:[]}}emojiToDataUrl(e,t=128){if(typeof document>"u")return`data:text/plain;base64,${btoa(e)}`;const o=document.createElement("canvas");o.width=t,o.height=t;const i=o.getContext("2d");return i?(i.font=`${t*.8}px "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif`,i.textAlign="center",i.textBaseline="middle",i.fillText(e,t/2,t/2),o.toDataURL("image/png")):`data:text/plain;base64,${btoa(e)}`}async importSticker(e,t,o="custom",i){const r=await this.fileToDataUrl(e),n={id:`custom_${Date.now()}_${Math.random().toString(36).slice(2,11)}`,name:t,category:o,imageUrl:r,tags:i};return this.addSticker(n),n}fileToDataUrl(e){return new Promise((t,o)=>{const i=new FileReader;i.onload=()=>t(i.result),i.onerror=()=>o(new Error("Failed to read file")),i.readAsDataURL(e)})}clearCustomStickers(){for(const[e,t]of this.stickers)t.category==="custom"&&this.stickers.delete(e)}}new yf;const B="full",Ce=a=>({controlId:a}),I=(a,e,t=1,o=1,i=0,r=.5,n=.5)=>({position:{x:a,y:e},scale:{x:t,y:o},rotation:i,anchor:{x:r,y:n},opacity:1}),q=a=>a,R=a=>a,_f=[{id:"cinema-letterbox",name:"Cinematic Letterbox",description:"Wide-screen bars with grain and vignette.",category:"cinema",thumbnailUrl:null,previewUrl:null,tags:["cinema","letterbox","grain"],supportedTargets:["video","image"],controls:[{id:"grainAmount",label:"Grain",type:"number",defaultValue:.3,min:0,max:1,step:.05},{id:"barOpacity",label:"Bar Opacity",type:"number",defaultValue:1,min:0,max:1,step:.05}],recipe:{effects:[{type:"film-grain",params:{intensity:Ce("grainAmount"),size:1.5}},{type:"vignette",params:{intensity:.4,radius:.8}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.05),content:{shapeType:"rectangle",width:1920,height:120,style:{fill:{type:"solid",color:"#000000",opacity:Ce("barOpacity")},stroke:{color:"#000000",width:0,opacity:0}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.95),content:{shapeType:"rectangle",width:1920,height:120,style:{fill:{type:"solid",color:"#000000",opacity:Ce("barOpacity")},stroke:{color:"#000000",width:0,opacity:0}}}})],audioEffects:[]}},{id:"cinema-light-frame",name:"Light Frame",description:"A subtle warm edge frame for cinematic shots.",category:"cinema",thumbnailUrl:null,previewUrl:null,tags:["cinema","frame","warm"],supportedTargets:["video","image"],controls:[{id:"frameOpacity",label:"Frame Opacity",type:"number",defaultValue:.22,min:0,max:.8,step:.02}],recipe:{effects:[{type:"contrast",params:{value:.08}},{type:"brightness",params:{value:.03}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),blendOpacity:Ce("frameOpacity"),content:{shapeType:"rectangle",width:1820,height:980,style:{fill:{type:"none",opacity:0},stroke:{color:"#f8c89a",width:8,opacity:1}}}})],audioEffects:[]}},{id:"cinema-warm-fade",name:"Warm Fade",description:"Soft warm grade for lifestyle and travel cuts.",category:"cinema",thumbnailUrl:null,previewUrl:null,tags:["cinema","warm","travel"],supportedTargets:["video","image"],controls:[{id:"warmth",label:"Warmth",type:"number",defaultValue:.14,min:0,max:.4,step:.01}],recipe:{effects:[{type:"brightness",params:{value:.02}},{type:"contrast",params:{value:.1}},{type:"saturation",params:{value:Ce("warmth")}}],overlays:[],audioEffects:[]}},{id:"glitch-digital",name:"Digital Glitch",description:"RGB drift with moving scanline accents.",category:"glitch",thumbnailUrl:null,previewUrl:null,tags:["glitch","rgb","scanline"],supportedTargets:["video","image"],controls:[{id:"glitchAmount",label:"Glitch",type:"number",defaultValue:.18,min:0,max:.6,step:.02}],recipe:{effects:[{type:"chromatic-aberration",params:{intensity:4}},{type:"film-grain",params:{intensity:Ce("glitchAmount"),size:2}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.2),keyframes:[{time:0,property:"position.y",value:.18},{time:.4,property:"position.y",value:.74},{time:.8,property:"position.y",value:.32},{time:1,property:"position.y",value:.86}],content:{shapeType:"rectangle",width:1920,height:32,style:{fill:{type:"solid",color:"rgba(0,255,255,0.12)",opacity:1},stroke:{color:"rgba(0,255,255,0.12)",width:0,opacity:0}}}})],audioEffects:[]}},{id:"glitch-rgb-scan",name:"RGB Scan",description:"Thin scanlines and channel separation.",category:"glitch",thumbnailUrl:null,previewUrl:null,tags:["glitch","scan","rgb"],supportedTargets:["video","image"],recipe:{effects:[{type:"chromatic-aberration",params:{intensity:6}},{type:"contrast",params:{value:.08}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),content:{shapeType:"rectangle",width:1920,height:1020,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,0,128,0.25)",width:2,opacity:1}}}})],audioEffects:[]}},{id:"glitch-static-frame",name:"Static Frame",description:"Noisy border treatment with light distortion.",category:"glitch",thumbnailUrl:null,previewUrl:null,tags:["glitch","static","noise"],supportedTargets:["video","image"],recipe:{effects:[{type:"film-grain",params:{intensity:.45,size:2.3}},{type:"contrast",params:{value:.15}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),content:{shapeType:"rectangle",width:1860,height:1020,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,255,255,0.18)",width:12,opacity:1}}}})],audioEffects:[]}},{id:"retro-vhs",name:"VHS Tape",description:"Classic tape softness with transport text.",category:"retro",thumbnailUrl:null,previewUrl:null,tags:["retro","vhs","tape"],supportedTargets:["video","image"],recipe:{effects:[{type:"chromatic-aberration",params:{intensity:3}},{type:"film-grain",params:{intensity:.6,size:2.5}},{type:"blur",params:{radius:.5}},{type:"vignette",params:{intensity:.45,radius:.7}}],overlays:[q({type:"text",trackType:"text",timing:B,transform:I(.08,.9,1,1,0,0,.5),content:{text:"PLAY >",style:{fontFamily:"JetBrains Mono",fontSize:28,color:"rgba(255,255,255,0.85)",fontWeight:600,textAlign:"left",verticalAlign:"middle",lineHeight:1.1,letterSpacing:1}}}),q({type:"text",trackType:"text",timing:B,transform:I(.92,.9,1,1,0,1,.5),content:{text:"SP",style:{fontFamily:"JetBrains Mono",fontSize:22,color:"rgba(255,255,255,0.65)",fontWeight:600,textAlign:"right",verticalAlign:"middle",lineHeight:1.1,letterSpacing:1}}})],audioEffects:[]}},{id:"retro-crt-monitor",name:"CRT Monitor",description:"Soft corner frame and green terminal vibe.",category:"retro",thumbnailUrl:null,previewUrl:null,tags:["retro","crt","monitor"],supportedTargets:["video","image"],recipe:{effects:[{type:"contrast",params:{value:.12}},{type:"brightness",params:{value:-.04}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),content:{shapeType:"rectangle",width:1840,height:1e3,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(105,255,173,0.25)",width:6,opacity:1},cornerRadius:18}}})],audioEffects:[]}},{id:"retro-old-film",name:"Old Film",description:"High grain monochrome with gate marker text.",category:"retro",thumbnailUrl:null,previewUrl:null,tags:["retro","film","mono"],supportedTargets:["video","image"],recipe:{effects:[{type:"film-grain",params:{intensity:.75,size:2.8}},{type:"contrast",params:{value:.22}},{type:"brightness",params:{value:-.08}}],overlays:[q({type:"text",trackType:"text",timing:{kind:"intro",duration:1.2},transform:I(.08,.08,1,1,0,0,.5),content:{text:"ROLL 04",style:{fontFamily:"JetBrains Mono",fontSize:22,color:"rgba(255,255,255,0.8)",fontWeight:600,textAlign:"left",verticalAlign:"middle",lineHeight:1.1,letterSpacing:1}}})],audioEffects:[]}},{id:"retro-sepia-drift",name:"Sepia Drift",description:"Subtle vintage warmth with a soft border.",category:"retro",thumbnailUrl:null,previewUrl:null,tags:["retro","sepia","vintage"],supportedTargets:["video","image"],recipe:{effects:[{type:"brightness",params:{value:.04}},{type:"contrast",params:{value:.06}},{type:"saturation",params:{value:-.08}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),blendOpacity:.3,content:{shapeType:"rectangle",width:1860,height:1020,style:{fill:{type:"none",opacity:0},stroke:{color:"#7d5b39",width:10,opacity:1}}}})],audioEffects:[]}},{id:"social-recording",name:"Recording Camera",description:"Classic REC indicator, timer, and frame border.",category:"social",thumbnailUrl:null,previewUrl:null,tags:["social","rec","recording"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.045,.055),emphasisAnimation:{type:"pulse",speed:1,intensity:.55,loop:!0},content:{shapeType:"circle",width:14,height:14,style:{fill:{type:"solid",color:"#ff4d4d",opacity:1},stroke:{color:"#ff4d4d",width:0,opacity:0}}}}),q({type:"text",trackType:"text",timing:B,transform:I(.075,.055,1,1,0,0,.5),content:{text:"REC",style:{fontFamily:"Inter",fontSize:18,color:"#ff4d4d",fontWeight:700,textAlign:"left",verticalAlign:"middle",lineHeight:1.1,letterSpacing:2}}}),q({type:"text",trackType:"text",timing:B,transform:I(.94,.06,1,1,0,1,.5),content:{text:"00:00:00",style:{fontFamily:"JetBrains Mono",fontSize:18,color:"rgba(255,255,255,0.85)",fontWeight:600,textAlign:"right",verticalAlign:"middle",lineHeight:1.1,letterSpacing:1}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),content:{shapeType:"rectangle",width:1760,height:920,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,255,255,0.32)",width:4,opacity:1}}}})],audioEffects:[]}},{id:"social-facecam-frame",name:"Facecam Frame",description:"Corner frame for reaction and gameplay clips.",category:"social",thumbnailUrl:null,previewUrl:null,tags:["social","facecam","reaction"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.78,.76),content:{shapeType:"rectangle",width:560,height:320,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,255,255,0.9)",width:6,opacity:1},cornerRadius:22}}})],audioEffects:[]}},{id:"social-countdown-lead",name:"Countdown Lead",description:"Short intro count-in for tutorials and hooks.",category:"social",thumbnailUrl:null,previewUrl:null,tags:["social","countdown","hook"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[q({type:"text",trackType:"text",timing:{kind:"intro",duration:2},transform:I(.5,.18),keyframes:[{time:0,property:"opacity",value:0},{time:.2,property:"opacity",value:1},{time:.8,property:"opacity",value:1},{time:1,property:"opacity",value:0}],content:{text:"3 2 1",style:{fontFamily:"Inter",fontSize:82,color:"#ffffff",fontWeight:800,textAlign:"center",verticalAlign:"middle",lineHeight:1,letterSpacing:8}}})],audioEffects:[]}},{id:"social-comment-pop",name:"Comment Pop",description:"Pinned comment bubble for social callouts.",category:"social",thumbnailUrl:null,previewUrl:null,tags:["social","comment","bubble"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:{kind:"intro",duration:3},transform:I(.5,.15),content:{shapeType:"rectangle",width:1080,height:140,style:{fill:{type:"solid",color:"rgba(255,255,255,0.92)",opacity:1},stroke:{color:"rgba(0,0,0,0.08)",width:2,opacity:1},cornerRadius:999}}}),q({type:"text",trackType:"text",timing:{kind:"intro",duration:3},transform:I(.5,.15),content:{text:"Pinned: Drop your best take below",style:{fontFamily:"Inter",fontSize:30,color:"#111111",fontWeight:700,textAlign:"center",verticalAlign:"middle",lineHeight:1.1,letterSpacing:0}}})],audioEffects:[]}},{id:"branding-watermark-drift",name:"Watermark Drift",description:"Soft moving corner watermark for brand protection.",category:"branding",thumbnailUrl:null,previewUrl:null,tags:["branding","watermark","corner"],supportedTargets:["video","image"],controls:[{id:"watermarkText",label:"Watermark",type:"text",defaultValue:"@openreel"},{id:"watermarkOpacity",label:"Opacity",type:"number",defaultValue:.45,min:.1,max:1,step:.05}],recipe:{effects:[],overlays:[q({type:"text",trackType:"text",timing:B,transform:I(.88,.92,1,1,0,1,.5),keyframes:[{time:0,property:"position.x",value:.88},{time:.5,property:"position.x",value:.84},{time:1,property:"position.x",value:.88}],blendOpacity:Ce("watermarkOpacity"),content:{text:"{control.watermarkText}",style:{fontFamily:"Inter",fontSize:22,color:"rgba(255,255,255,0.92)",fontWeight:600,textAlign:"right",verticalAlign:"middle",lineHeight:1.1,letterSpacing:.5}}})],audioEffects:[]}},{id:"branding-copyright",name:"Moving Copyright",description:"Full-width copyright crawl for delivered cuts.",category:"branding",thumbnailUrl:null,previewUrl:null,tags:["branding","copyright","crawl"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[q({type:"text",trackType:"text",timing:B,transform:I(.5,.95),keyframes:[{time:0,property:"position.x",value:1.2},{time:.1,property:"position.x",value:.5},{time:.9,property:"position.x",value:.5},{time:1,property:"position.x",value:-.2}],content:{text:"Copyright {year} All Rights Reserved",style:{fontFamily:"Inter",fontSize:18,color:"rgba(255,255,255,0.7)",fontWeight:500,textAlign:"center",verticalAlign:"middle",lineHeight:1.1,letterSpacing:.5}}})],audioEffects:[]}},{id:"branding-lower-third",name:"Lower Third",description:"Simple branded name tag.",category:"branding",thumbnailUrl:null,previewUrl:null,tags:["branding","lower third","name"],supportedTargets:["video","image"],controls:[{id:"name",label:"Name",type:"text",defaultValue:"Open Reel"},{id:"role",label:"Role",type:"text",defaultValue:"Creator"},{id:"accent",label:"Accent",type:"color",defaultValue:"#7bf1a8"}],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:{kind:"intro",duration:4},transform:I(.18,.88,1,1,0,0,.5),content:{shapeType:"rectangle",width:520,height:124,style:{fill:{type:"solid",color:"rgba(7,7,10,0.76)",opacity:1},stroke:{color:Ce("accent"),width:4,opacity:1},cornerRadius:18}}}),q({type:"text",trackType:"text",timing:{kind:"intro",duration:4},transform:I(.11,.865,1,1,0,0,.5),content:{text:"{control.name}",style:{fontFamily:"Inter",fontSize:34,color:"#ffffff",fontWeight:800,textAlign:"left",verticalAlign:"middle",lineHeight:1.1,letterSpacing:0}}}),q({type:"text",trackType:"text",timing:{kind:"intro",duration:4},transform:I(.11,.905,1,1,0,0,.5),content:{text:"{control.role}",style:{fontFamily:"Inter",fontSize:22,color:"rgba(255,255,255,0.72)",fontWeight:500,textAlign:"left",verticalAlign:"middle",lineHeight:1.1,letterSpacing:0}}})],audioEffects:[]}},{id:"branding-subscribe-tag",name:"Subscribe Tag",description:"End-card subscribe banner.",category:"branding",thumbnailUrl:null,previewUrl:null,tags:["branding","subscribe","end card"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:{kind:"outro",duration:3.5},transform:I(.5,.88),content:{shapeType:"rectangle",width:760,height:110,style:{fill:{type:"solid",color:"#ff3b30",opacity:1},stroke:{color:"#ff3b30",width:0,opacity:0},cornerRadius:999}}}),q({type:"text",trackType:"text",timing:{kind:"outro",duration:3.5},transform:I(.5,.88),content:{text:"Subscribe for the next drop",style:{fontFamily:"Inter",fontSize:28,color:"#ffffff",fontWeight:800,textAlign:"center",verticalAlign:"middle",lineHeight:1.1,letterSpacing:.5}}})],audioEffects:[]}},{id:"color-warm-pop",name:"Warm Pop",description:"Golden warmth with gentle contrast.",category:"color",thumbnailUrl:null,previewUrl:null,tags:["color","warm","pop"],supportedTargets:["video","image"],recipe:{effects:[{type:"brightness",params:{value:.05}},{type:"contrast",params:{value:.12}},{type:"saturation",params:{value:.14}}],overlays:[],audioEffects:[]}},{id:"color-cool-bloom",name:"Cool Bloom",description:"Softer cooler palette for night and tech footage.",category:"color",thumbnailUrl:null,previewUrl:null,tags:["color","cool","tech"],supportedTargets:["video","image"],recipe:{effects:[{type:"brightness",params:{value:-.02}},{type:"contrast",params:{value:.08}},{type:"saturation",params:{value:-.08}}],overlays:[],audioEffects:[]}},{id:"color-dramatic-noir",name:"Dramatic Noir",description:"High-contrast moody look.",category:"color",thumbnailUrl:null,previewUrl:null,tags:["color","dramatic","noir"],supportedTargets:["video","image"],recipe:{effects:[{type:"contrast",params:{value:.2}},{type:"brightness",params:{value:-.08}},{type:"vignette",params:{intensity:.55,radius:.72}}],overlays:[],audioEffects:[]}},{id:"color-vintage-wash",name:"Vintage Wash",description:"Low-contrast faded stock feel.",category:"color",thumbnailUrl:null,previewUrl:null,tags:["color","vintage","fade"],supportedTargets:["video","image"],recipe:{effects:[{type:"brightness",params:{value:.08}},{type:"contrast",params:{value:-.05}},{type:"saturation",params:{value:-.12}}],overlays:[],audioEffects:[]}},{id:"overlay-focus-frame",name:"Focus Frame",description:"Center guide frame with crosshair accents.",category:"overlay",thumbnailUrl:null,previewUrl:null,tags:["overlay","focus","frame"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),content:{shapeType:"rectangle",width:1360,height:760,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,255,255,0.4)",width:4,opacity:1}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),content:{shapeType:"line",width:120,height:6,style:{fill:{type:"solid",color:"rgba(255,255,255,0.55)",opacity:1},stroke:{color:"rgba(255,255,255,0.55)",width:0,opacity:0}}}})],audioEffects:[]}},{id:"overlay-soft-border",name:"Soft Border",description:"Thin elegant border for editorial framing.",category:"overlay",thumbnailUrl:null,previewUrl:null,tags:["overlay","border","editorial"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),content:{shapeType:"rectangle",width:1840,height:1e3,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,255,255,0.24)",width:5,opacity:1}}}})],audioEffects:[]}},{id:"overlay-spotlight-title",name:"Spotlight Title",description:"Headline treatment for hero moments.",category:"text-effects",thumbnailUrl:null,previewUrl:null,tags:["text","headline","hero"],supportedTargets:["video","image"],controls:[{id:"headline",label:"Headline",type:"text",defaultValue:"Headline"}],recipe:{effects:[],overlays:[q({type:"text",trackType:"text",timing:{kind:"intro",duration:4},transform:I(.5,.18),content:{text:"{control.headline}",style:{fontFamily:"Inter",fontSize:88,color:"#ffffff",fontWeight:800,textAlign:"center",verticalAlign:"middle",lineHeight:.95,letterSpacing:-1},animation:{preset:"slide-up",inDuration:.45,outDuration:.35,params:{easing:"easeOutCubic"}}}})],audioEffects:[]}},{id:"text-kinetic-punch",name:"Kinetic Punch",description:"Bold text punch-in for transitions and hooks.",category:"text-effects",thumbnailUrl:null,previewUrl:null,tags:["text","kinetic","hook"],supportedTargets:["video","image"],controls:[{id:"caption",label:"Caption",type:"text",defaultValue:"Watch this"},{id:"accent",label:"Accent",type:"color",defaultValue:"#ffb100"}],recipe:{effects:[],overlays:[q({type:"text",trackType:"text",timing:{kind:"intro",duration:3},transform:I(.5,.82),emphasisAnimation:{type:"bounce",speed:1,intensity:.5,loop:!0},content:{text:"{control.caption}",style:{fontFamily:"Inter",fontSize:56,color:Ce("accent"),fontWeight:900,textAlign:"center",verticalAlign:"middle",lineHeight:1,letterSpacing:0},animation:{preset:"pop",inDuration:.3,outDuration:.25,params:{easing:"easeOutBack"}}}})],audioEffects:[]}},{id:"text-stamp-upper",name:"Stamp Upper",description:"Upper-third stamp for chapter labels.",category:"text-effects",thumbnailUrl:null,previewUrl:null,tags:["text","stamp","chapter"],supportedTargets:["video","image"],controls:[{id:"label",label:"Label",type:"text",defaultValue:"Chapter One"}],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:{kind:"intro",duration:3.5},transform:I(.5,.12),content:{shapeType:"rectangle",width:720,height:92,style:{fill:{type:"solid",color:"rgba(255,255,255,0.08)",opacity:1},stroke:{color:"rgba(255,255,255,0.42)",width:2,opacity:1},cornerRadius:999}}}),q({type:"text",trackType:"text",timing:{kind:"intro",duration:3.5},transform:I(.5,.12),content:{text:"{control.label}",style:{fontFamily:"Inter",fontSize:32,color:"#ffffff",fontWeight:700,textAlign:"center",verticalAlign:"middle",lineHeight:1,letterSpacing:2}}})],audioEffects:[]}},{id:"text-neon-tag",name:"Neon Tag",description:"Bright tag for music and nightlife content.",category:"text-effects",thumbnailUrl:null,previewUrl:null,tags:["text","neon","music"],supportedTargets:["video","image"],controls:[{id:"tag",label:"Tag",type:"text",defaultValue:"LIVE SET"}],recipe:{effects:[],overlays:[q({type:"text",trackType:"text",timing:B,transform:I(.13,.14,1,1,0,0,.5),emphasisAnimation:{type:"glow",speed:1,intensity:.6,loop:!0},content:{text:"{control.tag}",style:{fontFamily:"Inter",fontSize:34,color:"#66f7ff",fontWeight:800,textAlign:"left",verticalAlign:"middle",lineHeight:1,letterSpacing:1}}})],audioEffects:[]}},{id:"social-live-badge",name:"Live Badge",description:"Pulsing LIVE indicator for stream-style overlays.",category:"social",thumbnailUrl:null,previewUrl:null,tags:["social","live","stream"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.92,.06),emphasisAnimation:{type:"pulse",speed:.8,intensity:.4,loop:!0},content:{shapeType:"rectangle",width:120,height:40,style:{fill:{type:"solid",color:"#ff0000",opacity:1},stroke:{color:"#ff0000",width:0,opacity:0},cornerRadius:8}}}),q({type:"text",trackType:"text",timing:B,transform:I(.92,.06),content:{text:"LIVE",style:{fontFamily:"Inter",fontSize:16,color:"#ffffff",fontWeight:800,textAlign:"center",verticalAlign:"middle",lineHeight:1,letterSpacing:2}}})],audioEffects:[]}},{id:"social-hashtag-strip",name:"Hashtag Strip",description:"Bottom hashtag bar for social video posts.",category:"social",thumbnailUrl:null,previewUrl:null,tags:["social","hashtag","bar"],supportedTargets:["video","image"],controls:[{id:"tags",label:"Hashtags",type:"text",defaultValue:"#openreel #editing #creative"}],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.94),content:{shapeType:"rectangle",width:1920,height:56,style:{fill:{type:"solid",color:"rgba(0,0,0,0.6)",opacity:1},stroke:{color:"rgba(0,0,0,0)",width:0,opacity:0}}}}),q({type:"text",trackType:"text",timing:B,transform:I(.5,.94),content:{text:"{control.tags}",style:{fontFamily:"Inter",fontSize:18,color:"rgba(255,255,255,0.9)",fontWeight:600,textAlign:"center",verticalAlign:"middle",lineHeight:1,letterSpacing:.5}}})],audioEffects:[]}},{id:"cinema-anamorphic-flare",name:"Anamorphic Flare",description:"Top and bottom bars with blue lens flare accents.",category:"cinema",thumbnailUrl:null,previewUrl:null,tags:["cinema","anamorphic","flare"],supportedTargets:["video","image"],recipe:{effects:[{type:"contrast",params:{value:.06}},{type:"vignette",params:{intensity:.3,radius:.85}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.035),content:{shapeType:"rectangle",width:1920,height:80,style:{fill:{type:"solid",color:"#000000",opacity:1},stroke:{color:"#000000",width:0,opacity:0}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.965),content:{shapeType:"rectangle",width:1920,height:80,style:{fill:{type:"solid",color:"#000000",opacity:1},stroke:{color:"#000000",width:0,opacity:0}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.3,.5),keyframes:[{time:0,property:"position.x",value:.1},{time:.5,property:"position.x",value:.7},{time:1,property:"position.x",value:.1}],content:{shapeType:"rectangle",width:320,height:4,style:{fill:{type:"solid",color:"rgba(100,180,255,0.15)",opacity:1},stroke:{color:"rgba(100,180,255,0)",width:0,opacity:0}}}})],audioEffects:[]}},{id:"cinema-noir-bars",name:"Noir Bars",description:"Heavy letterbox with deep contrast for dramatic scenes.",category:"cinema",thumbnailUrl:null,previewUrl:null,tags:["cinema","noir","dramatic"],supportedTargets:["video","image"],recipe:{effects:[{type:"contrast",params:{value:.18}},{type:"brightness",params:{value:-.06}},{type:"vignette",params:{intensity:.6,radius:.65}},{type:"saturation",params:{value:-.15}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.06),content:{shapeType:"rectangle",width:1920,height:140,style:{fill:{type:"solid",color:"#000000",opacity:1},stroke:{color:"#000000",width:0,opacity:0}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.94),content:{shapeType:"rectangle",width:1920,height:140,style:{fill:{type:"solid",color:"#000000",opacity:1},stroke:{color:"#000000",width:0,opacity:0}}}})],audioEffects:[]}},{id:"overlay-grid-guide",name:"Grid Guide",description:"Rule of thirds grid for composition reference.",category:"overlay",thumbnailUrl:null,previewUrl:null,tags:["overlay","grid","composition"],supportedTargets:["video","image"],controls:[{id:"gridOpacity",label:"Grid Opacity",type:"number",defaultValue:.2,min:.05,max:.6,step:.05}],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.333,.5),content:{shapeType:"rectangle",width:2,height:1080,style:{fill:{type:"solid",color:"rgba(255,255,255,0.2)",opacity:Ce("gridOpacity")},stroke:{color:"rgba(255,255,255,0)",width:0,opacity:0}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.666,.5),content:{shapeType:"rectangle",width:2,height:1080,style:{fill:{type:"solid",color:"rgba(255,255,255,0.2)",opacity:Ce("gridOpacity")},stroke:{color:"rgba(255,255,255,0)",width:0,opacity:0}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.333),content:{shapeType:"rectangle",width:1920,height:2,style:{fill:{type:"solid",color:"rgba(255,255,255,0.2)",opacity:Ce("gridOpacity")},stroke:{color:"rgba(255,255,255,0)",width:0,opacity:0}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.666),content:{shapeType:"rectangle",width:1920,height:2,style:{fill:{type:"solid",color:"rgba(255,255,255,0.2)",opacity:Ce("gridOpacity")},stroke:{color:"rgba(255,255,255,0)",width:0,opacity:0}}}})],audioEffects:[]}},{id:"overlay-corner-brackets",name:"Corner Brackets",description:"Elegant corner frame markers for cinematic focus.",category:"overlay",thumbnailUrl:null,previewUrl:null,tags:["overlay","brackets","frame"],supportedTargets:["video","image"],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.08,.1,1,1,0,0,0),content:{shapeType:"rectangle",width:80,height:80,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,255,255,0.6)",width:3,opacity:1}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.92,.1,1,1,0,1,0),content:{shapeType:"rectangle",width:80,height:80,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,255,255,0.6)",width:3,opacity:1}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.08,.9,1,1,0,0,1),content:{shapeType:"rectangle",width:80,height:80,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,255,255,0.6)",width:3,opacity:1}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.92,.9,1,1,0,1,1),content:{shapeType:"rectangle",width:80,height:80,style:{fill:{type:"none",opacity:0},stroke:{color:"rgba(255,255,255,0.6)",width:3,opacity:1}}}})],audioEffects:[]}},{id:"text-subtitle-bar",name:"Subtitle Bar",description:"Bottom subtitle with dark backing for readability.",category:"text-effects",thumbnailUrl:null,previewUrl:null,tags:["text","subtitle","caption"],supportedTargets:["video","image"],controls:[{id:"subtitle",label:"Subtitle",type:"text",defaultValue:"Your subtitle text here"}],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.88),content:{shapeType:"rectangle",width:1400,height:64,style:{fill:{type:"solid",color:"rgba(0,0,0,0.7)",opacity:1},stroke:{color:"rgba(0,0,0,0)",width:0,opacity:0},cornerRadius:12}}}),q({type:"text",trackType:"text",timing:B,transform:I(.5,.88),content:{text:"{control.subtitle}",style:{fontFamily:"Inter",fontSize:28,color:"#ffffff",fontWeight:600,textAlign:"center",verticalAlign:"middle",lineHeight:1.1,letterSpacing:0}}})],audioEffects:[]}},{id:"text-quote-block",name:"Quote Block",description:"Centered quote with decorative marks.",category:"text-effects",thumbnailUrl:null,previewUrl:null,tags:["text","quote","editorial"],supportedTargets:["video","image"],controls:[{id:"quote",label:"Quote",type:"text",defaultValue:"Create something worth sharing."}],recipe:{effects:[],overlays:[q({type:"text",trackType:"text",timing:{kind:"intro",duration:5},transform:I(.5,.42),content:{text:"“",style:{fontFamily:"Inter",fontSize:120,color:"rgba(255,255,255,0.2)",fontWeight:900,textAlign:"center",verticalAlign:"middle",lineHeight:.6,letterSpacing:0}}}),q({type:"text",trackType:"text",timing:{kind:"intro",duration:5},transform:I(.5,.5),content:{text:"{control.quote}",style:{fontFamily:"Inter",fontSize:36,color:"#ffffff",fontWeight:500,textAlign:"center",verticalAlign:"middle",lineHeight:1.4,letterSpacing:0},animation:{preset:"fade",inDuration:.6,outDuration:.4,params:{easing:"easeOutCubic"}}}})],audioEffects:[]}},{id:"color-teal-orange",name:"Teal & Orange",description:"Hollywood color grading — cool shadows, warm highlights.",category:"color",thumbnailUrl:null,previewUrl:null,tags:["color","teal","orange","hollywood"],supportedTargets:["video","image"],recipe:{effects:[{type:"contrast",params:{value:.1}},{type:"saturation",params:{value:.12}},{type:"brightness",params:{value:.02}}],overlays:[],audioEffects:[]}},{id:"color-monochrome",name:"Monochrome",description:"Clean black and white with lifted blacks.",category:"color",thumbnailUrl:null,previewUrl:null,tags:["color","monochrome","black","white"],supportedTargets:["video","image"],recipe:{effects:[{type:"saturation",params:{value:-1}},{type:"contrast",params:{value:.15}},{type:"brightness",params:{value:.04}}],overlays:[],audioEffects:[]}},{id:"glitch-datamosh",name:"Datamosh",description:"Heavy grain and color separation for chaotic energy.",category:"glitch",thumbnailUrl:null,previewUrl:null,tags:["glitch","datamosh","chaos"],supportedTargets:["video","image"],recipe:{effects:[{type:"chromatic-aberration",params:{intensity:8}},{type:"film-grain",params:{intensity:.55,size:3}},{type:"contrast",params:{value:.2}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.4),keyframes:[{time:0,property:"position.y",value:.12},{time:.15,property:"position.y",value:.88},{time:.3,property:"position.y",value:.25},{time:.5,property:"position.y",value:.72},{time:.7,property:"position.y",value:.4},{time:.85,property:"position.y",value:.92},{time:1,property:"position.y",value:.15}],content:{shapeType:"rectangle",width:1920,height:16,style:{fill:{type:"solid",color:"rgba(255,0,100,0.08)",opacity:1},stroke:{color:"rgba(255,0,100,0)",width:0,opacity:0}}}})],audioEffects:[]}},{id:"branding-end-card",name:"End Card",description:"Full outro card with name and call to action.",category:"branding",thumbnailUrl:null,previewUrl:null,tags:["branding","end card","outro"],supportedTargets:["video","image"],controls:[{id:"channel",label:"Channel Name",type:"text",defaultValue:"Your Channel"},{id:"cta",label:"Call to Action",type:"text",defaultValue:"Subscribe for more"}],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:{kind:"outro",duration:5},transform:I(.5,.5),content:{shapeType:"rectangle",width:1920,height:1080,style:{fill:{type:"solid",color:"rgba(0,0,0,0.85)",opacity:1},stroke:{color:"rgba(0,0,0,0)",width:0,opacity:0}}}}),q({type:"text",trackType:"text",timing:{kind:"outro",duration:5},transform:I(.5,.42),content:{text:"{control.channel}",style:{fontFamily:"Inter",fontSize:56,color:"#ffffff",fontWeight:800,textAlign:"center",verticalAlign:"middle",lineHeight:1,letterSpacing:-1},animation:{preset:"fade",inDuration:.5,outDuration:.3,params:{easing:"easeOutCubic"}}}}),q({type:"text",trackType:"text",timing:{kind:"outro",duration:5},transform:I(.5,.55),content:{text:"{control.cta}",style:{fontFamily:"Inter",fontSize:24,color:"rgba(255,255,255,0.7)",fontWeight:500,textAlign:"center",verticalAlign:"middle",lineHeight:1,letterSpacing:.5},animation:{preset:"fade",inDuration:.7,outDuration:.3,params:{easing:"easeOutCubic"}}}})],audioEffects:[]}},{id:"social-viewer-count",name:"Viewer Count",description:"Animated viewer/like counter badge.",category:"social",thumbnailUrl:null,previewUrl:null,tags:["social","viewers","counter"],supportedTargets:["video","image"],controls:[{id:"count",label:"Count",type:"text",defaultValue:"1.2K watching"}],recipe:{effects:[],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.92,.94),content:{shapeType:"rectangle",width:180,height:36,style:{fill:{type:"solid",color:"rgba(0,0,0,0.65)",opacity:1},stroke:{color:"rgba(255,255,255,0.15)",width:1,opacity:1},cornerRadius:18}}}),q({type:"text",trackType:"text",timing:B,transform:I(.92,.94),content:{text:"{control.count}",style:{fontFamily:"Inter",fontSize:13,color:"rgba(255,255,255,0.9)",fontWeight:600,textAlign:"center",verticalAlign:"middle",lineHeight:1,letterSpacing:.3}}})],audioEffects:[]}},{id:"retro-polaroid",name:"Polaroid",description:"White border frame with warm vintage tones.",category:"retro",thumbnailUrl:null,previewUrl:null,tags:["retro","polaroid","frame"],supportedTargets:["video","image"],recipe:{effects:[{type:"brightness",params:{value:.03}},{type:"saturation",params:{value:-.06}},{type:"contrast",params:{value:.05}}],overlays:[R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.5),content:{shapeType:"rectangle",width:1700,height:900,style:{fill:{type:"none",opacity:0},stroke:{color:"#f5f0e8",width:40,opacity:1}}}}),R({type:"shape",trackType:"graphics",timing:B,transform:I(.5,.94),content:{shapeType:"rectangle",width:1700,height:80,style:{fill:{type:"solid",color:"#f5f0e8",opacity:1},stroke:{color:"#f5f0e8",width:0,opacity:0}}}})],audioEffects:[]}},{id:"motion-saas-ad-card",name:"SaaS Ad Card",description:"Motion Creator starter for a product ad with editable copy, brand color, media placeholder, and animation intensity.",category:"ads",thumbnailUrl:null,previewUrl:null,tags:["motion","ads","saas","product"],supportedTargets:["video","image"],controls:[{id:"headline",label:"Headline",type:"text",defaultValue:"Launch faster"},{id:"brandColor",label:"Brand Color",type:"color",defaultValue:"#14b8a6"},{id:"duration",label:"Duration",type:"number",defaultValue:10,min:3,max:30,step:.5},{id:"intensity",label:"Animation Intensity",type:"number",defaultValue:.6,min:0,max:1,step:.05}],motionTemplate:{category:"ads",variables:[{id:"headline",label:"Headline",type:"text",defaultValue:"Launch faster"},{id:"brandColor",label:"Brand Color",type:"color",defaultValue:"#14b8a6"},{id:"media",label:"Product Media",type:"media",defaultValue:""},{id:"duration",label:"Duration",type:"number",defaultValue:10},{id:"brandKit",label:"Use Brand Kit",type:"boolean",defaultValue:!0},{id:"intensity",label:"Animation Intensity",type:"number",defaultValue:.6}]},recipe:{effects:[],overlays:[],audioEffects:[]}}];new Map(_f.map(a=>[a.id,a]));function pt(a){if(a===void 0)throw new ReferenceError("this hasn't been initialised - super() hasn't been called");return a}function Kn(a,e){a.prototype=Object.create(e.prototype),a.prototype.constructor=a,a.__proto__=e}/*!
 * GSAP 3.15.0
 * https://gsap.com
 *
 * @license Copyright 2008-2026, GreenSock. All rights reserved.
 * Subject to the terms at https://gsap.com/standard-license
 * @author: Jack Doyle, jack@greensock.com
*/var Me={autoSleep:120,force3D:"auto",nullTargetWarn:1,units:{lineHeight:""}},qa={duration:.5,overwrite:!1,delay:0},tr,se,H,$e=1e8,W=1/$e,Ai=Math.PI*2,xf=Ai/4,bf=0,Qn=Math.sqrt,wf=Math.cos,Sf=Math.sin,ne=function(e){return typeof e=="string"},ee=function(e){return typeof e=="function"},yt=function(e){return typeof e=="number"},ar=function(e){return typeof e>"u"},nt=function(e){return typeof e=="object"},_e=function(e){return e!==!1},or=function(){return typeof window<"u"},mo=function(e){return ee(e)||ne(e)},Jn=typeof ArrayBuffer=="function"&&ArrayBuffer.isView||function(){},pe=Array.isArray,kf=/random\([^)]+\)/g,Cf=/,\s*/g,ln=/(?:-?\.?\d|\.)+/gi,Zn=/[-+=.]*\d+[.e\-+]*\d*[e\-+]*\d*/g,ua=/[-+=.]*\d+[.e-]*\d*[a-z%]*/g,ci=/[-+=.]*\d+\.?\d*(?:e-|e\+)?\d*/gi,es=/[+-]=-?[.\d]+/,Of=/[^,'"\[\]\s]+/gi,Tf=/^[+\-=e\s\d]*\d+[.\d]*([a-z]*|%)\s*$/i,K,ot,Mi,ir,Be={},Uo={},ts,as=function(e){return(Uo=ba(e,Be))&&Se},rr=function(e,t){return console.warn("Invalid property",e,"set to",t,"Missing plugin? gsap.registerPlugin()")},Ha=function(e,t){return!t&&console.warn(e)},os=function(e,t){return e&&(Be[e]=t)&&Uo&&(Uo[e]=t)||Be},Xa=function(){return 0},Uf={suppressEvents:!0,isStart:!0,kill:!1},_o={suppressEvents:!0,kill:!1},If={suppressEvents:!0},nr={},At=[],Bi={},is,Oe={},ui={},cn=30,xo=[],sr="",lr=function(e){var t=e[0],o,i;if(nt(t)||ee(t)||(e=[e]),!(o=(t._gsap||{}).harness)){for(i=xo.length;i--&&!xo[i].targetTest(t););o=xo[i]}for(i=e.length;i--;)e[i]&&(e[i]._gsap||(e[i]._gsap=new Os(e[i],o)))||e.splice(i,1);return e},Ht=function(e){return e._gsap||lr(je(e))[0]._gsap},rs=function(e,t,o){return(o=e[t])&&ee(o)?e[t]():ar(o)&&e.getAttribute&&e.getAttribute(t)||o},xe=function(e,t){return(e=e.split(",")).forEach(t)||e},te=function(e){return Math.round(e*1e5)/1e5||0},X=function(e){return Math.round(e*1e7)/1e7||0},ga=function(e,t){var o=t.charAt(0),i=parseFloat(t.substr(2));return e=parseFloat(e),o==="+"?e+i:o==="-"?e-i:o==="*"?e*i:e/i},Af=function(e,t){for(var o=t.length,i=0;e.indexOf(t[i])<0&&++i<o;);return i<o},Io=function(){var e=At.length,t=At.slice(0),o,i;for(Bi={},At.length=0,o=0;o<e;o++)i=t[o],i&&i._lazy&&(i.render(i._lazy[0],i._lazy[1],!0)._lazy=0)},cr=function(e){return!!(e._initted||e._startAt||e.add)},ns=function(e,t,o,i){At.length&&!se&&Io(),e.render(t,o,!!(se&&t<0&&cr(e))),At.length&&!se&&Io()},ss=function(e){var t=parseFloat(e);return(t||t===0)&&(e+"").match(Of).length<2?t:ne(e)?e.trim():e},ls=function(e){return e},Ve=function(e,t){for(var o in t)o in e||(e[o]=t[o]);return e},Mf=function(e){return function(t,o){for(var i in o)i in t||i==="duration"&&e||i==="ease"||(t[i]=o[i])}},ba=function(e,t){for(var o in t)e[o]=t[o];return e},un=function a(e,t){for(var o in t)o!=="__proto__"&&o!=="constructor"&&o!=="prototype"&&(e[o]=nt(t[o])?a(e[o]||(e[o]={}),t[o]):t[o]);return e},Ao=function(e,t){var o={},i;for(i in e)i in t||(o[i]=e[i]);return o},Ea=function(e){var t=e.parent||K,o=e.keyframes?Mf(pe(e.keyframes)):Ve;if(_e(e.inherit))for(;t;)o(e,t.vars.defaults),t=t.parent||t._dp;return e},Bf=function(e,t){for(var o=e.length,i=o===t.length;i&&o--&&e[o]===t[o];);return o<0},cs=function(e,t,o,i,r){var n=e[i],s;if(r)for(s=t[r];n&&n[r]>s;)n=n._prev;return n?(t._next=n._next,n._next=t):(t._next=e[o],e[o]=t),t._next?t._next._prev=t:e[i]=t,t._prev=n,t.parent=t._dp=e,t},Wo=function(e,t,o,i){o===void 0&&(o="_first"),i===void 0&&(i="_last");var r=t._prev,n=t._next;r?r._next=n:e[o]===t&&(e[o]=n),n?n._prev=r:e[i]===t&&(e[i]=r),t._next=t._prev=t.parent=null},Vt=function(e,t){e.parent&&(!t||e.parent.autoRemoveChildren)&&e.parent.remove&&e.parent.remove(e),e._act=0},Xt=function(e,t){if(e&&(!t||t._end>e._dur||t._start<0))for(var o=e;o;)o._dirty=1,o=o.parent;return e},Vf=function(e){for(var t=e.parent;t&&t.parent;)t._dirty=1,t.totalDuration(),t=t.parent;return e},Vi=function(e,t,o,i){return e._startAt&&(se?e._startAt.revert(_o):e.vars.immediateRender&&!e.vars.autoRevert||e._startAt.render(t,!0,i))},Rf=function a(e){return!e||e._ts&&a(e.parent)},fn=function(e){return e._repeat?wa(e._tTime,e=e.duration()+e._rDelay)*e:0},wa=function(e,t){var o=Math.floor(e=X(e/t));return e&&o===e?o-1:o},Mo=function(e,t){return(e-t._start)*t._ts+(t._ts>=0?0:t._dirty?t.totalDuration():t._tDur)},Go=function(e){return e._end=X(e._start+(e._tDur/Math.abs(e._ts||e._rts||W)||0))},Yo=function(e,t){var o=e._dp;return o&&o.smoothChildTiming&&e._ts&&(e._start=X(o._time-(e._ts>0?t/e._ts:((e._dirty?e.totalDuration():e._tDur)-t)/-e._ts)),Go(e),o._dirty||Xt(o,e)),e},us=function(e,t){var o;if((t._time||!t._dur&&t._initted||t._start<e._time&&(t._dur||!t.add))&&(o=Mo(e.rawTime(),t),(!t._dur||so(0,t.totalDuration(),o)-t._tTime>W)&&t.render(o,!0)),Xt(e,t)._dp&&e._initted&&e._time>=e._dur&&e._ts){if(e._dur<e.duration())for(o=e;o._dp;)o.rawTime()>=0&&o.totalTime(o._tTime),o=o._dp;e._zTime=-W}},it=function(e,t,o,i){return t.parent&&Vt(t),t._start=X((yt(o)?o:o||e!==K?Ee(e,o,t):e._time)+t._delay),t._end=X(t._start+(t.totalDuration()/Math.abs(t.timeScale())||0)),cs(e,t,"_first","_last",e._sort?"_start":0),Ri(t)||(e._recent=t),i||us(e,t),e._ts<0&&Yo(e,e._tTime),e},fs=function(e,t){return(Be.ScrollTrigger||rr("scrollTrigger",t))&&Be.ScrollTrigger.create(t,e)},ps=function(e,t,o,i,r){if(fr(e,t,r),!e._initted)return 1;if(!o&&e._pt&&!se&&(e._dur&&e.vars.lazy!==!1||!e._dur&&e.vars.lazy)&&is!==Te.frame)return At.push(e),e._lazy=[r,i],1},Pf=function a(e){var t=e.parent;return t&&t._ts&&t._initted&&!t._lock&&(t.rawTime()<0||a(t))},Ri=function(e){var t=e.data;return t==="isFromStart"||t==="isStart"},Df=function(e,t,o,i){var r=e.ratio,n=t<0||!t&&(!e._start&&Pf(e)&&!(!e._initted&&Ri(e))||(e._ts<0||e._dp._ts<0)&&!Ri(e))?0:1,s=e._rDelay,l=0,c,u,f;if(s&&e._repeat&&(l=so(0,e._tDur,t),u=wa(l,s),e._yoyo&&u&1&&(n=1-n),u!==wa(e._tTime,s)&&(r=1-n,e.vars.repeatRefresh&&e._initted&&e.invalidate())),n!==r||se||i||e._zTime===W||!t&&e._zTime){if(!e._initted&&ps(e,t,i,o,l))return;for(f=e._zTime,e._zTime=t||(o?W:0),o||(o=t&&!f),e.ratio=n,e._from&&(n=1-n),e._time=0,e._tTime=l,c=e._pt;c;)c.r(n,c.d),c=c._next;t<0&&Vi(e,t,o,!0),e._onUpdate&&!o&&Ie(e,"onUpdate"),l&&e._repeat&&!o&&e.parent&&Ie(e,"onRepeat"),(t>=e._tDur||t<0)&&e.ratio===n&&(n&&Vt(e,1),!o&&!se&&(Ie(e,n?"onComplete":"onReverseComplete",!0),e._prom&&e._prom()))}else e._zTime||(e._zTime=t)},zf=function(e,t,o){var i;if(o>t)for(i=e._first;i&&i._start<=o;){if(i.data==="isPause"&&i._start>t)return i;i=i._next}else for(i=e._last;i&&i._start>=o;){if(i.data==="isPause"&&i._start<t)return i;i=i._prev}},Sa=function(e,t,o,i){var r=e._repeat,n=X(t)||0,s=e._tTime/e._tDur;return s&&!i&&(e._time*=n/e._dur),e._dur=n,e._tDur=r?r<0?1e10:X(n*(r+1)+e._rDelay*r):n,s>0&&!i&&Yo(e,e._tTime=e._tDur*s),e.parent&&Go(e),o||Xt(e.parent,e),e},pn=function(e){return e instanceof ye?Xt(e):Sa(e,e._dur)},Ff={_start:0,endTime:Xa,totalDuration:Xa},Ee=function a(e,t,o){var i=e.labels,r=e._recent||Ff,n=e.duration()>=$e?r.endTime(!1):e._dur,s,l,c;return ne(t)&&(isNaN(t)||t in i)?(l=t.charAt(0),c=t.substr(-1)==="%",s=t.indexOf("="),l==="<"||l===">"?(s>=0&&(t=t.replace(/=/,"")),(l==="<"?r._start:r.endTime(r._repeat>=0))+(parseFloat(t.substr(1))||0)*(c?(s<0?r:o).totalDuration()/100:1)):s<0?(t in i||(i[t]=n),i[t]):(l=parseFloat(t.charAt(s-1)+t.substr(s+1)),c&&o&&(l=l/100*(pe(o)?o[0]:o).totalDuration()),s>1?a(e,t.substr(0,s-1),o)+l:n+l)):t==null?n:+t},La=function(e,t,o){var i=yt(t[1]),r=(i?2:1)+(e<2?0:1),n=t[r],s,l;if(i&&(n.duration=t[1]),n.parent=o,e){for(s=n,l=o;l&&!("immediateRender"in s);)s=l.vars.defaults||{},l=_e(l.vars.inherit)&&l.parent;n.immediateRender=_e(s.immediateRender),e<2?n.runBackwards=1:n.startAt=t[r-1]}return new oe(t[0],n,t[r+1])},Nt=function(e,t){return e||e===0?t(e):t},so=function(e,t,o){return o<e?e:o>t?t:o},fe=function(e,t){return!ne(e)||!(t=Tf.exec(e))?"":t[1]},Nf=function(e,t,o){return Nt(o,function(i){return so(e,t,i)})},Pi=[].slice,ds=function(e,t){return e&&nt(e)&&"length"in e&&(!t&&!e.length||e.length-1 in e&&nt(e[0]))&&!e.nodeType&&e!==ot},Ef=function(e,t,o){return o===void 0&&(o=[]),e.forEach(function(i){var r;return ne(i)&&!t||ds(i,1)?(r=o).push.apply(r,je(i)):o.push(i)})||o},je=function(e,t,o){return H&&!t&&H.selector?H.selector(e):ne(e)&&!o&&(Mi||!ka())?Pi.call((t||ir).querySelectorAll(e),0):pe(e)?Ef(e,o):ds(e)?Pi.call(e,0):e?[e]:[]},Di=function(e){return e=je(e)[0]||Ha("Invalid scope")||{},function(t){var o=e.current||e.nativeElement||e;return je(t,o.querySelectorAll?o:o===e?Ha("Invalid scope")||ir.createElement("div"):e)}},ms=function(e){return e.sort(function(){return .5-Math.random()})},hs=function(e){if(ee(e))return e;var t=nt(e)?e:{each:e},o=Kt(t.ease),i=t.from||0,r=parseFloat(t.base)||0,n={},s=i>0&&i<1,l=isNaN(i)||s,c=t.axis,u=i,f=i;return ne(i)?u=f={center:.5,edges:.5,end:1}[i]||0:!s&&l&&(u=i[0],f=i[1]),function(d,m,h){var p=(h||t).length,g=n[p],_,y,v,b,x,C,w,k,S;if(!g){if(S=t.grid==="auto"?0:(t.grid||[1,$e])[1],!S){for(w=-$e;w<(w=h[S++].getBoundingClientRect().left)&&S<p;);S<p&&S--}for(g=n[p]=[],_=l?Math.min(S,p)*u-.5:i%S,y=S===$e?0:l?p*f/S-.5:i/S|0,w=0,k=$e,C=0;C<p;C++)v=C%S-_,b=y-(C/S|0),g[C]=x=c?Math.abs(c==="y"?b:v):Qn(v*v+b*b),x>w&&(w=x),x<k&&(k=x);i==="random"&&ms(g),g.max=w-k,g.min=k,g.v=p=(parseFloat(t.amount)||parseFloat(t.each)*(S>p?p-1:c?c==="y"?p/S:S:Math.max(S,p/S))||0)*(i==="edges"?-1:1),g.b=p<0?r-p:r,g.u=fe(t.amount||t.each)||0,o=o&&p<0?Zf(o):o}return p=(g[d]-g.min)/g.max||0,X(g.b+(o?o(p):p)*g.v)+g.u}},zi=function(e){var t=Math.pow(10,((e+"").split(".")[1]||"").length);return function(o){var i=X(Math.round(parseFloat(o)/e)*e*t);return(i-i%1)/t+(yt(o)?0:fe(o))}},gs=function(e,t){var o=pe(e),i,r;return!o&&nt(e)&&(i=o=e.radius||$e,e.values?(e=je(e.values),(r=!yt(e[0]))&&(i*=i)):e=zi(e.increment)),Nt(t,o?ee(e)?function(n){return r=e(n),Math.abs(r-n)<=i?r:n}:function(n){for(var s=parseFloat(r?n.x:n),l=parseFloat(r?n.y:0),c=$e,u=0,f=e.length,d,m;f--;)r?(d=e[f].x-s,m=e[f].y-l,d=d*d+m*m):d=Math.abs(e[f]-s),d<c&&(c=d,u=f);return u=!i||c<=i?e[u]:n,r||u===n||yt(n)?u:u+fe(n)}:zi(e))},vs=function(e,t,o,i){return Nt(pe(e)?!t:o===!0?!!(o=0):!i,function(){return pe(e)?e[~~(Math.random()*e.length)]:(o=o||1e-5)&&(i=o<1?Math.pow(10,(o+"").length-2):1)&&Math.floor(Math.round((e-o/2+Math.random()*(t-e+o*.99))/o)*o*i)/i})},Lf=function(){for(var e=arguments.length,t=new Array(e),o=0;o<e;o++)t[o]=arguments[o];return function(i){return t.reduce(function(r,n){return n(r)},i)}},$f=function(e,t){return function(o){return e(parseFloat(o))+(t||fe(o))}},jf=function(e,t,o){return _s(e,t,0,1,o)},ys=function(e,t,o){return Nt(o,function(i){return e[~~t(i)]})},Wf=function a(e,t,o){var i=t-e;return pe(e)?ys(e,a(0,e.length),t):Nt(o,function(r){return(i+(r-e)%i)%i+e})},Gf=function a(e,t,o){var i=t-e,r=i*2;return pe(e)?ys(e,a(0,e.length-1),t):Nt(o,function(n){return n=(r+(n-e)%r)%r||0,e+(n>i?r-n:n)})},Ka=function(e){return e.replace(kf,function(t){var o=t.indexOf("[")+1,i=t.substring(o||7,o?t.indexOf("]"):t.length-1).split(Cf);return vs(o?i:+i[0],o?0:+i[1],+i[2]||1e-5)})},_s=function(e,t,o,i,r){var n=t-e,s=i-o;return Nt(r,function(l){return o+((l-e)/n*s||0)})},Yf=function a(e,t,o,i){var r=isNaN(e+t)?0:function(m){return(1-m)*e+m*t};if(!r){var n=ne(e),s={},l,c,u,f,d;if(o===!0&&(i=1)&&(o=null),n)e={p:e},t={p:t};else if(pe(e)&&!pe(t)){for(u=[],f=e.length,d=f-2,c=1;c<f;c++)u.push(a(e[c-1],e[c]));f--,r=function(h){h*=f;var p=Math.min(d,~~h);return u[p](h-p)},o=t}else i||(e=ba(pe(e)?[]:{},e));if(!u){for(l in t)ur.call(s,e,l,"get",t[l]);r=function(h){return mr(h,s)||(n?e.p:e)}}}return Nt(o,r)},dn=function(e,t,o){var i=e.labels,r=$e,n,s,l;for(n in i)s=i[n]-t,s<0==!!o&&s&&r>(s=Math.abs(s))&&(l=n,r=s);return l},Ie=function(e,t,o){var i=e.vars,r=i[t],n=H,s=e._ctx,l,c,u;if(r)return l=i[t+"Params"],c=i.callbackScope||e,o&&At.length&&Io(),s&&(H=s),u=l?r.apply(c,l):r.call(c),H=n,u},Ra=function(e){return Vt(e),e.scrollTrigger&&e.scrollTrigger.kill(!!se),e.progress()<1&&Ie(e,"onInterrupt"),e},fa,xs=[],bs=function(e){if(e)if(e=!e.name&&e.default||e,or()||e.headless){var t=e.name,o=ee(e),i=t&&!o&&e.init?function(){this._props=[]}:e,r={init:Xa,render:mr,add:ur,kill:cp,modifier:lp,rawVars:0},n={targetTest:0,get:0,getSetter:dr,aliases:{},register:0};if(ka(),e!==i){if(Oe[t])return;Ve(i,Ve(Ao(e,r),n)),ba(i.prototype,ba(r,Ao(e,n))),Oe[i.prop=t]=i,e.targetTest&&(xo.push(i),nr[t]=1),t=(t==="css"?"CSS":t.charAt(0).toUpperCase()+t.substr(1))+"Plugin"}os(t,i),e.register&&e.register(Se,i,be)}else xs.push(e)},j=255,Pa={aqua:[0,j,j],lime:[0,j,0],silver:[192,192,192],black:[0,0,0],maroon:[128,0,0],teal:[0,128,128],blue:[0,0,j],navy:[0,0,128],white:[j,j,j],olive:[128,128,0],yellow:[j,j,0],orange:[j,165,0],gray:[128,128,128],purple:[128,0,128],green:[0,128,0],red:[j,0,0],pink:[j,192,203],cyan:[0,j,j],transparent:[j,j,j,0]},fi=function(e,t,o){return e+=e<0?1:e>1?-1:0,(e*6<1?t+(o-t)*e*6:e<.5?o:e*3<2?t+(o-t)*(2/3-e)*6:t)*j+.5|0},ws=function(e,t,o){var i=e?yt(e)?[e>>16,e>>8&j,e&j]:0:Pa.black,r,n,s,l,c,u,f,d,m,h;if(!i){if(e.substr(-1)===","&&(e=e.substr(0,e.length-1)),Pa[e])i=Pa[e];else if(e.charAt(0)==="#"){if(e.length<6&&(r=e.charAt(1),n=e.charAt(2),s=e.charAt(3),e="#"+r+r+n+n+s+s+(e.length===5?e.charAt(4)+e.charAt(4):"")),e.length===9)return i=parseInt(e.substr(1,6),16),[i>>16,i>>8&j,i&j,parseInt(e.substr(7),16)/255];e=parseInt(e.substr(1),16),i=[e>>16,e>>8&j,e&j]}else if(e.substr(0,3)==="hsl"){if(i=h=e.match(ln),!t)l=+i[0]%360/360,c=+i[1]/100,u=+i[2]/100,n=u<=.5?u*(c+1):u+c-u*c,r=u*2-n,i.length>3&&(i[3]*=1),i[0]=fi(l+1/3,r,n),i[1]=fi(l,r,n),i[2]=fi(l-1/3,r,n);else if(~e.indexOf("="))return i=e.match(Zn),o&&i.length<4&&(i[3]=1),i}else i=e.match(ln)||Pa.transparent;i=i.map(Number)}return t&&!h&&(r=i[0]/j,n=i[1]/j,s=i[2]/j,f=Math.max(r,n,s),d=Math.min(r,n,s),u=(f+d)/2,f===d?l=c=0:(m=f-d,c=u>.5?m/(2-f-d):m/(f+d),l=f===r?(n-s)/m+(n<s?6:0):f===n?(s-r)/m+2:(r-n)/m+4,l*=60),i[0]=~~(l+.5),i[1]=~~(c*100+.5),i[2]=~~(u*100+.5)),o&&i.length<4&&(i[3]=1),i},Ss=function(e){var t=[],o=[],i=-1;return e.split(Mt).forEach(function(r){var n=r.match(ua)||[];t.push.apply(t,n),o.push(i+=n.length+1)}),t.c=o,t},mn=function(e,t,o){var i="",r=(e+i).match(Mt),n=t?"hsla(":"rgba(",s=0,l,c,u,f;if(!r)return e;if(r=r.map(function(d){return(d=ws(d,t,1))&&n+(t?d[0]+","+d[1]+"%,"+d[2]+"%,"+d[3]:d.join(","))+")"}),o&&(u=Ss(e),l=o.c,l.join(i)!==u.c.join(i)))for(c=e.replace(Mt,"1").split(ua),f=c.length-1;s<f;s++)i+=c[s]+(~l.indexOf(s)?r.shift()||n+"0,0,0,0)":(u.length?u:r.length?r:o).shift());if(!c)for(c=e.split(Mt),f=c.length-1;s<f;s++)i+=c[s]+r[s];return i+c[f]},Mt=function(){var a="(?:\\b(?:(?:rgb|rgba|hsl|hsla)\\(.+?\\))|\\B#(?:[0-9a-f]{3,4}){1,2}\\b",e;for(e in Pa)a+="|"+e+"\\b";return new RegExp(a+")","gi")}(),qf=/hsl[a]?\(/,ks=function(e){var t=e.join(" "),o;if(Mt.lastIndex=0,Mt.test(t))return o=qf.test(t),e[1]=mn(e[1],o),e[0]=mn(e[0],o,Ss(e[1])),!0},Qa,Te=function(){var a=Date.now,e=500,t=33,o=a(),i=o,r=1e3/240,n=r,s=[],l,c,u,f,d,m,h=function p(g){var _=a()-i,y=g===!0,v,b,x,C;if((_>e||_<0)&&(o+=_-t),i+=_,x=i-o,v=x-n,(v>0||y)&&(C=++f.frame,d=x-f.time*1e3,f.time=x=x/1e3,n+=v+(v>=r?4:r-v),b=1),y||(l=c(p)),b)for(m=0;m<s.length;m++)s[m](x,d,C,g)};return f={time:0,frame:0,tick:function(){h(!0)},deltaRatio:function(g){return d/(1e3/(g||60))},wake:function(){ts&&(!Mi&&or()&&(ot=Mi=window,ir=ot.document||{},Be.gsap=Se,(ot.gsapVersions||(ot.gsapVersions=[])).push(Se.version),as(Uo||ot.GreenSockGlobals||!ot.gsap&&ot||{}),xs.forEach(bs)),u=typeof requestAnimationFrame<"u"&&requestAnimationFrame,l&&f.sleep(),c=u||function(g){return setTimeout(g,n-f.time*1e3+1|0)},Qa=1,h(2))},sleep:function(){(u?cancelAnimationFrame:clearTimeout)(l),Qa=0,c=Xa},lagSmoothing:function(g,_){e=g||1/0,t=Math.min(_||33,e)},fps:function(g){r=1e3/(g||240),n=f.time*1e3+r},add:function(g,_,y){var v=_?function(b,x,C,w){g(b,x,C,w),f.remove(v)}:g;return f.remove(g),s[y?"unshift":"push"](v),ka(),v},remove:function(g,_){~(_=s.indexOf(g))&&s.splice(_,1)&&m>=_&&m--},_listeners:s},f}(),ka=function(){return!Qa&&Te.wake()},z={},Hf=/^[\d.\-M][\d.\-,\s]/,Xf=/["']/g,Kf=function(e){for(var t={},o=e.substr(1,e.length-3).split(":"),i=o[0],r=1,n=o.length,s,l,c;r<n;r++)l=o[r],s=r!==n-1?l.lastIndexOf(","):l.length,c=l.substr(0,s),t[i]=isNaN(c)?c.replace(Xf,"").trim():+c,i=l.substr(s+1).trim();return t},Qf=function(e){var t=e.indexOf("(")+1,o=e.indexOf(")"),i=e.indexOf("(",t);return e.substring(t,~i&&i<o?e.indexOf(")",o+1):o)},Jf=function(e){var t=(e+"").split("("),o=z[t[0]];return o&&t.length>1&&o.config?o.config.apply(null,~e.indexOf("{")?[Kf(t[1])]:Qf(e).split(",").map(ss)):z._CE&&Hf.test(e)?z._CE("",e):o},Zf=function(e){return function(t){return 1-e(1-t)}},Kt=function(e,t){return e&&(ee(e)?e:z[e]||Jf(e))||t},aa=function(e,t,o,i){o===void 0&&(o=function(l){return 1-t(1-l)}),i===void 0&&(i=function(l){return l<.5?t(l*2)/2:1-t((1-l)*2)/2});var r={easeIn:t,easeOut:o,easeInOut:i},n;return xe(e,function(s){z[s]=Be[s]=r,z[n=s.toLowerCase()]=o;for(var l in r)z[n+(l==="easeIn"?".in":l==="easeOut"?".out":".inOut")]=z[s+"."+l]=r[l]}),r},Cs=function(e){return function(t){return t<.5?(1-e(1-t*2))/2:.5+e((t-.5)*2)/2}},pi=function a(e,t,o){var i=t>=1?t:1,r=(o||(e?.3:.45))/(t<1?t:1),n=r/Ai*(Math.asin(1/i)||0),s=function(u){return u===1?1:i*Math.pow(2,-10*u)*Sf((u-n)*r)+1},l=e==="out"?s:e==="in"?function(c){return 1-s(1-c)}:Cs(s);return r=Ai/r,l.config=function(c,u){return a(e,c,u)},l},di=function a(e,t){t===void 0&&(t=1.70158);var o=function(n){return n?--n*n*((t+1)*n+t)+1:0},i=e==="out"?o:e==="in"?function(r){return 1-o(1-r)}:Cs(o);return i.config=function(r){return a(e,r)},i};xe("Linear,Quad,Cubic,Quart,Quint,Strong",function(a,e){var t=e<5?e+1:e;aa(a+",Power"+(t-1),e?function(o){return Math.pow(o,t)}:function(o){return o},function(o){return 1-Math.pow(1-o,t)},function(o){return o<.5?Math.pow(o*2,t)/2:1-Math.pow((1-o)*2,t)/2})});z.Linear.easeNone=z.none=z.Linear.easeIn;aa("Elastic",pi("in"),pi("out"),pi());(function(a,e){var t=1/e,o=2*t,i=2.5*t,r=function(s){return s<t?a*s*s:s<o?a*Math.pow(s-1.5/e,2)+.75:s<i?a*(s-=2.25/e)*s+.9375:a*Math.pow(s-2.625/e,2)+.984375};aa("Bounce",function(n){return 1-r(1-n)},r)})(7.5625,2.75);aa("Expo",function(a){return Math.pow(2,10*(a-1))*a+a*a*a*a*a*a*(1-a)});aa("Circ",function(a){return-(Qn(1-a*a)-1)});aa("Sine",function(a){return a===1?1:-wf(a*xf)+1});aa("Back",di("in"),di("out"),di());z.SteppedEase=z.steps=Be.SteppedEase={config:function(e,t){e===void 0&&(e=1);var o=1/e,i=e+(t?0:1),r=t?1:0,n=1-W;return function(s){return((i*so(0,n,s)|0)+r)*o}}};qa.ease=z["quad.out"];xe("onComplete,onUpdate,onStart,onRepeat,onReverseComplete,onInterrupt",function(a){return sr+=a+","+a+"Params,"});var Os=function(e,t){this.id=bf++,e._gsap=this,this.target=e,this.harness=t,this.get=t?t.get:rs,this.set=t?t.getSetter:dr},Ja=function(){function a(t){this.vars=t,this._delay=+t.delay||0,(this._repeat=t.repeat===1/0?-2:t.repeat||0)&&(this._rDelay=t.repeatDelay||0,this._yoyo=!!t.yoyo||!!t.yoyoEase),this._ts=1,Sa(this,+t.duration,1,1),this.data=t.data,H&&(this._ctx=H,H.data.push(this)),Qa||Te.wake()}var e=a.prototype;return e.delay=function(o){return o||o===0?(this.parent&&this.parent.smoothChildTiming&&this.startTime(this._start+o-this._delay),this._delay=o,this):this._delay},e.duration=function(o){return arguments.length?this.totalDuration(this._repeat>0?o+(o+this._rDelay)*this._repeat:o):this.totalDuration()&&this._dur},e.totalDuration=function(o){return arguments.length?(this._dirty=0,Sa(this,this._repeat<0?o:(o-this._repeat*this._rDelay)/(this._repeat+1))):this._tDur},e.totalTime=function(o,i){if(ka(),!arguments.length)return this._tTime;var r=this._dp;if(r&&r.smoothChildTiming&&this._ts){for(Yo(this,o),!r._dp||r.parent||us(r,this);r&&r.parent;)r.parent._time!==r._start+(r._ts>=0?r._tTime/r._ts:(r.totalDuration()-r._tTime)/-r._ts)&&r.totalTime(r._tTime,!0),r=r.parent;!this.parent&&this._dp.autoRemoveChildren&&(this._ts>0&&o<this._tDur||this._ts<0&&o>0||!this._tDur&&!o)&&it(this._dp,this,this._start-this._delay)}return(this._tTime!==o||!this._dur&&!i||this._initted&&Math.abs(this._zTime)===W||!this._initted&&this._dur&&o||!o&&!this._initted&&(this.add||this._ptLookup))&&(this._ts||(this._pTime=o),ns(this,o,i)),this},e.time=function(o,i){return arguments.length?this.totalTime(Math.min(this.totalDuration(),o+fn(this))%(this._dur+this._rDelay)||(o?this._dur:0),i):this._time},e.totalProgress=function(o,i){return arguments.length?this.totalTime(this.totalDuration()*o,i):this.totalDuration()?Math.min(1,this._tTime/this._tDur):this.rawTime()>=0&&this._initted?1:0},e.progress=function(o,i){return arguments.length?this.totalTime(this.duration()*(this._yoyo&&!(this.iteration()&1)?1-o:o)+fn(this),i):this.duration()?Math.min(1,this._time/this._dur):this.rawTime()>0?1:0},e.iteration=function(o,i){var r=this.duration()+this._rDelay;return arguments.length?this.totalTime(this._time+(o-1)*r,i):this._repeat?wa(this._tTime,r)+1:1},e.timeScale=function(o,i){if(!arguments.length)return this._rts===-W?0:this._rts;if(this._rts===o)return this;var r=this.parent&&this._ts?Mo(this.parent._time,this):this._tTime;return this._rts=+o||0,this._ts=this._ps||o===-W?0:this._rts,this.totalTime(so(-Math.abs(this._delay),this.totalDuration(),r),i!==!1),Go(this),Vf(this)},e.paused=function(o){return arguments.length?(this._ps!==o&&(this._ps=o,o?(this._pTime=this._tTime||Math.max(-this._delay,this.rawTime()),this._ts=this._act=0):(ka(),this._ts=this._rts,this.totalTime(this.parent&&!this.parent.smoothChildTiming?this.rawTime():this._tTime||this._pTime,this.progress()===1&&Math.abs(this._zTime)!==W&&(this._tTime-=W)))),this):this._ps},e.startTime=function(o){if(arguments.length){this._start=X(o);var i=this.parent||this._dp;return i&&(i._sort||!this.parent)&&it(i,this,this._start-this._delay),this}return this._start},e.endTime=function(o){return this._start+(_e(o)?this.totalDuration():this.duration())/Math.abs(this._ts||1)},e.rawTime=function(o){var i=this.parent||this._dp;return i?o&&(!this._ts||this._repeat&&this._time&&this.totalProgress()<1)?this._tTime%(this._dur+this._rDelay):this._ts?Mo(i.rawTime(o),this):this._tTime:this._tTime},e.revert=function(o){o===void 0&&(o=If);var i=se;return se=o,cr(this)&&(this.timeline&&this.timeline.revert(o),this.totalTime(-.01,o.suppressEvents)),this.data!=="nested"&&o.kill!==!1&&this.kill(),se=i,this},e.globalTime=function(o){for(var i=this,r=arguments.length?o:i.rawTime();i;)r=i._start+r/(Math.abs(i._ts)||1),i=i._dp;return!this.parent&&this._sat?this._sat.globalTime(o):r},e.repeat=function(o){return arguments.length?(this._repeat=o===1/0?-2:o,pn(this)):this._repeat===-2?1/0:this._repeat},e.repeatDelay=function(o){if(arguments.length){var i=this._time;return this._rDelay=o,pn(this),i?this.time(i):this}return this._rDelay},e.yoyo=function(o){return arguments.length?(this._yoyo=o,this):this._yoyo},e.seek=function(o,i){return this.totalTime(Ee(this,o),_e(i))},e.restart=function(o,i){return this.play().totalTime(o?-this._delay:0,_e(i)),this._dur||(this._zTime=-W),this},e.play=function(o,i){return o!=null&&this.seek(o,i),this.reversed(!1).paused(!1)},e.reverse=function(o,i){return o!=null&&this.seek(o||this.totalDuration(),i),this.reversed(!0).paused(!1)},e.pause=function(o,i){return o!=null&&this.seek(o,i),this.paused(!0)},e.resume=function(){return this.paused(!1)},e.reversed=function(o){return arguments.length?(!!o!==this.reversed()&&this.timeScale(-this._rts||(o?-W:0)),this):this._rts<0},e.invalidate=function(){return this._initted=this._act=0,this._zTime=-W,this},e.isActive=function(){var o=this.parent||this._dp,i=this._start,r;return!!(!o||this._ts&&this._initted&&o.isActive()&&(r=o.rawTime(!0))>=i&&r<this.endTime(!0)-W)},e.eventCallback=function(o,i,r){var n=this.vars;return arguments.length>1?(i?(n[o]=i,r&&(n[o+"Params"]=r),o==="onUpdate"&&(this._onUpdate=i)):delete n[o],this):n[o]},e.then=function(o){var i=this,r=i._prom;return new Promise(function(n){var s=ee(o)?o:ls,l=function(){var u=i.then;i.then=null,r&&r(),ee(s)&&(s=s(i))&&(s.then||s===i)&&(i.then=u),n(s),i.then=u};i._initted&&i.totalProgress()===1&&i._ts>=0||!i._tTime&&i._ts<0?l():i._prom=l})},e.kill=function(){Ra(this)},a}();Ve(Ja.prototype,{_time:0,_start:0,_end:0,_tTime:0,_tDur:0,_dirty:0,_repeat:0,_yoyo:!1,parent:null,_initted:!1,_rDelay:0,_ts:1,_dp:0,ratio:0,_zTime:-W,_prom:0,_ps:!1,_rts:1});var ye=function(a){Kn(e,a);function e(o,i){var r;return o===void 0&&(o={}),r=a.call(this,o)||this,r.labels={},r.smoothChildTiming=!!o.smoothChildTiming,r.autoRemoveChildren=!!o.autoRemoveChildren,r._sort=_e(o.sortChildren),K&&it(o.parent||K,pt(r),i),o.reversed&&r.reverse(),o.paused&&r.paused(!0),o.scrollTrigger&&fs(pt(r),o.scrollTrigger),r}var t=e.prototype;return t.to=function(i,r,n){return La(0,arguments,this),this},t.from=function(i,r,n){return La(1,arguments,this),this},t.fromTo=function(i,r,n,s){return La(2,arguments,this),this},t.set=function(i,r,n){return r.duration=0,r.parent=this,Ea(r).repeatDelay||(r.repeat=0),r.immediateRender=!!r.immediateRender,new oe(i,r,Ee(this,n),1),this},t.call=function(i,r,n){return it(this,oe.delayedCall(0,i,r),n)},t.staggerTo=function(i,r,n,s,l,c,u){return n.duration=r,n.stagger=n.stagger||s,n.onComplete=c,n.onCompleteParams=u,n.parent=this,new oe(i,n,Ee(this,l)),this},t.staggerFrom=function(i,r,n,s,l,c,u){return n.runBackwards=1,Ea(n).immediateRender=_e(n.immediateRender),this.staggerTo(i,r,n,s,l,c,u)},t.staggerFromTo=function(i,r,n,s,l,c,u,f){return s.startAt=n,Ea(s).immediateRender=_e(s.immediateRender),this.staggerTo(i,r,s,l,c,u,f)},t.render=function(i,r,n){var s=this._time,l=this._dirty?this.totalDuration():this._tDur,c=this._dur,u=i<=0?0:X(i),f=this._zTime<0!=i<0&&(this._initted||!c),d,m,h,p,g,_,y,v,b,x,C,w;if(this!==K&&u>l&&i>=0&&(u=l),u!==this._tTime||n||f){if(s!==this._time&&c&&(u+=this._time-s,i+=this._time-s),d=u,b=this._start,v=this._ts,_=!v,f&&(c||(s=this._zTime),(i||!r)&&(this._zTime=i)),this._repeat){if(C=this._yoyo,g=c+this._rDelay,this._repeat<-1&&i<0)return this.totalTime(g*100+i,r,n);if(d=X(u%g),u===l?(p=this._repeat,d=c):(x=X(u/g),p=~~x,p&&p===x&&(d=c,p--),d>c&&(d=c)),x=wa(this._tTime,g),!s&&this._tTime&&x!==p&&this._tTime-x*g-this._dur<=0&&(x=p),C&&p&1&&(d=c-d,w=1),p!==x&&!this._lock){var k=C&&x&1,S=k===(C&&p&1);if(p<x&&(k=!k),s=k?0:u%c?c:u,this._lock=1,this.render(s||(w?0:X(p*g)),r,!c)._lock=0,this._tTime=u,!r&&this.parent&&Ie(this,"onRepeat"),this.vars.repeatRefresh&&!w&&(this.invalidate()._lock=1,x=p),s&&s!==this._time||_!==!this._ts||this.vars.onRepeat&&!this.parent&&!this._act)return this;if(c=this._dur,l=this._tDur,S&&(this._lock=2,s=k?c:-1e-4,this.render(s,!0),this.vars.repeatRefresh&&!w&&this.invalidate()),this._lock=0,!this._ts&&!_)return this}}if(this._hasPause&&!this._forcing&&this._lock<2&&(y=zf(this,X(s),X(d)),y&&(u-=d-(d=y._start))),this._tTime=u,this._time=d,this._act=!!v,this._initted||(this._onUpdate=this.vars.onUpdate,this._initted=1,this._zTime=i,s=0),!s&&u&&c&&!r&&!x&&(Ie(this,"onStart"),this._tTime!==u))return this;if(d>=s&&i>=0)for(m=this._first;m;){if(h=m._next,(m._act||d>=m._start)&&m._ts&&y!==m){if(m.parent!==this)return this.render(i,r,n);if(m.render(m._ts>0?(d-m._start)*m._ts:(m._dirty?m.totalDuration():m._tDur)+(d-m._start)*m._ts,r,n),d!==this._time||!this._ts&&!_){y=0,h&&(u+=this._zTime=-W);break}}m=h}else{m=this._last;for(var T=i<0?i:d;m;){if(h=m._prev,(m._act||T<=m._end)&&m._ts&&y!==m){if(m.parent!==this)return this.render(i,r,n);if(m.render(m._ts>0?(T-m._start)*m._ts:(m._dirty?m.totalDuration():m._tDur)+(T-m._start)*m._ts,r,n||se&&cr(m)),d!==this._time||!this._ts&&!_){y=0,h&&(u+=this._zTime=T?-W:W);break}}m=h}}if(y&&!r&&(this.pause(),y.render(d>=s?0:-W)._zTime=d>=s?1:-1,this._ts))return this._start=b,Go(this),this.render(i,r,n);this._onUpdate&&!r&&Ie(this,"onUpdate",!0),(u===l&&this._tTime>=this.totalDuration()||!u&&s)&&(b===this._start||Math.abs(v)!==Math.abs(this._ts))&&(this._lock||((i||!c)&&(u===l&&this._ts>0||!u&&this._ts<0)&&Vt(this,1),!r&&!(i<0&&!s)&&(u||s||!l)&&(Ie(this,u===l&&i>=0?"onComplete":"onReverseComplete",!0),this._prom&&!(u<l&&this.timeScale()>0)&&this._prom())))}return this},t.add=function(i,r){var n=this;if(yt(r)||(r=Ee(this,r,i)),!(i instanceof Ja)){if(pe(i))return i.forEach(function(s){return n.add(s,r)}),this;if(ne(i))return this.addLabel(i,r);if(ee(i))i=oe.delayedCall(0,i);else return this}return this!==i?it(this,i,r):this},t.getChildren=function(i,r,n,s){i===void 0&&(i=!0),r===void 0&&(r=!0),n===void 0&&(n=!0),s===void 0&&(s=-$e);for(var l=[],c=this._first;c;)c._start>=s&&(c instanceof oe?r&&l.push(c):(n&&l.push(c),i&&l.push.apply(l,c.getChildren(!0,r,n)))),c=c._next;return l},t.getById=function(i){for(var r=this.getChildren(1,1,1),n=r.length;n--;)if(r[n].vars.id===i)return r[n]},t.remove=function(i){return ne(i)?this.removeLabel(i):ee(i)?this.killTweensOf(i):(i.parent===this&&Wo(this,i),i===this._recent&&(this._recent=this._last),Xt(this))},t.totalTime=function(i,r){return arguments.length?(this._forcing=1,!this._dp&&this._ts&&(this._start=X(Te.time-(this._ts>0?i/this._ts:(this.totalDuration()-i)/-this._ts))),a.prototype.totalTime.call(this,i,r),this._forcing=0,this):this._tTime},t.addLabel=function(i,r){return this.labels[i]=Ee(this,r),this},t.removeLabel=function(i){return delete this.labels[i],this},t.addPause=function(i,r,n){var s=oe.delayedCall(0,r||Xa,n);return s.data="isPause",this._hasPause=1,it(this,s,Ee(this,i))},t.removePause=function(i){var r=this._first;for(i=Ee(this,i);r;)r._start===i&&r.data==="isPause"&&Vt(r),r=r._next},t.killTweensOf=function(i,r,n){for(var s=this.getTweensOf(i,n),l=s.length;l--;)Tt!==s[l]&&s[l].kill(i,r);return this},t.getTweensOf=function(i,r){for(var n=[],s=je(i),l=this._first,c=yt(r),u;l;)l instanceof oe?Af(l._targets,s)&&(c?(!Tt||l._initted&&l._ts)&&l.globalTime(0)<=r&&l.globalTime(l.totalDuration())>r:!r||l.isActive())&&n.push(l):(u=l.getTweensOf(s,r)).length&&n.push.apply(n,u),l=l._next;return n},t.tweenTo=function(i,r){r=r||{};var n=this,s=Ee(n,i),l=r,c=l.startAt,u=l.onStart,f=l.onStartParams,d=l.immediateRender,m,h=oe.to(n,Ve({ease:r.ease||"none",lazy:!1,immediateRender:!1,time:s,overwrite:"auto",duration:r.duration||Math.abs((s-(c&&"time"in c?c.time:n._time))/n.timeScale())||W,onStart:function(){if(n.pause(),!m){var g=r.duration||Math.abs((s-(c&&"time"in c?c.time:n._time))/n.timeScale());h._dur!==g&&Sa(h,g,0,1).render(h._time,!0,!0),m=1}u&&u.apply(h,f||[])}},r));return d?h.render(0):h},t.tweenFromTo=function(i,r,n){return this.tweenTo(r,Ve({startAt:{time:Ee(this,i)}},n))},t.recent=function(){return this._recent},t.nextLabel=function(i){return i===void 0&&(i=this._time),dn(this,Ee(this,i))},t.previousLabel=function(i){return i===void 0&&(i=this._time),dn(this,Ee(this,i),1)},t.currentLabel=function(i){return arguments.length?this.seek(i,!0):this.previousLabel(this._time+W)},t.shiftChildren=function(i,r,n){n===void 0&&(n=0);var s=this._first,l=this.labels,c;for(i=X(i);s;)s._start>=n&&(s._start+=i,s._end+=i),s=s._next;if(r)for(c in l)l[c]>=n&&(l[c]+=i);return Xt(this)},t.invalidate=function(i){var r=this._first;for(this._lock=0;r;)r.invalidate(i),r=r._next;return a.prototype.invalidate.call(this,i)},t.clear=function(i){i===void 0&&(i=!0);for(var r=this._first,n;r;)n=r._next,this.remove(r),r=n;return this._dp&&(this._time=this._tTime=this._pTime=0),i&&(this.labels={}),Xt(this)},t.totalDuration=function(i){var r=0,n=this,s=n._last,l=$e,c,u,f;if(arguments.length)return n.timeScale((n._repeat<0?n.duration():n.totalDuration())/(n.reversed()?-i:i));if(n._dirty){for(f=n.parent;s;)c=s._prev,s._dirty&&s.totalDuration(),u=s._start,u>l&&n._sort&&s._ts&&!n._lock?(n._lock=1,it(n,s,u-s._delay,1)._lock=0):l=u,u<0&&s._ts&&(r-=u,(!f&&!n._dp||f&&f.smoothChildTiming)&&(n._start+=X(u/n._ts),n._time-=u,n._tTime-=u),n.shiftChildren(-u,!1,-1/0),l=0),s._end>r&&s._ts&&(r=s._end),s=c;Sa(n,n===K&&n._time>r?n._time:r,1,1),n._dirty=0}return n._tDur},e.updateRoot=function(i){if(K._ts&&(ns(K,Mo(i,K)),is=Te.frame),Te.frame>=cn){cn+=Me.autoSleep||120;var r=K._first;if((!r||!r._ts)&&Me.autoSleep&&Te._listeners.length<2){for(;r&&!r._ts;)r=r._next;r||Te.sleep()}}},e}(Ja);Ve(ye.prototype,{_lock:0,_hasPause:0,_forcing:0});var ep=function(e,t,o,i,r,n,s){var l=new be(this._pt,e,t,0,1,Bs,null,r),c=0,u=0,f,d,m,h,p,g,_,y;for(l.b=o,l.e=i,o+="",i+="",(_=~i.indexOf("random("))&&(i=Ka(i)),n&&(y=[o,i],n(y,e,t),o=y[0],i=y[1]),d=o.match(ci)||[];f=ci.exec(i);)h=f[0],p=i.substring(c,f.index),m?m=(m+1)%5:p.substr(-5)==="rgba("&&(m=1),h!==d[u++]&&(g=parseFloat(d[u-1])||0,l._pt={_next:l._pt,p:p||u===1?p:",",s:g,c:h.charAt(1)==="="?ga(g,h)-g:parseFloat(h)-g,m:m&&m<4?Math.round:0},c=ci.lastIndex);return l.c=c<i.length?i.substring(c,i.length):"",l.fp=s,(es.test(i)||_)&&(l.e=0),this._pt=l,l},ur=function(e,t,o,i,r,n,s,l,c,u){ee(i)&&(i=i(r||0,e,n));var f=e[t],d=o!=="get"?o:ee(f)?c?e[t.indexOf("set")||!ee(e["get"+t.substr(3)])?t:"get"+t.substr(3)](c):e[t]():f,m=ee(f)?c?rp:As:pr,h;if(ne(i)&&(~i.indexOf("random(")&&(i=Ka(i)),i.charAt(1)==="="&&(h=ga(d,i)+(fe(d)||0),(h||h===0)&&(i=h))),!u||d!==i||Fi)return!isNaN(d*i)&&i!==""?(h=new be(this._pt,e,t,+d||0,i-(d||0),typeof f=="boolean"?sp:Ms,0,m),c&&(h.fp=c),s&&h.modifier(s,this,e),this._pt=h):(!f&&!(t in e)&&rr(t,i),ep.call(this,e,t,d,i,m,l||Me.stringFilter,c))},tp=function(e,t,o,i,r){if(ee(e)&&(e=$a(e,r,t,o,i)),!nt(e)||e.style&&e.nodeType||pe(e)||Jn(e))return ne(e)?$a(e,r,t,o,i):e;var n={},s;for(s in e)n[s]=$a(e[s],r,t,o,i);return n},Ts=function(e,t,o,i,r,n){var s,l,c,u;if(Oe[e]&&(s=new Oe[e]).init(r,s.rawVars?t[e]:tp(t[e],i,r,n,o),o,i,n)!==!1&&(o._pt=l=new be(o._pt,r,e,0,1,s.render,s,0,s.priority),o!==fa))for(c=o._ptLookup[o._targets.indexOf(r)],u=s._props.length;u--;)c[s._props[u]]=l;return s},Tt,Fi,fr=function a(e,t,o){var i=e.vars,r=i.ease,n=i.startAt,s=i.immediateRender,l=i.lazy,c=i.onUpdate,u=i.runBackwards,f=i.yoyoEase,d=i.keyframes,m=i.autoRevert,h=e._dur,p=e._startAt,g=e._targets,_=e.parent,y=_&&_.data==="nested"?_.vars.targets:g,v=e._overwrite==="auto"&&!tr,b=e.timeline,x=i.easeReverse||f,C,w,k,S,T,A,M,V,N,F,D,$,ae;if(b&&(!d||!r)&&(r="none"),e._ease=Kt(r,qa.ease),e._rEase=x&&(Kt(x)||e._ease),e._from=!b&&!!i.runBackwards,e._from&&(e.ratio=1),!b||d&&!i.stagger){if(V=g[0]?Ht(g[0]).harness:0,$=V&&i[V.prop],C=Ao(i,nr),p&&(p._zTime<0&&p.progress(1),t<0&&u&&s&&!m?p.render(-1,!0):p.revert(u&&h?_o:Uf),p._lazy=0),n){if(Vt(e._startAt=oe.set(g,Ve({data:"isStart",overwrite:!1,parent:_,immediateRender:!0,lazy:!p&&_e(l),startAt:null,delay:0,onUpdate:c&&function(){return Ie(e,"onUpdate")},stagger:0},n))),e._startAt._dp=0,e._startAt._sat=e,t<0&&(se||!s&&!m)&&e._startAt.revert(_o),s&&h&&t<=0&&o<=0){t&&(e._zTime=t);return}}else if(u&&h&&!p){if(t&&(s=!1),k=Ve({overwrite:!1,data:"isFromStart",lazy:s&&!p&&_e(l),immediateRender:s,stagger:0,parent:_},C),$&&(k[V.prop]=$),Vt(e._startAt=oe.set(g,k)),e._startAt._dp=0,e._startAt._sat=e,t<0&&(se?e._startAt.revert(_o):e._startAt.render(-1,!0)),e._zTime=t,!s)a(e._startAt,W,W);else if(!t)return}for(e._pt=e._ptCache=0,l=h&&_e(l)||l&&!h,w=0;w<g.length;w++){if(T=g[w],M=T._gsap||lr(g)[w]._gsap,e._ptLookup[w]=F={},Bi[M.id]&&At.length&&Io(),D=y===g?w:y.indexOf(T),V&&(N=new V).init(T,$||C,e,D,y)!==!1&&(e._pt=S=new be(e._pt,T,N.name,0,1,N.render,N,0,N.priority),N._props.forEach(function(Re){F[Re]=S}),N.priority&&(A=1)),!V||$)for(k in C)Oe[k]&&(N=Ts(k,C,e,D,T,y))?N.priority&&(A=1):F[k]=S=ur.call(e,T,k,"get",C[k],D,y,0,i.stringFilter);e._op&&e._op[w]&&e.kill(T,e._op[w]),v&&e._pt&&(Tt=e,K.killTweensOf(T,F,e.globalTime(t)),ae=!e.parent,Tt=0),e._pt&&l&&(Bi[M.id]=1)}A&&Vs(e),e._onInit&&e._onInit(e)}e._onUpdate=c,e._initted=(!e._op||e._pt)&&!ae,d&&t<=0&&b.render($e,!0,!0)},ap=function(e,t,o,i,r,n,s,l){var c=(e._pt&&e._ptCache||(e._ptCache={}))[t],u,f,d,m;if(!c)for(c=e._ptCache[t]=[],d=e._ptLookup,m=e._targets.length;m--;){if(u=d[m][t],u&&u.d&&u.d._pt)for(u=u.d._pt;u&&u.p!==t&&u.fp!==t;)u=u._next;if(!u)return Fi=1,e.vars[t]="+=0",fr(e,s),Fi=0,l?Ha(t+" not eligible for reset. Try splitting into individual properties"):1;c.push(u)}for(m=c.length;m--;)f=c[m],u=f._pt||f,u.s=(i||i===0)&&!r?i:u.s+(i||0)+n*u.c,u.c=o-u.s,f.e&&(f.e=te(o)+fe(f.e)),f.b&&(f.b=u.s+fe(f.b))},op=function(e,t){var o=e[0]?Ht(e[0]).harness:0,i=o&&o.aliases,r,n,s,l;if(!i)return t;r=ba({},t);for(n in i)if(n in r)for(l=i[n].split(","),s=l.length;s--;)r[l[s]]=r[n];return r},ip=function(e,t,o,i){var r=t.ease||i||"power1.inOut",n,s;if(pe(t))s=o[e]||(o[e]=[]),t.forEach(function(l,c){return s.push({t:c/(t.length-1)*100,v:l,e:r})});else for(n in t)s=o[n]||(o[n]=[]),n==="ease"||s.push({t:parseFloat(e),v:t[n],e:r})},$a=function(e,t,o,i,r){return ee(e)?e.call(t,o,i,r):ne(e)&&~e.indexOf("random(")?Ka(e):e},Us=sr+"repeat,repeatDelay,yoyo,repeatRefresh,yoyoEase,easeReverse,autoRevert",Is={};xe(Us+",id,stagger,delay,duration,paused,scrollTrigger",function(a){return Is[a]=1});var oe=function(a){Kn(e,a);function e(o,i,r,n){var s;typeof i=="number"&&(r.duration=i,i=r,r=null),s=a.call(this,n?i:Ea(i))||this;var l=s.vars,c=l.duration,u=l.delay,f=l.immediateRender,d=l.stagger,m=l.overwrite,h=l.keyframes,p=l.defaults,g=l.scrollTrigger,_=i.parent||K,y=(pe(o)||Jn(o)?yt(o[0]):"length"in i)?[o]:je(o),v,b,x,C,w,k,S,T;if(s._targets=y.length?lr(y):Ha("GSAP target "+o+" not found. https://gsap.com",!Me.nullTargetWarn)||[],s._ptLookup=[],s._overwrite=m,h||d||mo(c)||mo(u)){i=s.vars;var A=i.easeReverse||i.yoyoEase;if(v=s.timeline=new ye({data:"nested",defaults:p||{},targets:_&&_.data==="nested"?_.vars.targets:y}),v.kill(),v.parent=v._dp=pt(s),v._start=0,d||mo(c)||mo(u)){if(C=y.length,S=d&&hs(d),nt(d))for(w in d)~Us.indexOf(w)&&(T||(T={}),T[w]=d[w]);for(b=0;b<C;b++)x=Ao(i,Is),x.stagger=0,A&&(x.easeReverse=A),T&&ba(x,T),k=y[b],x.duration=+$a(c,pt(s),b,k,y),x.delay=(+$a(u,pt(s),b,k,y)||0)-s._delay,!d&&C===1&&x.delay&&(s._delay=u=x.delay,s._start+=u,x.delay=0),v.to(k,x,S?S(b,k,y):0),v._ease=z.none;v.duration()?c=u=0:s.timeline=0}else if(h){Ea(Ve(v.vars.defaults,{ease:"none"})),v._ease=Kt(h.ease||i.ease||"none");var M=0,V,N,F;if(pe(h))h.forEach(function(D){return v.to(y,D,">")}),v.duration();else{x={};for(w in h)w==="ease"||w==="easeEach"||ip(w,h[w],x,h.easeEach);for(w in x)for(V=x[w].sort(function(D,$){return D.t-$.t}),M=0,b=0;b<V.length;b++)N=V[b],F={ease:N.e,duration:(N.t-(b?V[b-1].t:0))/100*c},F[w]=N.v,v.to(y,F,M),M+=F.duration;v.duration()<c&&v.to({},{duration:c-v.duration()})}}c||s.duration(c=v.duration())}else s.timeline=0;return m===!0&&!tr&&(Tt=pt(s),K.killTweensOf(y),Tt=0),it(_,pt(s),r),i.reversed&&s.reverse(),i.paused&&s.paused(!0),(f||!c&&!h&&s._start===X(_._time)&&_e(f)&&Rf(pt(s))&&_.data!=="nested")&&(s._tTime=-W,s.render(Math.max(0,-u)||0)),g&&fs(pt(s),g),s}var t=e.prototype;return t.render=function(i,r,n){var s=this._time,l=this._tDur,c=this._dur,u=i<0,f=i>l-W&&!u?l:i<W?0:i,d,m,h,p,g,_,y,v;if(!c)Df(this,i,r,n);else if(f!==this._tTime||!i||n||!this._initted&&this._tTime||this._startAt&&this._zTime<0!==u||this._lazy){if(d=f,v=this.timeline,this._repeat){if(p=c+this._rDelay,this._repeat<-1&&u)return this.totalTime(p*100+i,r,n);if(d=X(f%p),f===l?(h=this._repeat,d=c):(g=X(f/p),h=~~g,h&&h===g?(d=c,h--):d>c&&(d=c)),_=this._yoyo&&h&1,_&&(d=c-d),g=wa(this._tTime,p),d===s&&!n&&this._initted&&h===g)return this._tTime=f,this;h!==g&&this.vars.repeatRefresh&&!_&&!this._lock&&d!==p&&this._initted&&(this._lock=n=1,this.render(X(p*h),!0).invalidate()._lock=0)}if(!this._initted){if(ps(this,u?i:d,n,r,f))return this._tTime=0,this;if(s!==this._time&&!(n&&this.vars.repeatRefresh&&h!==g))return this;if(c!==this._dur)return this.render(i,r,n)}if(this._rEase){var b=d<s;if(b!==this._inv){var x=b?s:c-s;this._inv=b,this._from&&(this.ratio=1-this.ratio),this._invRatio=this.ratio,this._invTime=s,this._invRecip=x?(b?-1:1)/x:0,this._invScale=b?-this.ratio:1-this.ratio,this._invEase=b?this._rEase:this._ease}this.ratio=y=this._invRatio+this._invScale*this._invEase((d-this._invTime)*this._invRecip)}else this.ratio=y=this._ease(d/c);if(this._from&&(this.ratio=y=1-y),this._tTime=f,this._time=d,!this._act&&this._ts&&(this._act=1,this._lazy=0),!s&&f&&!r&&!g&&(Ie(this,"onStart"),this._tTime!==f))return this;for(m=this._pt;m;)m.r(y,m.d),m=m._next;v&&v.render(i<0?i:v._dur*v._ease(d/this._dur),r,n)||this._startAt&&(this._zTime=i),this._onUpdate&&!r&&(u&&Vi(this,i,r,n),Ie(this,"onUpdate")),this._repeat&&h!==g&&this.vars.onRepeat&&!r&&this.parent&&Ie(this,"onRepeat"),(f===this._tDur||!f)&&this._tTime===f&&(u&&!this._onUpdate&&Vi(this,i,!0,!0),(i||!c)&&(f===this._tDur&&this._ts>0||!f&&this._ts<0)&&Vt(this,1),!r&&!(u&&!s)&&(f||s||_)&&(Ie(this,f===l?"onComplete":"onReverseComplete",!0),this._prom&&!(f<l&&this.timeScale()>0)&&this._prom()))}return this},t.targets=function(){return this._targets},t.invalidate=function(i){return(!i||!this.vars.runBackwards)&&(this._startAt=0),this._pt=this._op=this._onUpdate=this._lazy=this.ratio=0,this._ptLookup=[],this.timeline&&this.timeline.invalidate(i),a.prototype.invalidate.call(this,i)},t.resetTo=function(i,r,n,s,l){Qa||Te.wake(),this._ts||this.play();var c=Math.min(this._dur,(this._dp._time-this._start)*this._ts),u;return this._initted||fr(this,c),u=this._ease(c/this._dur),ap(this,i,r,n,s,u,c,l)?this.resetTo(i,r,n,s,1):(Yo(this,0),this.parent||cs(this._dp,this,"_first","_last",this._dp._sort?"_start":0),this.render(0))},t.kill=function(i,r){if(r===void 0&&(r="all"),!i&&(!r||r==="all"))return this._lazy=this._pt=0,this.parent?Ra(this):this.scrollTrigger&&this.scrollTrigger.kill(!!se),this;if(this.timeline){var n=this.timeline.totalDuration();return this.timeline.killTweensOf(i,r,Tt&&Tt.vars.overwrite!==!0)._first||Ra(this),this.parent&&n!==this.timeline.totalDuration()&&Sa(this,this._dur*this.timeline._tDur/n,0,1),this}var s=this._targets,l=i?je(i):s,c=this._ptLookup,u=this._pt,f,d,m,h,p,g,_;if((!r||r==="all")&&Bf(s,l))return r==="all"&&(this._pt=0),Ra(this);for(f=this._op=this._op||[],r!=="all"&&(ne(r)&&(p={},xe(r,function(y){return p[y]=1}),r=p),r=op(s,r)),_=s.length;_--;)if(~l.indexOf(s[_])){d=c[_],r==="all"?(f[_]=r,h=d,m={}):(m=f[_]=f[_]||{},h=r);for(p in h)g=d&&d[p],g&&((!("kill"in g.d)||g.d.kill(p)===!0)&&Wo(this,g,"_pt"),delete d[p]),m!=="all"&&(m[p]=1)}return this._initted&&!this._pt&&u&&Ra(this),this},e.to=function(i,r){return new e(i,r,arguments[2])},e.from=function(i,r){return La(1,arguments)},e.delayedCall=function(i,r,n,s){return new e(r,0,{immediateRender:!1,lazy:!1,overwrite:!1,delay:i,onComplete:r,onReverseComplete:r,onCompleteParams:n,onReverseCompleteParams:n,callbackScope:s})},e.fromTo=function(i,r,n){return La(2,arguments)},e.set=function(i,r){return r.duration=0,r.repeatDelay||(r.repeat=0),new e(i,r)},e.killTweensOf=function(i,r,n){return K.killTweensOf(i,r,n)},e}(Ja);Ve(oe.prototype,{_targets:[],_lazy:0,_startAt:0,_op:0,_onInit:0});xe("staggerTo,staggerFrom,staggerFromTo",function(a){oe[a]=function(){var e=new ye,t=Pi.call(arguments,0);return t.splice(a==="staggerFromTo"?5:4,0,0),e[a].apply(e,t)}});var pr=function(e,t,o){return e[t]=o},As=function(e,t,o){return e[t](o)},rp=function(e,t,o,i){return e[t](i.fp,o)},np=function(e,t,o){return e.setAttribute(t,o)},dr=function(e,t){return ee(e[t])?As:ar(e[t])&&e.setAttribute?np:pr},Ms=function(e,t){return t.set(t.t,t.p,Math.round((t.s+t.c*e)*1e6)/1e6,t)},sp=function(e,t){return t.set(t.t,t.p,!!(t.s+t.c*e),t)},Bs=function(e,t){var o=t._pt,i="";if(!e&&t.b)i=t.b;else if(e===1&&t.e)i=t.e;else{for(;o;)i=o.p+(o.m?o.m(o.s+o.c*e):Math.round((o.s+o.c*e)*1e4)/1e4)+i,o=o._next;i+=t.c}t.set(t.t,t.p,i,t)},mr=function(e,t){for(var o=t._pt;o;)o.r(e,o.d),o=o._next},lp=function(e,t,o,i){for(var r=this._pt,n;r;)n=r._next,r.p===i&&r.modifier(e,t,o),r=n},cp=function(e){for(var t=this._pt,o,i;t;)i=t._next,t.p===e&&!t.op||t.op===e?Wo(this,t,"_pt"):t.dep||(o=1),t=i;return!o},up=function(e,t,o,i){i.mSet(e,t,i.m.call(i.tween,o,i.mt),i)},Vs=function(e){for(var t=e._pt,o,i,r,n;t;){for(o=t._next,i=r;i&&i.pr>t.pr;)i=i._next;(t._prev=i?i._prev:n)?t._prev._next=t:r=t,(t._next=i)?i._prev=t:n=t,t=o}e._pt=r},be=function(){function a(t,o,i,r,n,s,l,c,u){this.t=o,this.s=r,this.c=n,this.p=i,this.r=s||Ms,this.d=l||this,this.set=c||pr,this.pr=u||0,this._next=t,t&&(t._prev=this)}var e=a.prototype;return e.modifier=function(o,i,r){this.mSet=this.mSet||this.set,this.set=up,this.m=o,this.mt=r,this.tween=i},a}();xe(sr+"parent,duration,ease,delay,overwrite,runBackwards,startAt,yoyo,immediateRender,repeat,repeatDelay,data,paused,reversed,lazy,callbackScope,stringFilter,id,yoyoEase,stagger,inherit,repeatRefresh,keyframes,autoRevert,scrollTrigger,easeReverse",function(a){return nr[a]=1});Be.TweenMax=Be.TweenLite=oe;Be.TimelineLite=Be.TimelineMax=ye;K=new ye({sortChildren:!1,defaults:qa,autoRemoveChildren:!0,id:"root",smoothChildTiming:!0});Me.stringFilter=ks;var Qt=[],bo={},fp=[],hn=0,pp=0,mi=function(e){return(bo[e]||fp).map(function(t){return t()})},Ni=function(){var e=Date.now(),t=[];e-hn>2&&(mi("matchMediaInit"),Qt.forEach(function(o){var i=o.queries,r=o.conditions,n,s,l,c;for(s in i)n=ot.matchMedia(i[s]).matches,n&&(l=1),n!==r[s]&&(r[s]=n,c=1);c&&(o.revert(),l&&t.push(o))}),mi("matchMediaRevert"),t.forEach(function(o){return o.onMatch(o,function(i){return o.add(null,i)})}),hn=e,mi("matchMedia"))},Rs=function(){function a(t,o){this.selector=o&&Di(o),this.data=[],this._r=[],this.isReverted=!1,this.id=pp++,t&&this.add(t)}var e=a.prototype;return e.add=function(o,i,r){ee(o)&&(r=i,i=o,o=ee);var n=this,s=function(){var c=H,u=n.selector,f;return c&&c!==n&&c.data.push(n),r&&(n.selector=Di(r)),H=n,f=i.apply(n,arguments),ee(f)&&n._r.push(f),H=c,n.selector=u,n.isReverted=!1,f};return n.last=s,o===ee?s(n,function(l){return n.add(null,l)}):o?n[o]=s:s},e.ignore=function(o){var i=H;H=null,o(this),H=i},e.getTweens=function(){var o=[];return this.data.forEach(function(i){return i instanceof a?o.push.apply(o,i.getTweens()):i instanceof oe&&!(i.parent&&i.parent.data==="nested")&&o.push(i)}),o},e.clear=function(){this._r.length=this.data.length=0},e.kill=function(o,i){var r=this;if(o?function(){for(var s=r.getTweens(),l=r.data.length,c;l--;)c=r.data[l],c.data==="isFlip"&&(c.revert(),c.getChildren(!0,!0,!1).forEach(function(u){return s.splice(s.indexOf(u),1)}));for(s.map(function(u){return{g:u._dur||u._delay||u._sat&&!u._sat.vars.immediateRender?u.globalTime(0):-1/0,t:u}}).sort(function(u,f){return f.g-u.g||-1/0}).forEach(function(u){return u.t.revert(o)}),l=r.data.length;l--;)c=r.data[l],c instanceof ye?c.data!=="nested"&&(c.scrollTrigger&&c.scrollTrigger.revert(),c.kill()):!(c instanceof oe)&&c.revert&&c.revert(o);r._r.forEach(function(u){return u(o,r)}),r.isReverted=!0}():this.data.forEach(function(s){return s.kill&&s.kill()}),this.clear(),i)for(var n=Qt.length;n--;)Qt[n].id===this.id&&Qt.splice(n,1)},e.revert=function(o){this.kill(o||{})},a}(),dp=function(){function a(t){this.contexts=[],this.scope=t,H&&H.data.push(this)}var e=a.prototype;return e.add=function(o,i,r){nt(o)||(o={matches:o});var n=new Rs(0,r||this.scope),s=n.conditions={},l,c,u;H&&!n.selector&&(n.selector=H.selector),this.contexts.push(n),i=n.add("onMatch",i),n.queries=o;for(c in o)c==="all"?u=1:(l=ot.matchMedia(o[c]),l&&(Qt.indexOf(n)<0&&Qt.push(n),(s[c]=l.matches)&&(u=1),l.addListener?l.addListener(Ni):l.addEventListener("change",Ni)));return u&&i(n,function(f){return n.add(null,f)}),this},e.revert=function(o){this.kill(o||{})},e.kill=function(o){this.contexts.forEach(function(i){return i.kill(o,!0)})},a}(),Bo={registerPlugin:function(){for(var e=arguments.length,t=new Array(e),o=0;o<e;o++)t[o]=arguments[o];t.forEach(function(i){return bs(i)})},timeline:function(e){return new ye(e)},getTweensOf:function(e,t){return K.getTweensOf(e,t)},getProperty:function(e,t,o,i){ne(e)&&(e=je(e)[0]);var r=Ht(e||{}).get,n=o?ls:ss;return o==="native"&&(o=""),e&&(t?n((Oe[t]&&Oe[t].get||r)(e,t,o,i)):function(s,l,c){return n((Oe[s]&&Oe[s].get||r)(e,s,l,c))})},quickSetter:function(e,t,o){if(e=je(e),e.length>1){var i=e.map(function(u){return Se.quickSetter(u,t,o)}),r=i.length;return function(u){for(var f=r;f--;)i[f](u)}}e=e[0]||{};var n=Oe[t],s=Ht(e),l=s.harness&&(s.harness.aliases||{})[t]||t,c=n?function(u){var f=new n;fa._pt=0,f.init(e,o?u+o:u,fa,0,[e]),f.render(1,f),fa._pt&&mr(1,fa)}:s.set(e,l);return n?c:function(u){return c(e,l,o?u+o:u,s,1)}},quickTo:function(e,t,o){var i,r=Se.to(e,Ve((i={},i[t]="+=0.1",i.paused=!0,i.stagger=0,i),o||{})),n=function(l,c,u){return r.resetTo(t,l,c,u)};return n.tween=r,n},isTweening:function(e){return K.getTweensOf(e,!0).length>0},defaults:function(e){return e&&e.ease&&(e.ease=Kt(e.ease,qa.ease)),un(qa,e||{})},config:function(e){return un(Me,e||{})},registerEffect:function(e){var t=e.name,o=e.effect,i=e.plugins,r=e.defaults,n=e.extendTimeline;(i||"").split(",").forEach(function(s){return s&&!Oe[s]&&!Be[s]&&Ha(t+" effect requires "+s+" plugin.")}),ui[t]=function(s,l,c){return o(je(s),Ve(l||{},r),c)},n&&(ye.prototype[t]=function(s,l,c){return this.add(ui[t](s,nt(l)?l:(c=l)&&{},this),c)})},registerEase:function(e,t){z[e]=Kt(t)},parseEase:function(e,t){return arguments.length?Kt(e,t):z},getById:function(e){return K.getById(e)},exportRoot:function(e,t){e===void 0&&(e={});var o=new ye(e),i,r;for(o.smoothChildTiming=_e(e.smoothChildTiming),K.remove(o),o._dp=0,o._time=o._tTime=K._time,i=K._first;i;)r=i._next,(t||!(!i._dur&&i instanceof oe&&i.vars.onComplete===i._targets[0]))&&it(o,i,i._start-i._delay),i=r;return it(K,o,0),o},context:function(e,t){return e?new Rs(e,t):H},matchMedia:function(e){return new dp(e)},matchMediaRefresh:function(){return Qt.forEach(function(e){var t=e.conditions,o,i;for(i in t)t[i]&&(t[i]=!1,o=1);o&&e.revert()})||Ni()},addEventListener:function(e,t){var o=bo[e]||(bo[e]=[]);~o.indexOf(t)||o.push(t)},removeEventListener:function(e,t){var o=bo[e],i=o&&o.indexOf(t);i>=0&&o.splice(i,1)},utils:{wrap:Wf,wrapYoyo:Gf,distribute:hs,random:vs,snap:gs,normalize:jf,getUnit:fe,clamp:Nf,splitColor:ws,toArray:je,selector:Di,mapRange:_s,pipe:Lf,unitize:$f,interpolate:Yf,shuffle:ms},install:as,effects:ui,ticker:Te,updateRoot:ye.updateRoot,plugins:Oe,globalTimeline:K,core:{PropTween:be,globals:os,Tween:oe,Timeline:ye,Animation:Ja,getCache:Ht,_removeLinkedListItem:Wo,reverting:function(){return se},context:function(e){return e&&H&&(H.data.push(e),e._ctx=H),H},suppressOverwrites:function(e){return tr=e}}};xe("to,from,fromTo,delayedCall,set,killTweensOf",function(a){return Bo[a]=oe[a]});Te.add(ye.updateRoot);fa=Bo.to({},{duration:0});var mp=function(e,t){for(var o=e._pt;o&&o.p!==t&&o.op!==t&&o.fp!==t;)o=o._next;return o},hp=function(e,t){var o=e._targets,i,r,n;for(i in t)for(r=o.length;r--;)n=e._ptLookup[r][i],n&&(n=n.d)&&(n._pt&&(n=mp(n,i)),n&&n.modifier&&n.modifier(t[i],e,o[r],i))},hi=function(e,t){return{name:e,headless:1,rawVars:1,init:function(i,r,n){n._onInit=function(s){var l,c;if(ne(r)&&(l={},xe(r,function(u){return l[u]=1}),r=l),t){l={};for(c in r)l[c]=t(r[c]);r=l}hp(s,r)}}}},Se=Bo.registerPlugin({name:"attr",init:function(e,t,o,i,r){var n,s,l;this.tween=o;for(n in t)l=e.getAttribute(n)||"",s=this.add(e,"setAttribute",(l||0)+"",t[n],i,r,0,0,n),s.op=n,s.b=l,this._props.push(n)},render:function(e,t){for(var o=t._pt;o;)se?o.set(o.t,o.p,o.b,o):o.r(e,o.d),o=o._next}},{name:"endArray",headless:1,init:function(e,t){for(var o=t.length;o--;)this.add(e,o,e[o]||0,t[o],0,0,0,0,0,1)}},hi("roundProps",zi),hi("modifiers"),hi("snap",gs))||Bo;oe.version=ye.version=Se.version="3.15.0";ts=1;or()&&ka();z.Power0;z.Power1;z.Power2;z.Power3;z.Power4;z.Linear;z.Quad;z.Cubic;z.Quart;z.Quint;z.Strong;z.Elastic;z.Back;z.SteppedEase;z.Bounce;z.Sine;z.Expo;z.Circ;/*!
 * CSSPlugin 3.15.0
 * https://gsap.com
 *
 * Copyright 2008-2026, GreenSock. All rights reserved.
 * Subject to the terms at https://gsap.com/standard-license
 * @author: Jack Doyle, jack@greensock.com
*/var gn,Ut,va,hr,Yt,vn,gr,gp=function(){return typeof window<"u"},_t={},Wt=180/Math.PI,ya=Math.PI/180,ra=Math.atan2,yn=1e8,vr=/([A-Z])/g,vp=/(left|right|width|margin|padding|x)/i,yp=/[\s,\(]\S/,rt={autoAlpha:"opacity,visibility",scale:"scaleX,scaleY",alpha:"opacity"},Ei=function(e,t){return t.set(t.t,t.p,Math.round((t.s+t.c*e)*1e4)/1e4+t.u,t)},_p=function(e,t){return t.set(t.t,t.p,e===1?t.e:Math.round((t.s+t.c*e)*1e4)/1e4+t.u,t)},xp=function(e,t){return t.set(t.t,t.p,e?Math.round((t.s+t.c*e)*1e4)/1e4+t.u:t.b,t)},bp=function(e,t){return t.set(t.t,t.p,e===1?t.e:e?Math.round((t.s+t.c*e)*1e4)/1e4+t.u:t.b,t)},wp=function(e,t){var o=t.s+t.c*e;t.set(t.t,t.p,~~(o+(o<0?-.5:.5))+t.u,t)},Ps=function(e,t){return t.set(t.t,t.p,e?t.e:t.b,t)},Ds=function(e,t){return t.set(t.t,t.p,e!==1?t.b:t.e,t)},Sp=function(e,t,o){return e.style[t]=o},kp=function(e,t,o){return e.style.setProperty(t,o)},Cp=function(e,t,o){return e._gsap[t]=o},Op=function(e,t,o){return e._gsap.scaleX=e._gsap.scaleY=o},Tp=function(e,t,o,i,r){var n=e._gsap;n.scaleX=n.scaleY=o,n.renderTransform(r,n)},Up=function(e,t,o,i,r){var n=e._gsap;n[t]=o,n.renderTransform(r,n)},Q="transform",we=Q+"Origin",Ip=function a(e,t){var o=this,i=this.target,r=i.style,n=i._gsap;if(e in _t&&r){if(this.tfm=this.tfm||{},e!=="transform")e=rt[e]||e,~e.indexOf(",")?e.split(",").forEach(function(s){return o.tfm[s]=dt(i,s)}):this.tfm[e]=n.x?n[e]:dt(i,e),e===we&&(this.tfm.zOrigin=n.zOrigin);else return rt.transform.split(",").forEach(function(s){return a.call(o,s,t)});if(this.props.indexOf(Q)>=0)return;n.svg&&(this.svgo=i.getAttribute("data-svg-origin"),this.props.push(we,t,"")),e=Q}(r||t)&&this.props.push(e,t,r[e])},zs=function(e){e.translate&&(e.removeProperty("translate"),e.removeProperty("scale"),e.removeProperty("rotate"))},Ap=function(){var e=this.props,t=this.target,o=t.style,i=t._gsap,r,n;for(r=0;r<e.length;r+=3)e[r+1]?e[r+1]===2?t[e[r]](e[r+2]):t[e[r]]=e[r+2]:e[r+2]?o[e[r]]=e[r+2]:o.removeProperty(e[r].substr(0,2)==="--"?e[r]:e[r].replace(vr,"-$1").toLowerCase());if(this.tfm){for(n in this.tfm)i[n]=this.tfm[n];i.svg&&(i.renderTransform(),t.setAttribute("data-svg-origin",this.svgo||"")),r=gr(),(!r||!r.isStart)&&!o[Q]&&(zs(o),i.zOrigin&&o[we]&&(o[we]+=" "+i.zOrigin+"px",i.zOrigin=0,i.renderTransform()),i.uncache=1)}},Fs=function(e,t){var o={target:e,props:[],revert:Ap,save:Ip};return e._gsap||Se.core.getCache(e),t&&e.style&&e.nodeType&&t.split(",").forEach(function(i){return o.save(i)}),o},Ns,Li=function(e,t){var o=Ut.createElementNS?Ut.createElementNS((t||"http://www.w3.org/1999/xhtml").replace(/^https/,"http"),e):Ut.createElement(e);return o&&o.style?o:Ut.createElement(e)},Ae=function a(e,t,o){var i=getComputedStyle(e);return i[t]||i.getPropertyValue(t.replace(vr,"-$1").toLowerCase())||i.getPropertyValue(t)||!o&&a(e,Ca(t)||t,1)||""},_n="O,Moz,ms,Ms,Webkit".split(","),Ca=function(e,t,o){var i=t||Yt,r=i.style,n=5;if(e in r&&!o)return e;for(e=e.charAt(0).toUpperCase()+e.substr(1);n--&&!(_n[n]+e in r););return n<0?null:(n===3?"ms":n>=0?_n[n]:"")+e},$i=function(){gp()&&window.document&&(gn=window,Ut=gn.document,va=Ut.documentElement,Yt=Li("div")||{style:{}},Li("div"),Q=Ca(Q),we=Q+"Origin",Yt.style.cssText="border-width:0;line-height:0;position:absolute;padding:0",Ns=!!Ca("perspective"),gr=Se.core.reverting,hr=1)},xn=function(e){var t=e.ownerSVGElement,o=Li("svg",t&&t.getAttribute("xmlns")||"http://www.w3.org/2000/svg"),i=e.cloneNode(!0),r;i.style.display="block",o.appendChild(i),va.appendChild(o);try{r=i.getBBox()}catch{}return o.removeChild(i),va.removeChild(o),r},bn=function(e,t){for(var o=t.length;o--;)if(e.hasAttribute(t[o]))return e.getAttribute(t[o])},Es=function(e){var t,o;try{t=e.getBBox()}catch{t=xn(e),o=1}return t&&(t.width||t.height)||o||(t=xn(e)),t&&!t.width&&!t.x&&!t.y?{x:+bn(e,["x","cx","x1"])||0,y:+bn(e,["y","cy","y1"])||0,width:0,height:0}:t},Ls=function(e){return!!(e.getCTM&&(!e.parentNode||e.ownerSVGElement)&&Es(e))},Rt=function(e,t){if(t){var o=e.style,i;t in _t&&t!==we&&(t=Q),o.removeProperty?(i=t.substr(0,2),(i==="ms"||t.substr(0,6)==="webkit")&&(t="-"+t),o.removeProperty(i==="--"?t:t.replace(vr,"-$1").toLowerCase())):o.removeAttribute(t)}},It=function(e,t,o,i,r,n){var s=new be(e._pt,t,o,0,1,n?Ds:Ps);return e._pt=s,s.b=i,s.e=r,e._props.push(o),s},wn={deg:1,rad:1,turn:1},Mp={grid:1,flex:1},Pt=function a(e,t,o,i){var r=parseFloat(o)||0,n=(o+"").trim().substr((r+"").length)||"px",s=Yt.style,l=vp.test(t),c=e.tagName.toLowerCase()==="svg",u=(c?"client":"offset")+(l?"Width":"Height"),f=100,d=i==="px",m=i==="%",h,p,g,_;if(i===n||!r||wn[i]||wn[n])return r;if(n!=="px"&&!d&&(r=a(e,t,o,"px")),_=e.getCTM&&Ls(e),(m||n==="%")&&(_t[t]||~t.indexOf("adius")))return h=_?e.getBBox()[l?"width":"height"]:e[u],te(m?r/h*f:r/100*h);if(s[l?"width":"height"]=f+(d?n:i),p=i!=="rem"&&~t.indexOf("adius")||i==="em"&&e.appendChild&&!c?e:e.parentNode,_&&(p=(e.ownerSVGElement||{}).parentNode),(!p||p===Ut||!p.appendChild)&&(p=Ut.body),g=p._gsap,g&&m&&g.width&&l&&g.time===Te.time&&!g.uncache)return te(r/g.width*f);if(m&&(t==="height"||t==="width")){var y=e.style[t];e.style[t]=f+i,h=e[u],y?e.style[t]=y:Rt(e,t)}else(m||n==="%")&&!Mp[Ae(p,"display")]&&(s.position=Ae(e,"position")),p===e&&(s.position="static"),p.appendChild(Yt),h=Yt[u],p.removeChild(Yt),s.position="absolute";return l&&m&&(g=Ht(p),g.time=Te.time,g.width=p[u]),te(d?h*r/f:h&&r?f/h*r:0)},dt=function(e,t,o,i){var r;return hr||$i(),t in rt&&t!=="transform"&&(t=rt[t],~t.indexOf(",")&&(t=t.split(",")[0])),_t[t]&&t!=="transform"?(r=eo(e,i),r=t!=="transformOrigin"?r[t]:r.svg?r.origin:Ro(Ae(e,we))+" "+r.zOrigin+"px"):(r=e.style[t],(!r||r==="auto"||i||~(r+"").indexOf("calc("))&&(r=Vo[t]&&Vo[t](e,t,o)||Ae(e,t)||rs(e,t)||(t==="opacity"?1:0))),o&&!~(r+"").trim().indexOf(" ")?Pt(e,t,r,o)+o:r},Bp=function(e,t,o,i){if(!o||o==="none"){var r=Ca(t,e,1),n=r&&Ae(e,r,1);n&&n!==o?(t=r,o=n):t==="borderColor"&&(o=Ae(e,"borderTopColor"))}var s=new be(this._pt,e.style,t,0,1,Bs),l=0,c=0,u,f,d,m,h,p,g,_,y,v,b,x;if(s.b=o,s.e=i,o+="",i+="",i.substring(0,6)==="var(--"&&(i=Ae(e,i.substring(4,i.indexOf(")")))),i==="auto"&&(p=e.style[t],e.style[t]=i,i=Ae(e,t)||i,p?e.style[t]=p:Rt(e,t)),u=[o,i],ks(u),o=u[0],i=u[1],d=o.match(ua)||[],x=i.match(ua)||[],x.length){for(;f=ua.exec(i);)g=f[0],y=i.substring(l,f.index),h?h=(h+1)%5:(y.substr(-5)==="rgba("||y.substr(-5)==="hsla(")&&(h=1),g!==(p=d[c++]||"")&&(m=parseFloat(p)||0,b=p.substr((m+"").length),g.charAt(1)==="="&&(g=ga(m,g)+b),_=parseFloat(g),v=g.substr((_+"").length),l=ua.lastIndex-v.length,v||(v=v||Me.units[t]||b,l===i.length&&(i+=v,s.e+=v)),b!==v&&(m=Pt(e,t,p,v)||0),s._pt={_next:s._pt,p:y||c===1?y:",",s:m,c:_-m,m:h&&h<4||t==="zIndex"?Math.round:0});s.c=l<i.length?i.substring(l,i.length):""}else s.r=t==="display"&&i==="none"?Ds:Ps;return es.test(i)&&(s.e=0),this._pt=s,s},Sn={top:"0%",bottom:"100%",left:"0%",right:"100%",center:"50%"},Vp=function(e){var t=e.split(" "),o=t[0],i=t[1]||"50%";return(o==="top"||o==="bottom"||i==="left"||i==="right")&&(e=o,o=i,i=e),t[0]=Sn[o]||o,t[1]=Sn[i]||i,t.join(" ")},Rp=function(e,t){if(t.tween&&t.tween._time===t.tween._dur){var o=t.t,i=o.style,r=t.u,n=o._gsap,s,l,c;if(r==="all"||r===!0)i.cssText="",l=1;else for(r=r.split(","),c=r.length;--c>-1;)s=r[c],_t[s]&&(l=1,s=s==="transformOrigin"?we:Q),Rt(o,s);l&&(Rt(o,Q),n&&(n.svg&&o.removeAttribute("transform"),i.scale=i.rotate=i.translate="none",eo(o,1),n.uncache=1,zs(i)))}},Vo={clearProps:function(e,t,o,i,r){if(r.data!=="isFromStart"){var n=e._pt=new be(e._pt,t,o,0,0,Rp);return n.u=i,n.pr=-10,n.tween=r,e._props.push(o),1}}},Za=[1,0,0,1,0,0],$s={},js=function(e){return e==="matrix(1, 0, 0, 1, 0, 0)"||e==="none"||!e},kn=function(e){var t=Ae(e,Q);return js(t)?Za:t.substr(7).match(Zn).map(te)},yr=function(e,t){var o=e._gsap||Ht(e),i=e.style,r=kn(e),n,s,l,c;return o.svg&&e.getAttribute("transform")?(l=e.transform.baseVal.consolidate().matrix,r=[l.a,l.b,l.c,l.d,l.e,l.f],r.join(",")==="1,0,0,1,0,0"?Za:r):(r===Za&&!e.offsetParent&&e!==va&&!o.svg&&(l=i.display,i.display="block",n=e.parentNode,(!n||!e.offsetParent&&!e.getBoundingClientRect().width)&&(c=1,s=e.nextElementSibling,va.appendChild(e)),r=kn(e),l?i.display=l:Rt(e,"display"),c&&(s?n.insertBefore(e,s):n?n.appendChild(e):va.removeChild(e))),t&&r.length>6?[r[0],r[1],r[4],r[5],r[12],r[13]]:r)},ji=function(e,t,o,i,r,n){var s=e._gsap,l=r||yr(e,!0),c=s.xOrigin||0,u=s.yOrigin||0,f=s.xOffset||0,d=s.yOffset||0,m=l[0],h=l[1],p=l[2],g=l[3],_=l[4],y=l[5],v=t.split(" "),b=parseFloat(v[0])||0,x=parseFloat(v[1])||0,C,w,k,S;o?l!==Za&&(w=m*g-h*p)&&(k=b*(g/w)+x*(-p/w)+(p*y-g*_)/w,S=b*(-h/w)+x*(m/w)-(m*y-h*_)/w,b=k,x=S):(C=Es(e),b=C.x+(~v[0].indexOf("%")?b/100*C.width:b),x=C.y+(~(v[1]||v[0]).indexOf("%")?x/100*C.height:x)),i||i!==!1&&s.smooth?(_=b-c,y=x-u,s.xOffset=f+(_*m+y*p)-_,s.yOffset=d+(_*h+y*g)-y):s.xOffset=s.yOffset=0,s.xOrigin=b,s.yOrigin=x,s.smooth=!!i,s.origin=t,s.originIsAbsolute=!!o,e.style[we]="0px 0px",n&&(It(n,s,"xOrigin",c,b),It(n,s,"yOrigin",u,x),It(n,s,"xOffset",f,s.xOffset),It(n,s,"yOffset",d,s.yOffset)),e.setAttribute("data-svg-origin",b+" "+x)},eo=function(e,t){var o=e._gsap||new Os(e);if("x"in o&&!t&&!o.uncache)return o;var i=e.style,r=o.scaleX<0,n="px",s="deg",l=getComputedStyle(e),c=Ae(e,we)||"0",u,f,d,m,h,p,g,_,y,v,b,x,C,w,k,S,T,A,M,V,N,F,D,$,ae,Re,bt,me,Qe,Pe,ve,De;return u=f=d=p=g=_=y=v=b=0,m=h=1,o.svg=!!(e.getCTM&&Ls(e)),l.translate&&((l.translate!=="none"||l.scale!=="none"||l.rotate!=="none")&&(i[Q]=(l.translate!=="none"?"translate3d("+(l.translate+" 0 0").split(" ").slice(0,3).join(", ")+") ":"")+(l.rotate!=="none"?"rotate("+l.rotate+") ":"")+(l.scale!=="none"?"scale("+l.scale.split(" ").join(",")+") ":"")+(l[Q]!=="none"?l[Q]:"")),i.scale=i.rotate=i.translate="none"),w=yr(e,o.svg),o.svg&&(o.uncache?(ae=e.getBBox(),c=o.xOrigin-ae.x+"px "+(o.yOrigin-ae.y)+"px",$=""):$=!t&&e.getAttribute("data-svg-origin"),ji(e,$||c,!!$||o.originIsAbsolute,o.smooth!==!1,w)),x=o.xOrigin||0,C=o.yOrigin||0,w!==Za&&(A=w[0],M=w[1],V=w[2],N=w[3],u=F=w[4],f=D=w[5],w.length===6?(m=Math.sqrt(A*A+M*M),h=Math.sqrt(N*N+V*V),p=A||M?ra(M,A)*Wt:0,y=V||N?ra(V,N)*Wt+p:0,y&&(h*=Math.abs(Math.cos(y*ya))),o.svg&&(u-=x-(x*A+C*V),f-=C-(x*M+C*N))):(De=w[6],Pe=w[7],bt=w[8],me=w[9],Qe=w[10],ve=w[11],u=w[12],f=w[13],d=w[14],k=ra(De,Qe),g=k*Wt,k&&(S=Math.cos(-k),T=Math.sin(-k),$=F*S+bt*T,ae=D*S+me*T,Re=De*S+Qe*T,bt=F*-T+bt*S,me=D*-T+me*S,Qe=De*-T+Qe*S,ve=Pe*-T+ve*S,F=$,D=ae,De=Re),k=ra(-V,Qe),_=k*Wt,k&&(S=Math.cos(-k),T=Math.sin(-k),$=A*S-bt*T,ae=M*S-me*T,Re=V*S-Qe*T,ve=N*T+ve*S,A=$,M=ae,V=Re),k=ra(M,A),p=k*Wt,k&&(S=Math.cos(k),T=Math.sin(k),$=A*S+M*T,ae=F*S+D*T,M=M*S-A*T,D=D*S-F*T,A=$,F=ae),g&&Math.abs(g)+Math.abs(p)>359.9&&(g=p=0,_=180-_),m=te(Math.sqrt(A*A+M*M+V*V)),h=te(Math.sqrt(D*D+De*De)),k=ra(F,D),y=Math.abs(k)>2e-4?k*Wt:0,b=ve?1/(ve<0?-ve:ve):0),o.svg&&($=e.getAttribute("transform"),o.forceCSS=e.setAttribute("transform","")||!js(Ae(e,Q)),$&&e.setAttribute("transform",$))),Math.abs(y)>90&&Math.abs(y)<270&&(r?(m*=-1,y+=p<=0?180:-180,p+=p<=0?180:-180):(h*=-1,y+=y<=0?180:-180)),t=t||o.uncache,o.x=u-((o.xPercent=u&&(!t&&o.xPercent||(Math.round(e.offsetWidth/2)===Math.round(-u)?-50:0)))?e.offsetWidth*o.xPercent/100:0)+n,o.y=f-((o.yPercent=f&&(!t&&o.yPercent||(Math.round(e.offsetHeight/2)===Math.round(-f)?-50:0)))?e.offsetHeight*o.yPercent/100:0)+n,o.z=d+n,o.scaleX=te(m),o.scaleY=te(h),o.rotation=te(p)+s,o.rotationX=te(g)+s,o.rotationY=te(_)+s,o.skewX=y+s,o.skewY=v+s,o.transformPerspective=b+n,(o.zOrigin=parseFloat(c.split(" ")[2])||!t&&o.zOrigin||0)&&(i[we]=Ro(c)),o.xOffset=o.yOffset=0,o.force3D=Me.force3D,o.renderTransform=o.svg?Dp:Ns?Ws:Pp,o.uncache=0,o},Ro=function(e){return(e=e.split(" "))[0]+" "+e[1]},gi=function(e,t,o){var i=fe(t);return te(parseFloat(t)+parseFloat(Pt(e,"x",o+"px",i)))+i},Pp=function(e,t){t.z="0px",t.rotationY=t.rotationX="0deg",t.force3D=0,Ws(e,t)},Lt="0deg",Ba="0px",$t=") ",Ws=function(e,t){var o=t||this,i=o.xPercent,r=o.yPercent,n=o.x,s=o.y,l=o.z,c=o.rotation,u=o.rotationY,f=o.rotationX,d=o.skewX,m=o.skewY,h=o.scaleX,p=o.scaleY,g=o.transformPerspective,_=o.force3D,y=o.target,v=o.zOrigin,b="",x=_==="auto"&&e&&e!==1||_===!0;if(v&&(f!==Lt||u!==Lt)){var C=parseFloat(u)*ya,w=Math.sin(C),k=Math.cos(C),S;C=parseFloat(f)*ya,S=Math.cos(C),n=gi(y,n,w*S*-v),s=gi(y,s,-Math.sin(C)*-v),l=gi(y,l,k*S*-v+v)}g!==Ba&&(b+="perspective("+g+$t),(i||r)&&(b+="translate("+i+"%, "+r+"%) "),(x||n!==Ba||s!==Ba||l!==Ba)&&(b+=l!==Ba||x?"translate3d("+n+", "+s+", "+l+") ":"translate("+n+", "+s+$t),c!==Lt&&(b+="rotate("+c+$t),u!==Lt&&(b+="rotateY("+u+$t),f!==Lt&&(b+="rotateX("+f+$t),(d!==Lt||m!==Lt)&&(b+="skew("+d+", "+m+$t),(h!==1||p!==1)&&(b+="scale("+h+", "+p+$t),y.style[Q]=b||"translate(0, 0)"},Dp=function(e,t){var o=t||this,i=o.xPercent,r=o.yPercent,n=o.x,s=o.y,l=o.rotation,c=o.skewX,u=o.skewY,f=o.scaleX,d=o.scaleY,m=o.target,h=o.xOrigin,p=o.yOrigin,g=o.xOffset,_=o.yOffset,y=o.forceCSS,v=parseFloat(n),b=parseFloat(s),x,C,w,k,S;l=parseFloat(l),c=parseFloat(c),u=parseFloat(u),u&&(u=parseFloat(u),c+=u,l+=u),l||c?(l*=ya,c*=ya,x=Math.cos(l)*f,C=Math.sin(l)*f,w=Math.sin(l-c)*-d,k=Math.cos(l-c)*d,c&&(u*=ya,S=Math.tan(c-u),S=Math.sqrt(1+S*S),w*=S,k*=S,u&&(S=Math.tan(u),S=Math.sqrt(1+S*S),x*=S,C*=S)),x=te(x),C=te(C),w=te(w),k=te(k)):(x=f,k=d,C=w=0),(v&&!~(n+"").indexOf("px")||b&&!~(s+"").indexOf("px"))&&(v=Pt(m,"x",n,"px"),b=Pt(m,"y",s,"px")),(h||p||g||_)&&(v=te(v+h-(h*x+p*w)+g),b=te(b+p-(h*C+p*k)+_)),(i||r)&&(S=m.getBBox(),v=te(v+i/100*S.width),b=te(b+r/100*S.height)),S="matrix("+x+","+C+","+w+","+k+","+v+","+b+")",m.setAttribute("transform",S),y&&(m.style[Q]=S)},zp=function(e,t,o,i,r){var n=360,s=ne(r),l=parseFloat(r)*(s&&~r.indexOf("rad")?Wt:1),c=l-i,u=i+c+"deg",f,d;return s&&(f=r.split("_")[1],f==="short"&&(c%=n,c!==c%(n/2)&&(c+=c<0?n:-n)),f==="cw"&&c<0?c=(c+n*yn)%n-~~(c/n)*n:f==="ccw"&&c>0&&(c=(c-n*yn)%n-~~(c/n)*n)),e._pt=d=new be(e._pt,t,o,i,c,_p),d.e=u,d.u="deg",e._props.push(o),d},Cn=function(e,t){for(var o in t)e[o]=t[o];return e},Fp=function(e,t,o){var i=Cn({},o._gsap),r="perspective,force3D,transformOrigin,svgOrigin",n=o.style,s,l,c,u,f,d,m,h;i.svg?(c=o.getAttribute("transform"),o.setAttribute("transform",""),n[Q]=t,s=eo(o,1),Rt(o,Q),o.setAttribute("transform",c)):(c=getComputedStyle(o)[Q],n[Q]=t,s=eo(o,1),n[Q]=c);for(l in _t)c=i[l],u=s[l],c!==u&&r.indexOf(l)<0&&(m=fe(c),h=fe(u),f=m!==h?Pt(o,l,c,h):parseFloat(c),d=parseFloat(u),e._pt=new be(e._pt,s,l,f,d-f,Ei),e._pt.u=h||0,e._props.push(l));Cn(s,i)};xe("padding,margin,Width,Radius",function(a,e){var t="Top",o="Right",i="Bottom",r="Left",n=(e<3?[t,o,i,r]:[t+r,t+o,i+o,i+r]).map(function(s){return e<2?a+s:"border"+s+a});Vo[e>1?"border"+a:a]=function(s,l,c,u,f){var d,m;if(arguments.length<4)return d=n.map(function(h){return dt(s,h,c)}),m=d.join(" "),m.split(d[0]).length===5?d[0]:m;d=(u+"").split(" "),m={},n.forEach(function(h,p){return m[h]=d[p]=d[p]||d[(p-1)/2|0]}),s.init(l,m,f)}});var Gs={name:"css",register:$i,targetTest:function(e){return e.style&&e.nodeType},init:function(e,t,o,i,r){var n=this._props,s=e.style,l=o.vars.startAt,c,u,f,d,m,h,p,g,_,y,v,b,x,C,w,k,S;hr||$i(),this.styles=this.styles||Fs(e),k=this.styles.props,this.tween=o;for(p in t)if(p!=="autoRound"&&(u=t[p],!(Oe[p]&&Ts(p,t,o,i,e,r)))){if(m=typeof u,h=Vo[p],m==="function"&&(u=u.call(o,i,e,r),m=typeof u),m==="string"&&~u.indexOf("random(")&&(u=Ka(u)),h)h(this,e,p,u,o)&&(w=1);else if(p.substr(0,2)==="--")c=(getComputedStyle(e).getPropertyValue(p)+"").trim(),u+="",Mt.lastIndex=0,Mt.test(c)||(g=fe(c),_=fe(u),_?g!==_&&(c=Pt(e,p,c,_)+_):g&&(u+=g)),this.add(s,"setProperty",c,u,i,r,0,0,p),n.push(p),k.push(p,0,s[p]);else if(m!=="undefined"){if(l&&p in l?(c=typeof l[p]=="function"?l[p].call(o,i,e,r):l[p],ne(c)&&~c.indexOf("random(")&&(c=Ka(c)),fe(c+"")||c==="auto"||(c+=Me.units[p]||fe(dt(e,p))||""),(c+"").charAt(1)==="="&&(c=dt(e,p))):c=dt(e,p),d=parseFloat(c),y=m==="string"&&u.charAt(1)==="="&&u.substr(0,2),y&&(u=u.substr(2)),f=parseFloat(u),p in rt&&(p==="autoAlpha"&&(d===1&&dt(e,"visibility")==="hidden"&&f&&(d=0),k.push("visibility",0,s.visibility),It(this,s,"visibility",d?"inherit":"hidden",f?"inherit":"hidden",!f)),p!=="scale"&&p!=="transform"&&(p=rt[p],~p.indexOf(",")&&(p=p.split(",")[0]))),v=p in _t,v){if(this.styles.save(p),S=u,m==="string"&&u.substring(0,6)==="var(--"){if(u=Ae(e,u.substring(4,u.indexOf(")"))),u.substring(0,5)==="calc("){var T=e.style.perspective;e.style.perspective=u,u=Ae(e,"perspective"),T?e.style.perspective=T:Rt(e,"perspective")}f=parseFloat(u)}if(b||(x=e._gsap,x.renderTransform&&!t.parseTransform||eo(e,t.parseTransform),C=t.smoothOrigin!==!1&&x.smooth,b=this._pt=new be(this._pt,s,Q,0,1,x.renderTransform,x,0,-1),b.dep=1),p==="scale")this._pt=new be(this._pt,x,"scaleY",x.scaleY,(y?ga(x.scaleY,y+f):f)-x.scaleY||0,Ei),this._pt.u=0,n.push("scaleY",p),p+="X";else if(p==="transformOrigin"){k.push(we,0,s[we]),u=Vp(u),x.svg?ji(e,u,0,C,0,this):(_=parseFloat(u.split(" ")[2])||0,_!==x.zOrigin&&It(this,x,"zOrigin",x.zOrigin,_),It(this,s,p,Ro(c),Ro(u)));continue}else if(p==="svgOrigin"){ji(e,u,1,C,0,this);continue}else if(p in $s){zp(this,x,p,d,y?ga(d,y+u):u);continue}else if(p==="smoothOrigin"){It(this,x,"smooth",x.smooth,u);continue}else if(p==="force3D"){x[p]=u;continue}else if(p==="transform"){Fp(this,u,e);continue}}else p in s||(p=Ca(p)||p);if(v||(f||f===0)&&(d||d===0)&&!yp.test(u)&&p in s)g=(c+"").substr((d+"").length),f||(f=0),_=fe(u)||(p in Me.units?Me.units[p]:g),g!==_&&(d=Pt(e,p,c,_)),this._pt=new be(this._pt,v?x:s,p,d,(y?ga(d,y+f):f)-d,!v&&(_==="px"||p==="zIndex")&&t.autoRound!==!1?wp:Ei),this._pt.u=_||0,v&&S!==u?(this._pt.b=c,this._pt.e=S,this._pt.r=bp):g!==_&&_!=="%"&&(this._pt.b=c,this._pt.r=xp);else if(p in s)Bp.call(this,e,p,c,y?y+u:u);else if(p in e)this.add(e,p,c||e[p],y?y+u:u,i,r);else if(p!=="parseTransform"){rr(p,u);continue}v||(p in s?k.push(p,0,s[p]):typeof e[p]=="function"?k.push(p,2,e[p]()):k.push(p,1,c||e[p])),n.push(p)}}w&&Vs(this)},render:function(e,t){if(t.tween._time||!gr())for(var o=t._pt;o;)o.r(e,o.d),o=o._next;else t.styles.revert()},get:dt,aliases:rt,getSetter:function(e,t,o){var i=rt[t];return i&&i.indexOf(",")<0&&(t=i),t in _t&&t!==we&&(e._gsap.x||dt(e,"x"))?o&&vn===o?t==="scale"?Op:Cp:(vn=o||{})&&(t==="scale"?Tp:Up):e.style&&!ar(e.style[t])?Sp:~t.indexOf("-")?kp:dr(e,t)},core:{_removeProperty:Rt,_getMatrix:yr}};Se.utils.checkPrefix=Ca;Se.core.getStyleSaver=Fs;(function(a,e,t,o){var i=xe(a+","+e+","+t,function(r){_t[r]=1});xe(e,function(r){Me.units[r]="deg",$s[r]=1}),rt[i[13]]=a+","+e,xe(o,function(r){var n=r.split(":");rt[n[1]]=i[n[0]]})})("x,y,z,scale,scaleX,scaleY,xPercent,yPercent","rotation,rotationX,rotationY,skewX,skewY","transform,transformOrigin,svgOrigin,force3D,smoothOrigin,transformPerspective","0:translateX,1:translateY,2:translateZ,8:rotate,8:rotationZ,8:rotateZ,9:rotateX,10:rotateY");xe("x,y,z,top,right,bottom,left,width,height,fontSize,padding,margin,perspective",function(a){Me.units[a]="px"});Se.registerPlugin(Gs);var Ys=Se.registerPlugin(Gs)||Se;Ys.core.Tween;/*!
 * paths 3.15.0
 * https://gsap.com
 *
 * Copyright 2008-2026, GreenSock. All rights reserved.
 * Subject to the terms at https://gsap.com/standard-license
 * @author: Jack Doyle, jack@greensock.com
*/var Np=/[achlmqstvz]|(-?\d*\.?\d*(?:e[\-+]?\d+)?)[0-9]/ig,Ep=/(?:(-)?\d*\.?\d*(?:e[\-+]?\d+)?)[0-9]/ig,Lp=/[\+\-]?\d*\.?\d+e[\+\-]?\d+/ig,$p=/(^[#\.][a-z]|[a-y][a-z])/i,jp=Math.PI/180,Wp=180/Math.PI,ho=Math.sin,go=Math.cos,We=Math.abs,ht=Math.sqrt,Gp=Math.atan2,Wi=1e8,On=function(e){return typeof e=="string"},qs=function(e){return typeof e=="number"},Yp=function(e){return typeof e>"u"},qp={},Hp={},Po=1e5,Hs=function(e){return Math.round((e+Wi)%1*Po)/Po||(e<0?0:1)},E=function(e){return Math.round(e*Po)/Po||0},Tn=function(e){return Math.round(e*1e10)/1e10||0},Un=function(e){return e.closed=Math.abs(e[0]-e[e.length-2])<.001&&Math.abs(e[1]-e[e.length-1])<.001},In=function(e,t,o,i){var r=e[t],n=i===1?6:Gi(r,o,i);if((n||!i)&&n+o+2<r.length)return e.splice(t,0,r.slice(0,o+n+2)),r.splice(0,o+n),1},Xs=function(e,t,o){var i=e.length,r=~~(o*i);if(e[r]>t){for(;--r&&e[r]>t;);r<0&&(r=0)}else for(;e[++r]<t&&r<i;);return r<i?r:i-1},Xp=function(e,t){var o=e.length;for(e.reverse();o--;)e[o].reversed||Jp(e[o])},An=function(e,t){return t.totalLength=e.totalLength,e.samples?(t.samples=e.samples.slice(0),t.lookup=e.lookup.slice(0),t.minLength=e.minLength,t.resolution=e.resolution):e.totalPoints&&(t.totalPoints=e.totalPoints),t},Kp=function(e,t){var o=e.length,i=e[o-1]||[],r=i.length;o&&t[0]===i[r-2]&&t[1]===i[r-1]&&(t=i.concat(t.slice(2)),o--),e[o]=t};function wo(a){a=On(a)&&$p.test(a)&&document.querySelector(a)||a;var e=a.getAttribute?a:0,t;return e&&(a=a.getAttribute("d"))?(e._gsPath||(e._gsPath={}),t=e._gsPath[a],t&&!t._dirty?t:e._gsPath[a]=Do(a)):a?On(a)?Do(a):qs(a[0])?[a]:a:console.warn("Expecting a <path> element or an SVG path data string")}function Qp(a){for(var e=[],t=0;t<a.length;t++)e[t]=An(a[t],a[t].slice(0));return An(a,e)}function Jp(a){var e=0,t;for(a.reverse();e<a.length;e+=2)t=a[e],a[e]=a[e+1],a[e+1]=t;a.reversed=!a.reversed}var Zp=function(e,t){var o=document.createElementNS("http://www.w3.org/2000/svg","path"),i=[].slice.call(e.attributes),r=i.length,n;for(t=","+t+",";--r>-1;)n=i[r].nodeName.toLowerCase(),t.indexOf(","+n+",")<0&&o.setAttributeNS(null,n,i[r].nodeValue);return o},ed={rect:"rx,ry,x,y,width,height",circle:"r,cx,cy",ellipse:"rx,ry,cx,cy",line:"x1,x2,y1,y2"},td=function(e,t){for(var o=t?t.split(","):[],i={},r=o.length;--r>-1;)i[o[r]]=+e.getAttribute(o[r])||0;return i};function ad(a,e){var t=a.tagName.toLowerCase(),o=.552284749831,i,r,n,s,l,c,u,f,d,m,h,p,g,_,y,v,b,x,C,w,k,S;return t==="path"||!a.getBBox?a:(c=Zp(a,"x,y,width,height,cx,cy,rx,ry,r,x1,x2,y1,y2,points"),S=td(a,ed[t]),t==="rect"?(s=S.rx,l=S.ry||s,r=S.x,n=S.y,m=S.width-s*2,h=S.height-l*2,s||l?(p=r+s*(1-o),g=r+s,_=g+m,y=_+s*o,v=_+s,b=n+l*(1-o),x=n+l,C=x+h,w=C+l*o,k=C+l,i="M"+v+","+x+" V"+C+" C"+[v,w,y,k,_,k,_-(_-g)/3,k,g+(_-g)/3,k,g,k,p,k,r,w,r,C,r,C-(C-x)/3,r,x+(C-x)/3,r,x,r,b,p,n,g,n,g+(_-g)/3,n,_-(_-g)/3,n,_,n,y,n,v,b,v,x].join(",")+"z"):i="M"+(r+m)+","+n+" v"+h+" h"+-m+" v"+-h+" h"+m+"z"):t==="circle"||t==="ellipse"?(t==="circle"?(s=l=S.r,f=s*o):(s=S.rx,l=S.ry,f=l*o),r=S.cx,n=S.cy,u=s*o,i="M"+(r+s)+","+n+" C"+[r+s,n+f,r+u,n+l,r,n+l,r-u,n+l,r-s,n+f,r-s,n,r-s,n-f,r-u,n-l,r,n-l,r+u,n-l,r+s,n-f,r+s,n].join(",")+"z"):t==="line"?i="M"+S.x1+","+S.y1+" L"+S.x2+","+S.y2:(t==="polyline"||t==="polygon")&&(d=(a.getAttribute("points")+"").match(Ep)||[],r=d.shift(),n=d.shift(),i="M"+r+","+n+" L"+d.join(","),t==="polygon"&&(i+=","+r+","+n+"z")),c.setAttribute("d",Js(c._gsRawPath=Do(i))),e&&a.parentNode&&(a.parentNode.insertBefore(c,a),a.parentNode.removeChild(a)),c)}function Ks(a,e,t){var o=a[e],i=a[e+2],r=a[e+4],n;return o+=(i-o)*t,i+=(r-i)*t,o+=(i-o)*t,n=i+(r+(a[e+6]-r)*t-i)*t-o,o=a[e+1],i=a[e+3],r=a[e+5],o+=(i-o)*t,i+=(r-i)*t,o+=(i-o)*t,E(Gp(i+(r+(a[e+7]-r)*t-i)*t-o,n)*Wp)}function Qs(a,e,t){t=Yp(t)?1:Tn(t)||0,e=Tn(e)||0;var o=Math.max(0,~~(We(t-e)-1e-8)),i=Qp(a);if(e>t&&(e=1-e,t=1-t,Xp(i),i.totalLength=0),e<0||t<0){var r=Math.abs(~~Math.min(e,t))+1;e+=r,t+=r}i.totalLength||Jt(i);var n=t>1,s=Mn(i,e,qp,!0),l=Mn(i,t,Hp),c=l.segment,u=s.segment,f=l.segIndex,d=s.segIndex,m=l.i,h=s.i,p=d===f,g=m===h&&p,_,y,v,b,x,C,w,k;if(n||o){for(_=f<d||p&&m<h||g&&l.t<s.t,In(i,d,h,s.t)&&(d++,_||(f++,g?(l.t=(l.t-s.t)/(1-s.t),m=0):p&&(m-=h))),Math.abs(1-(t-e))<1e-5?f=d-1:!l.t&&f?f--:In(i,f,m,l.t)&&_&&d++,s.t===1&&(d=(d+1)%i.length),x=[],C=i.length,w=1+C*o,k=d,w+=(C-d+f)%C,b=0;b<w;b++)Kp(x,i[k++%C]);i=x}else if(v=l.t===1?6:Gi(c,m,l.t),e!==t)for(y=Gi(u,h,g?s.t/l.t:s.t),p&&(v+=y),c.splice(m+v+2),(y||h)&&u.splice(0,h+y),b=i.length;b--;)(b<d||b>f)&&i.splice(b,1);else c.angle=Ks(c,m+v,0),m+=v,s=c[m],l=c[m+1],c.length=c.totalLength=0,c.totalPoints=i.totalPoints=8,c.push(s,l,s,l,s,l,s,l);return i.totalLength=0,i}function od(a,e,t){e=e||0,a.samples||(a.samples=[],a.lookup=[]);var o=~~a.resolution||12,i=1/o,r=a.length,n=a[e],s=a[e+1],l=e?e/6*o:0,c=a.samples,u=a.lookup,f=(e?a.minLength:Wi)||Wi,d=c[l+t*o-1],m=e?c[l-1]:0,h,p,g,_,y,v,b,x,C,w,k,S,T,A,M,V,N;for(c.length=u.length=0,p=e+2;p<r;p+=6){if(g=a[p+4]-n,_=a[p+2]-n,y=a[p]-n,x=a[p+5]-s,C=a[p+3]-s,w=a[p+1]-s,v=b=k=S=0,We(g)<.01&&We(x)<.01&&We(y)+We(w)<.01)a.length>8&&(a.splice(p,6),p-=6,r-=6);else for(h=1;h<=o;h++)A=i*h,T=1-A,v=b-(b=(A*A*g+3*T*(A*_+T*y))*A),k=S-(S=(A*A*x+3*T*(A*C+T*w))*A),V=ht(k*k+v*v),V<f&&(f=V),m+=V,c[l++]=m;n+=g,s+=x}if(d)for(d-=m;l<c.length;l++)c[l]+=d;if(c.length&&f){if(a.totalLength=N=c[c.length-1]||0,a.minLength=f,N/f<9999)for(V=M=0,h=0;h<N;h+=f)u[V++]=c[M]<h?++M:M}else a.totalLength=c[0]=0;return e?m-c[e/2-1]:m}function Jt(a,e){var t,o,i;for(i=t=o=0;i<a.length;i++)a[i].resolution=~~e||12,t+=od(a[i]),o+=a[i].length;return a.totalPoints=o,a.totalLength=t,a}function Gi(a,e,t){if(t<=0||t>=1)return 0;var o=a[e],i=a[e+1],r=a[e+2],n=a[e+3],s=a[e+4],l=a[e+5],c=a[e+6],u=a[e+7],f=o+(r-o)*t,d=r+(s-r)*t,m=i+(n-i)*t,h=n+(l-n)*t,p=f+(d-f)*t,g=m+(h-m)*t,_=s+(c-s)*t,y=l+(u-l)*t;return d+=(_-d)*t,h+=(y-h)*t,a.splice(e+2,4,E(f),E(m),E(p),E(g),E(p+(d-p)*t),E(g+(h-g)*t),E(d),E(h),E(_),E(y)),a.samples&&a.samples.splice(e/6*a.resolution|0,0,0,0,0,0,0,0),6}function Mn(a,e,t,o){t=t||{},a.totalLength||Jt(a),(e<0||e>1)&&(e=Hs(e));var i=0,r=a[0],n,s,l,c,u,f,d;if(!e)d=f=i=0,r=a[0];else if(e===1)d=1,i=a.length-1,r=a[i],f=r.length-8;else{if(a.length>1){for(l=a.totalLength*e,u=f=0;(u+=a[f++].totalLength)<l;)i=f;r=a[i],c=u-r.totalLength,e=(l-c)/(u-c)||0}n=r.samples,s=r.resolution,l=r.totalLength*e,f=r.lookup.length?r.lookup[~~(l/r.minLength)]||0:Xs(n,l,e),c=f?n[f-1]:0,u=n[f],u<l&&(c=u,u=n[++f]),d=1/s*((l-c)/(u-c)+f%s),f=~~(f/s)*6,o&&d===1&&(f+6<r.length?(f+=6,d=0):i+1<a.length&&(f=d=0,r=a[++i]))}return t.t=d,t.i=f,t.path=a,t.segment=r,t.segIndex=i,t}function Bn(a,e,t,o){var i=a[0],r=o||{},n,s,l,c,u,f,d,m,h;if((e<0||e>1)&&(e=Hs(e)),i.lookup||Jt(a),a.length>1){for(l=a.totalLength*e,u=f=0;(u+=a[f++].totalLength)<l;)i=a[f];c=u-i.totalLength,e=(l-c)/(u-c)||0}return n=i.samples,s=i.resolution,l=i.totalLength*e,f=i.lookup.length?i.lookup[e<1?~~(l/i.minLength):i.lookup.length-1]||0:Xs(n,l,e),c=f?n[f-1]:0,u=n[f],u<l&&(c=u,u=n[++f]),d=1/s*((l-c)/(u-c)+f%s)||0,h=1-d,f=~~(f/s)*6,m=i[f],r.x=E((d*d*(i[f+6]-m)+3*h*(d*(i[f+4]-m)+h*(i[f+2]-m)))*d+m),r.y=E((d*d*(i[f+7]-(m=i[f+1]))+3*h*(d*(i[f+5]-m)+h*(i[f+3]-m)))*d+m),t&&(r.angle=i.totalLength?Ks(i,f,d>=1?1-1e-9:d||1e-9):i.angle||0),r}function Da(a,e,t,o,i,r,n){for(var s=a.length,l,c,u,f,d;--s>-1;)for(l=a[s],c=l.length,u=0;u<c;u+=2)f=l[u],d=l[u+1],l[u]=f*e+d*o+r,l[u+1]=f*t+d*i+n;return a._dirty=1,a}function id(a,e,t,o,i,r,n,s,l){if(!(a===s&&e===l)){t=We(t),o=We(o);var c=i%360*jp,u=go(c),f=ho(c),d=Math.PI,m=d*2,h=(a-s)/2,p=(e-l)/2,g=u*h+f*p,_=-f*h+u*p,y=g*g,v=_*_,b=y/(t*t)+v/(o*o);b>1&&(t=ht(b)*t,o=ht(b)*o);var x=t*t,C=o*o,w=(x*C-x*v-C*y)/(x*v+C*y);w<0&&(w=0);var k=(r===n?-1:1)*ht(w),S=k*(t*_/o),T=k*-(o*g/t),A=(a+s)/2,M=(e+l)/2,V=A+(u*S-f*T),N=M+(f*S+u*T),F=(g-S)/t,D=(_-T)/o,$=(-g-S)/t,ae=(-_-T)/o,Re=F*F+D*D,bt=(D<0?-1:1)*Math.acos(F/ht(Re)),me=(F*ae-D*$<0?-1:1)*Math.acos((F*$+D*ae)/ht(Re*($*$+ae*ae)));isNaN(me)&&(me=d),!n&&me>0?me-=m:n&&me<0&&(me+=m),bt%=m,me%=m;var Qe=Math.ceil(We(me)/(m/4)),Pe=[],ve=me/Qe,De=4/3*ho(ve/2)/(1+go(ve/2)),_l=u*t,xl=f*t,bl=f*-o,wl=u*o,ke;for(ke=0;ke<Qe;ke++)i=bt+ke*ve,g=go(i),_=ho(i),F=go(i+=ve),D=ho(i),Pe.push(g-De*_,_+De*g,F+De*D,D-De*F,F,D);for(ke=0;ke<Pe.length;ke+=2)g=Pe[ke],_=Pe[ke+1],Pe[ke]=g*_l+_*bl+V,Pe[ke+1]=g*xl+_*wl+N;return Pe[ke-2]=s,Pe[ke-1]=l,Pe}}function Do(a){var e=(a+"").replace(Lp,function(S){var T=+S;return T<1e-4&&T>-1e-4?0:T}).match(Np)||[],t=[],o=0,i=0,r=2/3,n=e.length,s=0,l="ERROR: malformed path: "+a,c,u,f,d,m,h,p,g,_,y,v,b,x,C,w,k=function(T,A,M,V){y=(M-T)/3,v=(V-A)/3,p.push(T+y,A+v,M-y,V-v,M,V)};if(!a||!isNaN(e[0])||isNaN(e[1]))return console.log(l),t;for(c=0;c<n;c++)if(x=m,isNaN(e[c])?(m=e[c].toUpperCase(),h=m!==e[c]):c--,f=+e[c+1],d=+e[c+2],h&&(f+=o,d+=i),c||(g=f,_=d),m==="M")p&&(p.length<8?t.length-=1:s+=p.length,Un(p)),o=g=f,i=_=d,p=[f,d],t.push(p),c+=2,m="L";else if(m==="C")p||(p=[0,0]),h||(o=i=0),p.push(f,d,o+e[c+3]*1,i+e[c+4]*1,o+=e[c+5]*1,i+=e[c+6]*1),c+=6;else if(m==="S")y=o,v=i,(x==="C"||x==="S")&&(y+=o-p[p.length-4],v+=i-p[p.length-3]),h||(o=i=0),p.push(y,v,f,d,o+=e[c+3]*1,i+=e[c+4]*1),c+=4;else if(m==="Q")y=o+(f-o)*r,v=i+(d-i)*r,h||(o=i=0),o+=e[c+3]*1,i+=e[c+4]*1,p.push(y,v,o+(f-o)*r,i+(d-i)*r,o,i),c+=4;else if(m==="T")y=o-p[p.length-4],v=i-p[p.length-3],p.push(o+y,i+v,f+(o+y*1.5-f)*r,d+(i+v*1.5-d)*r,o=f,i=d),c+=2;else if(m==="H")k(o,i,o=f,i),c+=1;else if(m==="V")k(o,i,o,i=f+(h?i-o:0)),c+=1;else if(m==="L"||m==="Z")m==="Z"&&(f=g,d=_,p.closed=!0),(m==="L"||We(o-f)>.5||We(i-d)>.5)&&(k(o,i,f,d),m==="L"&&(c+=2)),o=f,i=d;else if(m==="A"){if(C=e[c+4],w=e[c+5],y=e[c+6],v=e[c+7],u=7,C.length>1&&(C.length<3?(v=y,y=w,u--):(v=w,y=C.substr(2),u-=2),w=C.charAt(1),C=C.charAt(0)),b=id(o,i,+e[c+1],+e[c+2],+e[c+3],+C,+w,(h?o:0)+y*1,(h?i:0)+v*1),c+=u,b)for(u=0;u<b.length;u++)p.push(b[u]);o=p[p.length-2],i=p[p.length-1]}else console.log(l);return c=p.length,c<6?(t.pop(),c=0):Un(p),t.totalPoints=s+c,t}function rd(a,e){e===void 0&&(e=1);for(var t=a[0],o=0,i=[t,o],r=2;r<a.length;r+=2)i.push(t,o,a[r],o=(a[r]-t)*e/2,t=a[r],-o);return i}function Yi(a,e){We(a[0]-a[2])<1e-4&&We(a[1]-a[3])<1e-4&&(a=a.slice(2));var t=a.length-2,o=+a[0],i=+a[1],r=+a[2],n=+a[3],s=[o,i,o,i],l=r-o,c=n-i,u=a.nonSmooth||[],f=Math.abs(a[t]-o)<.001&&Math.abs(a[t+1]-i)<.001,d,m,h,p,g,_,y,v,b,x,C,w,k,S,T;if(!t)return[o,i,o,i,o,i,o,i];for(f&&(a.push(r,n),r=o,n=i,o=a[t-2],i=a[t-1],a.unshift(o,i),t+=4,u=[0,0].concat(u)),e=e||e===0?+e:1,h=2;h<t;h+=2)if(d=o,m=i,o=r,i=n,r=+a[h+2],n=+a[h+3],!(o===r&&i===n)){if(p=l,g=c,l=r-o,c=n-i,u[h]){s.push(o-(o-d)/4,i-(i-m)/4,o,i,o+(r-o)/4,i+(n-i)/4);continue}_=ht(p*p+g*g),y=ht(l*l+c*c),v=ht(Math.pow(l/y+p/_,2)+Math.pow(c/y+g/_,2)),b=(_+y)*e*.25/v,x=o-(o-d)*(_?b/_:0),C=o+(r-o)*(y?b/y:0),w=o-(x+((C-x)*(_*3/(_+y)+.5)/4||0)),k=i-(i-m)*(_?b/_:0),S=i+(n-i)*(y?b/y:0),T=i-(k+((S-k)*(_*3/(_+y)+.5)/4||0)),s.push(E(x+w),E(k+T),E(o),E(i),E(C+w),E(S+T))}return o!==r||i!==n||s.length<4?s.push(E(r),E(n),E(r),E(n)):s.length-=2,s.length===2?s.push(o,i,o,i,o,i):f&&(s.splice(0,6),s.length-=6),s.closed=f,s}function Js(a){qs(a[0])&&(a=[a]);var e="",t=a.length,o,i,r,n;for(i=0;i<t;i++){for(n=a[i],e+="M"+E(n[0])+","+E(n[1])+" C",o=n.length,r=2;r<o;r++)e+=E(n[r++])+","+E(n[r++])+" "+E(n[r++])+","+E(n[r++])+" "+E(n[r++])+","+E(n[r])+" ";n.closed&&(e+="z")}return e}/*!
 * matrix 3.15.0
 * https://gsap.com
 *
 * Copyright 2008-2026, GreenSock. All rights reserved.
 * Subject to the terms at https://gsap.com/standard-license
 * @author: Jack Doyle, jack@greensock.com
*/var gt,Zt,_r,qo,za,So,zo,ja,Xe="transform",qi=Xe+"Origin",Zs,el=function(e){var t=e.ownerDocument||e;for(!(Xe in e.style)&&("msTransform"in e.style)&&(Xe="msTransform",qi=Xe+"Origin");t.parentNode&&(t=t.parentNode););if(Zt=window,zo=new to,t){gt=t,_r=t.documentElement,qo=t.body,ja=gt.createElementNS("http://www.w3.org/2000/svg","g"),ja.style.transform="none";var o=t.createElement("div"),i=t.createElement("div"),r=t&&(t.body||t.firstElementChild);r&&r.appendChild&&(r.appendChild(o),o.appendChild(i),o.style.position="static",o.style.transform="translate3d(0,0,1px)",Zs=i.offsetParent!==o,r.removeChild(o))}return t},nd=function(e){for(var t,o;e&&e!==qo;)o=e._gsap,o&&o.uncache&&o.get(e,"x"),o&&!o.scaleX&&!o.scaleY&&o.renderTransform&&(o.scaleX=o.scaleY=1e-4,o.renderTransform(1,o),t?t.push(o):t=[o]),e=e.parentNode;return t},tl=[],al=[],sd=function(){return Zt.pageYOffset||gt.scrollTop||_r.scrollTop||qo.scrollTop||0},ld=function(){return Zt.pageXOffset||gt.scrollLeft||_r.scrollLeft||qo.scrollLeft||0},xr=function(e){return e.ownerSVGElement||((e.tagName+"").toLowerCase()==="svg"?e:null)},cd=function a(e){if(Zt.getComputedStyle(e).position==="fixed")return!0;if(e=e.parentNode,e&&e.nodeType===1)return a(e)},vi=function a(e,t){if(e.parentNode&&(gt||el(e))){var o=xr(e),i=o?o.getAttribute("xmlns")||"http://www.w3.org/2000/svg":"http://www.w3.org/1999/xhtml",r=o?t?"rect":"g":"div",n=t!==2?0:100,s=t===3?100:0,l={position:"absolute",display:"block",pointerEvents:"none",margin:"0",padding:"0"},c=gt.createElementNS?gt.createElementNS(i.replace(/^https/,"http"),r):gt.createElement(r);return t&&(o?(So||(So=a(e)),c.setAttribute("width",.01),c.setAttribute("height",.01),c.setAttribute("transform","translate("+n+","+s+")"),c.setAttribute("fill","transparent"),So.appendChild(c)):(za||(za=a(e),Object.assign(za.style,l)),Object.assign(c.style,l,{width:"0.1px",height:"0.1px",top:s+"px",left:n+"px"}),za.appendChild(c))),c}throw"Need document and parent."},ud=function(e){for(var t=new to,o=0;o<e.numberOfItems;o++)t.multiply(e.getItem(o).matrix);return t},fd=function(e){var t=e.getCTM(),o;return t||(o=e.style[Xe],e.style[Xe]="none",e.appendChild(ja),t=ja.getCTM(),e.removeChild(ja),o?e.style[Xe]=o:e.style.removeProperty(Xe.replace(/([A-Z])/g,"-$1").toLowerCase())),t||zo.clone()},pd=function(e,t){var o=xr(e),i=e===o,r=o?tl:al,n=e.parentNode,s=n&&!o&&n.shadowRoot&&n.shadowRoot.appendChild?n.shadowRoot:n,l,c,u,f,d,m;if(e===Zt)return e;if(r.length||r.push(vi(e,1),vi(e,2),vi(e,3)),l=o?So:za,o)i?(u=fd(e),f=-u.e/u.a,d=-u.f/u.d,c=zo):e.getBBox?(u=e.getBBox(),c=e.transform?e.transform.baseVal:{},c=c.numberOfItems?c.numberOfItems>1?ud(c):c.getItem(0).matrix:zo,f=c.a*u.x+c.c*u.y,d=c.b*u.x+c.d*u.y):(c=new to,f=d=0),t&&e.tagName.toLowerCase()==="g"&&(f=d=0),(i||!e.getBoundingClientRect().width?o:n).appendChild(l),l.setAttribute("transform","matrix("+c.a+","+c.b+","+c.c+","+c.d+","+(c.e+f)+","+(c.f+d)+")");else{if(f=d=0,Zs)for(c=e.offsetParent,u=e;u&&(u=u.parentNode)&&u!==c&&u.parentNode;)(Zt.getComputedStyle(u)[Xe]+"").length>4&&(f=u.offsetLeft,d=u.offsetTop,u=0);if(m=Zt.getComputedStyle(e),m.position!=="absolute"&&m.position!=="fixed")for(c=e.offsetParent;n&&n!==c;)f+=n.scrollLeft||0,d+=n.scrollTop||0,n=n.parentNode;u=l.style,u.top=e.offsetTop-d+"px",u.left=e.offsetLeft-f+"px",u[Xe]=m[Xe],u[qi]=m[qi],u.position=m.position==="fixed"?"fixed":"absolute",s.appendChild(l)}return l},yi=function(e,t,o,i,r,n,s){return e.a=t,e.b=o,e.c=i,e.d=r,e.e=n,e.f=s,e},to=function(){function a(t,o,i,r,n,s){t===void 0&&(t=1),o===void 0&&(o=0),i===void 0&&(i=0),r===void 0&&(r=1),n===void 0&&(n=0),s===void 0&&(s=0),yi(this,t,o,i,r,n,s)}var e=a.prototype;return e.inverse=function(){var o=this.a,i=this.b,r=this.c,n=this.d,s=this.e,l=this.f,c=o*n-i*r||1e-10;return yi(this,n/c,-i/c,-r/c,o/c,(r*l-n*s)/c,-(o*l-i*s)/c)},e.multiply=function(o){var i=this.a,r=this.b,n=this.c,s=this.d,l=this.e,c=this.f,u=o.a,f=o.c,d=o.b,m=o.d,h=o.e,p=o.f;return yi(this,u*i+d*n,u*r+d*s,f*i+m*n,f*r+m*s,l+h*i+p*n,c+h*r+p*s)},e.clone=function(){return new a(this.a,this.b,this.c,this.d,this.e,this.f)},e.equals=function(o){var i=this.a,r=this.b,n=this.c,s=this.d,l=this.e,c=this.f;return i===o.a&&r===o.b&&n===o.c&&s===o.d&&l===o.e&&c===o.f},e.apply=function(o,i){i===void 0&&(i={});var r=o.x,n=o.y,s=this.a,l=this.b,c=this.c,u=this.d,f=this.e,d=this.f;return i.x=r*s+n*c+f||0,i.y=r*l+n*u+d||0,i},a}();function _a(a,e,t,o){if(!a||!a.parentNode||(gt||el(a)).documentElement===a)return new to;var i=nd(a),r=xr(a),n=r?tl:al,s=pd(a,t),l=n[0].getBoundingClientRect(),c=n[1].getBoundingClientRect(),u=n[2].getBoundingClientRect(),f=s.parentNode,d=!o&&cd(a),m=new to((c.left-l.left)/100,(c.top-l.top)/100,(u.left-l.left)/100,(u.top-l.top)/100,l.left+(d?0:ld()),l.top+(d?0:sd()));if(f.removeChild(s),i)for(l=i.length;l--;)c=i[l],c.scaleX=c.scaleY=0,c.renderTransform(1,c);return e?m.inverse():m}/*!
 * MotionPathPlugin 3.15.0
 * https://gsap.com
 *
 * @license Copyright 2008-2026, GreenSock. All rights reserved.
 * Subject to the terms at https://gsap.com/standard-license
 * @author: Jack Doyle, jack@greensock.com
*/var dd="x,translateX,left,marginLeft,xPercent".split(","),md="y,translateY,top,marginTop,yPercent".split(","),hd=Math.PI/180,Le,ol,sa,Hi,_i,Vn,gd=function(){return Le||typeof window<"u"&&(Le=window.gsap)&&Le.registerPlugin&&Le},Va=function(e,t,o,i){for(var r=t.length,n=i===2?0:i,s=0;s<r;s++)e[n]=parseFloat(t[s][o]),i===2&&(e[n+1]=0),n+=2;return e},pa=function(e,t,o){return parseFloat(e._gsap.get(e,t,o||"px"))||0},il=function(e){var t=e[0],o=e[1],i;for(i=2;i<e.length;i+=2)t=e[i]+=t,o=e[i+1]+=o},Rn=function(e,t,o,i,r,n,s,l,c){if(s.type==="cubic")t=[t];else{s.fromCurrent!==!1&&t.unshift(pa(o,i,l),r?pa(o,r,c):0),s.relative&&il(t);var u=r?Yi:rd;t=[u(t,s.curviness)]}return t=n(rl(t,o,s)),Fo(e,o,i,t,"x",l),r&&Fo(e,o,r,t,"y",c),Jt(t,s.resolution||(s.curviness===0?20:12))},vd=function(e){return e},yd=/[-+\.]*\d+\.?(?:e-|e\+)?\d*/g,Pn=function(e,t,o){var i=_a(e),r=0,n=0,s;return(e.tagName+"").toLowerCase()==="svg"?(s=e.viewBox.baseVal,s.width||(s={width:+e.getAttribute("width"),height:+e.getAttribute("height")})):s=t&&e.getBBox&&e.getBBox(),t&&t!=="auto"&&(r=t.push?t[0]*(s?s.width:e.offsetWidth||0):t.x,n=t.push?t[1]*(s?s.height:e.offsetHeight||0):t.y),o.apply(r||n?i.apply({x:r,y:n}):{x:i.e,y:i.f})},Xi=function(e,t,o,i){var r=_a(e.parentNode,!0,!0),n=r.clone().multiply(_a(t)),s=Pn(e,o,r),l=Pn(t,i,r),c=l.x,u=l.y,f;return n.e=n.f=0,i==="auto"&&t.getTotalLength&&t.tagName.toLowerCase()==="path"&&(f=t.getAttribute("d").match(yd)||[],f=n.apply({x:+f[0],y:+f[1]}),c+=f.x,u+=f.y),f&&(f=n.apply(t.getBBox()),c-=f.x,u-=f.y),n.e=c-s.x,n.f=u-s.y,n},rl=function(e,t,o){var i=o.align,r=o.matrix,n=o.offsetX,s=o.offsetY,l=o.alignOrigin,c=e[0][0],u=e[0][1],f=pa(t,"x"),d=pa(t,"y"),m,h,p;return!e||!e.length?wo("M0,0L0,0"):(i&&(i==="self"||(m=Hi(i)[0]||t)===t?Da(e,1,0,0,1,f-c,d-u):(l&&l[2]!==!1?Le.set(t,{transformOrigin:l[0]*100+"% "+l[1]*100+"%"}):l=[pa(t,"xPercent")/-100,pa(t,"yPercent")/-100],h=Xi(t,m,l,"auto"),p=h.apply({x:c,y:u}),Da(e,h.a,h.b,h.c,h.d,f+h.e-(p.x-h.e),d+h.f-(p.y-h.f)))),r?Da(e,r.a,r.b,r.c,r.d,r.e,r.f):(n||s)&&Da(e,1,0,0,1,n||0,s||0),e)},Fo=function(e,t,o,i,r,n){var s=t._gsap,l=s.harness,c=l&&l.aliases&&l.aliases[o],u=c&&c.indexOf(",")<0?c:o,f=e._pt=new ol(e._pt,t,u,0,0,vd,0,s.set(t,u,e));f.u=sa(s.get(t,u,n))||0,f.path=i,f.pp=r,e._props.push(u)},_d=function(e,t){return function(o){return e||t!==1?Qs(o,e,t):o}},nl={version:"3.15.0",name:"motionPath",register:function(e,t,o){Le=e,sa=Le.utils.getUnit,Hi=Le.utils.toArray,_i=Le.core.getStyleSaver,Vn=Le.core.reverting||function(){},ol=o},init:function(e,t,o){if(!Le)return console.warn("Please gsap.registerPlugin(MotionPathPlugin)"),!1;(!(typeof t=="object"&&!t.style)||!t.path)&&(t={path:t});var i=[],r=t,n=r.path,s=r.autoRotate,l=r.unitX,c=r.unitY,u=r.x,f=r.y,d=n[0],m=_d(t.start,"end"in t?t.end:1),h,p;if(this.rawPaths=i,this.target=e,this.tween=o,this.styles=_i&&_i(e,"transform"),(this.rotate=s||s===0)&&(this.rOffset=parseFloat(s)||0,this.radians=!!t.useRadians,this.rProp=t.rotation||"rotation",this.rSet=e._gsap.set(e,this.rProp,this),this.ru=sa(e._gsap.get(e,this.rProp))||0),Array.isArray(n)&&!("closed"in n)&&typeof d!="number"){for(p in d)!u&&~dd.indexOf(p)?u=p:!f&&~md.indexOf(p)&&(f=p);u&&f?i.push(Rn(this,Va(Va([],n,u,0),n,f,1),e,u,f,m,t,l||sa(n[0][u]),c||sa(n[0][f]))):u=f=0;for(p in d)p!==u&&p!==f&&i.push(Rn(this,Va([],n,p,2),e,p,0,m,t,sa(n[0][p])))}else h=m(rl(wo(t.path),e,t)),Jt(h,t.resolution),i.push(h),Fo(this,e,t.x||"x",h,"x",t.unitX||"px"),Fo(this,e,t.y||"y",h,"y",t.unitY||"px");o.vars.immediateRender&&this.render(o.progress(),this)},render:function(e,t){var o=t.rawPaths,i=o.length,r=t._pt;if(t.tween._time||!Vn()){for(e>1?e=1:e<0&&(e=0);i--;)Bn(o[i],e,!i&&t.rotate,o[i]);for(;r;)r.set(r.t,r.p,r.path[r.pp]+r.u,r.d,e),r=r._next;t.rotate&&t.rSet(t.target,t.rProp,o[0].angle*(t.radians?hd:1)+t.rOffset+t.ru,t,e)}else t.styles.revert()},getLength:function(e){return Jt(wo(e)).totalLength},sliceRawPath:Qs,getRawPath:wo,pointsToSegment:Yi,stringToRawPath:Do,rawPathToString:Js,transformRawPath:Da,getGlobalMatrix:_a,getPositionOnPath:Bn,cacheRawPathMeasurements:Jt,convertToPath:function(e,t){return Hi(e).map(function(o){return ad(o,t!==!1)})},convertCoordinates:function(e,t,o){var i=_a(t,!0,!0).multiply(_a(e));return o?i.apply(o):i},getAlignMatrix:Xi,getRelativePosition:function(e,t,o,i){var r=Xi(e,t,o,i);return{x:r.e,y:r.f}},arrayToRawPath:function(e,t){t=t||{};var o=Va(Va([],e,t.x||"x",0),e,t.y||"y",1);return t.relative&&il(o),[t.type==="cubic"?o:Yi(o,t.curviness)]}};gd()&&Le.registerPlugin(nl);Ys.registerPlugin(nl);const br=Symbol.for("yaml.alias"),xd=Symbol.for("yaml.document"),ea=Symbol.for("yaml.map"),sl=Symbol.for("yaml.pair"),wr=Symbol.for("yaml.scalar"),lo=Symbol.for("yaml.seq"),st=Symbol.for("yaml.node.type"),Ia=a=>!!a&&typeof a=="object"&&a[st]===br,Ho=a=>!!a&&typeof a=="object"&&a[st]===xd,ll=a=>!!a&&typeof a=="object"&&a[st]===ea,le=a=>!!a&&typeof a=="object"&&a[st]===sl,ie=a=>!!a&&typeof a=="object"&&a[st]===wr,Sr=a=>!!a&&typeof a=="object"&&a[st]===lo;function Ue(a){if(a&&typeof a=="object")switch(a[st]){case ea:case lo:return!0}return!1}function de(a){if(a&&typeof a=="object")switch(a[st]){case br:case ea:case wr:case lo:return!0}return!1}const cl=a=>(ie(a)||Ue(a))&&!!a.anchor,Gt=Symbol("break visit"),bd=Symbol("skip children"),Wa=Symbol("remove node");function Xo(a,e){const t=wd(e);Ho(a)?da(null,a.contents,t,Object.freeze([a]))===Wa&&(a.contents=null):da(null,a,t,Object.freeze([]))}Xo.BREAK=Gt;Xo.SKIP=bd;Xo.REMOVE=Wa;function da(a,e,t,o){const i=Sd(a,e,t,o);if(de(i)||le(i))return kd(a,o,i),da(a,i,t,o);if(typeof i!="symbol"){if(Ue(e)){o=Object.freeze(o.concat(e));for(let r=0;r<e.items.length;++r){const n=da(r,e.items[r],t,o);if(typeof n=="number")r=n-1;else{if(n===Gt)return Gt;n===Wa&&(e.items.splice(r,1),r-=1)}}}else if(le(e)){o=Object.freeze(o.concat(e));const r=da("key",e.key,t,o);if(r===Gt)return Gt;r===Wa&&(e.key=null);const n=da("value",e.value,t,o);if(n===Gt)return Gt;n===Wa&&(e.value=null)}}return i}function wd(a){return typeof a=="object"&&(a.Collection||a.Node||a.Value)?Object.assign({Alias:a.Node,Map:a.Node,Scalar:a.Node,Seq:a.Node},a.Value&&{Map:a.Value,Scalar:a.Value,Seq:a.Value},a.Collection&&{Map:a.Collection,Seq:a.Collection},a):a}function Sd(a,e,t,o){if(typeof t=="function")return t(a,e,o);if(ll(e))return t.Map?.(a,e,o);if(Sr(e))return t.Seq?.(a,e,o);if(le(e))return t.Pair?.(a,e,o);if(ie(e))return t.Scalar?.(a,e,o);if(Ia(e))return t.Alias?.(a,e,o)}function kd(a,e,t){const o=e[e.length-1];if(Ue(o))o.items[a]=t;else if(le(o))a==="key"?o.key=t:o.value=t;else if(Ho(o))o.contents=t;else{const i=Ia(o)?"alias":"scalar";throw new Error(`Cannot replace node with ${i} parent`)}}function ul(a){if(/[\x00-\x19\s,[\]{}]/.test(a)){const t=`Anchor must not contain whitespace or control characters: ${JSON.stringify(a)}`;throw new Error(t)}return!0}function Fa(a,e,t,o){if(o&&typeof o=="object")if(Array.isArray(o))for(let i=0,r=o.length;i<r;++i){const n=o[i],s=Fa(a,o,String(i),n);s===void 0?delete o[i]:s!==n&&(o[i]=s)}else if(o instanceof Map)for(const i of Array.from(o.keys())){const r=o.get(i),n=Fa(a,o,i,r);n===void 0?o.delete(i):n!==r&&o.set(i,n)}else if(o instanceof Set)for(const i of Array.from(o)){const r=Fa(a,o,i,i);r===void 0?o.delete(i):r!==i&&(o.delete(i),o.add(r))}else for(const[i,r]of Object.entries(o)){const n=Fa(a,o,i,r);n===void 0?delete o[i]:n!==r&&(o[i]=n)}return a.call(e,t,o)}function Ke(a,e,t){if(Array.isArray(a))return a.map((o,i)=>Ke(o,String(i),t));if(a&&typeof a.toJSON=="function"){if(!t||!cl(a))return a.toJSON(e,t);const o={aliasCount:0,count:1,res:void 0};t.anchors.set(a,o),t.onCreate=r=>{o.res=r,delete t.onCreate};const i=a.toJSON(e,t);return t.onCreate&&t.onCreate(i),i}return typeof a=="bigint"&&!t?.keep?Number(a):a}class kr{constructor(e){Object.defineProperty(this,st,{value:e})}clone(){const e=Object.create(Object.getPrototypeOf(this),Object.getOwnPropertyDescriptors(this));return this.range&&(e.range=this.range.slice()),e}toJS(e,{mapAsMap:t,maxAliasCount:o,onAnchor:i,reviver:r}={}){if(!Ho(e))throw new TypeError("A document argument is required");const n={anchors:new Map,doc:e,keep:!0,mapAsMap:t===!0,mapKeyWarned:!1,maxAliasCount:typeof o=="number"?o:100},s=Ke(this,"",n);if(typeof i=="function")for(const{count:l,res:c}of n.anchors.values())i(c,l);return typeof r=="function"?Fa(r,{"":s},"",s):s}}class Cd extends kr{constructor(e){super(br),this.source=e,Object.defineProperty(this,"tag",{set(){throw new Error("Alias nodes cannot have tags")}})}resolve(e,t){if(t?.maxAliasCount===0)throw new ReferenceError("Alias resolution is disabled");let o;t?.aliasResolveCache?o=t.aliasResolveCache:(o=[],Xo(e,{Node:(r,n)=>{(Ia(n)||cl(n))&&o.push(n)}}),t&&(t.aliasResolveCache=o));let i;for(const r of o){if(r===this)break;r.anchor===this.source&&(i=r)}return i}toJSON(e,t){if(!t)return{source:this.source};const{anchors:o,doc:i,maxAliasCount:r}=t,n=this.resolve(i,t);if(!n){const l=`Unresolved alias (the anchor must be set before the alias): ${this.source}`;throw new ReferenceError(l)}let s=o.get(n);if(s||(Ke(n,null,t),s=o.get(n)),s?.res===void 0){const l="This should not happen: Alias anchor was not resolved?";throw new ReferenceError(l)}if(r>=0&&(s.count+=1,s.aliasCount===0&&(s.aliasCount=ko(i,n,o)),s.count*s.aliasCount>r)){const l="Excessive alias count indicates a resource exhaustion attack";throw new ReferenceError(l)}return s.res}toString(e,t,o){const i=`*${this.source}`;if(e){if(ul(this.source),e.options.verifyAliasOrder&&!e.anchors.has(this.source)){const r=`Unresolved alias (the anchor must be set before the alias): ${this.source}`;throw new Error(r)}if(e.implicitKey)return`${i} `}return i}}function ko(a,e,t){if(Ia(e)){const o=e.resolve(a),i=t&&o&&t.get(o);return i?i.count*i.aliasCount:0}else if(Ue(e)){let o=0;for(const i of e.items){const r=ko(a,i,t);r>o&&(o=r)}return o}else if(le(e)){const o=ko(a,e.key,t),i=ko(a,e.value,t);return Math.max(o,i)}return 1}const fl=a=>!a||typeof a!="function"&&typeof a!="object";class Z extends kr{constructor(e){super(wr),this.value=e}toJSON(e,t){return t?.keep?this.value:Ke(this.value,e,t)}toString(){return String(this.value)}}Z.BLOCK_FOLDED="BLOCK_FOLDED";Z.BLOCK_LITERAL="BLOCK_LITERAL";Z.PLAIN="PLAIN";Z.QUOTE_DOUBLE="QUOTE_DOUBLE";Z.QUOTE_SINGLE="QUOTE_SINGLE";function Od(a,e,t){return t.find(o=>o.identify?.(a)&&!o.format)}function No(a,e,t){if(Ho(a)&&(a=a.contents),de(a))return a;if(le(a)){const f=t.schema[ea].createNode?.(t.schema,null,t);return f.items.push(a),f}(a instanceof String||a instanceof Number||a instanceof Boolean||typeof BigInt<"u"&&a instanceof BigInt)&&(a=a.valueOf());const{aliasDuplicateObjects:o,onAnchor:i,onTagObj:r,schema:n,sourceObjects:s}=t;let l;if(o&&a&&typeof a=="object"){if(l=s.get(a),l)return l.anchor??(l.anchor=i(a)),new Cd(l.anchor);l={anchor:null,node:null},s.set(a,l)}let c=Od(a,e,n.tags);if(!c){if(a&&typeof a.toJSON=="function"&&(a=a.toJSON()),!a||typeof a!="object"){const f=new Z(a);return l&&(l.node=f),f}c=a instanceof Map?n[ea]:Symbol.iterator in Object(a)?n[lo]:n[ea]}r&&(r(c),delete t.onTagObj);const u=c?.createNode?c.createNode(t.schema,a,t):typeof c?.nodeClass?.from=="function"?c.nodeClass.from(t.schema,a,t):new Z(a);return c.default||(u.tag=c.tag),l&&(l.node=u),u}function Dn(a,e,t){let o=t;for(let i=e.length-1;i>=0;--i){const r=e[i];if(typeof r=="number"&&Number.isInteger(r)&&r>=0){const n=[];n[r]=o,o=n}else o=new Map([[r,o]])}return No(o,void 0,{aliasDuplicateObjects:!1,keepUndefined:!1,onAnchor:()=>{throw new Error("This should not happen, please report a bug.")},schema:a,sourceObjects:new Map})}const Td=a=>a==null||typeof a=="object"&&!!a[Symbol.iterator]().next().done;class pl extends kr{constructor(e,t){super(e),Object.defineProperty(this,"schema",{value:t,configurable:!0,enumerable:!1,writable:!0})}clone(e){const t=Object.create(Object.getPrototypeOf(this),Object.getOwnPropertyDescriptors(this));return e&&(t.schema=e),t.items=t.items.map(o=>de(o)||le(o)?o.clone(e):o),this.range&&(t.range=this.range.slice()),t}addIn(e,t){if(Td(e))this.add(t);else{const[o,...i]=e,r=this.get(o,!0);if(Ue(r))r.addIn(i,t);else if(r===void 0&&this.schema)this.set(o,Dn(this.schema,i,t));else throw new Error(`Expected YAML collection at ${o}. Remaining path: ${i}`)}}deleteIn(e){const[t,...o]=e;if(o.length===0)return this.delete(t);const i=this.get(t,!0);if(Ue(i))return i.deleteIn(o);throw new Error(`Expected YAML collection at ${t}. Remaining path: ${o}`)}getIn(e,t){const[o,...i]=e,r=this.get(o,!0);return i.length===0?!t&&ie(r)?r.value:r:Ue(r)?r.getIn(i,t):void 0}hasAllNullValues(e){return this.items.every(t=>{if(!le(t))return!1;const o=t.value;return o==null||e&&ie(o)&&o.value==null&&!o.commentBefore&&!o.comment&&!o.tag})}hasIn(e){const[t,...o]=e;if(o.length===0)return this.has(t);const i=this.get(t,!0);return Ue(i)?i.hasIn(o):!1}setIn(e,t){const[o,...i]=e;if(i.length===0)this.set(o,t);else{const r=this.get(o,!0);if(Ue(r))r.setIn(i,t);else if(r===void 0&&this.schema)this.set(o,Dn(this.schema,i,t));else throw new Error(`Expected YAML collection at ${o}. Remaining path: ${i}`)}}}const Ud=a=>a.replace(/^(?!$)(?: $)?/gm,"#");function ao(a,e){return/^\n+$/.test(a)?a.substring(1):e?a.replace(/^(?! *$)/gm,e):a}const ma=(a,e,t)=>a.endsWith(`
`)?ao(t,e):t.includes(`
`)?`
`+ao(t,e):(a.endsWith(" ")?"":" ")+t,dl="flow",Ki="block",Co="quoted";function Ko(a,e,t="flow",{indentAtStart:o,lineWidth:i=80,minContentWidth:r=20,onFold:n,onOverflow:s}={}){if(!i||i<0)return a;i<r&&(r=0);const l=Math.max(1+r,1+i-e.length);if(a.length<=l)return a;const c=[],u={};let f=i-e.length;typeof o=="number"&&(o>i-Math.max(2,r)?c.push(0):f=i-o);let d,m,h=!1,p=-1,g=-1,_=-1;t===Ki&&(p=zn(a,p,e.length),p!==-1&&(f=p+l));for(let v;v=a[p+=1];){if(t===Co&&v==="\\"){switch(g=p,a[p+1]){case"x":p+=3;break;case"u":p+=5;break;case"U":p+=9;break;default:p+=1}_=p}if(v===`
`)t===Ki&&(p=zn(a,p,e.length)),f=p+e.length+l,d=void 0;else{if(v===" "&&m&&m!==" "&&m!==`
`&&m!=="	"){const b=a[p+1];b&&b!==" "&&b!==`
`&&b!=="	"&&(d=p)}if(p>=f)if(d)c.push(d),f=d+l,d=void 0;else if(t===Co){for(;m===" "||m==="	";)m=v,v=a[p+=1],h=!0;const b=p>_+1?p-2:g-1;if(u[b])return a;c.push(b),u[b]=!0,f=b+l,d=void 0}else h=!0}m=v}if(h&&s&&s(),c.length===0)return a;n&&n();let y=a.slice(0,c[0]);for(let v=0;v<c.length;++v){const b=c[v],x=c[v+1]||a.length;b===0?y=`
${e}${a.slice(0,x)}`:(t===Co&&u[b]&&(y+=`${a[b]}\\`),y+=`
${e}${a.slice(b+1,x)}`)}return y}function zn(a,e,t){let o=e,i=e+1,r=a[i];for(;r===" "||r==="	";)if(e<i+t)r=a[++e];else{do r=a[++e];while(r&&r!==`
`);o=e,i=e+1,r=a[i]}return o}const Qo=(a,e)=>({indentAtStart:e?a.indent.length:a.indentAtStart,lineWidth:a.options.lineWidth,minContentWidth:a.options.minContentWidth}),Jo=a=>/^(%|---|\.\.\.)/m.test(a);function Id(a,e,t){if(!e||e<0)return!1;const o=e-t,i=a.length;if(i<=o)return!1;for(let r=0,n=0;r<i;++r)if(a[r]===`
`){if(r-n>o)return!0;if(n=r+1,i-n<=o)return!1}return!0}function Ga(a,e){const t=JSON.stringify(a);if(e.options.doubleQuotedAsJSON)return t;const{implicitKey:o}=e,i=e.options.doubleQuotedMinMultiLineLength,r=e.indent||(Jo(a)?"  ":"");let n="",s=0;for(let l=0,c=t[l];c;c=t[++l])if(c===" "&&t[l+1]==="\\"&&t[l+2]==="n"&&(n+=t.slice(s,l)+"\\ ",l+=1,s=l,c="\\"),c==="\\")switch(t[l+1]){case"u":{n+=t.slice(s,l);const u=t.substr(l+2,4);switch(u){case"0000":n+="\\0";break;case"0007":n+="\\a";break;case"000b":n+="\\v";break;case"001b":n+="\\e";break;case"0085":n+="\\N";break;case"00a0":n+="\\_";break;case"2028":n+="\\L";break;case"2029":n+="\\P";break;default:u.substr(0,2)==="00"?n+="\\x"+u.substr(2):n+=t.substr(l,6)}l+=5,s=l+1}break;case"n":if(o||t[l+2]==='"'||t.length<i)l+=1;else{for(n+=t.slice(s,l)+`

`;t[l+2]==="\\"&&t[l+3]==="n"&&t[l+4]!=='"';)n+=`
`,l+=2;n+=r,t[l+2]===" "&&(n+="\\"),l+=1,s=l+1}break;default:l+=1}return n=s?n+t.slice(s):t,o?n:Ko(n,r,Co,Qo(e,!1))}function Qi(a,e){if(e.options.singleQuote===!1||e.implicitKey&&a.includes(`
`)||/[ \t]\n|\n[ \t]/.test(a))return Ga(a,e);const t=e.indent||(Jo(a)?"  ":""),o="'"+a.replace(/'/g,"''").replace(/\n+/g,`$&
${t}`)+"'";return e.implicitKey?o:Ko(o,t,dl,Qo(e,!1))}function ha(a,e){const{singleQuote:t}=e.options;let o;if(t===!1)o=Ga;else{const i=a.includes('"'),r=a.includes("'");i&&!r?o=Qi:r&&!i?o=Ga:o=t?Qi:Ga}return o(a,e)}let Ji;try{Ji=new RegExp(`(^|(?<!
))
+(?!
|$)`,"g")}catch{Ji=/\n+(?!\n|$)/g}function Oo({comment:a,type:e,value:t},o,i,r){const{blockQuote:n,commentString:s,lineWidth:l}=o.options;if(!n||/\n[\t ]+$/.test(t))return ha(t,o);const c=o.indent||(o.forceBlockIndent||Jo(t)?"  ":""),u=n==="literal"?!0:n==="folded"||e===Z.BLOCK_FOLDED?!1:e===Z.BLOCK_LITERAL?!0:!Id(t,l,c.length);if(!t)return u?`|
`:`>
`;let f,d;for(d=t.length;d>0;--d){const x=t[d-1];if(x!==`
`&&x!=="	"&&x!==" ")break}let m=t.substring(d);const h=m.indexOf(`
`);h===-1?f="-":t===m||h!==m.length-1?(f="+",r&&r()):f="",m&&(t=t.slice(0,-m.length),m[m.length-1]===`
`&&(m=m.slice(0,-1)),m=m.replace(Ji,`$&${c}`));let p=!1,g,_=-1;for(g=0;g<t.length;++g){const x=t[g];if(x===" ")p=!0;else if(x===`
`)_=g;else break}let y=t.substring(0,_<g?_+1:g);y&&(t=t.substring(y.length),y=y.replace(/\n+/g,`$&${c}`));let b=(p?c?"2":"1":"")+f;if(a&&(b+=" "+s(a.replace(/ ?[\r\n]+/g," ")),i&&i()),!u){const x=t.replace(/\n+/g,`
$&`).replace(/(?:^|\n)([\t ].*)(?:([\n\t ]*)\n(?![\n\t ]))?/g,"$1$2").replace(/\n+/g,`$&${c}`);let C=!1;const w=Qo(o,!0);n!=="folded"&&e!==Z.BLOCK_FOLDED&&(w.onOverflow=()=>{C=!0});const k=Ko(`${y}${x}${m}`,c,Ki,w);if(!C)return`>${b}
${c}${k}`}return t=t.replace(/\n+/g,`$&${c}`),`|${b}
${c}${y}${t}${m}`}function Ad(a,e,t,o){const{type:i,value:r}=a,{actualString:n,implicitKey:s,indent:l,indentStep:c,inFlow:u}=e;if(s&&r.includes(`
`)||u&&/[[\]{},]/.test(r))return ha(r,e);if(/^[\n\t ,[\]{}#&*!|>'"%@`]|^[?-]$|^[?-][ \t]|[\n:][ \t]|[ \t]\n|[\n\t ]#|[\n\t :]$/.test(r))return s||u||!r.includes(`
`)?ha(r,e):Oo(a,e,t,o);if(!s&&!u&&i!==Z.PLAIN&&r.includes(`
`))return Oo(a,e,t,o);if(Jo(r)){if(l==="")return e.forceBlockIndent=!0,Oo(a,e,t,o);if(s&&l===c)return ha(r,e)}const f=r.replace(/\n+/g,`$&
${l}`);if(n){const d=p=>p.default&&p.tag!=="tag:yaml.org,2002:str"&&p.test?.test(f),{compat:m,tags:h}=e.doc.schema;if(h.some(d)||m?.some(d))return ha(r,e)}return s?f:Ko(f,l,dl,Qo(e,!1))}function Md(a,e,t,o){const{implicitKey:i,inFlow:r}=e,n=typeof a.value=="string"?a:Object.assign({},a,{value:String(a.value)});let{type:s}=a;s!==Z.QUOTE_DOUBLE&&/[\x00-\x08\x0b-\x1f\x7f-\x9f\u{D800}-\u{DFFF}]/u.test(n.value)&&(s=Z.QUOTE_DOUBLE);const l=u=>{switch(u){case Z.BLOCK_FOLDED:case Z.BLOCK_LITERAL:return i||r?ha(n.value,e):Oo(n,e,t,o);case Z.QUOTE_DOUBLE:return Ga(n.value,e);case Z.QUOTE_SINGLE:return Qi(n.value,e);case Z.PLAIN:return Ad(n,e,t,o);default:return null}};let c=l(s);if(c===null){const{defaultKeyType:u,defaultStringType:f}=e.options,d=i&&u||f;if(c=l(d),c===null)throw new Error(`Unsupported default string type ${d}`)}return c}function Bd(a,e){const t=Object.assign({blockQuote:!0,commentString:Ud,defaultKeyType:null,defaultStringType:"PLAIN",directives:null,doubleQuotedAsJSON:!1,doubleQuotedMinMultiLineLength:40,falseStr:"false",flowCollectionPadding:!0,indentSeq:!0,lineWidth:80,minContentWidth:20,nullStr:"null",simpleKeys:!1,singleQuote:null,trailingComma:!1,trueStr:"true",verifyAliasOrder:!0},a.schema.toStringOptions,e);let o;switch(t.collectionStyle){case"block":o=!1;break;case"flow":o=!0;break;default:o=null}return{anchors:new Set,doc:a,flowCollectionPadding:t.flowCollectionPadding?" ":"",indent:"",indentStep:typeof t.indent=="number"?" ".repeat(t.indent):"  ",inFlow:o,options:t}}function Vd(a,e){if(e.tag){const i=a.filter(r=>r.tag===e.tag);if(i.length>0)return i.find(r=>r.format===e.format)??i[0]}let t,o;if(ie(e)){o=e.value;let i=a.filter(r=>r.identify?.(o));if(i.length>1){const r=i.filter(n=>n.test);r.length>0&&(i=r)}t=i.find(r=>r.format===e.format)??i.find(r=>!r.format)}else o=e,t=a.find(i=>i.nodeClass&&o instanceof i.nodeClass);if(!t){const i=o?.constructor?.name??(o===null?"null":typeof o);throw new Error(`Tag not resolved for ${i} value`)}return t}function Rd(a,e,{anchors:t,doc:o}){if(!o.directives)return"";const i=[],r=(ie(a)||Ue(a))&&a.anchor;r&&ul(r)&&(t.add(r),i.push(`&${r}`));const n=a.tag??(e.default?null:e.tag);return n&&i.push(o.directives.tagString(n)),i.join(" ")}function Eo(a,e,t,o){if(le(a))return a.toString(e,t,o);if(Ia(a)){if(e.doc.directives)return a.toString(e);if(e.resolvedAliases?.has(a))throw new TypeError("Cannot stringify circular structure without alias nodes");e.resolvedAliases?e.resolvedAliases.add(a):e.resolvedAliases=new Set([a]),a=a.resolve(e.doc)}let i;const r=de(a)?a:e.doc.createNode(a,{onTagObj:l=>i=l});i??(i=Vd(e.doc.schema.tags,r));const n=Rd(r,i,e);n.length>0&&(e.indentAtStart=(e.indentAtStart??0)+n.length+1);const s=typeof i.stringify=="function"?i.stringify(r,e,t,o):ie(r)?Md(r,e,t,o):r.toString(e,t,o);return n?ie(r)||s[0]==="{"||s[0]==="["?`${n} ${s}`:`${n}
${e.indent}${s}`:s}function Pd({key:a,value:e},t,o,i){const{allNullValues:r,doc:n,indent:s,indentStep:l,options:{commentString:c,indentSeq:u,simpleKeys:f}}=t;let d=de(a)&&a.comment||null;if(f){if(d)throw new Error("With simple keys, key nodes cannot have comments");if(Ue(a)||!de(a)&&typeof a=="object"){const w="With simple keys, collection cannot be used as a key value";throw new Error(w)}}let m=!f&&(!a||d&&e==null&&!t.inFlow||Ue(a)||(ie(a)?a.type===Z.BLOCK_FOLDED||a.type===Z.BLOCK_LITERAL:typeof a=="object"));t=Object.assign({},t,{allNullValues:!1,implicitKey:!m&&(f||!r),indent:s+l});let h=!1,p=!1,g=Eo(a,t,()=>h=!0,()=>p=!0);if(!m&&!t.inFlow&&g.length>1024){if(f)throw new Error("With simple keys, single line scalar must not span more than 1024 characters");m=!0}if(t.inFlow){if(r||e==null)return h&&o&&o(),g===""?"?":m?`? ${g}`:g}else if(r&&!f||e==null&&m)return g=`? ${g}`,d&&!h?g+=ma(g,t.indent,c(d)):p&&i&&i(),g;h&&(d=null),m?(d&&(g+=ma(g,t.indent,c(d))),g=`? ${g}
${s}:`):(g=`${g}:`,d&&(g+=ma(g,t.indent,c(d))));let _,y,v;de(e)?(_=!!e.spaceBefore,y=e.commentBefore,v=e.comment):(_=!1,y=null,v=null,e&&typeof e=="object"&&(e=n.createNode(e))),t.implicitKey=!1,!m&&!d&&ie(e)&&(t.indentAtStart=g.length+1),p=!1,!u&&l.length>=2&&!t.inFlow&&!m&&Sr(e)&&!e.flow&&!e.tag&&!e.anchor&&(t.indent=t.indent.substring(2));let b=!1;const x=Eo(e,t,()=>b=!0,()=>p=!0);let C=" ";if(d||_||y){if(C=_?`
`:"",y){const w=c(y);C+=`
${ao(w,t.indent)}`}x===""&&!t.inFlow?C===`
`&&v&&(C=`

`):C+=`
${t.indent}`}else if(!m&&Ue(e)){const w=x[0],k=x.indexOf(`
`),S=k!==-1,T=t.inFlow??e.flow??e.items.length===0;if(S||!T){let A=!1;if(S&&(w==="&"||w==="!")){let M=x.indexOf(" ");w==="&"&&M!==-1&&M<k&&x[M+1]==="!"&&(M=x.indexOf(" ",M+1)),(M===-1||k<M)&&(A=!0)}A||(C=`
${t.indent}`)}}else(x===""||x[0]===`
`)&&(C="");return g+=C+x,t.inFlow?b&&o&&o():v&&!b?g+=ma(g,t.indent,c(v)):p&&i&&i(),g}function Dd(a,e){(a==="debug"||a==="warn")&&console.warn(e)}const vo="<<",xi={identify:a=>a===vo||typeof a=="symbol"&&a.description===vo,default:"key",tag:"tag:yaml.org,2002:merge",test:/^<<$/,resolve:()=>Object.assign(new Z(Symbol(vo)),{addToJSMap:ml}),stringify:()=>vo},zd=(a,e)=>(xi.identify(e)||ie(e)&&(!e.type||e.type===Z.PLAIN)&&xi.identify(e.value))&&a?.doc.schema.tags.some(t=>t.tag===xi.tag&&t.default);function ml(a,e,t){const o=hl(a,t);if(Sr(o))for(const i of o.items)bi(a,e,i);else if(Array.isArray(o))for(const i of o)bi(a,e,i);else bi(a,e,o)}function bi(a,e,t){const o=hl(a,t);if(!ll(o))throw new Error("Merge sources must be maps or map aliases");const i=o.toJSON(null,a,Map);for(const[r,n]of i)e instanceof Map?e.has(r)||e.set(r,n):e instanceof Set?e.add(r):Object.prototype.hasOwnProperty.call(e,r)||Object.defineProperty(e,r,{value:n,writable:!0,enumerable:!0,configurable:!0});return e}function hl(a,e){return a&&Ia(e)?e.resolve(a.doc,a):e}function gl(a,e,{key:t,value:o}){if(de(t)&&t.addToJSMap)t.addToJSMap(a,e,o);else if(zd(a,t))ml(a,e,o);else{const i=Ke(t,"",a);if(e instanceof Map)e.set(i,Ke(o,i,a));else if(e instanceof Set)e.add(i);else{const r=Fd(t,i,a),n=Ke(o,r,a);r in e?Object.defineProperty(e,r,{value:n,writable:!0,enumerable:!0,configurable:!0}):e[r]=n}}return e}function Fd(a,e,t){if(e===null)return"";if(typeof e!="object")return String(e);if(de(a)&&t?.doc){const o=Bd(t.doc,{});o.anchors=new Set;for(const r of t.anchors.keys())o.anchors.add(r.anchor);o.inFlow=!0,o.inStringifyKey=!0;const i=a.toString(o);if(!t.mapKeyWarned){let r=JSON.stringify(i);r.length>40&&(r=r.substring(0,36)+'..."'),Dd(t.doc.options.logLevel,`Keys with collection values will be stringified due to JS Object restrictions: ${r}. Set mapAsMap: true to use object keys.`),t.mapKeyWarned=!0}return i}return JSON.stringify(e)}function Cr(a,e,t){const o=No(a,void 0,t),i=No(e,void 0,t);return new vt(o,i)}class vt{constructor(e,t=null){Object.defineProperty(this,st,{value:sl}),this.key=e,this.value=t}clone(e){let{key:t,value:o}=this;return de(t)&&(t=t.clone(e)),de(o)&&(o=o.clone(e)),new vt(t,o)}toJSON(e,t){const o=t?.mapAsMap?new Map:{};return gl(t,o,this)}toString(e,t,o){return e?.doc?Pd(this,e,t,o):JSON.stringify(this)}}function vl(a,e,t){return(e.inFlow??a.flow?Ed:Nd)(a,e,t)}function Nd({comment:a,items:e},t,{blockItemPrefix:o,flowChars:i,itemIndent:r,onChompKeep:n,onComment:s}){const{indent:l,options:{commentString:c}}=t,u=Object.assign({},t,{indent:r,type:null});let f=!1;const d=[];for(let h=0;h<e.length;++h){const p=e[h];let g=null;if(de(p))!f&&p.spaceBefore&&d.push(""),Lo(t,d,p.commentBefore,f),p.comment&&(g=p.comment);else if(le(p)){const y=de(p.key)?p.key:null;y&&(!f&&y.spaceBefore&&d.push(""),Lo(t,d,y.commentBefore,f))}f=!1;let _=Eo(p,u,()=>g=null,()=>f=!0);g&&(_+=ma(_,r,c(g))),f&&g&&(f=!1),d.push(o+_)}let m;if(d.length===0)m=i.start+i.end;else{m=d[0];for(let h=1;h<d.length;++h){const p=d[h];m+=p?`
${l}${p}`:`
`}}return a?(m+=`
`+ao(c(a),l),s&&s()):f&&n&&n(),m}function Ed({items:a},e,{flowChars:t,itemIndent:o}){const{indent:i,indentStep:r,flowCollectionPadding:n,options:{commentString:s}}=e;o+=r;const l=Object.assign({},e,{indent:o,inFlow:!0,type:null});let c=!1,u=0;const f=[];for(let h=0;h<a.length;++h){const p=a[h];let g=null;if(de(p))p.spaceBefore&&f.push(""),Lo(e,f,p.commentBefore,!1),p.comment&&(g=p.comment);else if(le(p)){const y=de(p.key)?p.key:null;y&&(y.spaceBefore&&f.push(""),Lo(e,f,y.commentBefore,!1),y.comment&&(c=!0));const v=de(p.value)?p.value:null;v?(v.comment&&(g=v.comment),v.commentBefore&&(c=!0)):p.value==null&&y?.comment&&(g=y.comment)}g&&(c=!0);let _=Eo(p,l,()=>g=null);c||(c=f.length>u||_.includes(`
`)),h<a.length-1?_+=",":e.options.trailingComma&&(e.options.lineWidth>0&&(c||(c=f.reduce((y,v)=>y+v.length+2,2)+(_.length+2)>e.options.lineWidth)),c&&(_+=",")),g&&(_+=ma(_,o,s(g))),f.push(_),u=f.length}const{start:d,end:m}=t;if(f.length===0)return d+m;if(!c){const h=f.reduce((p,g)=>p+g.length+2,2);c=e.options.lineWidth>0&&h>e.options.lineWidth}if(c){let h=d;for(const p of f)h+=p?`
${r}${i}${p}`:`
`;return`${h}
${i}${m}`}else return`${d}${n}${f.join(" ")}${n}${m}`}function Lo({indent:a,options:{commentString:e}},t,o,i){if(o&&i&&(o=o.replace(/^\n+/,"")),o){const r=ao(e(o),a);t.push(r.trimStart())}}function qt(a,e){const t=ie(e)?e.value:e;for(const o of a)if(le(o)&&(o.key===e||o.key===t||ie(o.key)&&o.key.value===t))return o}class la extends pl{static get tagName(){return"tag:yaml.org,2002:map"}constructor(e){super(ea,e),this.items=[]}static from(e,t,o){const{keepUndefined:i,replacer:r}=o,n=new this(e),s=(l,c)=>{if(typeof r=="function")c=r.call(t,l,c);else if(Array.isArray(r)&&!r.includes(l))return;(c!==void 0||i)&&n.items.push(Cr(l,c,o))};if(t instanceof Map)for(const[l,c]of t)s(l,c);else if(t&&typeof t=="object")for(const l of Object.keys(t))s(l,t[l]);return typeof e.sortMapEntries=="function"&&n.items.sort(e.sortMapEntries),n}add(e,t){let o;le(e)?o=e:!e||typeof e!="object"||!("key"in e)?o=new vt(e,e?.value):o=new vt(e.key,e.value);const i=qt(this.items,o.key),r=this.schema?.sortMapEntries;if(i){if(!t)throw new Error(`Key ${o.key} already set`);ie(i.value)&&fl(o.value)?i.value.value=o.value:i.value=o.value}else if(r){const n=this.items.findIndex(s=>r(o,s)<0);n===-1?this.items.push(o):this.items.splice(n,0,o)}else this.items.push(o)}delete(e){const t=qt(this.items,e);return t?this.items.splice(this.items.indexOf(t),1).length>0:!1}get(e,t){const i=qt(this.items,e)?.value;return(!t&&ie(i)?i.value:i)??void 0}has(e){return!!qt(this.items,e)}set(e,t){this.add(new vt(e,t),!0)}toJSON(e,t,o){const i=o?new o:t?.mapAsMap?new Map:{};t?.onCreate&&t.onCreate(i);for(const r of this.items)gl(t,i,r);return i}toString(e,t,o){if(!e)return JSON.stringify(this);for(const i of this.items)if(!le(i))throw new Error(`Map items must all be pairs; found ${JSON.stringify(i)} instead`);return!e.allNullValues&&this.hasAllNullValues(!1)&&(e=Object.assign({},e,{allNullValues:!0})),vl(this,e,{blockItemPrefix:"",flowChars:{start:"{",end:"}"},itemIndent:e.indent||"",onChompKeep:o,onComment:t})}}class yl extends pl{static get tagName(){return"tag:yaml.org,2002:seq"}constructor(e){super(lo,e),this.items=[]}add(e){this.items.push(e)}delete(e){const t=yo(e);return typeof t!="number"?!1:this.items.splice(t,1).length>0}get(e,t){const o=yo(e);if(typeof o!="number")return;const i=this.items[o];return!t&&ie(i)?i.value:i}has(e){const t=yo(e);return typeof t=="number"&&t<this.items.length}set(e,t){const o=yo(e);if(typeof o!="number")throw new Error(`Expected a valid index, not ${e}.`);const i=this.items[o];ie(i)&&fl(t)?i.value=t:this.items[o]=t}toJSON(e,t){const o=[];t?.onCreate&&t.onCreate(o);let i=0;for(const r of this.items)o.push(Ke(r,String(i++),t));return o}toString(e,t,o){return e?vl(this,e,{blockItemPrefix:"- ",flowChars:{start:"[",end:"]"},itemIndent:(e.indent||"")+"  ",onChompKeep:o,onComment:t}):JSON.stringify(this)}static from(e,t,o){const{replacer:i}=o,r=new this(e);if(t&&Symbol.iterator in Object(t)){let n=0;for(let s of t){if(typeof i=="function"){const l=t instanceof Set?s:String(n++);s=i.call(t,l,s)}r.items.push(No(s,void 0,o))}}return r}}function yo(a){let e=ie(a)?a.value:a;return e&&typeof e=="string"&&(e=Number(e)),typeof e=="number"&&Number.isInteger(e)&&e>=0?e:null}function Ld(a,e,t){const{replacer:o}=t,i=new yl(a);i.tag="tag:yaml.org,2002:pairs";let r=0;if(e&&Symbol.iterator in Object(e))for(let n of e){typeof o=="function"&&(n=o.call(e,String(r++),n));let s,l;if(Array.isArray(n))if(n.length===2)s=n[0],l=n[1];else throw new TypeError(`Expected [key, value] tuple: ${n}`);else if(n&&n instanceof Object){const c=Object.keys(n);if(c.length===1)s=c[0],l=n[s];else throw new TypeError(`Expected tuple with one key, not ${c.length} keys`)}else s=n;i.items.push(Cr(s,l,t))}return i}class Or extends yl{constructor(){super(),this.add=la.prototype.add.bind(this),this.delete=la.prototype.delete.bind(this),this.get=la.prototype.get.bind(this),this.has=la.prototype.has.bind(this),this.set=la.prototype.set.bind(this),this.tag=Or.tag}toJSON(e,t){if(!t)return super.toJSON(e);const o=new Map;t?.onCreate&&t.onCreate(o);for(const i of this.items){let r,n;if(le(i)?(r=Ke(i.key,"",t),n=Ke(i.value,r,t)):r=Ke(i,"",t),o.has(r))throw new Error("Ordered maps must not include duplicate keys");o.set(r,n)}return o}static from(e,t,o){const i=Ld(e,t,o),r=new this;return r.items=i.items,r}}Or.tag="tag:yaml.org,2002:omap";class Tr extends la{constructor(e){super(e),this.tag=Tr.tag}add(e){let t;le(e)?t=e:e&&typeof e=="object"&&"key"in e&&"value"in e&&e.value===null?t=new vt(e.key,null):t=new vt(e,null),qt(this.items,t.key)||this.items.push(t)}get(e,t){const o=qt(this.items,e);return!t&&le(o)?ie(o.key)?o.key.value:o.key:o}set(e,t){if(typeof t!="boolean")throw new Error(`Expected boolean value for set(key, value) in a YAML set, not ${typeof t}`);const o=qt(this.items,e);o&&!t?this.items.splice(this.items.indexOf(o),1):!o&&t&&this.items.push(new vt(e))}toJSON(e,t){return super.toJSON(e,t,Set)}toString(e,t,o){if(!e)return JSON.stringify(this);if(this.hasAllNullValues(!0))return super.toString(Object.assign({},e,{allNullValues:!0}),t,o);throw new Error("Set items must all have null values")}static from(e,t,o){const{replacer:i}=o,r=new this(e);if(t&&Symbol.iterator in Object(t))for(let n of t)typeof i=="function"&&(n=i.call(t,n,n)),r.items.push(Cr(n,null,o));return r}}Tr.tag="tag:yaml.org,2002:set";new Set("0123456789ABCDEFabcdef");new Set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-#;/?:@&=+$_.!~*'()");new Set(",[]{}");new Set(` ,[]{}
\r	`);const $d=a=>{let e=1;for(;e<a;)e*=2;return e};function Fn(a,e,t,o,i){const r=Math.max(0,Math.floor(o*i)),n=new Float32Array(r);for(let s=0;s<r;s++){const l=(t+s/i)*e,c=Math.floor(l),u=Math.min(a.length-1,c+1);if(c<0||c>=a.length)continue;const f=l-c;n[s]=(a[c]??0)*(1-f)+(a[u]??0)*f}return n}function Nn(a){if(a.length===0)return a;let e=0;for(const t of a)e+=t;return e/=a.length,Float32Array.from(a,t=>t-e)}function jd(a,e,t,o){if(a.length===0||e.length<a.length)return{offsetSeconds:0,confidence:0};const i=Nn(a),r=Nn(e),n=$d(i.length+r.length-1),s=new Float32Array(n);for(let v=0;v<i.length;v++)s[v]=i[i.length-1-v]??0;const l=new Float32Array(n);l.set(r);const c=new hf(n),u=c.forward(s),f=c.forward(l),d=new Float32Array(n),m=new Float32Array(n);for(let v=0;v<n;v++)d[v]=f.real[v]*u.real[v]-f.imag[v]*u.imag[v],m[v]=f.real[v]*u.imag[v]+f.imag[v]*u.real[v];const h=c.inverse(d,m);let p=0;for(const v of i)p+=v*v;const g=new Float64Array(r.length+1);for(let v=0;v<r.length;v++){const b=r[v]??0;g[v+1]=(g[v]??0)+b*b}let _=0,y=-1;for(let v=-t;v<=t;v++){const b=t+v,x=b+i.length;if(b<0||x>r.length)continue;const C=(g[x]??0)-(g[b]??0),w=Math.sqrt(p*C),k=b+i.length-1,S=w>0?(h[k]??0)/w:0;S>y&&(y=S,_=v)}return{offsetSeconds:_/o,confidence:Math.max(0,Math.min(1,y))}}function Wd(a){const e=a.filter(d=>Number.isFinite(d.timeSeconds)&&Number.isFinite(d.offsetSeconds)&&Number.isFinite(d.confidence)&&d.confidence>0);if(e.length===0)return{interceptSeconds:0,secondsPerSecond:0,partsPerMillion:0,confidence:0,observations:[]};let t=0,o=0,i=0;for(const d of e)t+=d.confidence,o+=d.timeSeconds*d.confidence,i+=d.offsetSeconds*d.confidence;const r=o/t,n=i/t;let s=0,l=0;for(const d of e){const m=d.timeSeconds-r;s+=d.confidence*m*(d.offsetSeconds-n),l+=d.confidence*m*m}const c=l>0?s/l:0,u=n-c*r,f=t/e.length;return{interceptSeconds:u,secondsPerSecond:c,partsPerMillion:c*1e6,confidence:Math.max(0,Math.min(1,f)),observations:e.map(d=>({...d}))}}function Gd(a,e,t,o={}){const i=Math.max(1,o.blockSeconds??5),r=Math.max(i,o.intervalSeconds??300),n=Math.max(.05,o.maxOffsetSeconds??2),s=Math.max(100,o.analysisSampleRate??400),l=Math.min(a.length,e.length)/t,c=[];for(let u=n;u+i+n<=l;u+=r){const f=Fn(a,t,u,i,s),d=Fn(e,t,u-n,i+n*2,s),m=jd(f,d,Math.round(n*s),s);c.push({timeSeconds:u+i/2,...m})}return Wd(c)}self.onmessage=a=>{const{requestId:e,reference:t,target:o,sampleRate:i,options:r}=a.data;try{self.postMessage({requestId:e,type:"result",model:Gd(t,o,i,r)})}catch(n){self.postMessage({requestId:e,type:"error",message:n instanceof Error?n.message:"Multicam sync failed"})}};
