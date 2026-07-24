const D = window.__MT_EXCLUSIVITY_DATA__;
if (!D || !Array.isArray(D.brands)) {
  throw new Error('Dashboard data missing — hard refresh (Cmd+Shift+R) or reopen from boltable');
}
const STATUS_OPTIONS = D.status_options || [
  'Not started', 'Researching', 'In discussion', 'Negotiating', 'Signed', 'Not viable'
];
const GH_STATE_TOKEN = __GH_TOKEN__;
const TEAM_STATE_REPO = 'boltable/mt-exclusivity-targeting';
const TEAM_STATE_PATH = 'public/exclusivity-state.json';
const TEAM_STATE_BRANCH = 'main';
const TEAM_STATE_READ_URLS = [
  `https://raw.githubusercontent.com/${TEAM_STATE_REPO}/${TEAM_STATE_BRANCH}/${TEAM_STATE_PATH}`,
  '/exclusivity-state.json',
];
const TEAM_SYNC_POLL_MS = 4000;

let teamStateVersion = D.team_state_version || 0;
let teamStateUpdatedAt = D.team_state_updated_at || '';
let teamStateBlobSha = null;
let teamStateSaving = false;
let teamSyncDirty = false;
let teamSyncTimer = null;
let brandState = {};
let sortKey = 'portfolio_share_pct';
let sortDir = -1;

const TABLE_COLS = [
  { key: 'brand_name', label: 'Brand', filter: 'none' },
  { key: 'portfolio_share_pct', label: 'Share of portfolio', num: true, filter: 'min', options: [[1, '≥1%'], [2, '≥2%'], [5, '≥5%'], [10, '≥10%']] },
  { key: 'bolt_mt_share_pct', label: 'Bolt MT %', num: true, filter: 'min', options: [[0.5, '≥0.5%'], [1, '≥1%'], [2, '≥2%'], [5, '≥5%']] },
  { key: 'getplace_bolt_ms_pct', label: 'GetPlace Bolt MS %', num: true, filter: 'min', options: [[30, '≥30%'], [40, '≥40%'], [50, '≥50%'], [60, '≥60%']] },
  { key: 'getplace_wolt_ms_pct', label: 'GetPlace Wolt MS %', num: true, filter: 'min', options: [[30, '≥30%'], [40, '≥40%'], [50, '≥50%']] },
  { key: 'getplace_ms_trend', label: 'MS trend', filter: 'enum', field: 'getplace_ms_trend', values: ['Gaining', 'Losing', 'Stable'] },
  { key: 'est_delivery_market_share_pct', label: 'Est. delivery %', num: true, filter: 'min', options: [[0.5, '≥0.5%'], [1, '≥1%'], [2, '≥2%'], [5, '≥5%']] },
  { key: 'gmv_total', label: 'GMV', num: true, filter: 'min', options: [[50000, '≥€50k'], [100000, '≥€100k'], [250000, '≥€250k'], [500000, '≥€500k']] },
  { key: 'gmv_mom_pct', label: 'MoM %', num: true, filter: 'mom', options: [['up', 'Growing'], ['down', 'Declining'], ['10', '≥+10%'], ['-10', '≤−10%']] },
  { key: 'local_order_share_pct', label: 'Local (+356) %', num: true, filter: 'local', options: [['70', '≥70%'], ['50', '≥50%'], ['30lt', '<30%']] },
  { key: 'non_local_order_share_pct', label: 'Non-local %', num: true, filter: 'min', options: [[10, '≥10%'], [20, '≥20%'], [30, '≥30%']] },
  { key: 'bolt_plus_order_share_pct', label: 'Bolt+ orders %', num: true, filter: 'min', options: [[10, '≥10%'], [20, '≥20%'], [30, '≥30%']] },
  { key: 'orders_total', label: 'Orders', num: true, filter: 'min', options: [[500, '≥500'], [1000, '≥1k'], [5000, '≥5k'], [10000, '≥10k']] },
  { key: 'providers', label: 'Outlets', num: true, filter: 'outlets', options: [['1', '1 outlet'], ['2-5', '2–5'], ['6', '6+']] },
  { key: 'segment', label: 'Segment', filter: 'enum', field: 'segment' },
  { key: 'am', label: 'AM', filter: 'enum', field: 'am' },
  { key: 'sf_owner', label: 'SF owner', filter: 'enum', field: 'sf_owner', allowEmpty: true },
  { key: 'sp', label: 'SP', filter: 'enum', field: 'sp', values: ['Active', 'Inactive'] },
  { key: 'sl', label: 'SL', filter: 'enum', field: 'sl', values: ['Active', 'Inactive'] },
  { key: 'bolt_plus', label: 'Bolt+ enrolled', filter: 'bool' },
  { key: 'exclusive_status', label: 'Exclusive', filter: 'exclusive', options: [['yes', 'Yes'], ['partial', 'Partial'], ['no', 'Not exclusive']] },
  { key: 'commission', label: 'Comm %', num: true, filter: 'min', options: [[0.15, '≥15%'], [0.20, '≥20%'], [0.25, '≥25%'], [0.30, '≥30%']] },
  { key: 'status', label: 'Status', filter: 'pipeline' },
  { key: 'comment', label: 'Comment', filter: 'comment', options: [['has', 'Has comment'], ['empty', 'Empty']] },
];

function trendCell(trend, change) {
  if (!trend) return '—';
  const cls = String(trend).toLowerCase().includes('gain') ? 'trend-up'
    : String(trend).toLowerCase().includes('los') ? 'trend-down' : 'trend-flat';
  const ch = change == null || Number.isNaN(Number(change)) ? '' : ` (${Number(change) > 0 ? '+' : ''}${Number(change).toFixed(1)}pp)`;
  return `<span class="pill ${cls}">${esc(trend)}${esc(ch)}</span>`;
}
function filterSelect(key) {
  return document.querySelector(`select.col-filter[data-filter="${key}"]`);
}
function filterValue(key) {
  const el = filterSelect(key);
  return el ? el.value : '';
}
function uniqueFieldValues(field) {
  return [...new Set(D.brands.map(b => String(b[field] ?? '').trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}
function buildFilterSelect(col) {
  if (col.filter === 'none') {
    return '<select class="col-filter" data-filter="brand_name" disabled title="Use search box"><option>—</option></select>';
  }
  let opts = '<option value="">All</option>';
  if (col.filter === 'enum') {
    const values = col.values || uniqueFieldValues(col.field || col.key);
    values.forEach(v => { opts += `<option value="${esc(v)}">${esc(v)}</option>`; });
    if (col.allowEmpty) opts += '<option value="__empty__">— (empty)</option>';
  } else if (col.filter === 'bool') {
    opts += '<option value="yes">Yes</option><option value="no">No</option>';
  } else if (col.filter === 'pipeline') {
    STATUS_OPTIONS.forEach(s => { opts += `<option value="${esc(s)}">${esc(s)}</option>`; });
  } else if (col.options) {
    col.options.forEach(([val, label]) => { opts += `<option value="${esc(String(val))}">${esc(label)}</option>`; });
  }
  return `<select class="col-filter" data-filter="${esc(col.key)}">${opts}</select>`;
}
function buildTableHead() {
  const head = document.getElementById('brandHead');
  head.innerHTML = `<tr>${TABLE_COLS.map(col => {
    const cls = col.num ? ' class="num"' : '';
    return `<th${cls} data-k="${esc(col.key)}"><div class="th-label">${esc(col.label)}</div>${buildFilterSelect(col)}</th>`;
  }).join('')}</tr>`;
  head.querySelectorAll('.th-label').forEach(el => {
    el.addEventListener('click', () => {
      const k = el.closest('th').dataset.k;
      if (sortKey === k) sortDir *= -1;
      else { sortKey = k; sortDir = (k === 'brand_name' || k === 'am' || k === 'sf_owner') ? 1 : -1; }
      renderTable();
    });
  });
  head.querySelectorAll('.col-filter:not([disabled])').forEach(el => {
    el.addEventListener('click', e => e.stopPropagation());
    el.addEventListener('change', () => renderTable());
  });
}
function passesMinFilter(val, minRaw) {
  if (!minRaw) return true;
  const n = Number(val);
  if (Number.isNaN(n)) return false;
  return n >= Number(minRaw);
}
function passesColumnFilters(b) {
  for (const col of TABLE_COLS) {
    const v = filterValue(col.key);
    if (!v) continue;
    if (col.filter === 'min') {
      if (!passesMinFilter(b[col.key], v)) return false;
    } else if (col.filter === 'mom') {
      const m = b.gmv_mom_pct;
      if (m == null || Number.isNaN(Number(m))) return false;
      if (v === 'up' && !(Number(m) > 0)) return false;
      if (v === 'down' && !(Number(m) < 0)) return false;
      if (v === '10' && !(Number(m) >= 10)) return false;
      if (v === '-10' && !(Number(m) <= -10)) return false;
    } else if (col.filter === 'local') {
      const lp = Number(b.local_order_share_pct);
      if (v === '30lt') { if (!(lp < 30)) return false; }
      else if (Number.isNaN(lp) || lp < Number(v)) return false;
    } else if (col.filter === 'outlets') {
      const p = Number(b.providers) || 0;
      if (v === '1' && p !== 1) return false;
      if (v === '2-5' && (p < 2 || p > 5)) return false;
      if (v === '6' && p < 6) return false;
    } else if (col.filter === 'enum') {
      const field = col.field || col.key;
      const cell = String(b[field] ?? '').trim();
      if (v === '__empty__') { if (cell) return false; }
      else if (cell !== v) return false;
    } else if (col.filter === 'bool') {
      if (v === 'yes' && !b[col.key]) return false;
      if (v === 'no' && b[col.key]) return false;
    } else if (col.filter === 'exclusive') {
      if (v === 'yes' && !b.is_exclusive) return false;
      if (v === 'partial' && !String(b.exclusive_status || '').startsWith('Partial')) return false;
      if (v === 'no' && String(b.exclusive_status || '—') !== '—') return false;
    } else if (col.filter === 'pipeline') {
      const st = brandState[b.id]?.status || 'Not started';
      if (st !== v) return false;
    } else if (col.filter === 'comment') {
      const c = (brandState[b.id]?.comment || '').trim();
      if (v === 'has' && !c) return false;
      if (v === 'empty' && c) return false;
    }
  }
  return true;
}
function clearAllFilters() {
  document.querySelectorAll('.col-filter:not([disabled])').forEach(el => { el.value = ''; });
  document.getElementById('q').value = '';
  renderTable();
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function euro(n) {
  const v = Number(n) || 0;
  return '€' + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}
function pct(n) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  return Number(n).toFixed(1) + '%';
}
function commPct(n) {
  const v = Number(n) || 0;
  return (v * 100).toFixed(1) + '%';
}
function segClass(s) {
  const x = String(s || '').toUpperCase();
  if (x.startsWith('ENT')) return 'ent';
  if (x === 'MM') return 'mm';
  if (x === 'SMB') return 'smb';
  return '';
}
function toBase64Utf8(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  bytes.forEach(b => bin += String.fromCharCode(b));
  return btoa(bin);
}

function initBrandStateFromEmbedded() {
  const embedded = D.team_state || {};
  for (const [id, dec] of Object.entries(embedded)) {
    brandState[id] = {
      status: dec.status || 'Not started',
      comment: dec.comment || '',
      by: dec.by || '',
      at: dec.at || '',
    };
  }
}

function collectDecisionsFromUI() {
  const out = {};
  for (const b of D.brands) {
    const sel = document.querySelector(`select[data-status="${b.id}"]`);
    const ta = document.querySelector(`textarea[data-comment="${b.id}"]`);
    const status = sel ? sel.value : (brandState[b.id]?.status || 'Not started');
    const comment = ta ? ta.value : (brandState[b.id]?.comment || '');
    const prev = brandState[b.id] || {};
    if (status !== 'Not started' || comment || prev.by) {
      out[b.id] = {
        status,
        comment,
        by: prev.by || 'local',
        at: prev.at || new Date().toISOString(),
      };
    }
  }
  return out;
}

function buildTeamStatePayload() {
  const decisions = collectDecisionsFromUI();
  for (const id of Object.keys(decisions)) {
    const row = decisions[id];
    const prev = brandState[id] || {};
    if ((row.status !== (prev.status || 'Not started')) || (row.comment !== (prev.comment || ''))) {
      row.by = 'dashboard-user';
      row.at = new Date().toISOString();
    }
  }
  return {
    version: teamStateVersion + 1,
    updatedAt: new Date().toISOString(),
    decisions,
  };
}

function applyTeamState(state) {
  if (!state) return;
  const dec = state.decisions || {};
  teamStateVersion = Math.max(teamStateVersion, state.version || 0);
  teamStateUpdatedAt = state.updatedAt || teamStateUpdatedAt;
  for (const b of D.brands) {
    const row = dec[b.id];
    if (row) {
      brandState[b.id] = {
        status: row.status || 'Not started',
        comment: row.comment || '',
        by: row.by || '',
        at: row.at || '',
      };
    } else if (!brandState[b.id]) {
      brandState[b.id] = { status: 'Not started', comment: '', by: '', at: '' };
    }
  }
  renderTable();
  updateSummary();
}

function updateTeamSyncBanner(msg, kind) {
  const el = document.getElementById('syncBar');
  if (!el) return;
  el.textContent = msg;
  el.className = 'sync-bar' + (kind ? ' ' + kind : '');
}

function updateSaveTeamButton(state) {
  const btn = document.getElementById('btnSaveTeam');
  const hint = document.getElementById('saveTeamHint');
  if (!btn) return;
  btn.classList.remove('save-dirty', 'save-ok', 'save-error');
  if (!GH_STATE_TOKEN) {
    btn.disabled = true;
    btn.textContent = 'Save for team (offline)';
    if (hint) hint.textContent = 'Rebuild with MT_PORTFOLIO_GH_TOKEN for team sync';
    return;
  }
  btn.disabled = state === 'saving';
  if (state === 'saving') btn.textContent = 'Saving…';
  else if (state === 'ok') { btn.textContent = 'Saved for team ✓'; btn.classList.add('save-ok'); }
  else if (state === 'error') { btn.textContent = 'Save failed — retry'; btn.classList.add('save-error'); }
  else if (state === 'dirty' || teamSyncDirty) { btn.textContent = 'Save for team *'; btn.classList.add('save-dirty'); }
  else btn.textContent = 'Save for team';
  if (hint) {
    if (!GH_STATE_TOKEN) hint.textContent = '';
    else if (state === 'ok') hint.textContent = 'Saved — teammates see updates within seconds';
    else if (teamSyncDirty) hint.textContent = 'Unsaved changes';
    else hint.textContent = 'Status + comments sync for the whole team';
  }
  if (state === 'ok') setTimeout(() => updateSaveTeamButton(teamSyncDirty ? 'dirty' : 'idle'), 3000);
}

async function readTeamStateFromNetwork() {
  const timeoutMs = 8000;
  for (const base of TEAM_STATE_READ_URLS) {
    try {
      const url = base + (base.includes('?') ? '&' : '?') + 't=' + Date.now();
      const res = await Promise.race([
        fetch(url, { cache: 'no-store' }),
        new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), timeoutMs)),
      ]);
      if (!res.ok) continue;
      return await res.json();
    } catch (e) { console.warn(e); }
  }
  return null;
}

async function fetchTeamStateMeta(syncVersionFromRemote) {
  if (!GH_STATE_TOKEN) return null;
  try {
    const res = await fetch(
      `https://api.github.com/repos/${TEAM_STATE_REPO}/contents/${TEAM_STATE_PATH}?ref=${TEAM_STATE_BRANCH}`,
      { headers: { Authorization: `Bearer ${GH_STATE_TOKEN}`, Accept: 'application/vnd.github+json' } }
    );
    if (!res.ok) return null;
    const meta = await res.json();
    teamStateBlobSha = meta.sha || null;
    if (meta.content) {
      const json = JSON.parse(atob(meta.content.replace(/\n/g, '')));
      if (syncVersionFromRemote && json.version) teamStateVersion = Math.max(teamStateVersion, json.version);
      return json;
    }
  } catch (e) { console.warn(e); }
  return null;
}

async function pushTeamState() {
  if (!GH_STATE_TOKEN || teamStateSaving) return false;
  teamStateSaving = true;
  updateTeamSyncBanner('Saving team notes…', 'pending');
  updateSaveTeamButton('saving');
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      await fetchTeamStateMeta(true);
      const payload = buildTeamStatePayload();
      const remote = await readTeamStateFromNetwork();
      if (remote && remote.decisions) {
        payload.decisions = { ...remote.decisions, ...payload.decisions };
        payload.version = Math.max(teamStateVersion, remote.version || 0) + 1;
      }
      const body = {
        message: `Exclusivity team state v${payload.version}`,
        content: toBase64Utf8(JSON.stringify(payload, null, 2)),
        branch: TEAM_STATE_BRANCH,
      };
      if (teamStateBlobSha) body.sha = teamStateBlobSha;
      const res = await fetch(
        `https://api.github.com/repos/${TEAM_STATE_REPO}/contents/${TEAM_STATE_PATH}`,
        {
          method: 'PUT',
          headers: {
            Authorization: `Bearer ${GH_STATE_TOKEN}`,
            Accept: 'application/vnd.github+json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(body),
        }
      );
      if (res.ok) {
        const data = await res.json();
        teamStateBlobSha = (data.content && data.content.sha) || teamStateBlobSha;
        teamStateVersion = payload.version;
        teamStateUpdatedAt = payload.updatedAt;
        teamSyncDirty = false;
        applyTeamState(payload);
        updateTeamSyncBanner(`Team sync on · saved v${teamStateVersion}`, 'ok');
        updateSaveTeamButton('ok');
        return true;
      }
      if (res.status === 409 && attempt < 2) continue;
      throw new Error('GitHub ' + res.status);
    }
  } catch (e) {
    updateTeamSyncBanner('Save failed — ' + (e.message || e), 'error');
    updateSaveTeamButton('error');
  } finally {
    teamStateSaving = false;
  }
  return false;
}

async function pollTeamState() {
  const remote = await readTeamStateFromNetwork();
  if (remote && (remote.version || 0) > teamStateVersion) applyTeamState(remote);
}

function filteredBrands() {
  const q = (document.getElementById('q').value || '').trim().toLowerCase();
  return D.brands.filter(b => {
    if (q && !String(b.brand_name).toLowerCase().includes(q) && !String(b.brand_key).toLowerCase().includes(q)) return false;
    return passesColumnFilters(b);
  }).sort((a, b) => {
    const av = a[sortKey]; const bv = b[sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'string') return sortDir * av.localeCompare(bv);
    return sortDir * (Number(av) - Number(bv));
  });
}

function rowClass(b) {
  const st = brandState[b.id]?.status || 'Not started';
  if (st === 'Signed') return 'row-signed';
  if (st === 'In discussion' || st === 'Negotiating') return 'row-active';
  if (b.is_exclusive) return 'row-exclusive';
  return '';
}
function exclusiveCell(b) {
  const status = b.exclusive_status || '—';
  if (status === '—') return '—';
  const detail = b.exclusive_detail ? `<div class="meta-row">${esc(b.exclusive_detail)}</div>` : '';
  return `${esc(status)}${detail}`;
}

function renderTable() {
  const rows = filteredBrands();
  const tbody = document.getElementById('brandBody');
  tbody.innerHTML = rows.map(b => {
    const st = brandState[b.id] || { status: 'Not started', comment: '', by: '', at: '' };
    const opts = STATUS_OPTIONS.map(o => `<option value="${esc(o)}"${o === st.status ? ' selected' : ''}>${esc(o)}</option>`).join('');
    const lp = Number(b.local_order_share_pct) || 0;
    const np = Number(b.non_local_order_share_pct) || 0;
    const meta = st.by ? `<div class="meta-row">${esc(st.by)} · ${st.at ? new Date(st.at).toLocaleString() : ''}</div>` : '';
    return `<tr class="${rowClass(b)}">
      <td><strong>${esc(b.brand_name)}</strong></td>
      <td class="num">${pct(b.portfolio_share_pct ?? b.share_pct)}</td>
      <td class="num">${pct(b.bolt_mt_share_pct)}</td>
      <td class="num">${pct(b.getplace_bolt_ms_pct)}</td>
      <td class="num">${pct(b.getplace_wolt_ms_pct)}</td>
      <td>${trendCell(b.getplace_ms_trend, b.getplace_ms_change_pp)}</td>
      <td class="num">${pct(b.est_delivery_market_share_pct)}</td>
      <td class="num">${euro(b.gmv_total)}</td>
      <td class="num">${b.gmv_mom_pct == null ? '—' : pct(b.gmv_mom_pct)}</td>
      <td class="num">${pct(b.local_order_share_pct)}<div class="local-bar"><span class="local" style="width:${lp}%"></span><span class="non" style="width:${np}%"></span></div></td>
      <td class="num">${pct(b.non_local_order_share_pct)}</td>
      <td class="num">${pct(b.bolt_plus_order_share_pct)}</td>
      <td class="num">${(b.orders_total || 0).toLocaleString()}</td>
      <td class="num">${b.providers}</td>
      <td><span class="pill ${segClass(b.segment)}">${esc(b.segment)}</span></td>
      <td>${esc(b.am)}</td>
      <td>${esc(b.sf_owner || '—')}</td>
      <td>${esc(b.sp)}</td>
      <td>${esc(b.sl)}</td>
      <td>${b.bolt_plus ? 'Yes' : '—'}</td>
      <td>${exclusiveCell(b)}</td>
      <td class="num">${commPct(b.commission)}</td>
      <td><select data-status="${b.id}" class="status-sel">${opts}</select></td>
      <td><textarea class="comment" data-comment="${b.id}" rows="2">${esc(st.comment)}</textarea>${meta}</td>
    </tr>`;
  }).join('');
  tbody.querySelectorAll('.status-sel, .comment').forEach(el => {
    el.addEventListener('change', () => { teamSyncDirty = true; updateSaveTeamButton('dirty'); updateSummary(); renderTable(); });
    el.addEventListener('input', () => { teamSyncDirty = true; updateSaveTeamButton('dirty'); });
  });
}

function updateSummary() {
  const cards = document.getElementById('summaryCards');
  const top5 = [...D.brands].sort((a,b) => (b.portfolio_share_pct ?? b.share_pct) - (a.portfolio_share_pct ?? a.share_pct)).slice(0, 5);
  const pipeline = {};
  for (const b of D.brands) {
    const st = brandState[b.id]?.status || 'Not started';
    pipeline[st] = (pipeline[st] || 0) + 1;
  }
  const pipeTxt = Object.entries(pipeline).filter(([k]) => k !== 'Not started').map(([k,v]) => `${k}: ${v}`).join(' · ') || 'No pipeline yet';
  const exclusiveCount = D.brands.filter(b => b.is_exclusive).length;
  const partialExclusive = D.brands.filter(b => String(b.exclusive_status || '').startsWith('Partial')).length;
  cards.innerHTML = `
    <div class="card"><div class="label">Brands</div><div class="value">${D.brand_count}</div></div>
    <div class="card"><div class="label">Book GMV</div><div class="value">${euro(D.total_gmv)}</div></div>
    <div class="card"><div class="label">Already exclusive</div><div class="value">${exclusiveCount}</div><div class="meta">${partialExclusive} partial</div></div>
    <div class="card"><div class="label">Top brand share</div><div class="value">${top5[0] ? pct(top5[0].portfolio_share_pct ?? top5[0].share_pct) : '—'}</div><div class="meta">${esc(top5[0]?.brand_name || '')}</div></div>
    <div class="card"><div class="label">Pipeline</div><div class="value" style="font-size:0.95rem">${esc(pipeTxt)}</div></div>`;
}

function initFilters() {
  buildTableHead();
  document.getElementById('q').addEventListener('input', () => renderTable());
  document.getElementById('btnClearFilters').addEventListener('click', clearAllFilters);
}

async function initTeamState() {
  let state = null;
  if (GH_STATE_TOKEN) state = await fetchTeamStateMeta();
  if (!state) state = await readTeamStateFromNetwork();
  if (state && state.decisions) {
    applyTeamState(state);
    updateTeamSyncBanner(`Team sync on · v${teamStateVersion} · ${Object.keys(state.decisions).length} saved`, 'ok');
  } else if (Object.keys(D.team_state || {}).length) {
    updateTeamSyncBanner(`Embedded team state v${D.team_state_version || 0}`, 'ok');
  } else if (GH_STATE_TOKEN) {
    updateTeamSyncBanner('Team sync on · add status/comments then Save for team', 'ok');
  } else {
    updateTeamSyncBanner('Read-only build — set MT_PORTFOLIO_GH_TOKEN and rebuild for team save', '');
  }
  updateSaveTeamButton('idle');
}

document.getElementById('btnSaveTeam').addEventListener('click', () => pushTeamState());

function bootDashboard() {
  try {
    initBrandStateFromEmbedded();
    initFilters();
    updateSummary();
    renderTable();
    initTeamState().then(() => {
      if (teamSyncTimer) clearInterval(teamSyncTimer);
      teamSyncTimer = setInterval(pollTeamState, TEAM_SYNC_POLL_MS);
    }).catch((e) => {
      console.warn(e);
      updateTeamSyncBanner('Team sync unavailable — table data is still loaded', 'error');
      updateSaveTeamButton('idle');
    });
  } catch (e) {
    console.error(e);
    updateTeamSyncBanner('Dashboard error — hard refresh (Cmd+Shift+R): ' + (e.message || e), 'error');
  }
}

bootDashboard();
