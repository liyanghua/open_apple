import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo, useCurrentFrame, interpolate, staticFile} from 'remotion';
export const P1LogoSample: React.FC<{videoSrc:string; logoSrc:string}> = ({videoSrc,logoSrc}) => {
 const f=useCurrentFrame(); const op=interpolate(f,[0,10,20,115,125],[0,0,1,1,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
 return <AbsoluteFill style={{background:'#000'}}><OffthreadVideo src={staticFile(videoSrc)} style={{width:'100%',height:'100%',objectFit:'cover'}}/><Img src={staticFile(logoSrc)} style={{position:'absolute',left:888,top:96,width:120,height:'auto',opacity:op}}/><div style={{position:'absolute',left:72,top:220,color:'#fff',fontFamily:'Microsoft YaHei, STHeiti, sans-serif',fontWeight:700,fontSize:64,lineHeight:1.28,opacity:op}}>高密织纹<br/>柔软亲肤</div><div style={{position:'absolute',left:72,top:390,width:72,height:8,background:'#4874CB',opacity:op}}/><div style={{position:'absolute',left:72,top:1450,color:'#fff',fontFamily:'Microsoft YaHei, STHeiti, sans-serif',fontSize:30,opacity:op}}>100%新疆长绒棉  以商品页事实为准</div></AbsoluteFill>;
};
