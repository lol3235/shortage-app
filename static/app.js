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

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

// ---------- 导航切换 ----------
document.querySelectorAll('#sidebar li').forEach(li => {
  li.addEventListener('click', () => {
    document.querySelectorAll('#sidebar li').forEach(x => x.classList.remove('active'));
    li.classList.add('active');
    const page = li.dataset.page;
    $('page-title').textContent = li.textContent;
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
    $('page-' + page).classList.remove('hidden');
    if (page === 'overview') loadOverview();
    if (page === 'settings') loadSettings();
    if (page === 'sync') refreshSyncInfo();
  });
});

// ---------- 总览 ----------
function loadOverview() {
  API('/api/overview').then(d => {
    $('cards').innerHTML = `
      <div class="card"><div class="num">${d.total}</div><div class="lbl">欠料条数</div></div>
      <div class="card"><div class="num">${d.total_qty}</div><div class="lbl">合计欠料数量</div></div>
      <div class="card"><div class="num">${d.urgent}</div><div class="lbl">紧急条目(空白/无交期/付款)</div></div>
      <div class="card"><div class="num">${d.sheets}</div><div class="lbl">已同步分表</div></div>`;
    const st = d.by_status || {};
    $('by-status').innerHTML = Object.keys(st).map(k =>
      `<div class="bar-row"><div class="name">${esc(k)}</div>
       <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, st[k] / (d.total||1) * 100)}%"></div></div>
       <div class="val">${st[k]}</div></div>`).join('') || '<p class="muted">无数据</p>';
    $('by-project').innerHTML = (d.by_project || []).map(p =>
      `<div class="bar-row"><div class="name" title="${esc(p.project)}">${esc(p.project)}</div>
       <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, p.count / (d.by_project[0]?.count||1) * 100)}%"></div></div>
       <div class="val">${p.count}</div></div>`).join('') || '<p class="muted">无数据</p>';
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
  { key: '预计到货时间', label: '预计到货' },
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
$('btn-project').addEventListener('click', () => {
  const kw = $('project-kw').value.trim();
  API('/api/project', { kw }).then(d => {
    if (d.error) { $('project-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    let h = `<p>共 <b>${d.rows}</b> 条，合计欠料 <b>${d.total_qty}</b></p>`;
    h += `<p class="muted">按紧急度：${Object.entries(d.by_status||{}).map(([k,v])=>`${k}:${v}`).join(' / ')||'—'}</p>`;
    h += '<h3 style="margin:12px 0 6px">按物料编码汇总</h3>';
    h += rowsTable(d.by_material.map(m => ({ mc: m.mc, name: m.name, qty: m.qty, status: Object.entries(m.status).map(([k,v])=>`${k}:${v}`).join('/') })),
      [{ key: 'mc', label: '物料编码' }, { key: 'name', label: '名称' }, { key: 'qty', label: '合计数量' }, { key: 'status', label: '紧急度' }]);
    $('project-result').innerHTML = h;
  });
});

// ---------- 物料汇总 ----------
$('btn-material').addEventListener('click', () => {
  const kw = $('material-kw').value.trim();
  API('/api/material', { kw }).then(d => {
    if (d.error) { $('material-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    let h = `<p>命中 <b>${d.rows}</b> 条，合计欠货 <b>${d.total_qty}</b></p>`;
    h += '<h3 style="margin:12px 0 6px">按物料编码汇总（跨项目加总）</h3>';
    h += rowsTable(d.by_material.map(m => ({ mc: m.mc, name: m.name, qty: m.qty, projects: m.projects, status: Object.entries(m.status).map(([k,v])=>`${k}:${v}`).join('/') })),
      [{ key: 'mc', label: '物料编码' }, { key: 'name', label: '名称' }, { key: 'qty', label: '合计数量' }, { key: 'projects', label: '项目数' }, { key: 'status', label: '紧急度' }]);
    h += '<h3 style="margin:12px 0 6px">按项目分布</h3>';
    h += rowsTable(d.by_project.map(p => ({ project: p.project, qty: p.qty, status: Object.entries(p.status).map(([k,v])=>`${k}:${v}`).join('/') })),
      [{ key: 'project', label: '项目' }, { key: 'qty', label: '合计数量' }, { key: 'status', label: '紧急度' }]);
    if (d.details && d.details.length) { h += '<h3 style="margin:12px 0 6px">明细 Top</h3>' + rowsTable(d.details, DETAIL_COLS); }
    $('material-result').innerHTML = h;
  });
});

// ---------- 品牌汇总 ----------
$('btn-brand').addEventListener('click', () => {
  const kw = $('brand-kw').value.trim();
  API('/api/brand', { kw }).then(d => {
    if (d.error) { $('brand-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    let h = `<p>该品牌命中 <b>${d.rows}</b> 条，合计欠货 <b>${d.total_qty}</b></p>`;
    h += '<h3 style="margin:12px 0 6px">按物料编码分布（跨项目加总）</h3>';
    h += rowsTable(d.by_material.map(m => ({ mc: m.mc, name: m.name, qty: m.qty, projects: m.projects, status: Object.entries(m.status).map(([k,v])=>`${k}:${v}`).join('/') })),
      [{ key: 'mc', label: '物料编码' }, { key: 'name', label: '名称' }, { key: 'qty', label: '合计数量' }, { key: 'projects', label: '项目数' }, { key: 'status', label: '紧急度' }]);
    h += '<h3 style="margin:12px 0 6px">按项目分布</h3>';
    h += rowsTable(d.by_project.map(p => ({ project: p.project, qty: p.qty, status: Object.entries(p.status).map(([k,v])=>`${k}:${v}`).join('/') })),
      [{ key: 'project', label: '项目' }, { key: 'qty', label: '合计数量' }, { key: 'status', label: '紧急度' }]);
    if (d.details && d.details.length) { h += '<h3 style="margin:12px 0 6px">明细 Top</h3>' + rowsTable(d.details, DETAIL_COLS); }
    $('brand-result').innerHTML = h;
  });
});

// ---------- 交期对比 ----------
$('btn-eta').addEventListener('click', () => {
  const kw = $('eta-kw').value.trim();
  API('/api/eta', { kw }).then(d => {
    if (d.error) { $('eta-result').innerHTML = `<p class="error">${esc(d.error)}</p>`; return; }
    let h = `<p>共 <b>${d.rows}</b> 条，其中 <b style="color:#b91c1c">${d.late}</b> 条存在交期风险</p>`;
    h += rowsTable(d.results.map(r => ({
      项目: r.项目, 物料编码: r.物料编码, 物料名称: r.物料名称,
      预计: r.预计, 期望: r.期望,
      判定: r.判定 === '来不及' ? `<span class="tag warn">⚠️ 来不及${r.相差天!=null?'('+r.相差天+'天)':''}</span>`
            : (r.判定 === '来得及' ? `<span class="tag ok">✅ 来得及</span>` : `<span class="tag muted">${esc(r.判定)}</span>`),
    })), [
      { key: '项目', label: '项目' }, { key: '物料编码', label: '物料编码' }, { key: '物料名称', label: '物料名称' },
      { key: '预计', label: '预计交期' }, { key: '期望', label: '期望交期' }, { key: '判定', label: '判定' },
    ]);
    $('eta-result').innerHTML = h;
  });
});

// ---------- 同步 ----------
function refreshSyncInfo() {
  API('/api/sync_status').then(d => {
    const t = d.last_sync || '未同步';
    $('sync-info').textContent = '上次同步：' + t + (d.last_count ? `（${d.last_count} 条）` : '');
    if ($('page-sync') && !$('page-sync').classList.contains('hidden')) {
      $('sync-progress').textContent = d.syncing ? '同步中…' : (d.error ? '同步失败：' + d.error : '就绪');
    }
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
    $('settings-content').innerHTML = `
      <p><b>数据源</b>：${esc(d.source)}</p>
      <p><b>本地数据库</b>：${esc(d.db_path)}</p>
      <p><b>状态过滤关键词（命中的条目不计入查询）</b>：<br>${d.resolved_keywords.map(esc).join('、')}</p>
      <p><b>已同步分表</b>：<br>${sheets || '暂无'}</p>`;
  });
}

// ---------- 初始化 ----------
refreshSyncInfo();
setInterval(refreshSyncInfo, 30000);
loadOverview();
