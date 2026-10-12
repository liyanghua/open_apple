import React from 'react';
import {AbsoluteFill,OffthreadVideo,staticFile,useCurrentFrame,interpolate} from 'remotion';
const caps=[{s:0.25,e:2.35,t:'高密织纹，柔软亲肤。'},{s:2.78,e:5.85,t:'纯棉材质，晴空蓝、柔胭粉，多款可选。'},{s:6.28,e:7.35,t:'PLAYBOY，让日常更有质感。'}];
export const CaptionSample:React.FC=()=>{const f=useCurrentFrame();const sec=f/30;const c=caps.find(x=>sec>=x.s&&sec<=x.e);return <AbsoluteFill><OffthreadVideo src={staticFile('caption/base-extended.mp4')} style={{width:'100%',height:'100%',objectFit:'cover'}}/><div style={{position:'absolute',left:72,right:72,bottom:210,minHeight:62,padding:'14px 24px',background:'rgba(17,17,17,.72)',borderRadius:12,color:'#fff',fontFamily:'Microsoft YaHei, STHeiti, sans-serif',fontSize:30,lineHeight:1.35,textAlign:'center',opacity:c?1:0}}>{c?.t}</div></AbsoluteFill>}
