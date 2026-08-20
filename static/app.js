// 欠料看板前端逻辑（原生 JS，无第三方依赖）
const API = (path, params) => {
  let url = path;
  if (params) {
    const qs = new URLSearchParams(params).toString();
    url += (url.includes('?') ? '&' : '?') + qs;
  }
  return fetch(url).then(r => r.json());
};
const POST = (path) => fetch(path, { method: 'POST' }).then(r => r.json());
const POST_JSON = (path, body) => fetch(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
}).then(r => r.json());

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

// 自动刷新所需的状态：当前所在模块 + 上一次已知同步时间
let currentPage = (document.querySelector('#sidebar li.active') || {}).dataset?.page || 'overview';
let lastKnownSync = null;
let currentProjectKw = '';

// ---------- 页面切换（带过渡动画） ----------
function showPage(page, title) {
  const prev = document.querySelector('.page:not(.hidden)');
  if (prev && prev.id === 'page-' + page) return; // 已在目标页
  // 侧栏高亮
  document.querySelectorAll('#sidebar li').forEach(x => x.classList.remove('active'));
  const li = document.querySelector('#sidebar li[data-page="' + page + '"]');
  if (li) li.classList.add('active');
  currentPage = page;
  $('page-title').textContent = title || (li ? li.textContent : page);
  // 隐藏所有页面（清掉残留动画 class）
  document.querySelectorAll('.page').forEach(p => { p.classList.add('hidden'); p.classList.remove('page-enter'); });
  // 显示目标页并播放入场动画
  const target = $('page-' + page);
  if (target) {
    target.classList.remove('hidden');
    void target.offsetWidth; // 强制 reflow，确保动画每次重新触发
    target.classList.add('page-enter');
  }
  // 按页加载数据
  if (page === 'overview') loadOverview();
  if (page === 'settings') loadSettings();
  if (page === 'sync') refreshSyncInfo();
  if (page === 'sheetmetal') loadSheetmetal();
  // 汇总/交期页面：点开后立即用空 keyword 展示默认汇总
  if (page === 'project' && !$('project-kw').value.trim()) $('btn-project').click();
  if (page === 'material' && !$('material-kw').value.trim()) $('btn-material').click();
  if (page === 'brand' && !$('brand-kw').value.trim()) $('btn-brand').click();
  if (page === 'eta' && !$('eta-kw').value.trim()) $('btn-eta').click();
}

// ---------- 初始化：按 HTML 初始 active 页加载 ----------
(function initActivePage() {
  if (currentPage !== 'overview') {
    const li = document.querySelector('#sidebar li.active');
    if (li) {
      showPage(currentPage, li.textContent);
    }
  }
})();

// ---------- 导航切换 ----------
document.querySelectorAll('#sidebar li').forEach(li => {
  li.addEventListener('click', () => {
    showPage(li.dataset.page);
  });
});

// ---------- 跳转项目汇总 ----------
function openProject(name) {
  showPage('project');
  $('project-kw').value = name;
  $('btn-project').click();
}

// ---------- 总览 ----------
function loadOverview() {
  API('/api/overview').then(d => {
    const wr = d.weekly_rate || {};
    const wrNum = wr.rate != null ? `${wr.rate}%` : (wr.label || '—');
    const wrColor = wr.rate != null ? (wr.rate >= 80 ? '#16A34A' : (wr.rate >= 60 ? '#F59E0B' : '#DC2626')) : '#6B7280';
    const wrSub = wr.rate != null ? `及时 ${wr.on_time}/${wr.total}` : (wr.label || '本周暂无新增');
    const sheetNames = (d.sheet_names && d.sheet_names.length)
      ? d.sheet_names.map(n => `<span class="sheet-name">${esc(n)}</span>`).join('')
      : '<span class="sheet-name muted">暂无</span>';
    $('cards').innerHTML = `
      <div class="card"><div class="num">${d.total}</div><div class="lbl">欠料条数</div></div>
      <div class="card"><div class="num">${d.total_qty}</div><div class="lbl">合计欠料数量</div></div>
      <div class="card"><div class="num">${d.urgent}</div><div class="lbl">紧急条目(空白/无交期/付款)</div></div>
      <div class="card">
        <div class="num">${d.sheets}</div>
        <div class="lbl">已同步分表</div>
        <div class="sheet-names" title="${(d.sheet_names || []).join('、')}">${sheetNames}</div>
      </div>
      <div class="card card-accent" title="本周新增材料中状态为已到货/已解决的占比">
        <div class="num" style="color:${wrColor}">${wrNum}</div>
        <div class="lbl">本周新增材料采购及时率</div>
        <div class="lbl" style="font-size:12px;color:#6b7280;margin-top:2px">${wrSub}</div>
      </div>`;
    const st = d.by_status || {};
    $('by-status').innerHTML = Object.keys(st).map(k =>
      `<div class="bar-row"><div class="name">${esc(k)}</div>
       <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, st[k] / (d.total||1) * 100)}%"></div></div>
       <div class="val">${st[k]}</div></div>`).join('') || '<p class="muted">无数据</p>';
    $('by-project').innerHTML = (d.by_project || []).map(p =>
      `<div class="bar-row"><a class="name project-link" href="javascript:void(0)" data-project="${esc(p.project)}" onclick="openProject(this.dataset.project);return false;" title="${esc(p.project)}">${esc(p.project)}</a>
       <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, p.count / (d.by_project[0]?.count||1) * 100)}%"></div></div>
       <div class="val">${p.count}</div>
       <div class="source" title="${esc(p.sheets || '')}">${esc(p.sheets || '—')}</div></div>`).join('') || '<p class="muted">无数据</p>';
  }).catch(e => $('cards').innerHTML = `<p class="error">加载失败：${esc(e)}</p>`);
}

// ---------- 表格渲染 ----------
function rowsTable(rows, cols) {
  if (!rows || !rows.length) return '<p class="muted">未找到数据</p>';
  const head = cols.map(c => `<th>${esc(c.label)}</th>`).join('');
  const body = rows.map(r => '<tr>' + cols.map(c => `<td>${esc(r[c.key])}</td>`).join('') + '</tr>').join('');
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

const DETAIL_COLS = [
  { key: '项目', label: '项目' }, { key: '物料编码', label: '物料编码' },
  { key: '物料名称', label: '物料名称' }, { key: '品牌', label: '品牌' },
  { key: '欠料数量', label: '欠料数量' }, { key: 'eta_status', label: '紧急度' },
  { key: '预计到货时间', label: '预计到货' }, { key: 'sheet', label: '来源表' },
];

// ---------- 查询 ----------
$('btn-search').addEventListener('click', () => {
  const kw = $('search-kw').value.trim();
  if (!kw) return;
  API('/api/search', { kw }).then(d => {
    if (d.error) { $('search-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    $('search-result').innerHTML = `<p class="muted">命中 ${d.rows.length} 条</p>` + rowsTable(d.rows, DETAIL_COLS);
  });
});

// ---------- 项目汇总 ----------
function refreshProject() {
  if (currentProjectKw) $('btn-project').click();
}

function renderProjectTable(rows) {
  if (!rows || !rows.length) return '<p class="muted">无数据</p>';
  const head = '<tr><th>物料编码</th><th>名称</th><th>品牌</th><th>合计数量</th><th>紧急度</th><th>来源表</th></tr>';
  const body = rows.map(m => {
    const status = Object.entries(m.status || {}).map(([k,v])=>`${k}:${v}`).join('/') || '—';
    return `<tr>
      <td>${esc(m.mc)}</td>
      <td>${esc(m.name)}</td>
      <td>${esc(m.brand)}</td>
      <td>${esc(m.qty)}</td>
      <td>${esc(status)}</td>
      <td>${esc(m.sheets || '—')}</td>
    </tr>`;
  }).join('');
  return `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

$('btn-project').addEventListener('click', () => {
  const kw = $('project-kw').value.trim();
  currentProjectKw = kw;
  API('/api/project', { kw }).then(d => {
    if (d.error) { $('project-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    let h = `<p>共 <b>${d.rows}</b> 条，合计欠料 <b>${d.total_qty}</b></p>`;
    if (d.mode === 'all_projects') {
      h += `<p class="muted">当前展示全部项目，可在上方搜索框输入项目名称或编码过滤</p>`;
      h += rowsTable((d.by_project || []).map(p => ({
        project: p.project,
        qty: p.qty,
        status: Object.entries(p.status || {}).map(([k,v])=>`${k}:${v}`).join('/'),
        sheets: p.sheets,
      })), [
        { key: 'project', label: '项目' },
        { key: 'qty', label: '合计数量' },
        { key: 'status', label: '紧急度' },
        { key: 'sheets', label: '来源表' },
      ]);
    } else {
      h += `<p class="muted">按紧急度：${Object.entries(d.by_status||{}).map(([k,v])=>`${k}:${v}`).join(' / ')||'—'}</p>`;
      h += '<h3 style="margin:12px 0 6px">按物料编码汇总</h3>';
      h += renderProjectTable(d.by_material || []);
    }
    $('project-result').innerHTML = h;
  });
});
$('project-kw').addEventListener('keydown', e => { if (e.key === 'Enter') $('btn-project').click(); });

// ---------- 物料汇总 ----------
$('btn-material').addEventListener('click', () => {
  const kw = $('material-kw').value.trim();
  API('/api/material', { kw }).then(d => {
    if (d.error) { $('material-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    let h = `<p>命中 <b>${d.rows}</b> 条，合计欠货 <b>${d.total_qty}</b></p>`;
    if (d.mode === 'all_materials') {
      h += `<p class="muted">当前展示全部物料，可在上方搜索框输入物料编码或名称过滤</p>`;
    }
    h += '<h3 style="margin:12px 0 6px">按物料编码汇总（跨项目加总）</h3>';
    h += rowsTable(d.by_material.map(m => ({ mc: m.mc, name: m.name, qty: m.qty, projects: m.projects, status: Object.entries(m.status).map(([k,v])=>`${k}:${v}`).join('/'), sheets: m.sheets })),
      [{ key: 'mc', label: '物料编码' }, { key: 'name', label: '名称' }, { key: 'qty', label: '合计数量' }, { key: 'projects', label: '项目数' }, { key: 'status', label: '紧急度' }, { key: 'sheets', label: '来源表' }]);
    if (d.mode !== 'all_materials') {
      h += '<h3 style="margin:12px 0 6px">按项目分布</h3>';
      h += rowsTable(d.by_project.map(p => ({ project: p.project, qty: p.qty, status: Object.entries(p.status).map(([k,v])=>`${k}:${v}`).join('/'), sheets: p.sheets })),
        [{ key: 'project', label: '项目' }, { key: 'qty', label: '合计数量' }, { key: 'status', label: '紧急度' }, { key: 'sheets', label: '来源表' }]);
      if (d.details && d.details.length) { h += '<h3 style="margin:12px 0 6px">明细 Top</h3>' + rowsTable(d.details, DETAIL_COLS); }
    }
    $('material-result').innerHTML = h;
  });
});
$('material-kw').addEventListener('keydown', e => { if (e.key === 'Enter') $('btn-material').click(); });

// ---------- 品牌汇总 ----------
$('btn-brand').addEventListener('click', () => {
  const kw = $('brand-kw').value.trim();
  API('/api/brand', { kw }).then(d => {
    if (d.error) { $('brand-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    let h = `<p>${kw ? '该品牌' : '全部'}命中 <b>${d.rows}</b> 条，合计欠货 <b>${d.total_qty}</b></p>`;
    if (d.mode === 'all_brands') {
      h += `<p class="muted">当前展示全部品牌，可在上方搜索框输入品牌名称过滤</p>`;
      h += '<h3 style="margin:12px 0 6px">按品牌汇总</h3>';
      h += rowsTable(d.by_brand.map(b => ({ brand: b.brand, qty: b.qty, materials: b.materials, status: Object.entries(b.status).map(([k,v])=>`${k}:${v}`).join('/'), sheets: b.sheets })),
        [{ key: 'brand', label: '品牌' }, { key: 'qty', label: '合计数量' }, { key: 'materials', label: '涉及物料数' }, { key: 'status', label: '紧急度' }, { key: 'sheets', label: '来源表' }]);
    } else {
      h += '<h3 style="margin:12px 0 6px">按物料编码分布（跨项目加总）</h3>';
      h += rowsTable(d.by_material.map(m => ({ mc: m.mc, name: m.name, qty: m.qty, projects: m.projects, status: Object.entries(m.status).map(([k,v])=>`${k}:${v}`).join('/'), sheets: m.sheets })),
        [{ key: 'mc', label: '物料编码' }, { key: 'name', label: '名称' }, { key: 'qty', label: '合计数量' }, { key: 'projects', label: '项目数' }, { key: 'status', label: '紧急度' }, { key: 'sheets', label: '来源表' }]);
      h += '<h3 style="margin:12px 0 6px">按项目分布</h3>';
      h += rowsTable(d.by_project.map(p => ({ project: p.project, qty: p.qty, status: Object.entries(p.status).map(([k,v])=>`${k}:${v}`).join('/'), sheets: p.sheets })),
        [{ key: 'project', label: '项目' }, { key: 'qty', label: '合计数量' }, { key: 'status', label: '紧急度' }, { key: 'sheets', label: '来源表' }]);
      if (d.details && d.details.length) { h += '<h3 style="margin:12px 0 6px">明细 Top</h3>' + rowsTable(d.details, DETAIL_COLS); }
    }
    $('brand-result').innerHTML = h;
  });
});
$('brand-kw').addEventListener('keydown', e => { if (e.key === 'Enter') $('btn-brand').click(); });

// ---------- 交期对比 ----------
function formatEtaDate(iso, fallback) {
  if (!iso) return fallback || '—';
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return iso;
  return `${parseInt(m[2], 10)}-${parseInt(m[3], 10)}`;
}

function renderEtaTimeline(entries) {
  if (!entries || !entries.length) return '';
  return entries.map(e => {
    const expDays = e.期望剩余天;
    const etaDays = e.预计剩余天;
    const diff = e.相差天;
    const hasBoth = expDays !== null && etaDays !== null;

    // 时间轴范围：以今天为锚点，覆盖期望/预计到货到货日
    const days = [0];
    if (expDays !== null) days.push(expDays);
    if (etaDays !== null) days.push(etaDays);
    const minDay = Math.min(...days) - 3;
    const maxDay = Math.max(...days) + 8;
    const range = (maxDay - minDay) || 1;
    const pct = d => Math.max(0, Math.min(100, (d - minDay) / range * 100));

    const todayPct = pct(0);
    const expPct = expDays !== null ? pct(expDays) : null;
    const etaPct = etaDays !== null ? pct(etaDays) : null;

    let gapHtml = '';
    if (hasBoth && expPct !== null && etaPct !== null) {
      const left = Math.min(expPct, etaPct);
      const width = Math.abs(etaPct - expPct);
      const cls = diff > 0 ? 'late' : (diff < 0 ? 'early' : 'ok');
      gapHtml = `<div class="eta-gap ${cls}" style="left:${left}%;width:${width}%"></div>`;
    }

    let statusHtml;
    if (diff === null) statusHtml = `<span class="tag muted">${esc(e.判定)}</span>`;
    else if (diff > 0) statusHtml = `<span class="tag warn">逾期 ${diff} 天</span>`;
    else if (diff < 0) statusHtml = `<span class="tag ok">提前 ${Math.abs(diff)} 天</span>`;
    else statusHtml = `<span class="tag ok">刚好</span>`;

    return `<div class="eta-entry">
      <div class="eta-entry-meta">
        <span class="eta-project" title="${esc(e.项目)}">${esc(e.项目 || '未命名')}</span>
        <span class="exp">需求：${esc(formatEtaDate(e.期望日期, e.期望))} <small>${expDays != null ? (expDays >= 0 ? `(剩余 ${expDays} 天)` : `(已逾期 ${Math.abs(expDays)} 天)`) : ''}</small></span>
        <span class="act">实际：${esc(formatEtaDate(e.预计日期, e.预计))} <small>${etaDays != null ? (etaDays >= 0 ? `(剩余 ${etaDays} 天)` : `(已逾期 ${Math.abs(etaDays)} 天)`) : ''}</small></span>
        ${statusHtml}
      </div>
      <div class="eta-track" title="灰色竖线=今天，橙色=需求交期，蓝色=实际预计到货">
        ${gapHtml}
        <div class="eta-today" style="left:${todayPct}%"></div>
        ${expPct !== null ? `<div class="eta-marker expected" style="left:${expPct}%"></div>` : ''}
        ${etaPct !== null ? `<div class="eta-marker actual" style="left:${etaPct}%"></div>` : ''}
      </div>
    </div>`;
  }).join('');
}

function renderEtaCards(groups) {
  if (!groups || !groups.length) return '<p class="muted">无数据</p>';
  return `<div class="eta-legend">
    <span><i class="dot" style="background:#F59E0B"></i>需求交期</span>
    <span><i class="dot" style="background:#23BABB"></i>实际预计到货</span>
    <span><i class="dot" style="background:#6B7280"></i>今天</span>
    <span><i class="dot" style="background:#FCA5A5"></i>逾期缺口</span>
    <span><i class="dot" style="background:#86EFAC"></i>提前余量</span>
  </div>
  <div class="eta-cards">
    ${groups.map(g => {
      const projects = g.projects.slice(0, 3).join(' / ') + (g.projects.length > 3 ? ` 等${g.projects.length}个项目` : '');
      const badge = g.late ? `<span class="tag warn">${g.late} 项逾期</span>`
        : (g.on_time ? `<span class="tag ok">${g.on_time} 项来得及</span>`
        : `<span class="tag muted">${g.no_date} 项缺交期</span>`);
      return `<div class="eta-card">
        <div class="eta-card-header">
          <div>
            <div class="eta-mc">${esc(g.mc)}</div>
            <div class="eta-name">${esc(g.name || '—')}</div>
            <div class="eta-projects">${esc(projects || '—')}</div>
          </div>
          <div>${badge}</div>
        </div>
        ${renderEtaTimeline(g.entries)}
      </div>`;
    }).join('')}
  </div>`;
}

$('btn-eta').addEventListener('click', () => {
  const kw = $('eta-kw').value.trim();
  API('/api/eta', { kw }).then(d => {
    if (d.error) { $('eta-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    let h = '';
    if (!kw) {
      h += `<p class="muted">当前展示全部欠料的交期对比，可在上方搜索框输入项目/物料/品牌过滤</p>`;
    }
    h += `<div class="cards" style="margin-bottom:14px">
      <div class="card"><div class="num">${d.rows}</div><div class="lbl">匹配条数</div></div>
      <div class="card"><div class="num" style="color:#DC2626">${d.late}</div><div class="lbl">逾期风险</div></div>
      <div class="card"><div class="num" style="color:#16A34A">${d.on_time}</div><div class="lbl">来得及</div></div>
      <div class="card"><div class="num">${d.no_date}</div><div class="lbl">缺交期信息</div></div>
    </div>`;
    h += renderEtaCards(d.by_material);
    $('eta-result').innerHTML = h;
  });
});
$('eta-kw').addEventListener('keydown', e => { if (e.key === 'Enter') $('btn-eta').click(); });

// ---------- 钣金欠料（箱体进度统计）----------
function loadSheetmetal() {
  API('/api/sheetmetal_overview').then(d => renderSheetmetalOverview(d));
  loadSheetmetalDetail();
}

function renderSheetmetalOverview(d) {
  $('sm-cards').innerHTML = `
    <div class="card"><div class="num">${d.total}</div><div class="lbl">条目总数</div></div>
    <div class="card"><div class="num">${d.total_qty}</div><div class="lbl">合计数量</div></div>
    <div class="card"><div class="num" style="color:#DC2626">${d.shortage}</div><div class="lbl">欠料条数</div></div>
    <div class="card"><div class="num" style="color:#DC2626">${d.shortage_qty}</div><div class="lbl">欠料数量</div></div>
    <div class="card"><div class="num" style="color:#16A34A">${d.arrived}</div><div class="lbl">已到货</div></div>`;
  $('sm-by-project').innerHTML = renderSmSplitRows(d.by_project, 'project');
  $('sm-by-category').innerHTML = smBarRows(d.by_category, 'category');
  $('sm-by-supplier').innerHTML = smBarRows(d.by_supplier, 'supplier');
  $('sm-by-batch').innerHTML = renderSmSplitRows(d.by_batch, 'batch');
}

function smBarRows(data, labelKey) {
  let arr;
  if (Array.isArray(data)) arr = data;
  else arr = Object.entries(data || {}).map(([k, v]) => ({ [labelKey]: k, count: v }));
  if (!arr.length) return '<p class="muted">无数据</p>';
  const max = Math.max(1, ...arr.map(x => x.count || 0));
  return arr.map(x => `<div class="bar-row"><div class="name">${esc(x[labelKey])}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, (x.count || 0) / max * 100)}%"></div></div>
    <div class="val">${x.count || 0}</div></div>`).join('');
}

function renderSmSplitRows(data, nameKey) {
  if (!data || !data.length) return '<p class="muted">无数据</p>';
  const max = Math.max(1, ...data.map(x => x.count || 0));
  return data.map(x => {
    const total = x.count || 0;
    const arr = x.arrived || 0;
    const sh = x.shortage || 0;
    const arrPct = total ? Math.min(100, arr / total * 100) : 0;
    const shPct = total ? Math.min(100, sh / total * 100) : 0;
    let timeLabel = '';
    if (x.remaining_days != null) {
      timeLabel = x.remaining_days >= 0
        ? `剩余 ${x.remaining_days} 天`
        : `逾期 ${Math.abs(x.remaining_days)} 天`;
    }
    return `<div class="bar-row">
      <div class="name">${esc(x[nameKey])}</div>
      <div class="bar-track">
        <div class="bar-stack">
          <div class="bar-fill-ok" style="width:${arrPct}%"></div>
          <div class="bar-fill-warn" style="width:${shPct}%"></div>
        </div>
      </div>
      <div class="sm-batch-val">
        已到 <b>${arr}</b> / 未到 <b style="color:#dc2626">${sh}</b>${timeLabel ? ' · ' + esc(timeLabel) : ''}
      </div>
    </div>`;
  }).join('');
}

let currentSmFilter = 'all';
function loadSheetmetalDetail() {
  const kw = $('sm-kw').value.trim();
  currentSmFilter = $('sm-filter').value;
  API('/api/sheetmetal_search', { kw }).then(d => {
    if (d.error) { $('sm-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    let items = d.items || [];
    if (currentSmFilter === 'shortage') items = items.filter(i => !i.arrived);
    else if (currentSmFilter === 'arrived') items = items.filter(i => i.arrived);
    const label = currentSmFilter === 'shortage' ? '仅欠料' : currentSmFilter === 'arrived' ? '仅已到货' : '全部';
    $('sm-result').innerHTML = `<p class="muted">命中 ${d.rows} 条，当前显示 ${items.length} 条（${label}）</p>` + renderSheetmetalTable(items);
  });
}

const SM_COLS = [
  { key: 'sheet', label: '来源表' }, { key: 'batch', label: '发货批次' },
  { key: 'drawing_batch', label: '图纸批次' }, { key: 'project', label: '项目' },
  { key: 'category', label: '设备类别' }, { key: 'supplier', label: '供应商' },
  { key: 'po_no', label: '采购单' }, { key: 'material_code', label: '物料编码' },
  { key: 'name', label: '名称' }, { key: 'spec', label: '规格' },
  { key: 'qty', label: '数量' }, { key: 'arrival', label: '到货情况', badge: true },
  { key: 'eta', label: '预计到货' }, { key: 'arrival_date', label: '实际到货' },
];

function renderSheetmetalTable(items) {
  if (!items || !items.length) return '<p class="muted">未找到数据</p>';
  const head = SM_COLS.map(c => `<th>${esc(c.label)}</th>`).join('');
  const body = items.map(r => '<tr>' + SM_COLS.map(c => {
    if (c.badge) {
      const arr = !!r.arrived;
      const txt = r[c.key] || (arr ? '已到货' : '未填');
      return `<td><span class="tag ${arr ? 'ok' : 'warn'}">${esc(txt)}</span></td>`;
    }
    return `<td>${esc(r[c.key])}</td>`;
  }).join('') + '</tr>').join('');
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

$('btn-sm-search').addEventListener('click', loadSheetmetalDetail);
$('sm-filter').addEventListener('change', loadSheetmetalDetail);
$('sm-kw').addEventListener('keydown', e => { if (e.key === 'Enter') loadSheetmetalDetail(); });

// 钣金同步
function triggerSmSync() {
  POST('/api/sheetmetal_sync').then(() => {
    $('sm-sync-info').textContent = '同步中…';
    pollSmSync();
  });
}
function pollSmSync() {
  const t = setInterval(() => {
    API('/api/sheetmetal_sync_status').then(d => {
      $('sm-sync-info').textContent = d.syncing ? '同步中…' : (d.error ? '失败：' + d.error : '完成 ✓');
      if (!d.syncing) {
        clearInterval(t);
        if (!d.error) loadSheetmetal();
      }
    });
  }, 1500);
}
$('btn-sm-sync').addEventListener('click', triggerSmSync);

// ---------- 同步 ----------
// 全局告警横幅：同步失败时在顶栏下方醒目提示，避免数据获取故障被静默掩盖
function updateAlertBar(d) {
  const bar = $('alert-bar');
  if (!bar) return;
  if (d.error) {
    bar.className = 'alert-bar show';
    bar.innerHTML = `<strong>⚠️ 数据同步失败，看板数据可能已过期</strong><span>${esc(d.error)}</span><button onclick="triggerSync()">立即重试</button>`;
  } else if (d.syncing) {
    bar.className = 'alert-bar show syncing';
    bar.innerHTML = `<strong>🔄 正在同步数据…</strong>`;
  } else {
    bar.className = 'alert-bar';
    bar.innerHTML = '';
  }
}
function refreshSyncInfo() {
  API('/api/sync_status').then(d => {
    const t = d.last_sync || '未同步';
    $('sync-info').textContent = '上次同步：' + t + (d.last_count ? `（${d.last_count} 条）` : '');
    if ($('page-sync') && !$('page-sync').classList.contains('hidden')) {
      $('sync-progress').textContent = d.syncing ? '同步中…' : (d.error ? '同步失败：' + d.error : '就绪');
    }
    updateAlertBar(d);
  });
}
function triggerSync() {
  POST('/api/sync').then(() => {
    $('sync-progress').textContent = '同步中…';
    pollSync();
  });
}
function pollSync() {
  const timer = setInterval(() => {
    API('/api/sync_status').then(d => {
      $('sync-info').textContent = '上次同步：' + (d.last_sync || '未同步') + (d.last_count ? `（${d.last_count} 条）` : '');
      $('sync-progress').textContent = d.syncing ? '同步中…' : (d.error ? '同步失败：' + d.error : '同步完成 ✓');
      updateAlertBar(d);
      if (!d.syncing) {
        clearInterval(timer);
        if (!d.error && $('page-overview') && !$('page-overview').classList.contains('hidden')) loadOverview();
      }
    });
  }, 1500);
}
$('btn-sync').addEventListener('click', triggerSync);
$('btn-sync-top').addEventListener('click', () => {
  // 切到同步页并触发
  document.querySelector('#sidebar li[data-page="sync"]').click();
  triggerSync();
});

// ---------- 设置 ----------
function loadSettings() {
  API('/api/settings').then(d => {
    const sheets = Object.entries(d.sheets || {}).map(([k, v]) => `${esc(k)}: ${v}`).join('<br>');
    const archived = (d.archived_sheets && d.archived_sheets.length)
      ? d.archived_sheets.map(esc).join('、')
      : '暂无';
    $('settings-content').innerHTML = `
      <p><b>数据源</b>：${esc(d.source)}</p>
      <p><b>本地数据库</b>：${esc(d.db_path)}</p>
      <p><b>状态过滤关键词（命中的条目不计入查询）</b>：<br>${d.resolved_keywords.map(esc).join('、')}</p>
      <p><b>已同步分表</b>：<br>${sheets || '暂无'}</p>
      <p><b>整表已归档（不计入任何统计）</b>：<br>${archived}</p>`;
  });
}

// ---------- 当前页自动刷新（准实时） ----------
function refreshCurrent() {
  if (currentPage === 'overview') return loadOverview();
  if (currentPage === 'sync') return refreshSyncInfo();
  if (currentPage === 'settings') return loadSettings();
  if (currentPage === 'sheetmetal') return loadSheetmetal();
  // 查询/汇总类页面：空 keyword 也自动重拉，保持默认汇总视图最新
  const qmap = {
    search:   ['search-kw',  'btn-search',   false],
    project:  ['project-kw', 'btn-project',  true],
    material: ['material-kw','btn-material', true],
    brand:    ['brand-kw',   'btn-brand',    true],
    eta:      ['eta-kw',     'btn-eta',      true],
  };
  const m = qmap[currentPage];
  if (!m) return;
  if (m[2] || $(m[0]).value.trim()) $(m[1]).click();
}

// ---------- 初始化 ----------
refreshSyncInfo();
// 每 15 秒检查同步状态：刷新状态文字；若数据库已更新则自动重拉当前页（准实时）
setInterval(() => {
  API('/api/sync_status').then(d => {
    $('sync-info').textContent = '上次同步：' + (d.last_sync || '未同步') + (d.last_count ? `（${d.last_count} 条）` : '');
    if ($('page-sync') && !$('page-sync').classList.contains('hidden')) {
      $('sync-progress').textContent = d.syncing ? '同步中…' : (d.error ? '同步失败：' + d.error : '就绪');
    }
    updateAlertBar(d);
    // 数据库已更新（且非首次进入）→ 自动重拉当前页，实现界面准实时
    if (d.last_sync && d.last_sync !== lastKnownSync) {
      if (lastKnownSync !== null) refreshCurrent();
      lastKnownSync = d.last_sync;
    }
  }).catch(() => {});
}, 15000);
loadOverview();
refreshSyncInfo();
