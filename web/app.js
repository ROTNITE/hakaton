'use strict';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const state = {
  runs: [], selected: null, summary: null, frames: [], map: {}, index: 0,
  records: [], cursor: null, fronts: [], compared: new Set(), timer: null, loadToken: 0,
  logToken: 0, aiLoaded: false, comparing: 0, heatmap: null, anomalies: null
};
const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const format = value => value === null || value === undefined ? '—' : typeof value === 'number' ? nf.format(value) : String(value);
const statusLabels = {
  success: 'Миссия завершена', time_limit: 'Горизонт достигнут', failed: 'Миссия остановлена',
  fixture_passed: 'Проверка пройдена', fixture_failed: 'Ошибка проверки',
  render_passed: 'Рендер проверен', render_failed: 'Ошибка рендера',
  incomplete: 'Неполный архив', safe_stopped: 'Безопасная остановка'
};
const kindLabels = { ground: 'Наземный', aerial: 'Дрон', underground: 'Подземный',
  surface_water: 'Надводный', underwater: 'Подводный', infrastructure: 'Сенсорный узел',
  digital: 'Вычислитель', operator: 'Оператор' };

function element(tag, text, className = '') {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function notice(text = '', error = false) {
  $('#notice').textContent = text;
  $('#notice').classList.toggle('error', error);
}

async function api(path) {
  const response = await fetch(path);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Не удалось прочитать архив');
  return value;
}

function endpoint(action, query = {}) {
  return '/api/runs/' + encodeURIComponent(state.selected) + '/' + action + '?' + new URLSearchParams(query);
}

function tab(name) {
  $$('.tab-panel').forEach(panel => { panel.hidden = panel.id !== name; });
  $$('[data-tab]').forEach(button => {
    button.classList.toggle('active', button.dataset.tab === name);
    button.setAttribute('aria-selected', String(button.dataset.tab === name));
  });
  if (name === 'journal' && state.selected && !state.records.length) loadRecords();
  if (name === 'ai' && state.summary && !state.aiLoaded) loadAI();
  requestAnimationFrame(drawAll);
}

function renderRuns() {
  const query = $('#run-search').value.trim().toLowerCase();
  const container = $('#run-list');
  container.replaceChildren();
  for (const run of state.runs.filter(row => (row.name + ' ' + (row.policy || '')).toLowerCase().includes(query))) {
    const item = element('div', undefined, 'run-item' + (state.selected === run.id ? ' selected' : ''));
    const check = element('input');
    check.type = 'checkbox';
    check.disabled = run.kind === 'visual';
    check.checked = state.compared.has(run.id);
    check.setAttribute('aria-label', 'Сравнить ' + run.name);
    check.onchange = () => check.checked ? state.compared.add(run.id) : state.compared.delete(run.id);
    const button = element('button', undefined, 'run-button');
    button.append(element('span', run.name, 'run-title'));
    button.append(element('span', (run.policy || run.kind) + ' · ' + (statusLabels[run.status] || run.status), 'run-meta'));
    button.onclick = () => selectRun(run.id);
    item.append(check, button);
    container.append(item);
  }
  $('#run-count').textContent = String(state.runs.length);
}

async function refresh() {
  try {
    state.runs = (await api('/api/runs')).runs;
    renderRuns();
    if (!state.selected && state.runs.length) {
      const requested = new URLSearchParams(location.search).get('run');
      const first = state.runs.find(run => run.id === requested) || state.runs.find(run => run.kind === 'mission') || state.runs[0];
      await selectRun(first.id);
    }
  } catch (error) { notice(error.message, true); }
}

async function selectRun(identifier) {
  stopPlayback();
  const token = ++state.loadToken;
  state.selected = identifier;
  state.frames = []; state.records = []; state.fronts = []; state.summary = null;
  state.aiLoaded = false; state.logToken++;
  state.index = 0; state.cursor = null;
  state.map = {};
  state.heatmap = null; state.anomalies = null;
  $('#heat-basis').hidden = true; $('#substeps').hidden = true; $('#substeps').open = false;
  for (const selector of ['#metrics', '#acceptance', '#competition-metrics', '#agent-details', '#records', '#causal-links',
    '#ai-metrics', '#usage', '#front-select', '#front-table', '#agent', '#map-legend']) $(selector).replaceChildren();
  $('#record-detail').textContent = 'Выберите запись.';
  $('#front-detail').textContent = ''; $('#record-count').textContent = '';
  $('#sample-basis').textContent = ''; $('#more-records').hidden = true;
  $('#time').max = 0; $('#time').value = 0; $('#time-value').textContent = '—'; $('#time-end').textContent = '—';
  drawAll();
  renderRuns();
  const run = state.runs.find(item => item.id === identifier);
  $('.export-menu').hidden = run.kind === 'visual';
  $('#run-name').textContent = run.name;
  $('#run-status').textContent = statusLabels[run.status] || run.status;
  $('#run-status').classList.toggle('failure', run.status.includes('fail'));
  history.replaceState(null, '', '?run=' + encodeURIComponent(identifier));
  $$('[data-export]').forEach(link => { link.href = endpoint('export', { format: link.dataset.export }); });
  $('#archive-id').textContent = '';
  notice('Проверяю архив и строю локальный индекс…');
  try {
    let report;
    for (;;) {
      report = await api(endpoint('summary'));
      if (token !== state.loadToken) return;
      if (report.state !== 'indexing') break;
      const progress = report.progress || {};
      const stage = { verify: 'Проверяю CRC и хэши архива', records: 'Индексирую журналы', metrics: 'Рассчитываю показатели' };
      notice((stage[progress.stage] || 'Подготавливаю индекс') + '… ' +
        Object.entries(progress.records || {}).map(([name, count]) => name + ': ' + format(count)).join(' · '));
      await new Promise(resolve => setTimeout(resolve, 700));
    }
    if (report.state === 'error') throw new Error(report.error);
    if (report.visual) {
      $('#metrics').replaceChildren(metric('Частота кадров', format(report.visual.fps) + ' FPS', 'Обзорный прогон'),
        metric('p95 кадра', format(report.visual.p95_frame_ms) + ' мс', 'Реальный рендер'),
        metric('Здания', format(report.visual.buildings), 'Нативная сцена'),
        metric('Память', format(report.visual.memory_mb) + ' MiB', 'Рабочий набор'));
      notice('Выбран визуальный прогон. Для просмотра миссии откройте запуск с нативным журналом Core.');
      state.frames = []; drawAll(); return;
    }
    state.summary = report.summary;
    renderMetrics();
    const [map, timeline] = await Promise.all([api(endpoint('map')), api(endpoint('timeline', { basis: $('#basis').value }))]);
    if (token !== state.loadToken) return;
    state.map = map; setTimeline(timeline);
    $('#archive-id').textContent = 'EPISODE ' + report.summary.episode_id;
    const labels = { 'native render frame profile unavailable': 'В этом архиве нет замеров рендера',
      'priority unavailable in this historical archive': 'В историческом архиве нет приоритетов целей' };
    notice(report.summary.metrics.unverified.map(value => labels[value] || value).join(' · '));
    if (!$('#journal').hidden) await loadRecords();
    if (!$('#ai').hidden) await loadAI();
  } catch (error) { if (token === state.loadToken) notice(error.message, true); }
}

function metric(label, value, note) {
  const node = element('article', undefined, 'metric');
  node.append(element('div', label, 'metric-label'), element('div', value, 'metric-value'), element('div', note, 'metric-note'));
  return node;
}

function detail(parent, name, value) {
  const row = element('div', undefined, 'detail-row');
  row.append(element('span', name), element('span', format(value)));
  parent.append(row);
}

function renderMetrics() {
  const summary = state.summary, m = summary.metrics;
  $('#metrics').replaceChildren(
    metric('Эвакуировано', format(m.rescued) + ' / ' + format(m.registered_targets), m.rescued_fraction === null ? 'Нет зарегистрированных целей' : format(100 * m.rescued_fraction) + '% зарегистрированных целей'),
    metric('Наблюдаемое время', format(m.cutoff_s) + ' с', 'Срез завершения эпизода'),
    metric('Расход энергии', format(m.energy_wh) + ' Wh', 'Накопленный фактический расход'),
    metric('p95 решения', format(m.decision_wall_s.p95 === null ? null : m.decision_wall_s.p95 * 1000) + ' мс', format(m.decision_count) + ' решений контроллера'));
  const acceptance = $('#acceptance');
  acceptance.replaceChildren();
  acceptance.append(element('div', summary.archive_verified ? '✓ CRC и хэши архива подтверждены' : 'Архив требует проверки'));
  acceptance.append(element('div', 'Статус среды · ' + summary.native_status));
  acceptance.append(element('div', format(m.telemetry_records) + ' записей телеметрии'));
  acceptance.append(element('div', 'Потоки · ' + Object.entries(summary.streams).map(([name, count]) => name + ' ' + nf.format(count)).join(' / ')));
  const competition = $('#competition-metrics');
  competition.replaceChildren();
  for (const [title, value, description] of [
    ['M1 · Завершённость целей', m.M1.value === null ? 'Не вычислен' : nf.format(m.M1.value),
      'Взвешенная доля фактически эвакуированных. Приоритеты берутся в финальном срезе.'],
    ['M2 · Передачи после возмущений', format(m.M2.post_disturbance_handovers),
      m.M2.physical_disturbances.length ? 'Физических возмущений: ' + format(m.M2.physical_disturbances.length) : 'Возмущения в архиве отсутствуют.'],
    ['M3 · Доставленные сообщения', format(m.M3.delivered_message_records),
      'Энергия ' + format(m.M3.energy_wh) + ' Wh · расстояние ' + format(m.M3.distance_m) + ' м'],
    ['M4 · Принятые изменения сценария', format(m.M6.accepted_transitions),
      Object.entries(m.M4.accepted_transitions).map(([op, count]) => op + ' ' + count).join(' · ') || 'Изменения не подтверждены.'],
    ['M5 · Межкомандная совместимость', 'Не проверен', 'Требуются реализации других команд и результаты совместных испытаний.'],
    ['M6 · Восстановленные цепочки', format(m.M6.strictly_joined_transitions) + ' / ' + format(m.M6.accepted_transitions),
      'Связаны исходное наблюдение, решение, проверки, ревизия и подтверждённые результаты.'],
    ['M7 · Записи физической телеметрии', format(m.M7.truth_telemetry),
      'Публичных наблюдений: ' + format(m.M7.public_observations)],
    ['Информационная свежесть', format(m.mean_stale_ratio === null ? null : m.mean_stale_ratio * 100) + '%',
      'Средняя доля устаревших сведений. Максимальная доставленная задержка ' + format(m.maximum_delivered_delay_s) + ' с.']
  ]) {
    const cell = element('div');
    cell.append(element('h3', title), element('div', value, 'detail-value'), element('p', description));
    competition.append(cell);
  }
}

function setTimeline(timeline) {
  const previousAgent = $('#agent').value;
  state.frames = timeline.frames; state.index = 0;
  $('#time').max = Math.max(0, state.frames.length - 1); $('#time').value = 0;
  $('#time-end').textContent = format(state.frames.at(-1)?.time) + ' с';
  $('#sample-basis').textContent = (timeline.basis === 'truth' ? 'Истина среды' : 'Доставленные наблюдения') +
    ' · кадр каждые ' + timeline.sample_stride + ' записи';
  const agents = new Map(state.frames.flatMap(frame => frame.agents).map(agent => [agent.id, agent]));
  $('#agent').replaceChildren();
  for (const [id, agent] of agents) {
    const option = element('option', id + ' · ' + (kindLabels[agent.kind] || agent.kind));
    option.value = id; $('#agent').append(option);
  }
  if (agents.has(previousAgent)) $('#agent').value = previousAgent;
  $('#substeps').hidden = timeline.basis !== 'truth';
  refreshHeatmap();
  updateFrame();
}

async function refreshHeatmap() {
  const basis = $('#basis').value, token = state.loadToken, mode = $('#heat-layer').value;
  const caption = $('#heat-basis');
  caption.hidden = mode === 'off' || !state.summary;
  if (caption.hidden) { drawMap(); return; }
  try {
    if (state.heatmap?.basis !== basis) {
      caption.textContent = 'Считаю по записанным позам…';
      const result = await api(endpoint('heatmap', { basis }));
      if (token !== state.loadToken || basis !== $('#basis').value) return;
      state.heatmap = result;
    }
    const source = basis === 'truth' ? 'телеметрия 10 Гц' : 'уникальные доставленные позы';
    caption.textContent = 'Весь эпизод · 10 × 10 м · ' + source +
      ($('#heat-layer').value === 'radio' ? ' · доля отсчётов без связи или с качеством < 0,5' : ' · яркость по числу отсчётов');
    drawMap();
  } catch (error) { if (token === state.loadToken) caption.textContent = error.message; }
}

async function loadSubsteps() {
  if (!$('#substeps').open || $('#substeps').hidden) { drawMap(); return; }
  const token = state.loadToken;
  try {
    if (!state.anomalies) {
      $('#substep-value').textContent = 'Загружаю подшаги…';
      const page = await api(endpoint('records', { stream: 'truth', kind: 'substep_trace', limit: 48 }));
      if (token !== state.loadToken) return;
      state.anomalies = page.records.map(row => row.record.payload);
      const options = state.anomalies.map((window, i) => {
        const option = element('option', format(window.trigger_at_s) + ' с · ' + window.agent_id + ' · ' + window.trigger);
        option.value = i;
        return option;
      });
      $('#substep-window').replaceChildren(...options);
      selectSubstepWindow();
    } else showSubstep();
  } catch (error) { if (token === state.loadToken) $('#substep-value').textContent = error.message; }
}

function selectedSubstepWindow() { return state.anomalies?.[Number($('#substep-window').value)]; }

function selectSubstepWindow() {
  const window = selectedSubstepWindow();
  $('#substep-time').max = Math.max(0, (window?.samples.length || 1) - 1);
  $('#substep-time').value = window ? Math.max(0, window.samples.findIndex(sample => sample.time_s >= window.trigger_at_s)) : 0;
  showSubstep();
}

function showSubstep() {
  const sample = selectedSubstepWindow()?.samples[Number($('#substep-time').value)];
  $('#substep-value').textContent = sample ? sample.time_s.toFixed(3) + ' с · ' +
    sample.position_m.map(format).join(' / ') + ' м · ' + format(Math.hypot(...sample.velocity_m_s)) + ' м/с' :
    'В архиве нет записанных окон.';
  drawMap();
}

function updateFrame() {
  const frame = state.frames[state.index];
  $('#time-value').textContent = format(frame?.time) + ' с';
  const actor = frame?.agents.find(agent => agent.id === $('#agent').value);
  const node = $('#agent-details'); node.replaceChildren();
  if (actor) {
    node.append(element('div', kindLabels[actor.kind] || actor.kind, 'muted'));
    node.append(element('div', actor.id, 'detail-value'));
    for (const [label, value] of [
      ['Состояние', actor.status], ['Роль', actor.role], ['Сценарии', actor.scenario_ids?.join(', ') || '—'],
      ['Позиция, м', actor.position?.map(format).join(' / ') || '—'], ['Батарея, Wh', actor.physical?.remaining_wh],
      ['Расход, Wh', actor.physical?.consumed_wh], ['Груз', actor.physical?.cargo_target_id || 'Свободен'],
      ['Связь', actor.communication?.reachable ? 'Доступна' : 'Нет доставленного канала'],
      ['Причина остановки', actor.physical?.stop_reason || '—'], ['Команда', actor.physical?.active_command_id || '—']
    ]) detail(node, label, value);
    const freshness = actor.freshness?.position;
    if (freshness) {
      detail(node, 'Поза измерена, с', freshness.observed_at);
      detail(node, 'Поза доставлена, с', freshness.received_at);
      detail(node, 'Возраст позы, с', Math.max(0, frame.time - freshness.observed_at));
    }
  } else node.append(element('p', 'Сведения об агенте отсутствуют в выбранном кадре.', 'muted'));
  drawAll();
}

function canvasContext(identifier) {
  const canvas = $(identifier), rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const ratio = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
  const context = canvas.getContext('2d');
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { context, width: rect.width, height: rect.height };
}

function color(id) {
  let hash = 2166136261;
  for (const character of id) hash = Math.imul(hash ^ character.codePointAt(0), 16777619);
  return 'hsl(' + ((Math.imul(hash, 2654435761) >>> 0) % 360) + ' 53% 68%)';
}

function drawMap() {
  const surface = canvasContext('#map');
  if (!surface) return;
  const { context: ctx, width, height } = surface;
  const bounds = state.map.bounds || { min: [0, 0], max: [250, 250] };
  const scale = Math.min((width - 46) / (bounds.max[0] - bounds.min[0]), (height - 36) / (bounds.max[1] - bounds.min[1]));
  const offsetX = (width - (bounds.max[0] - bounds.min[0]) * scale) / 2;
  const offsetY = (height - (bounds.max[1] - bounds.min[1]) * scale) / 2;
  const point = p => [offsetX + (p[0] - bounds.min[0]) * scale, height - offsetY - (p[1] - bounds.min[1]) * scale];
  ctx.fillStyle = '#111a15'; ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = '#29352b'; ctx.lineWidth = 1;
  for (let value = 0; value <= (state.map.size_m || 250); value += 25) {
    let a = point([value, bounds.min[1]]), b = point([value, bounds.max[1]]);
    ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
    a = point([bounds.min[0], value]); b = point([bounds.max[0], value]);
    ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
  }
  const road = state.map.road_graph;
  if (road) {
    const nodes = new Map(road.nodes.map(node => [node.id, node.position]));
    ctx.strokeStyle = '#3b463b';
    for (const edge of road.edges) {
      ctx.lineWidth = Math.max(1.4, edge.width_m * scale);
      ctx.beginPath(); ctx.moveTo(...point(nodes.get(edge.from))); ctx.lineTo(...point(nodes.get(edge.to))); ctx.stroke();
    }
  }
  function drawBox(box, fill, stroke) {
    if (!box?.min || !box?.max) return;
    const left = point([box.min[0], box.max[1]]), right = point([box.max[0], box.min[1]]);
    ctx.fillStyle = fill; ctx.fillRect(left[0], left[1], right[0] - left[0], right[1] - left[1]);
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.strokeRect(left[0], left[1], right[0] - left[0], right[1] - left[1]); }
  }
  if ($('#layer-buildings').checked) {
    for (const house of state.map.buildings || []) drawBox(house.bounds, '#59614e', '#6c745b');
    for (const facility of state.map.facilities || []) drawBox(facility.bounds, '#3b4e46', '#5f7163');
  }
  if (state.map.base) drawBox(state.map.base, '#475735', '#a6c779');
  const frame = state.frames[state.index];
  if (!frame) return;
  const heat = state.heatmap, heatMode = $('#heat-layer').value;
  if (heatMode !== 'off' && heat?.basis === $('#basis').value) {
    const maxCount = heat.cells.reduce((largest, cell) => Math.max(largest, cell[2]), 1);
    for (const [i, j, count, radioSamples, weak] of heat.cells) {
      const intensity = heatMode === 'radio' ? (radioSamples ? weak / radioSamples : 0) : Math.log1p(count) / Math.log1p(maxCount);
      if (!intensity) continue;
      const min = [heat.bounds.min[0] + i * heat.cell_m, heat.bounds.min[1] + j * heat.cell_m];
      const max = min.map((v, d) => Math.min(v + heat.cell_m, heat.bounds.max[d]));
      drawBox({ min, max }, 'rgba(245, 160, 83, ' + (.12 + .66 * intensity) + ')');
    }
  }
  if ($('#layer-hazards').checked) {
    for (const zone of frame.zones) if (['hazard', 'restricted', 'water', 'low_connectivity'].includes(zone.type)) {
      drawBox(zone.geometry, zone.type === 'water' ? '#3c8f9a55' : '#e38c5655', '#c58c58');
    }
  }
  const currentAgents = new Map(frame.agents.map(agent => [agent.id, agent]));
  if ($('#layer-trails').checked) {
    const trails = new Map();
    for (const recorded of state.frames.slice(0, state.index + 1)) for (const agent of recorded.agents) {
      if (!agent.position) continue;
      if (!trails.has(agent.id)) trails.set(agent.id, []);
      trails.get(agent.id).push(agent.position);
    }
    for (const [id, points] of trails) {
      ctx.strokeStyle = color(id); ctx.globalAlpha = .65; ctx.lineWidth = id === $('#agent').value ? 2 : 1.2;
      ctx.beginPath(); points.forEach((p, index) => index ? ctx.lineTo(...point(p)) : ctx.moveTo(...point(p)));
      ctx.stroke(); ctx.globalAlpha = 1;
    }
  }
  if ($('#layer-network').checked) {
    ctx.strokeStyle = '#83c5b8'; ctx.lineWidth = 1; ctx.setLineDash([3, 4]);
    for (const link of frame.network.known_links || []) {
      const from = currentAgents.get(link.from)?.position || (state.map.infrastructure || []).find(node => node.id === link.from)?.position;
      const to = currentAgents.get(link.to)?.position;
      if (from && to) { ctx.beginPath(); ctx.moveTo(...point(from)); ctx.lineTo(...point(to)); ctx.stroke(); }
    }
    ctx.setLineDash([]);
  }
  if ($('#layer-targets').checked) for (const target of frame.targets) {
    if (!target.position) continue;
    const p = point(target.position);
    ctx.fillStyle = target.evacuation_state === 'evacuated' || target.rescued ? '#cee58d' : '#e4ad88';
    ctx.beginPath(); ctx.arc(...p, target.status === 'suspected' ? 2 : 3.2, 0, Math.PI * 2); ctx.fill();
  }
  for (const agent of frame.agents) {
    if (!agent.position) continue;
    const p = point(agent.position), chosen = agent.id === $('#agent').value;
    ctx.fillStyle = color(agent.id);
    ctx.beginPath(); ctx.arc(...p, chosen ? 5 : 3.8, 0, Math.PI * 2); ctx.fill();
    if (chosen) { ctx.strokeStyle = '#f3f4e7'; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(...p, 8, 0, Math.PI * 2); ctx.stroke(); }
  }
  const anomaly = $('#substeps').open && !$('#substeps').hidden ? selectedSubstepWindow() : null;
  if (anomaly?.samples.length) {
    ctx.strokeStyle = '#ffd373'; ctx.lineWidth = 3; ctx.beginPath();
    anomaly.samples.forEach((sample, i) => i ? ctx.lineTo(...point(sample.position_m)) : ctx.moveTo(...point(sample.position_m)));
    ctx.stroke();
    const sample = anomaly.samples[Number($('#substep-time').value)];
    if (sample) { ctx.fillStyle = '#ffd373'; ctx.beginPath(); ctx.arc(...point(sample.position_m), 6, 0, Math.PI * 2); ctx.fill(); }
  }
  const legend = $('#map-legend'); legend.replaceChildren();
  for (const actor of frame.agents.slice(0, 8)) {
    const label = element('span'); const dot = element('i', undefined, 'legend-dot');
    dot.style.background = color(actor.id); label.append(dot, document.createTextNode(actor.id)); legend.append(label);
  }
  ctx.fillStyle = '#a4b19d'; ctx.font = '9px Roboto';
  ctx.fillText(format(state.map.size_m || 250) + ' м', width - 47, 18);
}

function lineChart(identifier, series, axisLabel = '') {
  const surface = canvasContext(identifier);
  if (!surface) return;
  const { context: ctx, width, height } = surface;
  const left = 34, top = 14, w = width - 48, h = height - 39;
  const xs = series.flatMap(item => item.points.map(p => p[0]));
  const maxX = Math.max(1, ...xs);
  const maxY = Math.max(1, ...series.filter(item => !item.secondary).flatMap(item => item.points.map(p => p[1])));
  const secondaryY = Math.max(1, ...series.filter(item => item.secondary).flatMap(item => item.points.map(p => p[1])));
  ctx.font = '9px Roboto'; ctx.lineWidth = 1;
  for (let tick = 0; tick < 4; tick++) {
    const y = top + h - h * tick / 3;
    ctx.strokeStyle = '#2c382d'; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + w, y); ctx.stroke();
    ctx.fillStyle = '#829182'; ctx.fillText(format(maxY * tick / 3), 0, y + 3);
  }
  ctx.fillStyle = '#829182'; ctx.fillText('0 с', left, height - 7);
  ctx.fillText(format(maxX) + (axisLabel || ' с'), width - 55, height - 7);
  for (const item of series) {
    ctx.strokeStyle = item.color; ctx.lineWidth = 1.8; ctx.beginPath();
    item.points.forEach(([x, y], i) => {
      const px = left + x / maxX * w, py = top + h - y / (item.secondary ? secondaryY : maxY) * h;
      if (i) {
        if (item.step) {
          const previous = item.points[i - 1];
          ctx.lineTo(px, top + h - previous[1] / (item.secondary ? secondaryY : maxY) * h);
        }
        ctx.lineTo(px, py);
      } else ctx.moveTo(px, py);
    }); ctx.stroke();
  }
  if (series.some(item => item.secondary)) {
    ctx.fillStyle = '#df9b77'; ctx.fillText(format(secondaryY) + ' Wh', width - 75, 10);
  }
}

function drawProgress() {
  const found = [], rescued = [], energy = [];
  for (const frame of state.frames) {
    const detected = $('#basis').value === 'truth' ? frame.targets.filter(target => target.discovered).length : frame.targets.length;
    found.push([frame.time, detected]);
    rescued.push([frame.time, frame.targets.filter(target => target.evacuation_state === 'evacuated' || target.rescued).length]);
    energy.push([frame.time, frame.agents.reduce((total, agent) => total + (agent.physical?.consumed_wh || 0), 0)]);
  }
  lineChart('#progress', [{ points: found, color: '#78ccca', step: true }, { points: rescued, color: '#d1e98a', step: true },
    { points: energy, color: '#df9b77', secondary: true }]);
}

function drawAll() {
  drawMap(); drawProgress(); drawPareto();
}

function stopPlayback() {
  clearInterval(state.timer); state.timer = null; $('#play').textContent = '▶';
}

async function loadRecords(append = false) {
  if (!state.selected || !state.summary) return;
  const runToken = state.loadToken, logToken = ++state.logToken;
  try {
    const page = await api(endpoint('records', { q: $('#log-query').value, stream: $('#log-stream').value,
      kind: $('#log-kind').value, cursor: append ? state.cursor || 0 : 0 }));
    if (runToken !== state.loadToken || logToken !== state.logToken) return;
    if (!append) { state.records = []; $('#records').replaceChildren(); }
    state.cursor = page.next_cursor;
    for (const row of page.records) {
      state.records.push(row);
      const button = element('button', undefined, 'record-item');
      const payload = row.record.payload;
      button.append(element('span', format(row.time) + ' с', 'record-time'));
      const label = element('span', row.kind);
      label.append(element('small', row.stream + ' · ' + (payload.agent_id || payload.target_id || payload.decision_id ||
        payload.scenario_id || payload.reason || payload.type || row.record.trace_id || 'Запись #' + row.id)));
      button.append(label);
      button.onclick = () => showRecord(row, button);
      $('#records').append(button);
    }
    $('#record-count').textContent = format(state.records.length) + ' записей в просмотре';
    $('#more-records').hidden = state.cursor === null;
    if (!page.records.length && !append) $('#records').append(element('p', 'Совпадений не найдено.', 'muted'));
  } catch (error) { if (runToken === state.loadToken && logToken === state.logToken) notice(error.message, true); }
}

function showRecord(row, button) {
  $$('.record-item').forEach(item => item.classList.toggle('active', item === button));
  $('#record-detail').textContent = JSON.stringify(row.record, null, 2);
  const payload = row.record.payload, links = $('#causal-links');
  links.replaceChildren();
  const references = new Set([row.record.decision_id, row.record.request_id, payload.decision_id,
    payload.command_id, payload.agent_id, payload.target_id, payload.message_id,
    payload.decision?.decision_id, payload.result?.request?.request_id].filter(value => typeof value === 'string'));
  for (const reference of references) {
    const link = element('button', 'Найти ' + reference, 'secondary');
    link.onclick = () => { $('#log-query').value = reference; $('#log-kind').value = ''; loadRecords(); };
    links.append(link);
  }
  if (state.frames.length) {
    const index = state.frames.findIndex(frame => frame.time >= row.time);
    state.index = index < 0 ? state.frames.length - 1 : index; $('#time').value = state.index; updateFrame();
  }
}

async function loadAI() {
  if (!state.summary) return;
  const token = state.loadToken;
  try {
    const [result, usage] = await Promise.all([api(endpoint('fronts')), api(endpoint('usage'))]);
    if (token !== state.loadToken) return;
    state.aiLoaded = true;
    state.fronts = result.fronts;
    $('#front-select').replaceChildren();
    state.fronts.forEach((front, index) => {
      const option = element('option', front.planner + ' · ' + format(front.based_on_time) + ' с');
      option.value = index; $('#front-select').append(option);
    });
    const m = state.summary.metrics, node = $('#ai-metrics');
    node.replaceChildren();
    detail(node, 'Режим', state.summary.ai_mode || 'OFF');
    detail(node, 'Global запросы / ответы', format(m.ai_requests.global || 0) + ' / ' + format(m.ai_responses.global || 0));
    detail(node, 'Local запросы / ответы', format(m.ai_requests.local || 0) + ' / ' + format(m.ai_responses.local || 0));
    const milliseconds = value => format(value === null ? null : value * 1000) + ' мс';
    detail(node, 'p50 решения', milliseconds(m.decision_wall_s.p50));
    detail(node, 'p95 решения', milliseconds(m.decision_wall_s.p95));
    detail(node, 'p95 оптимизатора', milliseconds(m.optimizer_wall_s.p95));
    detail(node, 'Завершённые расчёты NSGA-II', m.optimizer_wall_s.n);
    detail(node, 'Сценарные исходы', m.scenario_outcomes.map(item => item.scenario_id + ' → ' + item.outcome).join(' / ') || '—');
    renderUsage(usage);
    drawPareto();
  } catch (error) { if (token === state.loadToken) notice(error.message, true); }
}

function dataTable(labels, rows) {
  const table = element('table'), head = element('thead'), title = element('tr'), body = element('tbody');
  for (const label of labels) title.append(element('th', label));
  head.append(title);
  for (const row of rows) {
    const tr = element('tr');
    for (const value of row) tr.append(element('td', format(value)));
    body.append(tr);
  }
  table.append(head, body);
  return table;
}

function renderUsage(usage) {
  const container = $('#usage'); container.replaceChildren();
  container.append(element('h3', 'Учёт API из архива'));
  if (!usage.available) { container.append(element('p', 'Для этого запуска учёт API отсутствует.', 'muted')); return; }
  container.append(element('p', 'Снимок на ' + (usage.manifest.created_utc || 'момент завершения запуска') +
    '. Общий счётчик включает предыдущие миссии.', 'muted'));
  const rows = [
    ['Сетевые обращения', usage.run.network_attempts, usage.cumulative.network_attempts],
    ['Успешные ответы API', usage.run.statuses.api_success || 0, usage.cumulative.statuses.api_success || 0],
    ['Отклонено контроллером', usage.run.semantic_rejections, usage.cumulative.semantic_rejections],
    ['Физически подтверждено', usage.run.physical_applications_confirmed, usage.cumulative.physical_applications_confirmed],
    ['Блокировки бюджетом', usage.run.budget_blocked, usage.cumulative.budget_blocked]
  ];
  const tokenValue = record => record.complete_total === null ?
    format(record.known_sum) + ' известно · ' + format(record.unknown_records) + ' без данных' : format(record.complete_total);
  for (const [key, label] of [['input_tokens', 'Входные токены'], ['output_tokens', 'Выходные токены'], ['total_tokens', 'Все токены']]) {
    rows.push([label, tokenValue(usage.run.tokens[key]), tokenValue(usage.cumulative.tokens[key])]);
  }
  const wrap = element('div', undefined, 'table-wrap');
  wrap.append(dataTable(['Показатель', 'Этот запуск', 'Всего на дату архива'], rows)); container.append(wrap);
  const budget = usage.cumulative.budget;
  if (budget) container.append(element('p', 'LIVE-бюджет: ' + budget.used + ' / ' + budget.limit +
    ' · остаток ' + (budget.limit - budget.used) + '.', 'usage-budget'));
  for (const [currency, money] of Object.entries(usage.cumulative.money || {})) {
    const cost = money.estimated_complete_total ?? (money.known_subtotal_minimum + ' … ' + money.known_subtotal_maximum);
    container.append(element('p', 'Оценка известной части: ' + cost + ' ' + currency + '. ' +
      money.unbounded_records + ' обращений без полной оценки. ' +
      (money.actual_debit === null ? 'Фактическое списание не подтверждено.' : 'Списание: ' + money.actual_debit + ' ' + currency), 'muted'));
  }
  const attempts = element('details', undefined, 'usage-details');
  attempts.append(element('summary', 'Сетевые попытки · ' + usage.attempts.length));
  const attemptTable = element('div', undefined, 'table-wrap');
  attemptTable.append(dataTable(['UTC', 'Роль', 'Агент', 'Статус', 'Задержка, с', 'Токены'], usage.attempts.map(row => [
    row.reserved_utc, row.role, row.agent_id || '—', row.status, row.latency_s, row.normalized_usage?.total_tokens
  ]))); attempts.append(attemptTable); container.append(attempts);
  const raw = element('details', undefined, 'usage-details');
  raw.append(element('summary', 'Исходный учёт JSON'));
  raw.addEventListener('toggle', () => {
    if (raw.open && raw.childElementCount === 1) raw.append(element('pre', JSON.stringify(usage, null, 2)));
  }); container.append(raw);
}

function drawPareto() {
  const surface = canvasContext('#pareto');
  if (!surface) return;
  const { context: ctx, width, height } = surface;
  const front = state.fronts[Number($('#front-select').value)];
  if (!front) { ctx.fillStyle = '#9ba99e'; ctx.font = '12px Roboto'; ctx.fillText('В этом архиве фронт отсутствует', 25, 40); return; }
  const objectiveRows = new Map();
  for (const row of front.points) {
    const key = JSON.stringify(row.objectives);
    if (!objectiveRows.has(key)) objectiveRows.set(key, { objectives: row.objectives, count: 0 });
    objectiveRows.get(key).count++;
  }
  const points = [...objectiveRows.values()].map(row => row.objectives);
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  ctx.strokeStyle = '#46543e'; ctx.strokeRect(35, 20, width - 55, height - 60);
  for (const p of points) {
    const x = 35 + (maxX === minX ? .5 : (p[0] - minX) / (maxX - minX)) * (width - 55);
    const y = height - 40 - (maxY === minY ? .5 : (p[1] - minY) / (maxY - minY)) * (height - 60);
    ctx.fillStyle = p.every((v, i) => v === front.selected?.[i]) ? '#df9b77' : '#d1e98a';
    ctx.beginPath(); ctx.arc(x, y, 3.8, 0, Math.PI * 2); ctx.fill();
  }
  ctx.fillStyle = '#9ba99e'; ctx.font = '10px Roboto';
  const objectiveLabels = front.planner === 'scout' ? ['−Полезность покрытия', 'Время окончания, с', 'Энергия, Wh'] :
    ['Неспасённый приоритет', 'Взвешенное время, с', 'Энергия, Wh'];
  ctx.fillText(objectiveLabels[0] + ' ↓', Math.max(35, width - 180), height - 13);
  ctx.fillText(objectiveLabels[1] + ' ↓', 35, 12);
  ctx.fillText(format(minX), 35, height - 27); ctx.fillText(format(maxX), width - 65, height - 27);
  ctx.fillText(format(maxY), 38, 33); ctx.fillText(format(minY), 38, height - 45);
  $('#front-detail').textContent = format(points.length) + ' уникальных оценок · ' + format(front.points.length) +
    ' кандидатов · вычислений ' + format(front.stats?.evaluations) +
    ' · seed ' + format(front.stats?.seed) + ' · HV / IGD+ требуют общей контрольной постановки.';
  $('#front-table').replaceChildren(dataTable([...objectiveLabels, 'Кандидатов', 'Выбор'], [...objectiveRows.values()].map(row => [
    ...row.objectives, row.count,
    row.objectives.every((v, i) => v === front.selected?.[i]) ? 'Оценки выбранного плана' : '—'
  ])));
}

async function compareRuns() {
  const token = ++state.comparing;
  try {
    if (state.compared.size < 2) { notice('Выберите минимум два запуска в списке слева.'); return; }
    let result;
    for (;;) {
      result = await api('/api/compare?' + new URLSearchParams({ runs: [...state.compared].join(',') }));
      if (token !== state.comparing) return;
      if (result.state === 'ready') break;
      notice('Подготавливаю индексы выбранных запусков…');
      await new Promise(resolve => setTimeout(resolve, 800));
    }
    const table = element('table'), head = element('thead'), labels = element('tr');
    for (const text of ['Запуск', 'Эвакуировано', 'Время, с', 'Расход, Wh', 'M1', 'p95 решения, мс']) labels.append(element('th', text));
    head.append(labels); table.append(head);
    const body = element('tbody');
    const palette = ['#d1e98a', '#78ccca', '#df9b77', '#af9ddd', '#9ebfe1'];
    for (const [index, run] of result.runs.entries()) {
      const m = run.metrics, tr = element('tr');
      for (const value of [run.name, format(m.rescued) + '/' + m.registered_targets, m.cutoff_s, m.energy_wh,
        m.M1.value, m.decision_wall_s.p95 === null ? null : m.decision_wall_s.p95 * 1000]) tr.append(element('td', format(value)));
      tr.firstElementChild.style.color = palette[index % palette.length];
      body.append(tr);
    }
    table.append(body);
    const wrap = element('div', undefined, 'table-wrap'); wrap.append(table);
    $('#comparison').replaceChildren(wrap);
    for (const pair of result.pairwise) {
      $('#comparison').append(element('p', pair.same_layout ?
        'Одинаковый мир. Разность эвакуаций ' + format(pair.differences.rescued) + ', расхода ' + format(pair.differences.energy_wh) + ' Wh.' :
        'Исходные миры различаются. Парная разность для этих запусков не рассчитывается.', 'muted'));
    }
    const timelines = await Promise.all(result.runs.map(run => api('/api/runs/' + encodeURIComponent(run.run_id) + '/timeline')));
    if (token !== state.comparing) return;
    lineChart('#comparison-chart', result.runs.map((run, index) => ({
      color: palette[index % palette.length], step: true,
      points: timelines[index].frames.map(frame => [frame.time,
        frame.targets.filter(target => target.evacuation_state === 'evacuated').length])
    })));
    notice('');
  } catch (error) { notice(error.message, true); }
}

$$('[data-tab]').forEach(button => { button.onclick = () => tab(button.dataset.tab); });
$('#refresh').onclick = refresh;
$('#run-search').oninput = renderRuns;
$('#time').oninput = event => { stopPlayback(); state.index = Number(event.target.value); updateFrame(); };
$('#agent').onchange = updateFrame;
$('#basis').onchange = async () => {
  if (!state.summary) return;
  const token = state.loadToken, basis = $('#basis').value;
  try {
    stopPlayback();
    const timeline = await api(endpoint('timeline', { basis }));
    if (token === state.loadToken && basis === $('#basis').value) setTimeline(timeline);
  } catch (error) { if (token === state.loadToken) notice(error.message, true); }
};
$$('.layer-controls input').forEach(input => { input.onchange = drawMap; });
$('#heat-layer').onchange = refreshHeatmap;
$('#substeps').ontoggle = loadSubsteps;
$('#substep-window').onchange = selectSubstepWindow;
$('#substep-time').oninput = showSubstep;
$('#play').onclick = () => {
  if (state.timer) { stopPlayback(); return; }
  if (!state.frames.length) return;
  if (state.index >= state.frames.length - 1) state.index = 0;
  $('#play').textContent = 'Ⅱ';
  state.timer = setInterval(() => {
    if (++state.index >= state.frames.length) { state.index = state.frames.length - 1; stopPlayback(); }
    $('#time').value = state.index; updateFrame();
  }, 130);
};
$('#log-filter').onsubmit = event => { event.preventDefault(); loadRecords(); };
$('#more-records').onclick = () => loadRecords(true);
$('#copy-record').onclick = async () => {
  try { await navigator.clipboard.writeText($('#record-detail').textContent); notice('JSON записи скопирован.'); }
  catch { notice('Копирование недоступно. JSON можно выделить в панели записи.'); }
};
$('#agent-log').onclick = () => { $('#log-query').value = $('#agent').value; tab('journal'); loadRecords(); };
$('#compare-load').onclick = compareRuns;
$('#front-select').onchange = drawPareto;
new ResizeObserver(() => requestAnimationFrame(drawAll)).observe(document.querySelector('main'));
refresh();
