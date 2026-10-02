const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const STORAGE_KEY = '104crawler.form';
const VIEW_KEY = '104crawler.view';

const DEFAULTS = {
  keywords: [], order: '15', area: [], ro: '0', isnew: '', newDays: '', jobexp: [], s9: [], s5: '',
  wktm: false, oneClass: false, edu: '', indcat: [], zone: [], maxPage: 5, fetchDetail: true,
};

function store(key, value) { try { localStorage.setItem(key, value); } catch {} }
function load(key) { try { return localStorage.getItem(key); } catch { return null; } }

async function api(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `請求失敗 (${res.status})`);
  return data;
}

// ---------- 樹狀多選 (地區 / 產業) ----------
class TreePicker {
  constructor(el, tree, { openCodes = [], placeholder = '未選擇＝不限' } = {}) {
    this.el = el;
    this.selected = new Set();
    this.names = {};
    this.placeholder = placeholder;
    this.onChange = () => {};
    el.innerHTML = `
      <div class="picker-top">
        <input type="text" class="text" placeholder="搜尋…">
        <button type="button" class="btn small ghost">清除</button>
      </div>
      <div class="picker-selected"></div>
      <div class="picker-body">${tree.map(g => this.groupHtml(g, openCodes.includes(g.no))).join('')}</div>`;
    this.body = $('.picker-body', el);
    this.tags = $('.picker-selected', el);

    this.body.addEventListener('change', e => {
      if (e.target.type !== 'checkbox') return;
      e.stopPropagation();
      this.toggle(e.target.dataset.code, e.target.checked);
    });
    this.body.addEventListener('click', e => {
      const btn = e.target.closest('.expand');
      if (!btn) return;
      const sub = btn.closest('.item').nextElementSibling;
      sub.hidden = !sub.hidden;
      btn.textContent = (sub.hidden ? '▸ ' : '▾ ') + btn.dataset.count;
    });
    this.tags.addEventListener('click', e => {
      const code = e.target.closest('button')?.dataset.code;
      if (code) this.toggle(code, false);
    });
    $('.picker-top button', el).addEventListener('click', () => this.setValues([]));
    $('.picker-top input', el).addEventListener('input', e => { e.stopPropagation(); this.search(e.target.value.trim()); });
    this.renderTags();
  }

  groupHtml(g, open) {
    this.names[g.no] = g.des;
    const children = g.n || [];
    return `<details ${open ? 'open' : ''} data-group="${g.no}">
      <summary>${esc(g.des)}</summary>
      <div class="group-items">
        <div class="item"><label><input type="checkbox" data-code="${g.no}">全部${esc(g.des)}</label></div>
        ${children.map(c => this.itemHtml(c, g.no)).join('')}
      </div></details>`;
  }

  itemHtml(c, parent) {
    this.names[c.no] = c.des;
    const subs = c.n || [];
    const expand = subs.length ? `<button type="button" class="expand" data-count="${subs.length}">▸ ${subs.length}</button>` : '';
    return `<div class="item" data-parent="${parent}"><label><input type="checkbox" data-code="${c.no}">${esc(c.des)}</label>${expand}</div>
      ${subs.length ? `<div class="subitems" hidden>${subs.map(s => {
        this.names[s.no] = s.des;
        return `<div class="item" data-parent="${c.no}"><label><input type="checkbox" data-code="${s.no}">${esc(s.des)}</label></div>`;
      }).join('')}</div>` : ''}`;
  }

  // 104代碼為10碼階層式: 前4碼群組 後面每3碼一層 (例: 6001001000 台北市 → 6001001005 大安區)
  isAncestor(a, b) {
    if (a === b) return false;
    const prefix = a.replace(/(000)+$/, '');
    return b.startsWith(prefix);
  }

  toggle(code, on) {
    if (on) {
      // 選了上層 就移除已選的下層
      for (const c of [...this.selected]) if (this.isAncestor(code, c)) this.selected.delete(c);
      this.selected.add(code);
    } else {
      this.selected.delete(code);
    }
    this.sync();
  }

  sync() {
    for (const input of $$('input[type=checkbox]', this.body)) {
      const code = input.dataset.code;
      const coveredByParent = [...this.selected].some(s => this.isAncestor(s, code));
      input.checked = this.selected.has(code) || coveredByParent;
      input.disabled = coveredByParent;
      input.closest('.item').classList.toggle('disabled', coveredByParent);
    }
    this.renderTags();
    this.onChange();
  }

  renderTags() {
    this.tags.innerHTML = this.selected.size
      ? [...this.selected].map(c => `<span class="tag">${esc(this.names[c] || c)}<button type="button" data-code="${c}" aria-label="移除">×</button></span>`).join('')
      : `<span class="placeholder">${esc(this.placeholder)}</span>`;
  }

  search(q) {
    for (const d of $$('details', this.body)) {
      let groupHit = false;
      for (const item of $$('.group-items > .item', d)) {
        const sub = item.nextElementSibling?.classList.contains('subitems') ? item.nextElementSibling : null;
        const selfHit = !q || item.textContent.includes(q);
        let subHit = false;
        if (sub) {
          for (const s of $$('.item', sub)) {
            const hit = !q || s.textContent.includes(q) || selfHit;
            s.classList.toggle('hidden-by-search', !hit);
            subHit ||= q && s.textContent.includes(q);
          }
          sub.hidden = !subHit;
        }
        const show = selfHit || subHit;
        item.classList.toggle('hidden-by-search', !show);
        groupHit ||= show;
      }
      d.classList.toggle('hidden-by-search', !groupHit && !!q);
      if (q) d.open = groupHit;
    }
  }

  values() { return [...this.selected]; }
  setValues(codes) { this.selected = new Set(codes || []); this.sync(); }
}

// ---------- 關鍵字標籤輸入 ----------
class TagInput {
  constructor(el) {
    this.el = el;
    this.input = $('input', el);
    this.values = [];
    this.onChange = () => {};
    this.input.addEventListener('keydown', e => {
      if (e.isComposing) return; // 中文輸入法選字中
      if (e.key === 'Enter' || e.key === ',' || e.key === '，') {
        e.preventDefault();
        this.commit();
      } else if (e.key === 'Backspace' && !this.input.value && this.values.length) {
        this.remove(this.values.length - 1);
      }
    });
    this.input.addEventListener('input', e => {
      e.stopPropagation();
      if (/[,，]/.test(this.input.value)) this.commit();
      else this.onChange();
    });
    this.input.addEventListener('blur', () => this.commit());
    el.addEventListener('click', e => {
      const btn = e.target.closest('button[data-index]');
      if (btn) this.remove(Number(btn.dataset.index));
      else this.input.focus();
    });
  }

  commit() {
    const parts = this.input.value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
    this.input.value = '';
    const next = [...this.values];
    for (const p of parts) if (!next.includes(p)) next.push(p);
    if (next.length !== this.values.length) this.setValues(next);
  }

  remove(index) {
    this.setValues(this.values.filter((_, i) => i !== index));
  }

  // 尚未按Enter的文字也算進去
  current() {
    const pending = this.input.value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
    return [...new Set([...this.values, ...pending])];
  }

  setValues(values) {
    this.values = values || [];
    $$('.tag', this.el).forEach(t => t.remove());
    this.input.insertAdjacentHTML('beforebegin', this.values.map((v, i) =>
      `<span class="tag">${esc(v)}<button type="button" data-index="${i}" aria-label="移除">×</button></span>`).join(''));
    this.input.placeholder = this.values.length ? '再加一個…' : '輸入後按 Enter 或逗號，例如：數據分析';
    this.onChange();
  }
}

// ---------- 進度面板 ----------
const STATUS_TEXT = { pending: '準備中…', running: '搜尋中…', done: '完成', stopped: '已停止', error: '發生錯誤' };

class StatusPanel {
  constructor(el, { showNew = false } = {}) {
    this.el = el;
    this.onStop = () => {};
    el.innerHTML = `
      <div class="status-head">
        <strong class="st-text">尚未開始</strong>
        <div class="status-btns">
          <button type="button" class="btn danger st-stop" disabled>停止</button>
          <a class="btn primary disabled st-csv" href="#" download>下載 CSV</a>
        </div>
      </div>
      <div class="st-message"></div>
      <div class="progress"><div class="bar"></div></div>
      <div class="stats">
        <div><span class="st-total">–</span><label>104 符合筆數</label></div>
        <div><span class="st-page">–</span><label class="st-page-label">頁數進度</label></div>
        <div><span class="st-count">0</span><label>已取得</label></div>
        ${showNew ? '<div><span class="st-new">0</span><label>新增</label></div>' : ''}
        <div><span class="st-skipped">0</span><label>條件不符略過</label></div>
      </div>
      <details class="log-wrap"><summary>執行紀錄</summary><pre class="st-log"></pre></details>`;
    $('.st-stop', el).addEventListener('click', () => { $('.st-stop', el).disabled = true; this.onStop(); });
  }

  reset() {
    this.update({ status: 'pending', message: '', page: 0, maxPage: 1, count: 0, skipped: 0, newCount: 0, logs: [], keywords: [''] });
    $('.st-csv', this.el).classList.add('disabled');
    $('.st-stop', this.el).disabled = false;
  }

  update(s) {
    const el = this.el;
    const running = s.status === 'running' || s.status === 'pending';
    const kwCount = (s.keywords || []).length;
    const multi = kwCount > 1;
    const pages = Math.min(s.maxPage, s.lastPage || s.maxPage);
    let text = STATUS_TEXT[s.status];
    if (running && s.batch) text = `全部執行 ${s.batch.index + 1}/${s.batch.total}：${s.batch.name}　${text}`;
    if (running && multi) text += ` 關鍵字 ${s.keywordIndex + 1}/${kwCount}「${s.keyword}」`;
    $('.st-text', el).textContent = text;
    $('.st-message', el).textContent = running ? '' : (s.message || '');
    $('.st-total', el).textContent = s.total == null ? '–' : s.total.toLocaleString();
    $('.st-page', el).textContent = s.page ? `${s.page} / ${pages}` : '–';
    $('.st-page-label', el).textContent = s.lastPage == null ? '頁數進度'
      : `頁數進度（設定 ${s.maxPage} 頁，104 共 ${s.lastPage} 頁${multi ? '，目前關鍵字' : ''}）`;
    $('.st-count', el).textContent = s.count;
    if ($('.st-new', el)) $('.st-new', el).textContent = s.newCount ?? 0;
    $('.st-skipped', el).textContent = s.skipped;
    // 多關鍵字時 進度條依「已完成關鍵字 + 目前關鍵字頁數」計算
    const kwProgress = s.page ? (s.page - 1) / pages : 0;
    let overall = ((s.keywordIndex || 0) + kwProgress) / Math.max(1, kwCount);
    // 全部執行: 已完成的追蹤 + 目前追蹤的進度
    if (s.batch) overall = (s.batch.index + overall) / Math.max(1, s.batch.total);
    $('.bar', el).style.width = running ? `${Math.max(2, overall * 100)}%` : '100%';
    const log = $('.st-log', el);
    log.textContent = (s.logs || []).join('\n');
    log.scrollTop = 1e9;
    $('.st-stop', el).disabled = !running;
  }

  setCsv(href) {
    const a = $('.st-csv', this.el);
    a.href = href || '#';
    a.classList.toggle('disabled', !href);
  }
}

// ---------- 結果表格 ----------
function fmtDate(d) {
  return /^\d{8}$/.test(d) ? `${d.slice(4, 6)}/${d.slice(6)}` : d;
}

function hostOf(url) {
  try { return new URL(url).hostname; } catch { return ''; }
}

function rowHtml(r, { favCols = false } = {}) {
  const ext = r.source === 'external';
  const badge = (r.isNew ? '<span class="badge-new">新</span>' : '') + (ext ? '<span class="badge-ext">外部</span>' : '');
  const kw = (r.matchedKeywords ? `<div class="co">🔍 ${esc(r.matchedKeywords)}</div>` : '')
    + (r.note ? `<div class="co">📝 ${esc(r.note)}</div>` : '');
  const fav = favoriteJobs.has(r.jobNo);
  // 外部職缺: 沒有公司頁連結 公司下方改顯示網站網域
  const company = ext
    ? `${esc(r.jobCompanyName)}<div class="co">${esc(hostOf(r.jobDetailUrl))}</div>`
    : `<a href="${esc(r.jobCompanyUrl)}" target="_blank" rel="noopener">${esc(r.jobCompanyName)}</a><div class="co">${esc(r.jobCompanyIndustry)}</div>`;
  // 外部職缺: 隱藏對它沒有意義 改為編輯
  const lastCell = ext
    ? `<button type="button" class="hide-btn ext-edit-btn" data-job="${esc(r.jobNo)}" title="編輯外部職缺" aria-label="編輯">✎</button>`
    : `<button type="button" class="hide-btn" data-job="${esc(r.jobNo)}" title="隱藏此職缺，之後不再顯示" aria-label="隱藏">✕</button>`;
  return `<tr class="${r.isNew ? 'is-new' : ''}">
    <td class="act"><button type="button" class="fav-btn ${fav ? 'on' : ''}" data-job="${esc(r.jobNo)}"
      aria-pressed="${fav}" title="${fav ? '取消最愛' : '加入最愛'}" aria-label="${fav ? '取消最愛' : '加入最愛'}">${fav ? '★' : '☆'}</button></td>
    <td>${esc(fmtDate(r.jobAnnounceDate))}</td>
    <td>${badge}<a href="${esc(r.jobDetailUrl)}" target="_blank" rel="noopener">${esc(r.jobTitles)}</a>${kw}</td>
    <td>${company}</td>
    <td>${esc(r.jobLocation)}</td>
    <td>${esc(r.jobSalary)}</td>
    <td>${esc(r.jobRqYear)}</td>
    <td>${esc(r.jobRqEducation)}</td>
    ${favCols ? `<td>${groupSelectHtml(r)}</td><td>${stageButtonHtml(r)}</td>
    <td class="nowrap">${esc(fmtTime(r.favoritedAt))}</td>` : ''}
    <td class="act">${lastCell}</td>
  </tr>`;
}

// ---------- 隱藏職缺 (全域) ----------
const hiddenJobs = new Map();
const allTables = [];
let toastTimer = null;

function refreshHidden() {
  $('#hiddenBtn').textContent = `已隱藏 (${hiddenJobs.size})`;
  allTables.forEach(t => t.render());
  if ($('#hiddenDialog').open) renderHiddenList();
}

async function hideJob(row) {
  // 隱藏與最愛互斥: 已收藏的先確認 後端會一併移出最愛
  const favorite = favoriteJobs.get(row.jobNo);
  if (favorite) {
    const extra = favorite.events?.length ? '，並刪除群組與應徵紀錄' : '';
    if (!confirm(`「${row.jobTitles}」在最愛裡，隱藏會一併移出最愛${extra}。確定隱藏？`)) return;
  }
  const info = { jobNo: row.jobNo, title: row.jobTitles, company: row.jobCompanyName, url: row.jobDetailUrl };
  let result;
  try {
    result = await api('/api/hidden', { method: 'POST', body: JSON.stringify(info) });
  } catch (err) { alert(err.message); return; }
  hiddenJobs.set(row.jobNo, info);
  favoriteJobs.delete(row.jobNo);
  refreshHidden();
  refreshFavorites();
  showToast(`已隱藏「${row.jobTitles}」`, async () => {
    // 原本是最愛: 連同群組與歷程完整還原 (後端會一併取消隱藏)
    if (result.removedFavorite) await restoreFavorite(result.removedFavorite);
    else await unhideJob(row.jobNo);
  });
}

// ---------- 最愛職缺 (全域) ----------
const favoriteJobs = new Map(); // jobNo → 收藏的完整資料 (含 favoritedAt)
let favTable = null;

function nowText() {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function refreshFavorites() {
  $('.tab[data-view=favorites]').textContent = `最愛 (${favoriteJobs.size})`;
  if (favTable) {
    const rows = [...favoriteJobs.values()].sort((a, b) => (b.favoritedAt || '').localeCompare(a.favoritedAt || ''));
    favTable.setTitle(`<strong>共 ${rows.length} 筆收藏</strong>`);
    favTable.setCsv(rows.length ? '/api/favorites/csv' : null);
    favTable.rows = rows;
    renderFavToolbar();
  }
  allTables.forEach(t => t.render());
}

async function loadFavorites() {
  const list = await api('/api/favorites').catch(() => null);
  if (!list) return;
  favoriteJobs.clear();
  for (const f of list) favoriteJobs.set(f.jobNo, f);
  refreshFavorites();
}

async function addFavorite(row, { toast = true } = {}) {
  const { isNew, ...data } = row;
  const saved = { ...data, favoritedAt: row.favoritedAt || nowText() };
  try {
    await api('/api/favorites', { method: 'POST', body: JSON.stringify(data) });
  } catch (err) { alert(err.message); return; }
  favoriteJobs.set(row.jobNo, saved);
  if (hiddenJobs.delete(row.jobNo)) refreshHidden();
  refreshFavorites();
  if (toast) showToast(`已加入最愛「${row.jobTitles}」`, () => removeFavorite(row.jobNo, { toast: false }));
}

async function removeFavorite(jobNo, { toast = true } = {}) {
  const saved = favoriteJobs.get(jobNo);
  if (saved?.events?.length) {
    const stages = saved.events.map(e => e.stageName).join('、');
    if (!confirm(`「${saved.jobTitles}」有應徵紀錄（${stages}），移出最愛會一併刪除群組與應徵紀錄。確定移出？`)) return;
  }
  let result;
  try {
    result = await api(`/api/favorites/${encodeURIComponent(jobNo)}`, { method: 'DELETE' });
  } catch (err) { alert(err.message); return; }
  favoriteJobs.delete(jobNo);
  refreshFavorites();
  if (toast && saved && result.removed) {
    showToast(`已移出最愛「${saved.jobTitles}」`, () => restoreFavorite(result.removed));
  }
}

// 還原被移出的最愛 (含收藏時間 群組 歷程) 並取消隱藏
async function restoreFavorite(bundle) {
  try {
    await api('/api/favorites/restore', { method: 'POST', body: JSON.stringify(bundle) });
  } catch (err) { alert(err.message); return; }
  if (hiddenJobs.delete(bundle.jobNo)) refreshHidden();
  await loadFavorites();
}

function toggleFavorite(row) {
  return favoriteJobs.has(row.jobNo) ? removeFavorite(row.jobNo) : addFavorite(row);
}

// ---------- 最愛: 群組與應徵進度 ----------
let favGroups = [];   // [{ id, name, used }]
let appStages = [];   // [{ id, name, used }]
const favFilter = { group: 'all', stage: 'all' }; // group: all|none|id  stage: all|none|id
let progressJobNo = null;

const LIST_LABEL = { groups: '群組', stages: '階段' };

async function loadLists() {
  const [groups, stages] = await Promise.all([api('/api/lists/groups'), api('/api/lists/stages')])
    .catch(() => [favGroups, appStages]);
  favGroups = groups;
  appStages = stages;
  // 篩選中的群組/階段被刪除時 回到全部
  if (favFilter.group !== 'all' && favFilter.group !== 'none' && !favGroups.some(g => g.id === favFilter.group)) favFilter.group = 'all';
  if (favFilter.stage !== 'all' && favFilter.stage !== 'none' && !appStages.some(s => s.id === favFilter.stage)) favFilter.stage = 'all';
}

function fmtDay(iso) {
  return /^\d{4}-\d{2}-\d{2}$/.test(iso || '') ? `${iso.slice(5, 7)}/${iso.slice(8)}` : (iso || '');
}

function todayIso() {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function favFilterMatch(r) {
  const g = favFilter.group, st = favFilter.stage;
  if (g === 'none' && r.groupId != null) return false;
  if (g !== 'all' && g !== 'none' && r.groupId !== g) return false;
  if (st === 'none' && r.current) return false;
  if (st !== 'all' && st !== 'none' && r.current?.stageId !== st) return false;
  return true;
}

function groupSelectHtml(r) {
  const options = [`<option value="">未分組</option>`,
    ...favGroups.map(g => `<option value="${g.id}" ${r.groupId === g.id ? 'selected' : ''}>${esc(g.name)}</option>`),
    `<option value="__new">＋新增群組…</option>`];
  return `<select class="grp-select" data-job="${esc(r.jobNo)}" aria-label="群組">${options.join('')}</select>`;
}

function stageButtonHtml(r) {
  const c = r.current;
  const label = c ? `${esc(c.stageName)} <span class="stage-date">${esc(fmtDay(c.date))}</span>` : '未投遞';
  return `<button type="button" class="stage-btn ${c ? 'has-stage' : ''}" data-job="${esc(r.jobNo)}"
    title="查看與新增應徵紀錄">${label}</button>`;
}

async function changeGroup(jobNo, value, select) {
  let groupId = value === '' ? null : Number(value);
  if (value === '__new') {
    const name = prompt('新群組名稱：');
    if (!name || !name.trim()) { select.value = favoriteJobs.get(jobNo)?.groupId ?? ''; return; }
    try {
      groupId = (await api('/api/lists/groups', { method: 'POST', body: JSON.stringify({ name }) })).id;
    } catch (err) {
      alert(err.message);
      select.value = favoriteJobs.get(jobNo)?.groupId ?? '';
      return;
    }
  }
  try {
    await api(`/api/favorites/${encodeURIComponent(jobNo)}/group`, { method: 'PUT', body: JSON.stringify({ groupId }) });
  } catch (err) { alert(err.message); }
  await loadLists();
  await loadFavorites();
}

// 篩選列: 群組篩選鈕 + 進度下拉 + 管理按鈕
function renderFavToolbar() {
  const el = $('#favToolbar');
  if (!el) return;
  const favs = [...favoriteJobs.values()];
  const count = fn => favs.filter(fn).length;
  const chip = (value, label, n) => `<button type="button" class="chip ${String(favFilter.group) === String(value) ? 'active' : ''}"
    data-group="${value}">${esc(label)} <span class="chip-n">${n}</span></button>`;
  el.innerHTML = `
    <div class="chips">
      ${chip('all', '全部', favs.length)}
      ${chip('none', '未分組', count(f => f.groupId == null))}
      ${favGroups.map(g => chip(g.id, g.name, count(f => f.groupId === g.id))).join('')}
    </div>
    <div class="fav-tools">
      <label class="inline">應徵進度
        <select id="stageFilter" class="text small-select">
          <option value="all">全部</option>
          <option value="none" ${favFilter.stage === 'none' ? 'selected' : ''}>未投遞 (${count(f => !f.current)})</option>
          ${appStages.map(s => `<option value="${s.id}" ${favFilter.stage === s.id ? 'selected' : ''}>${esc(s.name)} (${count(f => f.current?.stageId === s.id)})</option>`).join('')}
        </select>
      </label>
      <button type="button" class="btn small primary" id="addExternalBtn">＋ 新增外部職缺</button>
      <button type="button" class="btn small" id="manageBtn">管理群組與階段</button>
    </div>`;
}

function initFavToolbar() {
  const el = $('#favToolbar');
  el.addEventListener('click', e => {
    const chip = e.target.closest('.chip');
    if (chip) {
      const v = chip.dataset.group;
      favFilter.group = v === 'all' || v === 'none' ? v : Number(v);
      refreshFavorites();
    } else if (e.target.closest('#manageBtn')) {
      openManage();
    } else if (e.target.closest('#addExternalBtn')) {
      openExternalForm(null);
    }
  });
  el.addEventListener('change', e => {
    if (e.target.id !== 'stageFilter') return;
    const v = e.target.value;
    favFilter.stage = v === 'all' || v === 'none' ? v : Number(v);
    refreshFavorites();
  });
}

// ---------- 外部職缺 (非104 手動輸入) ----------
let externalEditing = null; // null=新增 / 職缺資料=編輯

function openExternalForm(row) {
  externalEditing = row;
  const f = $('#externalForm');
  f.reset();
  $('#externalTitle').textContent = row ? '編輯外部職缺' : '新增外部職缺';
  $('#externalSave').textContent = row ? '儲存' : '加入最愛';
  // 群組只在新增時設定 (之後用表格上的群組選單切換)
  $('#extGroupRow').hidden = !!row;
  $('#extGroup').innerHTML = `<option value="">未分組</option>` +
    favGroups.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join('');
  if (row) {
    f.url.value = row.jobDetailUrl || '';
    f.title.value = row.jobTitles || '';
    f.company.value = row.jobCompanyName || '';
    f.location.value = row.jobLocation || '';
    f.salary.value = row.jobSalary || '';
    f.note.value = row.note || '';
  } else if (typeof favFilter.group === 'number') {
    $('#extGroup').value = favFilter.group; // 正在看某個群組時 預設加入該群組
  }
  $('#externalDialog').showModal();
  f.url.focus();
}

async function saveExternal(e) {
  e.preventDefault();
  const f = $('#externalForm');
  const body = {
    url: f.url.value.trim(), title: f.title.value.trim(), company: f.company.value.trim(),
    location: f.location.value.trim(), salary: f.salary.value.trim(), note: f.note.value.trim(),
  };
  if (!externalEditing) body.groupId = f.group.value ? Number(f.group.value) : null;
  try {
    if (externalEditing) {
      await api(`/api/favorites/external/${encodeURIComponent(externalEditing.jobNo)}`, { method: 'PUT', body: JSON.stringify(body) });
    } else {
      await api('/api/favorites/external', { method: 'POST', body: JSON.stringify(body) });
    }
  } catch (err) { alert(err.message); return; }
  const wasEditing = !!externalEditing;
  $('#externalDialog').close();
  await loadLists();
  await loadFavorites();
  if (!wasEditing) showToastPlain(`已加入外部職缺「${body.title}」`);
}

// 沒有「復原」按鈕的提示
function showToastPlain(text) {
  const el = $('#toast');
  el.innerHTML = `<span>${esc(text)}</span>`;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

// ---------- 應徵進度視窗 ----------
function openProgress(jobNo) {
  progressJobNo = jobNo;
  $('#eventDate').value = todayIso();
  $('#eventNote').value = '';
  $('#eventStage').value = ''; // 重新依這個職缺的目前階段選預設值
  renderProgress();
  if (!$('#progressDialog').open) $('#progressDialog').showModal();
}

function renderProgress() {
  const fav = favoriteJobs.get(progressJobNo);
  if (!fav) { $('#progressDialog').close(); return; }
  $('#progressTitle').textContent = fav.jobTitles;
  $('#progressCompany').textContent = fav.jobCompanyName || '';
  const events = fav.events || [];
  $('#eventList').innerHTML = events.length ? events.map(e => `
    <li>
      <span class="ev-date">${esc(fmtDay(e.date))}</span>
      <span class="ev-stage">${esc(e.stageName)}</span>
      <span class="ev-note">${esc(e.note)}</span>
      <button type="button" class="hide-btn" data-event="${e.id}" title="刪除這筆紀錄" aria-label="刪除">✕</button>
    </li>`).join('') : '<li class="empty-note">尚無應徵紀錄（未投遞）</li>';
  const select = $('#eventStage');
  const keep = select.value;
  select.innerHTML = appStages.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  // 預設選「目前階段的下一個」 方便依序推進
  const currentIndex = appStages.findIndex(s => s.id === fav.current?.stageId);
  const next = appStages[Math.min(currentIndex + 1, appStages.length - 1)];
  select.value = appStages.some(s => String(s.id) === keep) && keep ? keep : (next ? next.id : '');
  $('#eventAddBtn').disabled = !appStages.length;
  $('#noStageHint').hidden = appStages.length > 0;
}

async function addEvent() {
  const stageId = Number($('#eventStage').value);
  const date = $('#eventDate').value;
  if (!stageId) { alert('請先到「管理群組與階段」新增應徵階段'); return; }
  if (!date) { alert('請選擇日期'); return; }
  try {
    await api(`/api/favorites/${encodeURIComponent(progressJobNo)}/events`, {
      method: 'POST', body: JSON.stringify({ stageId, date, note: $('#eventNote').value }),
    });
  } catch (err) { alert(err.message); return; }
  $('#eventNote').value = '';
  $('#eventStage').value = '';
  await loadLists();
  await loadFavorites();
  renderProgress();
}

function initProgress() {
  initFavToolbar();
  $('#externalForm').addEventListener('submit', saveExternal);
  $('#externalCancel').addEventListener('click', () => $('#externalDialog').close());
  $('#progressClose').addEventListener('click', () => $('#progressDialog').close());
  $('#eventAddBtn').addEventListener('click', addEvent);
  $('#eventNote').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); addEvent(); } });
  $('#eventList').addEventListener('click', async e => {
    const id = e.target.closest('[data-event]')?.dataset.event;
    if (!id || !confirm('刪除這筆應徵紀錄？')) return;
    try {
      await api(`/api/events/${id}`, { method: 'DELETE' });
    } catch (err) { alert(err.message); return; }
    await loadLists();
    await loadFavorites();
    renderProgress();
  });
  $('#manageClose').addEventListener('click', () => $('#manageDialog').close());
  $('#manageDialog').addEventListener('click', onManageClick);
  $('#manageDialog').addEventListener('keydown', e => {
    const input = e.target.closest('.list-add input');
    if (input && e.key === 'Enter' && !e.isComposing) { e.preventDefault(); addListItem(input.dataset.kind); }
  });
}

// ---------- 管理群組與階段 ----------
function openManage() {
  renderManage();
  $('#manageDialog').showModal();
}

function renderManage() {
  for (const kind of ['groups', 'stages']) {
    const items = kind === 'groups' ? favGroups : appStages;
    const unit = kind === 'groups' ? '個職缺' : '筆紀錄';
    $(`#manage-${kind}`).innerHTML = items.length ? items.map((it, i) => `
      <li data-kind="${kind}" data-id="${it.id}">
        <span class="li-name">${esc(it.name)}</span>
        <span class="li-used">${it.used} ${unit}</span>
        <button type="button" class="btn small ghost" data-act="up" ${i === 0 ? 'disabled' : ''} aria-label="上移">↑</button>
        <button type="button" class="btn small ghost" data-act="down" ${i === items.length - 1 ? 'disabled' : ''} aria-label="下移">↓</button>
        <button type="button" class="btn small" data-act="rename">改名</button>
        <button type="button" class="btn small ghost danger-text" data-act="delete">刪除</button>
      </li>`).join('') : `<li class="empty-note">還沒有${LIST_LABEL[kind]}</li>`;
  }
}

async function refreshAfterListChange() {
  await loadLists();
  await loadFavorites();
  renderManage();
  if ($('#progressDialog').open) renderProgress();
}

async function addListItem(kind) {
  const input = $(`.list-add input[data-kind=${kind}]`);
  const name = input.value.trim();
  if (!name) { input.focus(); return; }
  try {
    await api(`/api/lists/${kind}`, { method: 'POST', body: JSON.stringify({ name }) });
  } catch (err) { alert(err.message); return; }
  input.value = '';
  await refreshAfterListChange();
  input.focus();
}

async function onManageClick(e) {
  const addBtn = e.target.closest('.list-add button');
  if (addBtn) { addListItem(addBtn.dataset.kind); return; }
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const li = btn.closest('li');
  const kind = li.dataset.kind, id = Number(li.dataset.id);
  const item = (kind === 'groups' ? favGroups : appStages).find(it => it.id === id);
  const label = LIST_LABEL[kind];
  try {
    if (btn.dataset.act === 'up' || btn.dataset.act === 'down') {
      await api(`/api/lists/${kind}/${id}/move`, { method: 'POST', body: JSON.stringify({ direction: btn.dataset.act === 'up' ? -1 : 1 }) });
    } else if (btn.dataset.act === 'rename') {
      const name = prompt(`${label}新名稱：`, item.name);
      if (name === null || !name.trim() || name.trim() === item.name) return;
      await api(`/api/lists/${kind}/${id}`, { method: 'PUT', body: JSON.stringify({ name }) });
    } else if (btn.dataset.act === 'delete') {
      const effect = kind === 'groups'
        ? (item.used ? `\n裡面的 ${item.used} 個職缺會變成「未分組」。` : '')
        : (item.used ? `\n有 ${item.used} 筆應徵紀錄用到這個階段，紀錄會保留並顯示原本的名稱。` : '');
      if (!confirm(`刪除${label}「${item.name}」？${effect}`)) return;
      await api(`/api/lists/${kind}/${id}`, { method: 'DELETE' });
    }
  } catch (err) { alert(err.message); return; }
  await refreshAfterListChange();
}

async function unhideJob(jobNo) {
  try {
    await api(`/api/hidden/${encodeURIComponent(jobNo)}`, { method: 'DELETE' });
  } catch (err) { alert(err.message); return; }
  hiddenJobs.delete(jobNo);
  refreshHidden();
}

function showToast(text, undo) {
  const el = $('#toast');
  el.innerHTML = `<span>${esc(text)}</span><button type="button" class="btn small">復原</button>`;
  el.hidden = false;
  $('button', el).onclick = () => { el.hidden = true; undo(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 6000);
}

function renderHiddenList() {
  const items = [...hiddenJobs.values()];
  $('#hiddenList').innerHTML = items.length ? items.map(h => `
    <div class="hidden-item">
      <div><a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title || h.jobNo)}</a><div class="co">${esc(h.company)}</div></div>
      <button type="button" class="btn small" data-unhide="${esc(h.jobNo)}">恢復</button>
    </div>`).join('') : '<p class="empty-note">沒有隱藏的職缺</p>';
}

function initHidden(list) {
  for (const h of list) hiddenJobs.set(h.jobNo, h);
  refreshHidden();
  $('#hiddenBtn').addEventListener('click', () => { renderHiddenList(); $('#hiddenDialog').showModal(); });
  $('#hiddenClose').addEventListener('click', () => $('#hiddenDialog').close());
  $('#hiddenList').addEventListener('click', e => {
    const jobNo = e.target.closest('[data-unhide]')?.dataset.unhide;
    if (jobNo) unhideJob(jobNo);
  });
}

class ResultsTable {
  constructor(el, { emptyText, newToggle = false, favCols = false, extraFilter = null } = {}) {
    this.el = el;
    this.rows = [];
    this.emptyText = emptyText;
    this.rowOptions = { favCols };
    this.columns = favCols ? 12 : 9;
    this.extraFilter = extraFilter;
    el.innerHTML = `
      <div class="table-head">
        <div class="table-title"></div>
        <div class="table-tools">
          ${newToggle ? '<label class="pill"><input type="checkbox" class="only-new"><span>只看新增</span></label>' : ''}
          <a class="btn small primary rt-csv" href="#" download hidden>下載 CSV</a>
        </div>
      </div>
      <input type="text" class="text rt-filter" placeholder="在結果中篩選（職稱、公司、地點、關鍵字…）">
      <div class="table-scroll">
        <table class="${favCols ? 'fav-table' : ''}">
          <thead><tr>
            <th class="act" title="加入最愛">最愛</th>
            <th class="sortable" data-sort="date" title="點擊排序">日期<span class="sort-arrow"></span></th>
            <th>職稱</th>
            <th class="sortable" data-sort="company" title="點擊排序">公司<span class="sort-arrow"></span></th>
            <th>地點</th><th>待遇</th><th>經歷</th><th>學歷</th>
            ${favCols ? '<th>群組</th><th>應徵進度</th><th>收藏時間</th>' : ''}
            ${favCols ? '<th class="act" title="104職缺：隱藏／外部職缺：編輯">隱藏／編輯</th>'
              : '<th class="act" title="隱藏後不再顯示">隱藏</th>'}
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>`;
    this.tbody = $('tbody', el);
    this.sort = null; // { key: 'date'|'company', dir: 1|-1 } null=原始順序
    $('.rt-filter', el).addEventListener('input', () => this.render());
    $('.only-new', el)?.addEventListener('change', () => this.render());
    $('thead', el).addEventListener('click', e => {
      const th = e.target.closest('th[data-sort]');
      if (th) this.toggleSort(th.dataset.sort);
    });
    this.tbody.addEventListener('click', e => {
      const btn = e.target.closest('.hide-btn, .fav-btn, .stage-btn');
      const row = btn && this.rows.find(r => r.jobNo === btn.dataset.job);
      if (!row) return;
      if (btn.classList.contains('fav-btn')) toggleFavorite(row);
      else if (btn.classList.contains('stage-btn')) openProgress(row.jobNo);
      else if (btn.classList.contains('ext-edit-btn')) openExternalForm(row);
      else hideJob(row);
    });
    this.tbody.addEventListener('change', e => {
      const select = e.target.closest('.grp-select');
      if (select) changeGroup(select.dataset.job, select.value, select);
    });
    allTables.push(this);
    this.render();
  }

  // 點擊循環: 日期 新→舊→舊→新→原始 / 公司 A→Z→Z→A→原始
  toggleSort(key) {
    const firstDir = key === 'date' ? -1 : 1;
    if (!this.sort || this.sort.key !== key) this.sort = { key, dir: firstDir };
    else if (this.sort.dir === firstDir) this.sort.dir = -firstDir;
    else this.sort = null;
    for (const th of $$('th[data-sort]', this.el)) {
      const active = this.sort?.key === th.dataset.sort;
      th.classList.toggle('sorted', active);
      $('.sort-arrow', th).textContent = active ? (this.sort.dir === 1 ? ' ▲' : ' ▼') : '';
      th.setAttribute('aria-sort', active ? (this.sort.dir === 1 ? 'ascending' : 'descending') : 'none');
    }
    this.render();
  }

  sorted(rows) {
    if (!this.sort) return rows;
    const { key, dir } = this.sort;
    const collator = new Intl.Collator('zh-Hant-TW');
    const value = r => (key === 'date' ? r.jobAnnounceDate : r.jobCompanyName) || '';
    // 同值時保留原始順序 (Array.prototype.sort 為穩定排序)
    return [...rows].sort((a, b) => dir * (key === 'date'
      ? value(a).localeCompare(value(b))
      : collator.compare(value(a), value(b))));
  }

  visible(rows) {
    const q = $('.rt-filter', this.el).value.trim().toLowerCase();
    const onlyNew = $('.only-new', this.el)?.checked;
    return rows.filter(r => !hiddenJobs.has(r.jobNo) && (!onlyNew || r.isNew) &&
      (!this.extraFilter || this.extraFilter(r)) && (!q ||
      [r.jobTitles, r.jobCompanyName, r.jobLocation, r.jobCompanyIndustry, r.jobSalary, r.matchedKeywords]
        .join(' ').toLowerCase().includes(q)));
  }

  render() {
    const rows = this.sorted(this.visible(this.rows));
    this.tbody.innerHTML = rows.length ? rows.map(r => rowHtml(r, this.rowOptions)).join('')
      : `<tr class="empty"><td colspan="${this.columns}">${this.rows.length ? '沒有符合的結果' : esc(this.emptyText)}</td></tr>`;
  }

  setRows(rows) { this.rows = rows; this.render(); }

  appendRows(rows) {
    if (!rows.length) return;
    this.rows.push(...rows);
    // 排序中的話 新資料要插到正確位置 整個重畫
    if (this.sort || this.rows.length === rows.length) { this.render(); return; }
    this.tbody.insertAdjacentHTML('beforeend', this.visible(rows).map(r => rowHtml(r, this.rowOptions)).join(''));
  }

  setTitle(html) { $('.table-title', this.el).innerHTML = html; }

  setCsv(href) {
    const a = $('.rt-csv', this.el);
    a.href = href || '#';
    a.hidden = !href;
  }
}

// ---------- 執行與輪詢 (一次只能一個爬蟲) ----------
let busy = false;

function setBusy(value) {
  busy = value;
  $('#startBtn').disabled = value;
  $$('.watch-run').forEach(b => { b.disabled = value; });
  updateRunAllButton();
}

// onRunChange: 全部執行換到下一個追蹤時呼叫 (runId改變)
async function runJob(url, body, panel, { onRows = () => {}, onDone = () => {}, onRunChange = () => {} } = {}) {
  let job;
  try {
    job = await api(url, { method: 'POST', body: body ? JSON.stringify(body) : '{}' });
  } catch (err) {
    alert(err.message);
    return;
  }
  setBusy(true);
  panel.reset();
  panel.onStop = () => fetch(`/api/jobs/${job.id}/stop`, { method: 'POST' });
  let loaded = 0, currentRun = null;
  const poll = async () => {
    let s;
    try {
      // run: 告訴伺服器目前拿的是哪一次執行的資料 換了的話伺服器會從頭回傳
      s = await api(`/api/jobs/${job.id}?since=${loaded}&run=${currentRun ?? ''}`);
    } catch (err) {
      setTimeout(poll, 3000);
      return;
    }
    if (s.runId !== currentRun) {
      if (currentRun !== null) loaded = 0;
      currentRun = s.runId;
      await onRunChange(s);
    }
    loaded += s.rows.length;
    onRows(s.rows, s, job);
    panel.update(s);
    if (s.status === 'running' || s.status === 'pending') {
      setTimeout(poll, 1500);
    } else {
      setBusy(false);
      // 爬蟲會用新資料更新已收藏的職缺 重新載入最愛
      loadFavorites();
      onDone(s, job);
    }
  };
  poll();
}

// ---------- 搜尋表單 ----------
let areaPicker, industPicker, keywordInput, filterOptions;
let editState = null;

function renderPills(filters) {
  for (const box of $$('.pills[data-name]')) {
    const name = box.dataset.name;
    const type = box.dataset.type;
    const opts = [
      ...(box.dataset.any ? [{ value: '', label: box.dataset.any }] : []),
      ...filters[name],
      ...(box.dataset.custom ? [{ value: 'custom', label: box.dataset.custom }] : []),
    ];
    box.innerHTML = opts.map(o =>
      `<label class="pill"><input type="${type}" name="${name}" value="${o.value}"><span>${esc(o.label)}</span></label>`).join('');
  }
}

function readForm() {
  const radio = n => $(`input[name=${n}]:checked`)?.value ?? '';
  const checks = n => $$(`input[name=${n}]:checked`).map(i => Number(i.value));
  const num = v => (v === '' ? '' : Number(v));
  const customDays = radio('isnew') === 'custom';
  return {
    keywords: keywordInput.current(),
    order: num(radio('order')),
    area: areaPicker.values(),
    ro: num(radio('ro')),
    isnew: customDays ? '' : num(radio('isnew')),
    newDays: customDays ? Math.max(1, Number($('#newDays').value) || 1) : '',
    jobexp: checks('jobexp'),
    s9: checks('s9'),
    s5: num(radio('s5')),
    wktm: $('#wktm').checked,
    oneClass: $('#oneClass').checked,
    edu: num(radio('edu')),
    indcat: industPicker.values(),
    zone: checks('zone'),
    maxPage: Number($('#maxPage').value) || 1,
    fetchDetail: $('#fetchDetail').checked,
  };
}

function writeForm(v) {
  v = { ...DEFAULTS, ...v };
  // 相容舊版單一關鍵字
  const keywords = v.keywords?.length ? v.keywords : (v.keyword ? [v.keyword] : []);
  keywordInput.input.value = '';
  keywordInput.setValues(keywords);
  for (const n of ['order', 'ro', 'isnew', 's5', 'edu']) {
    for (const i of $$(`input[name=${n}]`)) i.checked = String(v[n]) === i.value;
  }
  if (v.newDays) {
    $('input[name=isnew][value=custom]').checked = true;
    $('#newDays').value = v.newDays;
  }
  for (const n of ['jobexp', 's9', 'zone']) {
    for (const i of $$(`input[name=${n}]`)) i.checked = (v[n] || []).map(String).includes(i.value);
  }
  $('#wktm').checked = v.wktm;
  $('#oneClass').checked = v.oneClass;
  $('#maxPage').value = v.maxPage;
  $('#fetchDetail').checked = v.fetchDetail;
  areaPicker.setValues(v.area);
  industPicker.setValues(v.indcat);
  updateEstimate();
}

// 表單拆成 搜尋條件 與 執行設定
function splitForm(form) {
  const { maxPage, fetchDetail, ...filters } = form;
  return { filters, maxPage, fetchDetail };
}

function saveForm() {
  // 編輯追蹤時不覆蓋平常的搜尋條件
  if (!editState) store(STORAGE_KEY, JSON.stringify(readForm()));
  updateEstimate();
}

function updateEstimate() {
  $('#newDaysRow').hidden = $('input[name=isnew]:checked')?.value !== 'custom';
  const pages = Number($('#maxPage').value) || 1;
  const kw = Math.max(1, keywordInput.current().length);
  const detail = $('#fetchDetail').checked;
  const sec = kw * (detail ? pages * 20 * 3.5 : pages * 1.5);
  const t = sec < 90 ? `約 ${Math.ceil(sec)} 秒` : `約 ${Math.ceil(sec / 60)} 分鐘`;
  const kwText = kw > 1 ? `${kw} 個關鍵字 × ` : '';
  $('#estimate').textContent = (detail
    ? `${kwText}每頁 20 筆，每筆詳細資料間隔 3 秒，最多 ${kw * pages * 20} 筆，${t}。不勾選只抓列表，速度快很多，但會少了職務類別、擅長工具、其他條件。`
    : `只抓搜尋列表，${kwText}最多 ${kw * pages * 20} 筆，${t}。`)
    + (kw > 1 ? '（上限值，重複職缺不會重抓詳細資料）' : '');
}

// state: null=一般搜尋 / { mode: 'edit'|'copy', watch }
function setEditing(state) {
  editState = state;
  $('#editBanner').hidden = !state;
  $('#editTitle').textContent = state?.mode === 'copy' ? `複製追蹤「${state.watch.name}」` : '編輯追蹤';
  $('#saveWatchBtn').textContent = !state ? '存成追蹤' : state.mode === 'copy' ? '儲存為新追蹤' : '更新追蹤';
  if (state) {
    $('#editNameInput').value = state.mode === 'copy' ? copyName(state.watch.name) : state.watch.name;
  }
}

// 「名稱 的副本」 已存在時加編號: 的副本 2、的副本 3…
function copyName(base) {
  const names = new Set(watches.map(w => w.name));
  let name = `${base} 的副本`;
  for (let i = 2; names.has(name); i++) name = `${base} 的副本 ${i}`;
  return name;
}

function startEditing(mode, watch) {
  setEditing({ mode, watch });
  writeForm({ ...watch.filters, maxPage: watch.maxPage, fetchDetail: watch.fetchDetail });
  showView('search');
  window.scrollTo(0, 0);
  $('#editNameInput').focus();
  $('#editNameInput').select();
}

// 結束編輯/複製 表單恢復成平常存的搜尋條件
function finishEditing() {
  setEditing(null);
  let saved = {};
  try { saved = JSON.parse(load(STORAGE_KEY) || '{}'); } catch {}
  writeForm(saved);
}

// ---------- 搜尋分頁 ----------
let searchPanel, searchTable;

function initSearch() {
  searchPanel = new StatusPanel($('#searchStatus'));
  searchTable = new ResultsTable($('#searchResults'), { emptyText: '設定好條件後按「開始搜尋」' });

  $('#form').addEventListener('submit', e => {
    e.preventDefault();
    keywordInput.commit();
    searchTable.setRows([]);
    searchPanel.setCsv(null);
    runJob('/api/jobs', splitForm(readForm()), searchPanel, {
      onRows: (rows, s, job) => {
        searchTable.appendRows(rows);
        if (s.count) searchPanel.setCsv(`/api/jobs/${job.id}/csv`);
      },
    });
  });

  $('#resetBtn').addEventListener('click', () => { writeForm({}); saveForm(); });
  $('#saveWatchBtn').addEventListener('click', saveWatch);
  $('#cancelEditBtn').addEventListener('click', () => {
    finishEditing();
    showView('watches');
  });
  // 名稱欄按Enter不要觸發「開始搜尋」 改為儲存
  $('#editNameInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); saveWatch(); }
  });
}

async function saveWatch() {
  keywordInput.commit();
  const { filters, maxPage, fetchDetail } = splitForm(readForm());
  if (editState) {
    const name = $('#editNameInput').value.trim();
    if (!name) {
      alert('請輸入追蹤名稱');
      $('#editNameInput').focus();
      return;
    }
    const body = JSON.stringify({ name, filters, maxPage, fetchDetail });
    let saved;
    try {
      // 名稱重複等錯誤: 留在表單上 已填的條件不會不見
      saved = editState.mode === 'copy'
        ? await api('/api/watches', { method: 'POST', body })
        : await api(`/api/watches/${editState.watch.id}`, { method: 'PUT', body });
    } catch (err) {
      alert(err.message);
      $('#editNameInput').focus();
      return;
    }
    finishEditing();
    selectedRunId = null;
    await loadWatches(saved.id);
    showView('watches');
    return;
  }
  const suggested = filters.keywords.join('、') || '我的追蹤';
  const name = prompt('追蹤名稱：', suggested);
  if (name === null) return;
  if (!name.trim()) { alert('請輸入追蹤名稱'); return; }
  try {
    const watch = await api('/api/watches', { method: 'POST', body: JSON.stringify({ name, filters, maxPage, fetchDetail }) });
    await loadWatches(watch.id);
    if (confirm(`已建立追蹤「${watch.name}」。要切換到追蹤清單嗎？`)) showView('watches');
  } catch (err) { alert(err.message); }
}

// ---------- 追蹤分頁 ----------
let watches = [], selectedWatchId = null, selectedRunId = null, watchPanel, runTable;

function optionLabel(name, value) {
  return filterOptions[name].find(o => String(o.value) === String(value))?.label;
}

function summarize(f, w) {
  const parts = [];
  const kw = f.keywords?.length ? f.keywords : (f.keyword ? [f.keyword] : []);
  parts.push(kw.length ? kw.join('、') : '不限關鍵字');
  if (f.area?.length) parts.push(f.area.map(c => areaPicker.names[c] || c).join('、'));
  if (f.ro) parts.push(optionLabel('ro', f.ro));
  if (f.newDays) parts.push(`${f.newDays} 天內`);
  else if (f.isnew !== '' && f.isnew != null) parts.push(optionLabel('isnew', f.isnew));
  if (f.jobexp?.length) parts.push(f.jobexp.map(v => optionLabel('jobexp', v)).join('、'));
  if (f.edu) parts.push(optionLabel('edu', f.edu));
  if (f.indcat?.length) parts.push(f.indcat.map(c => industPicker.names[c] || c).join('、'));
  if (f.zone?.length) parts.push(f.zone.map(v => optionLabel('zone', v)).join('、'));
  parts.push(`每字 ${w.maxPage} 頁${w.fetchDetail ? '' : '・只抓列表'}`);
  return parts.filter(Boolean).join('｜');
}

function fmtTime(t) {
  return t ? t.slice(5, 16).replace('-', '/') : '';
}

const RUN_STATUS = { running: '執行中', done: '完成', stopped: '已停止', error: '錯誤' };

function renderWatches() {
  const el = $('#watchList');
  updateRunAllButton();
  if (!watches.length) {
    el.innerHTML = '<p class="empty-note">還沒有追蹤。<br>到「搜尋」設定條件後，按「存成追蹤」。</p>';
    return;
  }
  el.innerHTML = watches.map(w => {
    const last = w.lastRun;
    const lastText = last
      ? `${fmtTime(last.startedAt)}・${RUN_STATUS[last.status]}・共 ${last.totalCount} 筆`
      : '尚未執行';
    const badge = last && last.newCount ? `<span class="new-count">+${last.newCount}</span>` : '';
    return `<div class="watch-card ${w.id === selectedWatchId ? 'selected' : ''}" data-id="${w.id}">
      <div class="watch-name">${esc(w.name)}${badge}</div>
      <div class="watch-summary">${esc(summarize(w.filters, w))}</div>
      <div class="watch-last">${esc(lastText)}</div>
      <div class="watch-actions">
        <button type="button" class="btn small primary watch-run" ${busy ? 'disabled' : ''}>執行</button>
        <button type="button" class="btn small watch-edit">編輯條件</button>
        <button type="button" class="btn small watch-copy">複製</button>
        <button type="button" class="btn small ghost danger-text watch-delete">刪除</button>
      </div>
    </div>`;
  }).join('');
}

async function loadWatches(selectId) {
  watches = await api('/api/watches');
  if (selectId !== undefined) selectedWatchId = selectId;
  if (!watches.some(w => w.id === selectedWatchId)) selectedWatchId = watches[0]?.id ?? null;
  renderWatches();
  await loadRuns();
}

async function loadRuns(selectRunId) {
  const watch = watches.find(w => w.id === selectedWatchId);
  $('#runsTitle').textContent = watch ? `「${watch.name}」的執行紀錄` : '執行紀錄';
  if (!watch) {
    $('#runsList').innerHTML = '';
    $('#runResults').hidden = true;
    return;
  }
  const runs = await api(`/api/watches/${watch.id}/runs`);
  if (selectRunId !== undefined) selectedRunId = selectRunId;
  if (!runs.some(r => r.id === selectedRunId)) selectedRunId = runs[0]?.id ?? null;
  $('#runsList').innerHTML = runs.length ? `
    <table class="runs-table">
      <thead><tr><th>執行時間</th><th>狀態</th><th>總筆數</th><th>新增</th></tr></thead>
      <tbody>${runs.map(r => `
        <tr data-run="${r.id}" class="${r.id === selectedRunId ? 'selected' : ''}" title="${esc(r.message || '')}">
          <td>${esc(fmtTime(r.startedAt))}</td>
          <td>${RUN_STATUS[r.status] || r.status}</td>
          <td>${r.totalCount}</td>
          <td>${r.newCount ? `<span class="new-count">+${r.newCount}</span>` : '0'}</td>
        </tr>`).join('')}</tbody>
    </table>` : '<p class="empty-note">尚未執行。按左側的「執行」開始。</p>';
  if (selectedRunId) await loadRun(selectedRunId);
  else $('#runResults').hidden = true;
}

// 結果表格是否正在顯示執行中的即時資料 (切去看其他紀錄後 即時資料不再加進表格)
let runTableLive = false;

async function loadRun(runId) {
  runTableLive = false;
  selectedRunId = runId;
  $$('#runsList tr[data-run]').forEach(tr => tr.classList.toggle('selected', Number(tr.dataset.run) === runId));
  const run = await api(`/api/runs/${runId}`);
  $('#runResults').hidden = false;
  const first = run.isFirstRun ? '<span class="first-run">首次執行，全部視為新增</span>' : '';
  runTable.setTitle(`<strong>${esc(fmtTime(run.startedAt))} 的結果</strong>　共 ${run.totalCount} 筆，新增 ${run.newCount} 筆 ${first}
    ${run.message ? `<div class="co">${esc(run.message)}</div>` : ''}`);
  runTable.setRows(run.rows);
  runTable.setCsv(run.totalCount ? `/api/runs/${runId}/csv` : null);
}

function runWatch(watch) {
  selectedWatchId = watch.id;
  renderWatches();
  $('#watchStatus').hidden = false;
  $('#runResults').hidden = false;
  runTable.setTitle(`<strong>執行中：${esc(watch.name)}</strong>`);
  runTable.setRows([]);
  runTable.setCsv(null);
  runTableLive = true;
  $('#batchSummary').hidden = true;
  runJob(`/api/watches/${watch.id}/run`, null, watchPanel, {
    onRows: rows => { if (runTableLive) runTable.appendRows(rows); },
    onDone: async s => {
      watchPanel.setCsv(s.runId && s.count ? `/api/runs/${s.runId}/csv` : null);
      await loadWatches(watch.id);
      if (s.runId) await loadRuns(s.runId);
    },
  });
}

// ---------- 全部執行 ----------
const BATCH_STATUS = { ...RUN_STATUS, pending: '未執行', deleted: '已刪除' };

function updateRunAllButton() {
  const btn = $('#runAllBtn');
  if (btn) btn.disabled = busy || !watches.length;
}

// 只更新卡片 (不重新載入右側結果 以免打斷即時顯示)
async function refreshWatchCards() {
  watches = await api('/api/watches').catch(() => watches);
  renderWatches();
}

function renderBatchSummary(s) {
  const b = s.batch;
  const newTotal = b.results.reduce((n, r) => n + r.newCount, 0);
  const statusText = s.status === 'stopped' ? '（已停止）' : '';
  $('#batchSummary').innerHTML = `
    <div class="panel-head">
      <h2>全部執行結果${statusText}</h2>
      <button type="button" class="btn small ghost" id="batchClose">關閉</button>
    </div>
    <p class="batch-total">${b.total} 個追蹤，共新增 <strong>${newTotal}</strong> 筆</p>
    <table class="runs-table batch-table">
      <thead><tr><th>追蹤</th><th>狀態</th><th>總筆數</th><th>新增</th></tr></thead>
      <tbody>${b.results.map(r => `
        <tr ${r.runId ? `data-watch="${r.watchId}" data-run="${r.runId}"` : ''} class="${r.runId ? '' : 'no-run'}"
          title="${esc(r.message || '')}">
          <td>${esc(r.name)}</td>
          <td class="st-${r.status}">${BATCH_STATUS[r.status] || r.status}</td>
          <td>${r.runId ? r.totalCount : '–'}</td>
          <td>${r.newCount ? `<span class="new-count">+${r.newCount}</span>` : (r.runId ? '0' : '–')}</td>
        </tr>`).join('')}</tbody>
    </table>
    <p class="hint">點一列可查看該追蹤這次的結果。</p>`;
  $('#batchSummary').hidden = false;
}

function runAllWatches() {
  if (!watches.length) return;
  $('#watchStatus').hidden = false;
  $('#runResults').hidden = false;
  $('#batchSummary').hidden = true;
  runTable.setRows([]);
  runTable.setCsv(null);
  runTable.setTitle('<strong>全部執行：準備中…</strong>');
  runTableLive = true;
  runJob('/api/watches/run-all', null, watchPanel, {
    // 換到下一個追蹤: 表格改顯示新的追蹤 卡片更新上一個的結果
    onRunChange: async s => {
      if (!s.batch || !s.runId) return;
      selectedWatchId = s.watchId;
      await refreshWatchCards();
      if (runTableLive) {
        runTable.setRows([]);
        runTable.setTitle(`<strong>全部執行 ${s.batch.index + 1}/${s.batch.total}：${esc(s.batch.name)}</strong>`);
      }
    },
    onRows: rows => { if (runTableLive) runTable.appendRows(rows); },
    onDone: async s => {
      watchPanel.setCsv(null);
      renderBatchSummary(s);
      // 選有新增的第一個追蹤 沒有的話維持目前選擇
      const firstNew = s.batch.results.find(r => r.newCount > 0 && r.runId);
      await loadWatches(firstNew ? firstNew.watchId : selectedWatchId);
      if (firstNew) await loadRuns(firstNew.runId);
    },
  });
}

function initWatches() {
  watchPanel = new StatusPanel($('#watchStatus'), { showNew: true });
  runTable = new ResultsTable($('#runResults'), { emptyText: '沒有結果', newToggle: true });

  $('#runAllBtn').addEventListener('click', runAllWatches);
  $('#batchSummary').addEventListener('click', async e => {
    if (e.target.closest('#batchClose')) { $('#batchSummary').hidden = true; return; }
    const tr = e.target.closest('tr[data-run]');
    if (!tr) return;
    selectedWatchId = Number(tr.dataset.watch);
    renderWatches();
    await loadRuns(Number(tr.dataset.run));
    $('#runResults').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  $('#watchList').addEventListener('click', async e => {
    const card = e.target.closest('.watch-card');
    if (!card) return;
    const watch = watches.find(w => w.id === Number(card.dataset.id));
    if (e.target.closest('.watch-run')) {
      runWatch(watch);
    } else if (e.target.closest('.watch-edit')) {
      startEditing('edit', watch);
    } else if (e.target.closest('.watch-copy')) {
      startEditing('copy', watch);
    } else if (e.target.closest('.watch-delete')) {
      if (!confirm(`確定刪除追蹤「${watch.name}」？\n所有執行紀錄與看過的職缺紀錄都會一起刪除，無法復原。`)) return;
      try {
        await api(`/api/watches/${watch.id}`, { method: 'DELETE' });
      } catch (err) { alert(err.message); return; }
      // 正在編輯的追蹤被刪除: 結束編輯 (複製模式不受影響 條件已在表單上)
      if (editState?.mode === 'edit' && editState.watch.id === watch.id) finishEditing();
      await loadWatches();
    } else if (watch.id !== selectedWatchId) {
      selectedWatchId = watch.id;
      selectedRunId = null;
      renderWatches();
      await loadRuns();
    }
  });

  $('#runsList').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-run]');
    if (tr) loadRun(Number(tr.dataset.run));
  });
}

// ---------- 分頁 ----------
function showView(name) {
  for (const tab of $$('.tab')) {
    const active = tab.dataset.view === name;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active);
  }
  for (const view of $$('.view')) view.hidden = view.id !== `view-${name}`;
  store(VIEW_KEY, name);
}

// ---------- 網頁開關通知 (全部網頁關閉時 伺服器自動結束) ----------
function initLifecycle() {
  const clientId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  let failures = 0;
  const beat = async () => {
    try {
      await fetch('/api/heartbeat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ clientId }) });
      failures = 0;
      $('#serverGone').hidden = true;
    } catch {
      // 連不到伺服器: 程式可能已結束 (例如另一個分頁關閉後自動結束)
      if (++failures >= 2) $('#serverGone').hidden = false;
    }
  };
  beat();
  setInterval(beat, 20000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) beat(); });
  window.addEventListener('pagehide', () => navigator.sendBeacon(`/api/bye?client=${encodeURIComponent(clientId)}`));
  // 爬蟲執行中關閉網頁: 先跳出瀏覽器的離開確認 (瀏覽器不允許自訂文字)
  window.addEventListener('beforeunload', e => {
    if (busy) { e.preventDefault(); e.returnValue = true; }
  });
}

// ---------- 初始化 ----------
async function init() {
  initLifecycle();
  let opts;
  try {
    opts = await api('/api/options');
  } catch (err) { alert(err.message); return; }
  filterOptions = opts.filters;

  renderPills(opts.filters);
  keywordInput = new TagInput($('#keywordInput'));
  areaPicker = new TreePicker($('#areaPicker'), opts.area, { openCodes: ['6001000000'], placeholder: '未選擇＝全部地區' });
  industPicker = new TreePicker($('#industPicker'), opts.indust, { placeholder: '未選擇＝全部產業' });

  let saved = {};
  try { saved = JSON.parse(load(STORAGE_KEY) || '{}'); } catch {}
  writeForm(saved);

  keywordInput.onChange = saveForm;
  areaPicker.onChange = saveForm;
  industPicker.onChange = saveForm;
  $('#form').addEventListener('input', saveForm);
  $('#form').addEventListener('change', saveForm);

  initSearch();
  initWatches();
  initHidden(await api('/api/hidden').catch(() => []));
  favTable = new ResultsTable($('#favResults'), {
    emptyText: '還沒有最愛。在搜尋或追蹤結果中點職缺前面的 ☆ 加入。', favCols: true, extraFilter: favFilterMatch,
  });
  initProgress();
  await loadLists();
  await loadFavorites();
  $$('.tab').forEach(t => t.addEventListener('click', () => showView(t.dataset.view)));
  const savedView = load(VIEW_KEY);
  showView(['watches', 'favorites'].includes(savedView) ? savedView : 'search');
  await loadWatches();
}

init();
