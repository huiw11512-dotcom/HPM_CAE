"""Custom drag editor used by the Gradio V1.0 workbench.

The component is rendered by :class:`gradio.HTML`.  Geometry changes are
reported through a standard Gradio ``change`` event, so the Python project
model remains the single source of truth.
"""
from __future__ import annotations

import json
from typing import Any

from hpm_platform.ui.project_model import CAEProject


def scene_editor_value(project: CAEProject) -> str:
    path = project.motion.trajectory(project.target.center_x_lambda, project.target.center_y_lambda)
    payload: dict[str, Any] = {
        "span_x": float(project.plane.span_x_lambda),
        "span_y": float(project.plane.span_y_lambda),
        "array_nx": int(project.array.nx),
        "array_ny": int(project.array.ny),
        "spacing_x": float(project.array.spacing_x_lambda),
        "spacing_y": float(project.array.spacing_y_lambda),
        "target_x": float(project.target.center_x_lambda),
        "target_y": float(project.target.center_y_lambda),
        "target_major": float(project.target.semi_major_lambda),
        "target_minor": float(project.target.semi_minor_lambda),
        "target_rotation": float(project.target.rotation_deg),
        "guard_scale": float(project.target.guard_scale),
        "protected_enabled": bool(project.protected_zone.enabled),
        "protected_x": float(project.protected_zone.center_x_lambda),
        "protected_y": float(project.protected_zone.center_y_lambda),
        "protected_radius": float(project.protected_zone.radius_lambda),
        "motion_enabled": bool(project.motion.enabled),
        "motion_path": path.tolist(),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


EDITOR_HTML = r"""
<div class="hpm-scene-editor">
  <div class="hpm-editor-toolbar">
    <div><b>平面场景编辑器</b><span>拖拽中心与控制柄；按住 Shift 以 0.1λ 吸附</span></div>
    <div class="hpm-editor-actions"><button data-action="reset">恢复</button><button data-action="snap" class="active">吸附 0.05λ</button></div>
  </div>
  <div class="hpm-editor-canvas-wrap"><canvas tabindex="0"></canvas></div>
  <div class="hpm-editor-legend">
    <span><i class="target"></i>目标区</span><span><i class="guard"></i>过渡区</span><span><i class="protect"></i>保护区</span><span><i class="path"></i>运动轨迹</span>
    <code data-role="readout">ready</code>
  </div>
</div>
"""


EDITOR_CSS = r"""
.hpm-scene-editor{background:#091422;border:1px solid #26354d;border-radius:10px;overflow:hidden;color:#e7eef9;font-family:Inter,'Segoe UI','Microsoft YaHei',sans-serif}
.hpm-editor-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 12px;border-bottom:1px solid #26354d;background:#0d1828}.hpm-editor-toolbar b{font-size:13px}.hpm-editor-toolbar span{font-size:10px;color:#91a2bb;margin-left:9px}.hpm-editor-actions{display:flex;gap:6px}.hpm-editor-actions button{font-size:10px;padding:5px 9px;border:1px solid #26354d;border-radius:6px;background:#111f33;color:#e7eef9;cursor:pointer}.hpm-editor-actions button.active{border-color:#35d8ff;color:#35d8ff;background:rgba(53,216,255,.08)}
.hpm-editor-canvas-wrap{height:560px;min-height:420px;padding:8px;background:radial-gradient(circle at 50% 44%,#10233a,#07101d 72%)}.hpm-editor-canvas-wrap canvas{width:100%;height:100%;display:block;border-radius:7px;touch-action:none;cursor:crosshair;outline:none}
.hpm-editor-legend{display:flex;align-items:center;gap:15px;flex-wrap:wrap;padding:8px 12px;border-top:1px solid #26354d;background:#0d1828;font-size:10px;color:#91a2bb}.hpm-editor-legend i{display:inline-block;width:13px;height:3px;margin-right:5px;vertical-align:middle}.hpm-editor-legend i.target{background:#ffc857}.hpm-editor-legend i.guard{border-top:2px dashed #ffc857}.hpm-editor-legend i.protect{background:#4ee0a5}.hpm-editor-legend i.path{border-top:2px dotted #ab8cff}.hpm-editor-legend code{margin-left:auto;color:#35d8ff;background:#07101d;border:1px solid #26354d;border-radius:5px;padding:4px 7px}
"""


EDITOR_JS = r"""
const shell = element.querySelector('.hpm-scene-editor');
const canvas = shell.querySelector('canvas');
const wrap = shell.querySelector('.hpm-editor-canvas-wrap');
const readout = shell.querySelector('[data-role="readout"]');
const resetButton = shell.querySelector('[data-action="reset"]');
const snapButton = shell.querySelector('[data-action="snap"]');
let initial = {};
try { initial = JSON.parse(props.value || '{}'); } catch (_) { initial = {}; }
let state = JSON.parse(JSON.stringify(initial));
let active = null;
let snapEnabled = true;
let W = 800, H = 520, dpr = window.devicePixelRatio || 1;
const pad = 42;
const C = {bg:'#07101d',panel:'#0d1828',grid:'#26354d',text:'#e7eef9',muted:'#91a2bb',cyan:'#35d8ff',amber:'#ffc857',green:'#4ee0a5',purple:'#ab8cff',red:'#ff6b7a'};

function resize(){
  const rect = wrap.getBoundingClientRect();
  W = Math.max(620, Math.floor(rect.width - 16));
  H = Math.max(400, Math.floor(rect.height - 16));
  canvas.width = Math.floor(W*dpr); canvas.height = Math.floor(H*dpr);
  canvas.style.width = W+'px'; canvas.style.height = H+'px';
  draw();
}
function xp(x){ return pad + (x + state.span_x/2) / state.span_x * (W-2*pad); }
function yp(y){ return H-pad - (y + state.span_y/2) / state.span_y * (H-2*pad); }
function xv(px){ return (px-pad)/(W-2*pad)*state.span_x-state.span_x/2; }
function yv(py){ return (H-pad-py)/(H-2*pad)*state.span_y-state.span_y/2; }
function dist(a,b,c,d){ return Math.hypot(a-c,b-d); }
function clamp(v,a,b){ return Math.max(a,Math.min(b,v)); }
function snap(v, step){ return Math.round(v/step)*step; }
function localPoint(x,y){
  const rect=canvas.getBoundingClientRect(); return {x:(x-rect.left)*W/rect.width,y:(y-rect.top)*H/rect.height};
}
function handlePoints(){
  const a=state.target_rotation*Math.PI/180, ca=Math.cos(a), sa=Math.sin(a);
  const tx=state.target_x, ty=state.target_y;
  return {
    target_center:[xp(tx),yp(ty)],
    target_major:[xp(tx+ca*state.target_major),yp(ty+sa*state.target_major)],
    target_minor:[xp(tx-sa*state.target_minor),yp(ty+ca*state.target_minor)],
    target_rotation:[xp(tx+ca*state.target_major*1.42),yp(ty+sa*state.target_major*1.42)],
    protected_center:[xp(state.protected_x),yp(state.protected_y)],
    protected_radius:[xp(state.protected_x+state.protected_radius),yp(state.protected_y)]
  };
}
function gridStep(){
  const span=Math.max(state.span_x,state.span_y); return span<=8?0.5:(span<=16?1:2);
}
function drawGrid(ctx){
  const step=gridStep(); ctx.lineWidth=1; ctx.font='10px Inter,Segoe UI,sans-serif';
  for(let x=Math.ceil(-state.span_x/2/step)*step;x<=state.span_x/2+1e-9;x+=step){
    const p=xp(x); ctx.strokeStyle=Math.abs(x)<1e-9?'rgba(53,216,255,.32)':'rgba(38,53,77,.68)'; ctx.beginPath();ctx.moveTo(p,pad);ctx.lineTo(p,H-pad);ctx.stroke();
    if(Math.abs(x)>1e-9){ctx.fillStyle=C.muted;ctx.fillText(x.toFixed(1),p+3,H-pad+14);}
  }
  for(let y=Math.ceil(-state.span_y/2/step)*step;y<=state.span_y/2+1e-9;y+=step){
    const p=yp(y); ctx.strokeStyle=Math.abs(y)<1e-9?'rgba(53,216,255,.32)':'rgba(38,53,77,.68)';ctx.beginPath();ctx.moveTo(pad,p);ctx.lineTo(W-pad,p);ctx.stroke();
    if(Math.abs(y)>1e-9){ctx.fillStyle=C.muted;ctx.fillText(y.toFixed(1),pad-31,p-3);}
  }
  ctx.strokeStyle=C.grid;ctx.strokeRect(pad,pad,W-2*pad,H-2*pad);
}
function drawArray(ctx){
  const ax=(state.array_nx-1)*state.spacing_x/2, ay=(state.array_ny-1)*state.spacing_y/2;
  ctx.save();ctx.strokeStyle='rgba(53,216,255,.55)';ctx.fillStyle='rgba(53,216,255,.06)';ctx.lineWidth=1.5;
  ctx.fillRect(xp(-ax),yp(ay),xp(ax)-xp(-ax),yp(-ay)-yp(ay));ctx.strokeRect(xp(-ax),yp(ay),xp(ax)-xp(-ax),yp(-ay)-yp(ay));
  const maxDots=144, total=state.array_nx*state.array_ny, stride=Math.max(1,Math.ceil(Math.sqrt(total/maxDots)));
  ctx.fillStyle=C.cyan;
  for(let ix=0;ix<state.array_nx;ix+=stride){for(let iy=0;iy<state.array_ny;iy+=stride){
    const x=(ix-(state.array_nx-1)/2)*state.spacing_x,y=(iy-(state.array_ny-1)/2)*state.spacing_y;
    ctx.beginPath();ctx.arc(xp(x),yp(y),1.8,0,Math.PI*2);ctx.fill();
  }}
  ctx.fillStyle=C.muted;ctx.fillText('阵列投影',xp(-ax)+5,yp(ay)+14);ctx.restore();
}
function ellipse(ctx,cx,cy,rx,ry,rot,color,fill,dash){
  ctx.save();ctx.translate(xp(cx),yp(cy));
  const sx=(W-2*pad)/state.span_x, sy=(H-2*pad)/state.span_y;
  ctx.rotate(-rot*Math.PI/180);ctx.beginPath();ctx.ellipse(0,0,Math.abs(rx*sx),Math.abs(ry*sy),0,0,Math.PI*2);
  if(dash)ctx.setLineDash(dash);ctx.lineWidth=2;ctx.strokeStyle=color;ctx.stroke();if(fill){ctx.fillStyle=fill;ctx.fill();}ctx.restore();
}
function drawPath(ctx){
  if(!state.motion_enabled || !state.motion_path || state.motion_path.length<2)return;
  ctx.save();ctx.setLineDash([4,7]);ctx.strokeStyle=C.purple;ctx.lineWidth=2;ctx.beginPath();
  state.motion_path.forEach((p,i)=>{if(i===0)ctx.moveTo(xp(p[0]),yp(p[1]));else ctx.lineTo(xp(p[0]),yp(p[1]));});ctx.stroke();ctx.setLineDash([]);
  state.motion_path.forEach((p,i)=>{if(i%Math.max(1,Math.floor(state.motion_path.length/7))===0||i===state.motion_path.length-1){ctx.fillStyle=C.purple;ctx.beginPath();ctx.arc(xp(p[0]),yp(p[1]),3,0,Math.PI*2);ctx.fill();}});ctx.restore();
}
function dot(ctx,p,color,r=6,ring=true){ctx.save();if(ring){ctx.strokeStyle='#07101d';ctx.lineWidth=3;ctx.beginPath();ctx.arc(p[0],p[1],r+2,0,Math.PI*2);ctx.stroke();}ctx.fillStyle=color;ctx.beginPath();ctx.arc(p[0],p[1],r,0,Math.PI*2);ctx.fill();ctx.restore();}
function draw(){
  const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);ctx.fillStyle=C.bg;ctx.fillRect(0,0,W,H);
  drawGrid(ctx);drawArray(ctx);drawPath(ctx);
  ellipse(ctx,state.target_x,state.target_y,state.target_major*state.guard_scale,state.target_minor*state.guard_scale,state.target_rotation,'rgba(255,200,87,.55)',null,[5,6]);
  ellipse(ctx,state.target_x,state.target_y,state.target_major,state.target_minor,state.target_rotation,C.amber,'rgba(255,200,87,.10)',null);
  if(state.protected_enabled)ellipse(ctx,state.protected_x,state.protected_y,state.protected_radius,state.protected_radius,0,C.green,'rgba(78,224,165,.10)',null);
  const hp=handlePoints();dot(ctx,hp.target_center,C.amber,7);dot(ctx,hp.target_major,C.amber,5);dot(ctx,hp.target_minor,C.amber,5);dot(ctx,hp.target_rotation,C.purple,5);
  if(state.protected_enabled){dot(ctx,hp.protected_center,C.green,7);dot(ctx,hp.protected_radius,C.green,5);}
  ctx.fillStyle=C.text;ctx.font='600 11px Inter,Segoe UI,sans-serif';ctx.fillText('TARGET',hp.target_center[0]+11,hp.target_center[1]-9);
  if(state.protected_enabled)ctx.fillText('PROTECTED',hp.protected_center[0]+11,hp.protected_center[1]-9);
  readout.textContent=`目标 (${state.target_x.toFixed(2)}, ${state.target_y.toFixed(2)})λ · a/b ${state.target_major.toFixed(2)}/${state.target_minor.toFixed(2)}λ · ${state.target_rotation.toFixed(1)}°`;
}
function hitTest(p){
  const hp=handlePoints();let best=null,bestD=18;
  Object.entries(hp).forEach(([k,h])=>{if(!state.protected_enabled&&k.startsWith('protected'))return;const d=dist(p.x,p.y,h[0],h[1]);if(d<bestD){best=k;bestD=d;}});return best;
}
function emit(){
  const payload={
    target_x:state.target_x,target_y:state.target_y,target_major:state.target_major,target_minor:state.target_minor,target_rotation:state.target_rotation,
    protected_x:state.protected_x,protected_y:state.protected_y,protected_radius:state.protected_radius,action:active||'edit'
  };
  props.value=JSON.stringify(state); trigger('input',payload);
}
canvas.addEventListener('pointerdown',e=>{const p=localPoint(e.clientX,e.clientY);active=hitTest(p);if(active){canvas.setPointerCapture(e.pointerId);e.preventDefault();}});
canvas.addEventListener('pointermove',e=>{
  if(!active)return;const p=localPoint(e.clientX,e.clientY);let x=xv(p.x),y=yv(p.y);const step=(snapEnabled||e.shiftKey)?0.05:0.001;x=snap(x,step);y=snap(y,step);
  const halfX=state.span_x/2,halfY=state.span_y/2;
  if(active==='target_center'){
    const ext=Math.max(state.target_major,state.target_minor)*state.guard_scale;state.target_x=clamp(x,-halfX+ext+0.05,halfX-ext-0.05);state.target_y=clamp(y,-halfY+ext+0.05,halfY-ext-0.05);
  } else if(active==='protected_center'){
    state.protected_x=clamp(x,-halfX+state.protected_radius+0.05,halfX-state.protected_radius-0.05);state.protected_y=clamp(y,-halfY+state.protected_radius+0.05,halfY-state.protected_radius-0.05);
  } else if(active==='protected_radius'){
    state.protected_radius=clamp(Math.hypot(x-state.protected_x,y-state.protected_y),0.15,Math.min(halfX,halfY)-0.1);
  } else {
    const dx=x-state.target_x,dy=y-state.target_y,a=state.target_rotation*Math.PI/180,ca=Math.cos(a),sa=Math.sin(a);
    if(active==='target_major')state.target_major=clamp(Math.abs(dx*ca+dy*sa),0.2,Math.min(halfX,halfY)-0.2);
    if(active==='target_minor')state.target_minor=clamp(Math.abs(-dx*sa+dy*ca),0.2,Math.min(halfX,halfY)-0.2);
    if(active==='target_rotation')state.target_rotation=Math.atan2(dy,dx)*180/Math.PI;
  }
  draw();e.preventDefault();
});
canvas.addEventListener('pointerup',e=>{if(active){emit();active=null;canvas.releasePointerCapture(e.pointerId);}});
canvas.addEventListener('pointercancel',()=>{active=null;});
resetButton.addEventListener('click',()=>{state=JSON.parse(JSON.stringify(initial));draw();active='reset';emit();active=null;});
snapButton.addEventListener('click',()=>{snapEnabled=!snapEnabled;snapButton.classList.toggle('active',snapEnabled);snapButton.textContent=snapEnabled?'吸附 0.05λ':'自由拖拽';});
new ResizeObserver(resize).observe(wrap);resize();
"""
