const state = {
  project: null,
  result: null,
  selectedId: null,
  frame: 0,
  playing: false,
  timer: null,
  showField: true,
  showTrajectories: true,
  camera: null,
};

const componentNames = {
  geometry: '几何', material: '材料', array: '阵列', emitter: '发射', receiver: '接收',
  motion: '运动', boundary: '边界', scatterer: '散射', enclosure: '腔体', aperture: '孔缝',
  probe: '探针', role: '角色', uncertainty: '不确定度'
};

function component(entity, type) {
  return (entity.components || []).find(item => item.type === type);
}

function hasRole(entity, role) {
  const item = component(entity, 'role');
  return Boolean(item && item.roles && item.roles.includes(role));
}

function entityCategory(entity) {
  if (component(entity, 'array')) return '阵列系统';
  if (component(entity, 'motion')) return '运动对象';
  if (component(entity, 'probe')) return '分析探针';
  if (component(entity, 'receiver')) return '接收设备';
  if (hasRole(entity, 'environment')) return '环境对象';
  return '其他对象';
}

function entityIcon(entity) {
  if (component(entity, 'array')) return 'bi-grid-3x3-gap';
  if (component(entity, 'motion')) return 'bi-airplane';
  if (component(entity, 'probe')) return 'bi-bounding-box';
  if (component(entity, 'receiver')) return 'bi-broadcast-pin';
  if (hasRole(entity, 'environment')) return 'bi-buildings';
  return 'bi-box';
}

function log(message) {
  const el = document.getElementById('logText');
  const time = new Date().toLocaleTimeString('zh-CN', {hour12: false});
  el.textContent += `\n[${time}] ${message}`;
  el.scrollTop = el.scrollHeight;
}

function status(message) {
  document.getElementById('statusText').textContent = message;
}

function toast(message, kind='primary') {
  const container = document.getElementById('toastContainer');
  const wrapper = document.createElement('div');
  wrapper.className = 'toast show mb-2';
  wrapper.innerHTML = `<div class="toast-body border-start border-3 border-${kind}">${message}</div>`;
  container.appendChild(wrapper);
  setTimeout(() => wrapper.remove(), 3200);
}

async function api(url, options={}) {
  const response = await fetch(url, {
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

async function apiForm(url, formData) {
  const response = await fetch(url, {method: 'POST', body: formData});
  if (!response.ok) {
    let detail = `${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

async function bootstrap() {
  status('载入场景…');
  const data = await api('/api/bootstrap');
  state.project = data.project;
  state.result = data.latest_result;
  state.selectedId = null;
  state.frame = 0;
  renderAll();
  renderExampleOptions(data.examples);
  status('准备就绪');
}

function renderExampleOptions(examples) {
  const select = document.getElementById('exampleSelect');
  select.innerHTML = `<option value="">切换示例工程…</option>` + examples.map(item =>
    `<option value="${item.id}">${item.name}</option>`
  ).join('');
}

function renderAll() {
  document.getElementById('projectName').textContent = state.project.metadata.name;
  renderTree();
  renderInspector();
  renderMission();
  configureTimeline();
  renderScene();
  renderReceiverChart();
  renderMetrics();
}

function renderTree() {
  const groups = {};
  for (const entity of state.project.scene.entities) {
    const category = entityCategory(entity);
    (groups[category] ||= []).push(entity);
  }
  const order = ['阵列系统', '运动对象', '接收设备', '环境对象', '分析探针', '其他对象'];
  const panel = document.getElementById('treePanel');
  panel.innerHTML = order.filter(key => groups[key]?.length).map(category => `
    <div class="tree-group">
      <div class="tree-group-title"><i class="bi bi-chevron-down"></i>${category}<span class="ms-auto">${groups[category].length}</span></div>
      ${groups[category].map(entity => `
        <button class="tree-item ${state.selectedId === entity.id ? 'selected' : ''}" data-id="${entity.id}">
          <span class="entity-icon"><i class="bi ${entityIcon(entity)}"></i></span>
          <span class="text-truncate">
            ${escapeHtml(entity.name)}
            <span class="entity-meta">${entity.components.map(item => componentNames[item.type] || item.type).slice(0,3).join(' · ')}</span>
          </span>
        </button>`).join('')}
    </div>`).join('');
  panel.querySelectorAll('.tree-item').forEach(button => {
    button.addEventListener('click', () => selectEntity(button.dataset.id));
  });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function selectEntity(id) {
  state.selectedId = id;
  renderTree();
  renderInspector();
  renderScene();
}

function renderInspector() {
  const entity = state.project.scene.entities.find(item => item.id === state.selectedId);
  const empty = document.getElementById('inspectorEmpty');
  const form = document.getElementById('inspectorForm');
  const deleteBtn = document.getElementById('deleteBtn');
  if (!entity) {
    empty.classList.remove('d-none');
    form.classList.add('d-none');
    deleteBtn.classList.add('d-none');
    document.getElementById('selectedType').textContent = '请选择场景对象';
    return;
  }
  empty.classList.add('d-none');
  form.classList.remove('d-none');
  deleteBtn.classList.remove('d-none');
  document.getElementById('selectedType').textContent = `${entityCategory(entity)} · ${entity.id.slice(0,8)}`;
  document.getElementById('entityName').value = entity.name;
  document.getElementById('posX').value = entity.transform.position_m.x;
  document.getElementById('posY').value = entity.transform.position_m.y;
  document.getElementById('posZ').value = entity.transform.position_m.z;
  document.getElementById('rotX').value = entity.transform.rotation_deg.x;
  document.getElementById('rotY').value = entity.transform.rotation_deg.y;
  document.getElementById('rotZ').value = entity.transform.rotation_deg.z;
  document.getElementById('componentList').innerHTML = entity.components.map(item =>
    `<span class="component-chip">${componentNames[item.type] || item.type}</span>`
  ).join('');

  const motion = component(entity, 'motion');
  const motionInfo = document.getElementById('motionInfo');
  if (motion && motion.mode !== 'static') {
    motionInfo.classList.remove('d-none');
    motionInfo.innerHTML = `<strong>运动模型：</strong>${motion.mode}<br><strong>路径点：</strong>${(motion.waypoints || []).length} 个`;
  } else motionInfo.classList.add('d-none');

  const array = component(entity, 'array');
  const arrayInfo = document.getElementById('arrayInfo');
  if (array) {
    arrayInfo.classList.remove('d-none');
    arrayInfo.innerHTML = `<strong>阵列：</strong>${array.nx} × ${array.ny}<br><strong>频率：</strong>${(array.frequency_hz/1e9).toFixed(2)} GHz<br><strong>法向：</strong>${array.boresight_axis}`;
  } else arrayInfo.classList.add('d-none');
}

function getEntityPosition(entity, frame=state.frame) {
  if (state.result?.entity_positions?.[entity.id]) {
    const positions = state.result.entity_positions[entity.id];
    return positions[Math.min(frame, positions.length - 1)];
  }
  const p = entity.transform.position_m;
  return [p.x, p.y, p.z];
}

function colorFor(entity) {
  return component(entity, 'geometry')?.color || '#64748b';
}

function arrayElements(entity, position) {
  const array = component(entity, 'array');
  const nX = array.nx, nY = array.ny;
  const wavelength = 299792458 / array.frequency_hz;
  const dx = array.dx_m || wavelength / 2;
  const dy = array.dy_m || wavelength / 2;
  const x=[], y=[], z=[];
  for (let ix=0; ix<nX; ix++) for (let iy=0; iy<nY; iy++) {
    x.push(position[0] + (ix-(nX-1)/2)*dx*12);
    y.push(position[1] + (iy-(nY-1)/2)*dy*12);
    z.push(position[2]);
  }
  return {x,y,z};
}

function boxMesh(entity, position, selected=false) {
  const g = component(entity, 'geometry');
  const dx=g.dimensions_m.x/2, dy=g.dimensions_m.y/2, dz=g.dimensions_m.z/2;
  const x=[-dx,dx,dx,-dx,-dx,dx,dx,-dx].map(v=>v+position[0]);
  const y=[-dy,-dy,dy,dy,-dy,-dy,dy,dy].map(v=>v+position[1]);
  const z=[-dz,-dz,-dz,-dz,dz,dz,dz,dz].map(v=>v+position[2]);
  return {
    type:'mesh3d', x,y,z,
    i:[0,0,0,4,4,4,0,1,2,3,1,2],
    j:[1,2,3,5,6,7,1,2,3,0,5,6],
    k:[2,3,1,6,7,5,5,6,7,4,4,5],
    color:g.color, opacity:selected ? 1 : (g.opacity ?? .9),
    flatshading:true, hovertemplate:`<b>${escapeHtml(entity.name)}</b><br>建筑/环境对象<extra></extra>`,
    name:entity.name, showscale:false
  };
}

function renderScene() {
  if (!state.project) return;
  const traces=[];
  const entities=state.project.scene.entities.filter(e=>e.enabled);
  const frame=state.frame;

  if (state.result && state.showField && state.result.plane?.field?.length) {
    const field = state.result.plane.field[Math.min(frame, state.result.plane.field.length-1)];
    traces.push({
      type:'surface',
      x:state.result.plane.x_m,
      y:state.result.plane.y_m,
      z:state.result.plane.z_m,
      surfacecolor:field,
      colorscale:[[0,'#081526'],[.18,'#123663'],[.42,'#0ea5e9'],[.68,'#22c55e'],[.85,'#f59e0b'],[1,'#ef4444']],
      cmin:0, cmax:1, opacity:.72, showscale:true,
      colorbar:{title:'归一化场',len:.48,thickness:10,x:.98,y:.58,tickfont:{color:'#91a3b9',size:9},titlefont:{color:'#b8c7d9',size:9}},
      hovertemplate:'x=%{x:.1f} m<br>y=%{y:.1f} m<br>场=%{surfacecolor:.3f}<extra></extra>',
      name:'场切片'
    });
  }

  for (const entity of entities) {
    const position=getEntityPosition(entity, frame);
    const geometry=component(entity,'geometry');
    const selected=entity.id===state.selectedId;
    if (!geometry) continue;

    if (component(entity,'array')) {
      const grid=arrayElements(entity,position);
      traces.push({
        type:'scatter3d',mode:'markers',x:grid.x,y:grid.y,z:grid.z,
        marker:{size:selected?5:3,color:colorFor(entity),symbol:'square',line:{color:selected?'#ffffff':'#0f172a',width:selected?2:0.4}},
        name:entity.name,customdata:Array(grid.x.length).fill(entity.id),
        hovertemplate:`<b>${escapeHtml(entity.name)}</b><br>阵元 %{pointNumber}<extra></extra>`
      });
      traces.push({type:'scatter3d',mode:'markers',x:[position[0]],y:[position[1]],z:[position[2]],marker:{size:selected?12:8,color:'#22d3ee',symbol:'diamond',line:{color:'#fff',width:selected?2:0}},name:entity.name,customdata:[entity.id],hovertemplate:`<b>${escapeHtml(entity.name)}</b><br>阵列平台<extra></extra>`});
    } else if (geometry.shape==='box') {
      traces.push(boxMesh(entity,position,selected));
    } else if (geometry.shape==='plane' && !component(entity,'probe')) {
      const dx=geometry.dimensions_m.x/2, dy=geometry.dimensions_m.y/2;
      traces.push({type:'mesh3d',x:[position[0]-dx,position[0]+dx,position[0]+dx,position[0]-dx],y:[position[1]-dy,position[1]-dy,position[1]+dy,position[1]+dy],z:[position[2],position[2],position[2],position[2]],i:[0,0],j:[1,2],k:[2,3],color:geometry.color,opacity:.32,name:entity.name,hoverinfo:'skip',showscale:false});
    } else if (component(entity,'probe')) {
      if (!state.result || !state.showField) {
        const dx=geometry.dimensions_m.x/2, dy=geometry.dimensions_m.y/2;
        traces.push({type:'mesh3d',x:[position[0]-dx,position[0]+dx,position[0]+dx,position[0]-dx],y:[position[1]-dy,position[1]-dy,position[1]+dy,position[1]+dy],z:[position[2],position[2],position[2],position[2]],i:[0,0],j:[1,2],k:[2,3],color:'#38bdf8',opacity:.13,name:entity.name,hovertemplate:`<b>${escapeHtml(entity.name)}</b><br>平面探针<extra></extra>`,showscale:false});
      }
    } else {
      const isMoving=Boolean(component(entity,'motion'));
      const isReceiver=Boolean(component(entity,'receiver'));
      traces.push({
        type:'scatter3d',mode:selected?'markers+text':'markers',
        x:[position[0]],y:[position[1]],z:[position[2]],
        text:selected?[entity.name]:undefined,textposition:'top center',textfont:{color:'#f8fafc',size:11},
        marker:{size:selected?11:(isMoving?8:7),color:colorFor(entity),symbol:isMoving?'diamond':(isReceiver?'cross':'circle'),line:{color:selected?'#fff':'#101827',width:selected?2:1}},
        customdata:[entity.id],name:entity.name,
        hovertemplate:`<b>${escapeHtml(entity.name)}</b><br>x=${position[0].toFixed(1)} m<br>y=${position[1].toFixed(1)} m<br>z=${position[2].toFixed(1)} m<extra></extra>`
      });
    }

    const motion=component(entity,'motion');
    if (motion && motion.waypoints?.length && state.showTrajectories) {
      traces.push({type:'scatter3d',mode:'lines',x:motion.waypoints.map(p=>p.position_m.x),y:motion.waypoints.map(p=>p.position_m.y),z:motion.waypoints.map(p=>p.position_m.z),line:{color:colorFor(entity),width:selected?6:3,dash:'dash'},opacity:.75,hoverinfo:'skip',showlegend:false});
    }
  }

  const layout={
    margin:{l:0,r:0,t:0,b:0},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',showlegend:false,
    uirevision:'studio-scene',
    scene:{
      bgcolor:'#080d14',
      xaxis:{title:'X / m',gridcolor:'#263449',zerolinecolor:'#3a4b62',color:'#72849a',showbackground:false},
      yaxis:{title:'Y / m',gridcolor:'#263449',zerolinecolor:'#3a4b62',color:'#72849a',showbackground:false},
      zaxis:{title:'Z / m',gridcolor:'#263449',zerolinecolor:'#3a4b62',color:'#72849a',showbackground:false},
      aspectmode:'data',
      camera:state.camera || {eye:{x:1.45,y:-1.6,z:1.05},center:{x:0,y:0,z:-.12},up:{x:0,y:0,z:1}}
    },
    font:{family:'Microsoft YaHei UI, sans-serif',color:'#9fb0c5'}
  };
  Plotly.react('scenePlot',traces,layout,{responsive:true,displaylogo:false,scrollZoom:true,modeBarButtonsToRemove:['toImage','sendDataToCloud']});
  const plot=document.getElementById('scenePlot');
  if (!plot.__eventsBound) {
    plot.on('plotly_click', data => {
      const id=data?.points?.[0]?.customdata;
      if (id) selectEntity(id);
    });
    plot.on('plotly_relayout', data => {
      if (data['scene.camera']) state.camera=data['scene.camera'];
    });
    plot.__eventsBound=true;
  }
}

function configureTimeline() {
  const slider=document.getElementById('timelineSlider');
  const frames=state.result?.times_s?.length || 1;
  slider.max=Math.max(0,frames-1);
  state.frame=Math.min(state.frame,frames-1);
  slider.value=state.frame;
  updateTimelineReadout();
}

function updateTimelineReadout() {
  const times=state.result?.times_s || [0];
  const current=times[Math.min(state.frame,times.length-1)] || 0;
  document.getElementById('currentTime').textContent=`${current.toFixed(2)} s`;
  document.getElementById('frameReadout').textContent=`帧 ${state.frame+1} / ${times.length}`;
  document.getElementById('metricFrame').textContent=`${state.frame+1}/${times.length}`;
}

function renderReceiverChart() {
  const chart=document.getElementById('receiverChart');
  if (!state.result || !Object.keys(state.result.receiver_amplitudes || {}).length) {
    Plotly.purge(chart);
    return;
  }
  const entities=Object.fromEntries(state.project.scene.entities.map(e=>[e.id,e]));
  const traces=Object.entries(state.result.receiver_amplitudes).map(([id,values])=>({
    type:'scatter',mode:'lines',x:state.result.times_s,y:values,name:entities[id]?.name || id.slice(0,8),line:{width:1.8}
  }));
  const layout={margin:{l:48,r:18,t:12,b:30},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'#0b1320',font:{color:'#879bb3',size:9},xaxis:{title:'时间 / s',gridcolor:'#243247'},yaxis:{title:'归一化接收幅度',range:[0,1.05],gridcolor:'#243247'},legend:{orientation:'h',y:1.18,x:0}};
  Plotly.react(chart,traces,layout,{responsive:true,displayModeBar:false});
}

function renderMetrics() {
  const overlay=document.getElementById('metricOverlay');
  if (!state.result) { overlay.classList.add('d-none'); return; }
  overlay.classList.remove('d-none');
  const s=state.result.summary;
  document.getElementById('metricMean').textContent=s.mean_receiver_amplitude.toFixed(3);
  document.getElementById('metricMin').textContent=s.minimum_receiver_amplitude.toFixed(3);
  document.getElementById('metricStable').textContent=(s.temporal_stability*100).toFixed(1)+'%';
  updateTimelineReadout();
}

function renderMission() {
  const dock=document.getElementById('missionDock');
  if (!state.project.missions.length) {
    dock.innerHTML='<button id="createMissionBtn" class="btn btn-sm btn-primary">创建默认动态覆盖任务</button>';
    dock.querySelector('#createMissionBtn').addEventListener('click', createMission);
    return;
  }
  const mission=state.project.missions[0];
  const emitterCount=state.project.scene.entities.filter(e=>hasRole(e,'emitter_platform')).length;
  const targetCount=state.project.scene.entities.filter(e=>hasRole(e,'trackable')).length;
  const receiverCount=state.project.scene.entities.filter(e=>component(e,'receiver')).length;
  dock.innerHTML=`<div class="mission-grid">
    <div class="mission-block"><small>任务</small><strong>${escapeHtml(mission.name)}</strong><p>${escapeHtml(mission.description || mission.mission_type)}</p></div>
    <div class="mission-block"><small>参与对象</small><strong>${emitterCount} 个阵列 · ${targetCount} 个运动对象 · ${receiverCount} 个接收器</strong><p>由角色/组件查询自动选择，不使用固定编号。</p></div>
    <div class="mission-block"><small>控制策略</small><strong>${mission.solver.controller_mode}</strong><p>目标查询：${mission.solver.target_query}</p></div>
    <div class="mission-block"><small>时间网格</small><strong>${mission.time_grid.frame_count} 帧</strong><p>${mission.time_grid.start_s.toFixed(1)}–${mission.time_grid.stop_s.toFixed(1)} s</p></div>
  </div>`;
}

async function runMission() {
  const mission=state.project.missions[0];
  if (!mission) { toast('请先创建任务','warning'); return; }
  const button=document.getElementById('runBtn');
  button.disabled=true;
  button.innerHTML='<span class="spinner-border spinner-border-sm me-1"></span>求解中';
  status('正在计算多实体动态场景…');
  log(`开始任务：${mission.name}`);
  try {
    state.result=await api(`/api/missions/${mission.id}/run`,{method:'POST'});
    state.frame=0;
    configureTimeline(); renderScene(); renderReceiverChart(); renderMetrics(); renderMission();
    log(`任务完成：${state.result.summary.frame_count} 帧，${state.result.summary.emitter_count} 个阵列，${state.result.summary.receiver_count} 个接收器，耗时 ${state.result.summary.runtime_ms.toFixed(1)} ms。`);
    status('求解完成，可拖动时间线回放');
    toast('动态任务已完成','success');
  } catch(error) {
    log(`任务失败：${error.message}`);
    status('任务失败'); toast(error.message,'danger');
  } finally {
    button.disabled=false;
    button.innerHTML='<i class="bi bi-play-fill me-1"></i>运行任务';
  }
}

async function createMission() {
  await api('/api/missions/default',{method:'POST'});
  await bootstrap();
}

async function saveProject() {
  status('正在保存工程…');
  try {
    const data=await api('/api/project/save',{method:'POST',body:JSON.stringify({filename:state.project.metadata.name})});
    const link=document.createElement('a'); link.href=data.download_url; link.download=data.filename; link.click();
    status('工程已保存'); toast('工程已保存为 .hpmdt 文件','success');
  } catch(error) { status('保存失败'); toast(error.message,'danger'); }
}

async function newProject() {
  if (!confirm('新建空白工程将替换当前未保存内容，是否继续？')) return;
  stopPlayback();
  status('正在新建工程…');
  const data = await api('/api/project/new', {method:'POST'});
  state.project=data.project; state.result=data.latest_result; state.selectedId=null; state.frame=0; state.camera=null;
  renderAll(); status('空白工程已创建'); toast('已新建空白工程','success');
}

async function openProject(file) {
  if (!file) return;
  stopPlayback();
  status('正在打开工程…');
  const form = new FormData();
  form.append('file', file);
  try {
    const data = await apiForm('/api/project/open', form);
    state.project=data.project; state.result=data.latest_result; state.selectedId=null; state.frame=0; state.camera=null;
    renderAll(); status('工程已打开'); toast(`已打开：${file.name}`,'success');
  } catch(error) {
    status('打开失败'); toast(error.message,'danger');
  } finally {
    document.getElementById('projectFileInput').value='';
  }
}

async function loadExample(id) {
  if (!id) return;
  stopPlayback();
  status('正在切换工程…');
  const data=await api(`/api/examples/${id}/load`,{method:'POST'});
  state.project=data.project; state.result=data.latest_result; state.selectedId=null; state.frame=0; state.camera=null;
  renderAll(); status('示例工程已载入');
}

async function addAsset(kind) {
  const entity=await api('/api/entities',{method:'POST',body:JSON.stringify({kind})});
  state.project.scene.entities.push(entity);
  state.selectedId=entity.id;
  renderAll();
  toast(`已添加：${entity.name}`,'success');
}

async function updateSelected(event) {
  event.preventDefault();
  if (!state.selectedId) return;
  const entity=state.project.scene.entities.find(e=>e.id===state.selectedId);
  const payload={
    name:document.getElementById('entityName').value,
    transform:{
      position_m:{x:+document.getElementById('posX').value,y:+document.getElementById('posY').value,z:+document.getElementById('posZ').value},
      rotation_deg:{x:+document.getElementById('rotX').value,y:+document.getElementById('rotY').value,z:+document.getElementById('rotZ').value},
      scale:entity.transform.scale,
    }
  };
  const updated=await api(`/api/entities/${state.selectedId}`,{method:'PATCH',body:JSON.stringify(payload)});
  Object.assign(entity,updated);
  state.result=null; state.frame=0;
  renderAll(); status('场景已修改，请重新运行任务');
}

async function deleteSelected() {
  if (!state.selectedId) return;
  const entity=state.project.scene.entities.find(e=>e.id===state.selectedId);
  if (!confirm(`确认删除“${entity.name}”？`)) return;
  await api(`/api/entities/${state.selectedId}`,{method:'DELETE'});
  state.project.scene.entities=state.project.scene.entities.filter(e=>e.id!==state.selectedId);
  state.selectedId=null; state.result=null; renderAll();
}

function playPause() {
  if (!state.result || state.result.times_s.length < 2) return;
  if (state.playing) stopPlayback(); else startPlayback();
}

function startPlayback() {
  state.playing=true;
  document.getElementById('playBtn').innerHTML='<i class="bi bi-pause-fill"></i>';
  state.timer=setInterval(()=>{
    const count=state.result.times_s.length;
    state.frame=(state.frame+1)%count;
    document.getElementById('timelineSlider').value=state.frame;
    updateTimelineReadout(); renderScene();
  },260);
}

function stopPlayback() {
  state.playing=false;
  clearInterval(state.timer); state.timer=null;
  document.getElementById('playBtn').innerHTML='<i class="bi bi-play-fill"></i>';
}

function bindUI() {
  document.getElementById('runBtn').addEventListener('click',runMission);
  document.getElementById('newBtn').addEventListener('click',newProject);
  document.getElementById('openBtn').addEventListener('click',()=>document.getElementById('projectFileInput').click());
  document.getElementById('projectFileInput').addEventListener('change',e=>openProject(e.target.files?.[0]));
  document.getElementById('saveBtn').addEventListener('click',saveProject);
  document.getElementById('exampleSelect').addEventListener('change',e=>loadExample(e.target.value));
  document.getElementById('inspectorForm').addEventListener('submit',updateSelected);
  document.getElementById('deleteBtn').addEventListener('click',deleteSelected);
  document.getElementById('playBtn').addEventListener('click',playPause);
  document.getElementById('timelineSlider').addEventListener('input',e=>{
    stopPlayback(); state.frame=+e.target.value; updateTimelineReadout(); renderScene();
  });
  document.querySelectorAll('.asset-card').forEach(button=>button.addEventListener('click',()=>addAsset(button.dataset.kind)));
  document.querySelectorAll('.panel-tab').forEach(button=>button.addEventListener('click',()=>{
    document.querySelectorAll('.panel-tab').forEach(b=>b.classList.toggle('active',b===button));
    document.getElementById('treePanel').classList.toggle('d-none',button.dataset.panel!=='tree');
    document.getElementById('assetPanel').classList.toggle('d-none',button.dataset.panel!=='assets');
  }));
  document.querySelectorAll('.dock-tab').forEach(button=>button.addEventListener('click',()=>{
    document.querySelectorAll('.dock-tab').forEach(b=>b.classList.toggle('active',b===button));
    ['timeline','chart','mission','log'].forEach(name=>document.getElementById(name+'Dock').classList.toggle('d-none',name!==button.dataset.dock));
    if (button.dataset.dock==='chart') setTimeout(()=>Plotly.Plots.resize('receiverChart'),40);
  }));
  document.getElementById('toggleFieldBtn').addEventListener('click',e=>{state.showField=!state.showField;e.currentTarget.classList.toggle('active',state.showField);renderScene();});
  document.getElementById('toggleTrajectoryBtn').addEventListener('click',e=>{state.showTrajectories=!state.showTrajectories;e.currentTarget.classList.toggle('active',state.showTrajectories);renderScene();});
  document.getElementById('homeViewBtn').addEventListener('click',()=>{state.camera={eye:{x:1.45,y:-1.6,z:1.05},center:{x:0,y:0,z:-.12},up:{x:0,y:0,z:1}};renderScene();});
  document.getElementById('topViewBtn').addEventListener('click',()=>{state.camera={eye:{x:0,y:0,z:2.7},center:{x:0,y:0,z:0},up:{x:0,y:1,z:0}};renderScene();});
  window.addEventListener('resize',()=>{Plotly.Plots.resize('scenePlot'); if(state.result) Plotly.Plots.resize('receiverChart');});
}

document.addEventListener('DOMContentLoaded',async()=>{
  bindUI();
  try { await bootstrap(); }
  catch(error) { status('启动失败'); toast(error.message,'danger'); console.error(error); }
});
