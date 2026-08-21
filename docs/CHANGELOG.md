# 欠料看板（shortage_app）变更日志 CHANGELOG

> 记录所有**人工功能 / 修复 / 部署**提交。自动数据同步产生的 `sync: update seed.sql ...` 提交不列入（由 app.py 后台周期推送，仅时间戳，易刷屏）。
> 仓库：github.com/lol3235/shortage-app ｜ 线上：https://shortage-app.onrender.com/

---

## v1.6.8 · 2026-08-21 · 修复自动同步推送失败后meta签名永久失效的bug

| 提交 | 类型 | 说明 |
|---|---|---|
| Bug修复 | 后端 | **`_auto_sync_loop` 推送逻辑重构**：原代码在调用 `_export_and_check_seed()` 时立即写入 meta 签名，若后续 git push 失败，meta 已被更新，导致后续循环永远认为"数据未变化"而跳过推送，形成永久失效。新逻辑：`_export_and_check_seed` 只计算签名不写 meta；推送成功后才写入 meta；推送失败时保留旧签名，下轮继续尝试 |
| Bug修复 | 后端 | `_git_push_seed` 改为返回 `True/False`， caller 据此决定是否更新 meta |
| 验证 | 部署 | Render 自动恢复最新数据（commit 5ef0150，last_sync=17:35:59，last_count=290），本地自动同步循环持续正常运行 |

---

## v1.6.7 · 2026-08-21 · 品牌汇总新增「型号」列

| 提交 | 类型 | 说明 |
|---|---|---|
| 功能 | UI | **品牌汇总单品牌详情页增加「型号」列**——在「按物料编码分布（跨项目加总）」表格中，原只有「物料编码 / 名称 / 合计数量 / 项目数 / 紧急度 / 来源表」，现新增「型号」列（来源字段：`规格说明`），位于「名称」与「合计数量」之间，便于同一物料编码对应不同型号时快速区分 |
| 改进 | 数据 | `logic.brand_summary` 的 `by_material` 聚合结果新增 `model` 字段，前端 `static/app.js` 同步渲染该列；向后兼容，现有测试与 API 不变 |

---

## v1.6.6 · 2026-08-21 · 部署形态扩展：腾讯云轻量应用服务器自托管（规划/部分就绪）

| 提交 | 类型 | 说明 |
|---|---|---|
| 部署 | 决策 | 新增第三种运行形态候选：**腾讯云轻量应用服务器（Lighthouse）自托管**。地域 ap-beijing，实例 `lhins-pgehtw8y`，2C2G/50G SSD/4Mbps，系统 **OpenCloudOS 9.6 + 宝塔Linux面板**（镜像 `lhbp-0x9mfhxs`）。经评估**放弃换成 Ubuntu** 的方案——Ubuntu 不带来功能增益且会丢失宝塔面板的可视化运维便利（本项目不想天天敲命令），故维持现镜像、仅补装 Node.js |
| 部署 | 环境 | 在该实例通过 dnf 官方源安装 **Node.js 20 LTS**（`nodejs-20-1.oc9`，含 npm 10.8.2，路径 `/usr/bin/node`、`/usr/bin/npm`），补齐 wecom-cli / kdocs-cli 的运行前提 |
| 文档 | PRD/CHANGELOG | PRD §9.1 新增「自托管」形态说明（规划中），§9.2 补充「服务器自身即同步源」架构要点；本文档升 v1.6.6 |

### 状态与后续
- **当前进度**：服务器已开通、系统定型、Node 已装。**尚未部署应用代码、未安装 wecom-cli/kdocs-cli、未登录 CLI、未配 systemd/nginx。**
- **自托管相对 Render 的核心优势**：服务器装好两套 CLI 并登录后，云端即可**真正在线同步**（不再依赖本地电脑常开 + `seed.sql` 推送触发重部署）；数据落在用户自己的腾讯云账号，且可加 HTTPS / 自定义域名 / IP 白名单。
- **阻塞项**：`wecom-cli init` 与 `kdocs-cli auth login` 为交互式（扫码/浏览器），必须由用户在服务器终端完成，助手无法代登。

---

## v1.6.5 · 2026-08-20 · 修复同步失败：失效代理清理 + Render 跨平台兼容 + 子表列表重试

| 提交 | 类型 | 说明 |
|---|---|---|
| 修复 | 环境兼容 | **自动清理失效代理环境变量** —— 新增 `sync._clean_env_for_subprocess()`，调用 wecom-cli / kdocs-cli / git 前检测 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 指向的端口是否可连；若代理已死（常见如 `127.0.0.1:7897` 遗留环境变量），自动剔除这些变量再执行外部命令。一次性解决「因本地残留代理设置导致 wecom-cli 连企微被拒绝、git push 连 GitHub 失败」的问题 |
| 修复 | 跨平台 | **彻底解决 Render(Linux) 上 `creationflags is only supported on Windows platforms` 报错** —— `sync.py`、钣金 `sync_sheetmetal.py`、`app.py` 的 git 调用全部改为仅在 `sys.platform == "win32"` 时传 `CREATE_NO_WINDOW`，非 Windows 平台不再硬编码 `creationflags`，从源头消除平台差异导致的同步崩溃 |
| 改进 | 同步 | **增强 `_list_sheets` 重试**：子表列表接口同样加入 3 次退避重试（2s/4s/8s），并把 `fetch_markdown` 默认整体重试次数提到 3 次、子表间隔提到 2.0s，进一步降低偶发限流导致同步失败的概率 |
| 改进 | 同步 | **云端友好降级**：`sync.can_sync_online()` 公共函数判断当前是否具备在线同步能力（本地 wecom-cli 或企微 API 凭证）。`sync_to_db()` 与 `app.do_sync()` 在无法在线同步时直接返回可读中文提示，告知用户「当前为 seed.sql 快照模式，需本地 Windows app 自动同步或配置 WECOM_API 凭证」，不再弹出技术性英文报错 |
| 改进 | UI | `api_sync_status` 新增 `syncable` 字段；前端告警横幅在 `syncable=false` 时隐藏「立即重试」按钮，并附加「当前为快照模式」提示，避免用户在云端反复点击重试 |

### 根因说明（本次截图错误的真实原因）
- 表面上看是 `creationflags is only supported on Windows platforms`，说明请求落在了 Render（Linux）云端；但本地也曾频繁出现 `rc=1` 同步失败。
- 深入排查后发现：`rc=1` 并非企微频率限制，而是 wecom-cli 尝试通过环境变量里的 `HTTP_PROXY/HTTPS_PROXY=127.0.0.1:7897` 连接企微 API，但该代理端口并未运行 → `ConnectionRefused`。
- 同一批失效代理环境变量也导致 git push 到 GitHub 失败（`Failed to connect to github.com over proxy`）。
- 修复后：调用任何外部命令前都会自动清理不可用的代理变量；本地 Windows 仍隐藏黑窗；云端 Render 会给出明确提示，数据继续用本地 app 推送的 `seed.sql` 快照。

---

## v1.6.4 · 2026-08-20 · 新增「整表归档」规则：分表末尾标注已归档则整表不统计

| 提交 | 类型 | 说明 |
|---|---|---|
| 功能 | 统计 | **整表归档规则** —— 沿用「逐行标注已归档不统计」的思路，新增：某张分表（子表）末尾出现「已归档」页脚行时，该分表**所有行**统一改写为状态「已归档」，由既有 `filter_active` 在查询期统一排除，**整表不参与任何汇总/查询/本周新增**。与逐行归档走同一套过滤链路，行为一致、可逆（去掉页脚即恢复统计） |
| 功能 | 透明化 | 同步时把检测到的「整表归档」分表名持久化到 `meta.archived_sheets`，`/api/sync_status` 与 `/api/settings` 返回，`设置` 页新增「整表已归档（不计入任何统计）」清单，便于核对规则是否误触发 |
| 改进 | 解析 | `_csv_to_markdown` 改为返回 `(markdown, archived)` 元组；新增 `_sheet_is_archived` 检测器：仅扫描表尾 15 行、**物料编码列无效**且文本含「已归档」的页脚行才命中，避免把「逐行标注已归档」的正常数据行或含「已归档」字样的备注误判为整表归档 |
| 测试 | 回归 | 新增 `tests/test_archive.py`（4 例）：整表归档检测+标记、无页脚不触发、逐行归档不触发整表、页脚含有效物料编码不误触；`run_tests.py` 默认纳入该模块 |

### 使用方式
- **逐行归档（原规则）**：在物料行的「状态」列写「已归档」。
- **整表归档（新规则）**：在分表**末尾单独加一行**，在该行的任意单元格写「已归档」（无物料编码），整张分表即被排除。
- 规则集中在 `sync.py:_sheet_is_archived` / `_csv_to_markdown`，过滤集中在 `logic.filter_active`。

---

## v1.6.3 · 2026-08-19 · UI 全面毛玻璃化：背景光斑 + 切换过渡 + 高级感视觉

| 提交 | 类型 | 说明 |
|---|---|---|
| 优化 | UI | **整站毛玻璃 Glassmorphism 改造** —— 侧栏、顶栏、卡片、面板、输入框、表格、徽章全部加 `backdrop-filter: blur(20px) saturate(170%)` + 半透明白背景 + 细白边；背景从纯灰改为「浅色品牌渐变 + 4 个浮动光斑」（青绿/黄绿大圆 blur 90px 慢速浮动 26-44s） |
| 优化 | 动画 | **页面切换过渡** —— 抽 `showPage(page, title)` 统一处理导航/跳转项目/初始化三处切换；新页面入场动画 `pageIn`（0.34s cubic-bezier）：opacity 0→1 + translateY 16→0 + scale 0.985→1 + blur 2→0 同步缓动 |
| 优化 | UI | 按钮升级为胶囊形 + 渐变背景 + hover 上浮阴影；卡片 hover 强化（translateY -3px + 双层阴影 + 白边亮起）；侧栏菜单 hover 右移 3px + active 渐变高亮；告警条 slide-down 入场；滚动条改为青绿主题 |
| 优化 | UI | 兼容兜底：`@supports not (backdrop-filter)` 时用 0.92 不透明白背景，不支持毛玻璃的浏览器照样可读 |
| 修复 | UI | init 启动时主动调一次 `refreshSyncInfo()`，避免首次进入非 sync 页面时右上角「—」（之前要等 15s 定时器首次触发） |
| 文档 | PRD/CHANGELOG | PRD §2.3 VI 小节追加毛玻璃设计规则；CHANGELOG 升 v1.6.3 |

### 背景光斑设计
- 4 个 `.bg-blob` 装饰元素（fixed 定位 + blur 90px）：
  - `#6FE0E1→#23BABB` 青绿光斑（左上 480×480，26s 浮动）
  - `#D9E96B→#C1D52D` 黄绿光斑（右下 420×420，32s 浮动）
  - 中央青绿小光斑 + 右上黄绿小光斑（错开节奏 38s/44s）
- 这些是毛玻璃「视觉底」——有光斑 + 半透明 + blur 才能看出玻璃感

### 切换动画
- 0.34s `cubic-bezier(0.22, 1, 0.36, 1)`（标准 Material iOS 风格）
- 同时启动 opacity / translateY / scale / filter 四个属性
- 强制 `offsetWidth` reflow 保证每次重新触发
- 防止残留：切换前清掉所有 `.page` 的 `.page-enter` class

**截图验证**：4 个页面（总览 / 钣金）毛玻璃效果均生效，光斑透出，侧栏深色毛玻璃 + 菜单 active 渐变高亮 + 卡片悬浮阴影都正常。提交 `7b14bdb` 已推 main，Render 自动重部署。

---

## v1.6.2 · 2026-08-19 · 同步 API 迁移至新版 wecom-cli sheet（修复 rc=2 接口不存在）

| 提交 | 类型 | 说明 |
|---|---|---|
| 修复 | 同步 | **紧急修复 wecom-cli 升级后断同步** —— `doc get_doc_content` 旧接口废弃（rc=2 该接口不存在），整个看板停滞在 2026-08-19 15:09 的旧数据；改用新版 `sheet get` 列出子表 + `sheet ranges get --mode csv` 同步拉取每个子表，新接口同步返回数据无需 task_id 轮询 |
| 修复 | 解析 | 用 Python `csv` 标准模块解析带引号字段（旧版 `split(",")` 错误拆分 `"1/4""NPT螺纹,..."` 这种含逗号引号字段，导致 物料名称 列错位） |
| 修复 | 解析 | 修复 wecom-cli 0810 子表「下行走漏」bug：处理状态列出现 9 位项目编码（260xxxxxx）是下一行项目编码漏到本行，自动拆分两行（数据从 656 恢复到 1042 条） |
| 修复 | 解析 | 移除 `COL_ALIASES` 中「备注」对「状态」的别名（巨茂第四批「备注」列被误判为「状态」，导致 17 条 备注 文字被错填进 状态 字段） |
| 改进 | 同步 | `_fetch_sheet_csv` 单子表内置 3 次重试（2s/4s/8s 退避），应对偶发频率限制 rc=1 |
| 改进 | 同步 | `fetch_markdown` 子表间 1.5s 间隔 + 单子表失败不阻断整体（保证最差也有 ~94% 数据），整体 2 次重试 |
| 改进 | 同步 | `_csv_to_markdown` 真实列数 = 表头非空 cell 数（处理 0810 类「表头后段全空 14 列但实际 24 列」sheet） |
| 清理 | 代码 | 删除废弃的 `_start_task` / `_poll_task` / `_decode_doc_reply`（旧 doc get_doc_content 异步轮询链路已不再使用） |
| 文档 | 更新 | PRD/CHANGELOG 当前 v1.6.2 |

---

## v1.6.1 · 2026-08-19 · 壹月科技 VI 重构：品牌色 + LOGO 上墙

| 提交 | 类型 | 说明 |
|---|---|---|
| 视觉 | 改版 | 应用壹月科技官方 LOGO + 品牌色（青绿 `#23BABB` + 黄绿 `#C1D52D`），侧栏加 LOGO 白底卡片 + 品牌副标题、侧栏渐变背景 + 黄绿装饰条、指标卡顶条颜色、徽章色板、按钮主色、表格/进度/告警配色全部统一为品牌色 |
| 视觉 | 改进 | 整体提升卡片阴影、悬停动效、面板标题前的小色条、表格悬停态、徽章增加 `info` / `accent` 两个新色 |
| 视觉 | 新增 | 顶栏「欠料看板」标题前加品牌色装饰条；侧栏底部「本地运行」状态指示灯（带脉动动画）；顶栏底部和 body 顶部加品牌色细线 |
| 视觉 | 新增 | 「本周新增材料采购及时率」卡片采用黄绿强调色（`card-accent`）以与基础指标卡区分 |
| 视觉 | 响应式 | 屏幕 < 720px 时侧栏自动收起为 64px 图标条 |
| 行为 | 改进 | 页面初始化改为按 HTML 初始 `active` 菜单加载对应页面（之前总是默认总览页） |
| 文件 | 新增 | `static/logo.png` 壹月科技 LOGO（PNG）；`static/favicon.png` 浏览器标签图标 |
| 文档 | 更新 | PRD/CHANGELOG 当前 v1.6.1 |

---

## v1.6.0 · 2026-08-19 · 同步故障诊断与告警（修复企微授权过期静默失败）

| 提交 | 类型 | 说明 |
|---|---|---|
| `sync.py` | fix | 新增 `_decode_doc_reply()`：解析 `get_doc_content` 返回，遇 `errcode`（如 851014 授权过期 / 851008 无读取权限）抛出含 errcode+errmsg+帮助指引的清晰异常，替代原先隐晦的 `KeyError('task_id')` |
| `static/app.js` | ui | 新增全局告警横幅 `updateAlertBar()`：同步失败时在顶栏下方醒目红条提示「数据同步失败，看板数据可能已过期」并附「立即重试」按钮；同步中显示蓝色提示 |
| `static/index.html` | ui | 顶栏下方新增 `#alert-bar` 告警横幅容器 |
| `static/style.css` | ui | 新增 `.alert-bar` 样式（失败红 / 同步中蓝） |

**本期核心变化**：修复「企微机器人文档权限过期」导致的同步静默失败——原先 wecom-cli 返回 rc=0 但内容为 errcode 错误，被误解析成 `KeyError('task_id')`，前端无任何提示。现改为：错误信息完整透明（含授权指引链接），并加全局告警横幅，任何影响数据获取的故障都会在看板顶部醒目提示，不再静默掩盖。

---

## v1.5.9 · 2026-08-19 · 总览新增本周新增材料采购及时率卡片

| 提交 | 类型 | 说明 |
|---|---|---|
| `db.py` | feat | 新增 `sync_snapshot` 与 `weekly_new_items` 表；新增 `_item_key`、`get_last_snapshot`、`save_snapshot`、`record_weekly_new_items`、`get_weekly_new_items`、`clean_old_weekly_items` |
| `sync.py` | feat | `sync_to_db` 同步完成后与上次快照对比，识别真正新增的（项目编码+物料编码）组合并写入 `weekly_new_items`；保存本次快照并清理过期记录 |
| `logic.py` | feat | 新增 `weekly_punctuality_rate()`：读取本周新增条目，按状态含“已到货/已解决/已完成”计算采购及时率；`overview()` 返回 `weekly_rate` 字段 |
| `static/app.js` | ui | 总览指标卡由 4 张扩展为 5 张，新增“本周新增材料采购及时率”卡片，显示百分比、颜色分档（≥80%绿 / 60-80%橙 / <60%红）及“及时 X/Y” |
| `docs/PRD.md` | docs | PRD 升 v1.5.9，§3.1 更新 5 张指标卡及本周新增采购及时率口径 |

**本期核心变化**：总览新增第 5 张指标卡“本周新增的材料采购及时率”。通过同步快照diff识别真正新增条目，避免把旧数据重复刷新误判为新增；以“已到货/已解决”状态判定采购是否及时。

---

## v1.5.8 · 2026-08-19 · 汇总面板默认展示全部，搜索框再过滤

| 提交 | 类型 | 说明 |
|---|---|---|
| `logic.py` | feat | `project_summary`/`material_summary`/`brand_summary`/`eta_check` 支持 keyword 为空：分别返回「全部项目汇总」「全部物料汇总」「全部品牌汇总」「全部欠料交期对比」，新增 `mode` 字段区分默认/搜索视图 |
| `logic.py` | fix | `_parse_date()` 增加日期合法性校验，避免无效日期（如 2 月 30 日）进入 `datetime.date()` 抛出 `ValueError` |
| `static/app.js` | ux | 切换到项目/物料/品牌/交期页面时，若搜索框为空则自动加载默认全部数据；汇总渲染根据 `mode` 切换默认列表/搜索明细；四个搜索框均支持回车触发 |
| `static/index.html` | ux | 四个搜索框 placeholder 改为「留空=全部…；输入过滤…」 |
| `docs/PRD.md` | docs | PRD 升 v1.5.8，§3.3–3.6 更新默认展示全部汇总的说明 |

**本期核心变化**：「项目汇总 / 物料汇总 / 品牌汇总 / 交期对比」点开后不再光秃秃，立即展示全部汇总；需要精确定位时再用上方搜索框过滤，搜索结果会替换默认视图。

---

## v1.5.7 · 2026-08-19 · 交期对比面板可视化（按物料编码聚合）

| 提交 | 类型 | 说明 |
|---|---|---|
| `逻辑.py` | feat | `eta_check` 增加日期解析结果（`预计日期`、`期望日期`、`预计剩余天`、`期望剩余天`）并按 `物料编码` 聚合，返回 `by_material` 分组（含各项目明细、逾期/来得及/缺交期统计、涉及项目列表） |
| `static/app.js` | ui | 交期对比改卡片式渲染：`renderEtaCards` + `renderEtaTimeline`，顶部指标卡展示匹配条数/逾期风险/来得及/缺交期信息；每张物料卡片内用时间轴展示需求交期（橙）vs 实际预计到货（蓝），灰色竖线=今天，红/绿段表示逾期缺口或提前余量 |
| `static/style.css` | ui | 新增 `.eta-cards`、`.eta-card`、`.eta-track`、`.eta-marker`、`.eta-gap`、`.eta-legend` 等样式 |
| `docs/PRD.md` | docs | PRD 升 v1.5.7，§3.6 更新交期对比可视化说明 |

**本期核心变化**：「交期对比」不再只有光秃秃的六列表格，改为按物料编码聚合的卡片 + 时间轴可视化，需求交期与实际预计到货、剩余/逾期天数一目了然。

---

## v1.5.6 · 2026-08-19 · 钣金项目分布按预计到货显示剩余/逾期天数

| 提交 | 类型 | 说明 |
|---|---|---|
| `02aecf2` | feat | `sheetmetal_overview` 的 `by_project` 每条新增 `arrived` / `shortage` / `remaining_days`（按该项目未到货条目中「预计到货(ETA)」最早日期计算剩余天数，负值=逾期；全部到货返回 None）。前端项目分布面板改用与批次分布相同的拆分条渲染（绿=已到货、红=未到货 + 剩余/逾期天数标签）；面板下方加一行说明口径 |
| `logic.py` | 新增 `_sheetmetal_project_stats()` 辅助函数；`renderSmBatchRows(data)` 重构为通用 `renderSmSplitRows(data, nameKey)`，批次与项目面板共用 |

**本期核心变化**：除巨茂（按批次交期）外的所有项目，也能直接看到"距预计到货还剩/已逾期多少天"，欠料跟进视角拉齐。巨茂在项目面板按 ETA 显示（与批次面板按批次交期不同口径，已在面板说明）。

---

## v1.5.5 · 2026-08-19 · 钣金发货批次无欠料时不显示剩余/逾期时间

| 提交 | 类型 | 说明 |
|---|---|---|
| `c409af2` | fix | `sheetmetal_overview` 的 `by_batch.remaining_days` 仅在该批次存在未到货条目（`shortage > 0`）时才计算和返回；否则返回 `None`。前端接收到 `None` 即不显示「剩余/逾期 X 天」，避免「已到 27 / 未到 0 · 逾期 27 天」这类歧义展示 |

**本期核心变化**：批次已全部到货时不再显示逾期天数，界面只保留「已到 X / 未到 0」和绿色完成条。

---

## v1.5.4 · 2026-08-19 · 钣金发货批次剩余时间改为按批次交期计算

| 提交 | 类型 | 说明 |
|---|---|---|
| `dc28d9e` | fix | `sheetmetal_overview` 的 `by_batch.remaining_days` 改为**按批次名（批次交期，如 10.4 / 9.20）解析日期**计算剩余天数；原 ETA 仅作 fallback（当批次名无法解析为日期时）。已到货条目不计入剩余时间（提前交货不在批次倒计时中显示） |

**本期核心变化**：批次倒计时口径对齐业务真实含义——批次名即交期，剩余时间 = 批次交期 − 今天（逾期为负，但该类批次当前均已到货故不显示）。此前按 ETA 计算会因"可提前交货"导致倒计时失真。

---

## v1.5.3 · 2026-08-19 · 钣金发货批次分布显示到货状态与剩余时间

| 提交 | 类型 | 说明 |
|---|---|---|
| `8646ab7` | feat | `logic.py` 新增 `_parse_eta_days()` 解析 ETA 文本（M.D / M/D / M月D日 / XX天内）为距离今天的天数；`sheetmetal_overview` 的 `by_batch` 每条增加 `arrived`、`shortage`、`remaining_days`，按批次聚合已到货/未到货数量与最短剩余时间 |
| `8646ab7` | feat | 前端 `static/app.js` 发货批次分布改专用 `renderSmBatchRows()`：绿色段=已到货、红色段=未到货，右侧文字显示「已到 X / 未到 Y · 剩余/逾期 Z 天」 |
| `8646ab7` | ui | `static/style.css` 新增 `.bar-stack`、`.bar-fill-ok`、`.bar-fill-warn`、`.sm-batch-val` 样式 |
| `8646ab7` | docs | PRD §3.9 更新发货批次分布说明 |

**本期核心变化**：发货批次分布不再只显示总数，而是直观拆分已到货（绿）/ 未到货（红），并对未到货批次给出剩余需求时间，方便识别哪些批次还赶得上、哪些已经逾期。

---

## v1.5.2 · 2026-08-19 · 钣金模块数据口径对齐（按项目分布）

| 提交 | 类型 | 说明 |
|---|---|---|
| `3cb10bb` | fix | `sync_sheetmetal.py`：批次 `batch` 改映射「壹月发货批次」列（即发货批次表头，值如 8.20/10.4/9.20/7.23/6.30）；原「图纸批次」列保留为独立字段 `drawing_batch`；合计行跳过改用品名/物料判断，避免列错位漏判 |
| `3cb10bb` | fix | `db.py`：`sheetmetal_items` 新增 `drawing_batch` 列（schema + SHEETMETAL_FIELDS），seed 同步带该列 |
| `3cb10bb` | fix | `logic.sheetmetal_overview`：移除 `by_sheet` / `sheets`（不再按分表统计），新增 `by_project`（按项目名称聚合，巨茂为其中之一）；供应商分布保持整表聚合 |
| `3cb10bb` | fix | 前端 `static/app.js` / `index.html`：移除「分表数」卡片与「分表分布」面板，改「项目分布」面板；批次列标签改「发货批次」、新增「图纸批次」列、移除「备注」列；面板标题修正（设备类别分布 / 供应商分布（整表聚合）/ 发货批次分布（仅巨茂）） |
| `3cb10bb` | docs | PRD §3.9 更新字段与分布口径说明 |

**本期核心变化**：明确钣金模块数据模型——批次仅巨茂有且取「发货批次」表头；两个分表统一以「项目名称」为区分维度（巨茂只是其中一个项目），界面不再单独统计分表，改为按项目分布；供应商分布跨所有项目聚合。

---

## v1.5.1 · 2026-08-19 · 钣金模块修复

| 提交 | 类型 | 说明 |
|---|---|---|
| `cfc34fc` | fix | `app.py` 启动时显式调用 `db.init_sheetmetal_db()`，避免 `sheetmetal.db` 为空/重建时表结构缺失导致 `no such table: sheetmetal_items` |
| `cfc34fc` | fix | `sync_sheetmetal.py` 修正巨茂分表列布局：从旧 11 列更新为当前 13 列（新增项目名称、供应商，列索引整体错位），恢复 194 条巨茂数据解析；同步增加事务保护，任一明细分表解析为空时整体抛异常、不覆盖旧数据 |
| `cfc34fc` | fix | `app.py` / `sync_sheetmetal.py` 子进程调用统一加 `encoding="utf-8", errors="replace"`，避免中文 Windows 默认 GBK 解码失败导致同步子进程 stdout 为 None |
| `cfc34fc` | docs | PRD §3.9 更新巨茂/非巨茂分表列数与字段说明 |

---

## v1.5 · 2026-08-18 · 新增钣金欠料独立模块

| 提交 | 类型 | 说明 |
|---|---|---|
| `bf35c65` | feat | 新增「钣金欠料」独立模块：接入金山文档「箱体进度统计」表（kdocs file_id `HeqbtFcx3rMqYYFRpA9n1xZrPzbTeaL4X`），与企微主线平行，独立数据库 `data/sheetmetal.db` + 快照 `data/seed_sheetmetal.sql` |
| `bf35c65` | feat | 数据层 `db.py` 新增 `sheetmetal_items` / `meta_sheetmetal` 表及 upsert / get_all / get_meta / export_sheetmetal_seed_sql；`sync_sheetmetal.py` 经 `kdocs-cli` 拉取两个明细分表（巨茂 `5A-巨茂箱体进度8.17` / 非巨茂 `箱体进度统计（非巨茂）`）归一化入库；`_bootstrap_sheetmetal.py` 支持一键初始化 |
| `bf35c65` | feat | 聚合 `logic.sheetmetal_overview` / `sheetmetal_search` / `sheetmetal_is_arrived`；`app.py` 新增 `/api/sheetmetal_*` 四路由 + 钣金同步线程；前端 `static/` 新增「钣金欠料」导航页（指标卡 + 分表/类别/供应商/批次分布 + 模糊查询/筛选 + 同步按钮） |
| `bf35c65` | docs | PRD 升 v1.5，新增 §3.9「钣金欠料」章节；本 CHANGELOG 补 v1.5 条目 |

**本期核心变化**：在既有企微欠料主线之外，新增一条**独立数据源**（金山文档箱体进度统计）的欠料跟踪模块，沿用「独立 DB + 独立 seed + 自动同步 + 双形态部署」架构；到货判定以「到货情况」文本为准（含「已到货」即视为到货），未引入结构化状态列。

---

## v1.3 · 2026-08-12 · 在线表写回（方案 B）

| 提交 | 类型 | 说明 |
|---|---|---|
| `66fde6d` | feat | 标记到货时**回写企业微信在线表**状态列：`sync.py` 封装 `sheet_get_info`/`sheet_update_range_data`；新增 `writeback.py`（`plan_online_write` 只读定位 + `apply_online_write` 写入，含单表连续/无断层/唯一命中/坐标界内/状态列存在 多重安全闸）；前端加确认弹窗预览将改哪些子表/行/旧值→新值 |
| `66fde6d` | docs | PRD 升 v1.3，新增 §10「在线表写回」，说明权限要求（智能机器人需在线表【编辑】权限，否则 `851003 no authority`）与已知限制 |

**本期核心变化**：确认到货不再只在本地看板生效，可一键同步改写在线表对应单元格；写前强制预览确认，最大限度避免误改生产数据。当前实测写入被权限拦截（`851003`），需先在企业微信给智能机器人授予该在线表编辑权限后方可生效。

---

## v1.4 · 2026-08-13 · 彻底删除人工到货/解决层与在线表写回

| 提交 | 类型 | 说明 |
|---|---|---|
| `5db3b66` | refactor | 废弃方案 B（网页端写回企业微信在线表）：`app.py` 移除 `import writeback` 及 `preview`/`write_online` 分支，`/api/resolve`、`/api/resolve_text` 仅做本地覆盖；前端确认弹窗改为「确认到货（本地标记）」，明确提示原始在线表需手动修改；`writeback.py` 标注废弃保留 |
| `5db3b66` | docs | PRD §10 改为「已废弃」并说明根因（10 人以上企业模式机器人仅能编辑自己创建的文档，欠料表为成员创建，写入恒报 851003）；同步 CHANGELOG |
| 0399d9c | refactor | 彻底删除「确认到货」「快速到货登记」入口及后端 `/api/resolve`、`/api/resolve_text`、`/api/overrides`；移除 `manual_overrides` 表、`manual_status` 列、`writeback.py`、`logic.resolve_text`、sync.py 写回封装；项目汇总表格去掉「操作」列 |
| 0399d9c | docs | PRD §3.3 / §4 / §10 更新为「已删除」；CHANGELOG 更新 |

**本期核心变化**：因企业微信平台限制，网页端无法改写成员创建的原始在线表；在无法写回原始表的情况下，单独的本地标记/隐藏功能对用户无意义。经用户确认，彻底删除人工到货/解决层与在线表写回能力，恢复为纯只读看板；如需隐藏某行，请直接修改企业微信在线表的状态列，下次同步后自动过滤。

---

## v1.2 · 2026-08-12 · 本地人工到货/解决层

| 提交 | 类型 | 说明 |
|---|---|---|
| `152ad62` | feat | 增加本地人工到货/解决层：项目汇总每行「确认到货」按钮 + 顶部「快速到货登记」文本框；后端新增 `/api/resolve`、`/api/resolve_text`、`/api/overrides` 及 `manual_overrides` 表 |

**本期核心变化**：用户可直接在看板内标记某项目某物料已到货/已解决，标记后看板自动剔除；覆盖记录随 `seed.sql` 同步到云端，不会被后续企微同步刷回。

---

## v1.1 · 2026-08-12 · 数据源重构 + 运行健壮性修复

| 提交 | 类型 | 说明 |
|---|---|---|
| `a7e358a` | feat | 可插拔数据源：企微开放 API 优先 + wecom-cli 回退，支持云端直连企微；禁用旧 ShortageBot 自启 |
| `8739154` | chore | `.gitignore` 忽略 `.backup/`、`.workbuddy/` 等本地与助手元数据，避免误提交 |
| `bf9c80c` | fix | 云端看板显示「上次同步时间」：seed.sql 携带 `meta.last_sync/last_count`，启动兜底修复旧实例 |
| `3eeb944` | fix | 修复 pythonw 进程找不到 git.exe 导致 seed.sql 推送失败（云端/本地数据不一致） |
| `2741027` | fix | 修复本地弹黑窗（git remote set-url 补 `CREATE_NO_WINDOW`）；单实例锁改用 `Global\` 命名互斥体防重复实例 |
| `33ae048` | fix | 修复巨茂批次分表表头错位：双「项目编码」列导致项目名误映射为领用车间 |
| `983ed8a` | fix | 列映射增加「项目名称」别名，适配用户规范后的在线表表头 |
| `523a2ab` | feat | 项目汇总「按物料编码汇总」表格增加「品牌」列，取该编码下最 frequent 品牌 |
| `aded4d6` | fix | 解析纵向合并单元格：对 项目编码/项目/单据编号/申请部门/单据日期/期望交期/预计到货时间 做前向填充，日期类字段限制在同一单据编号内，避免跨单据污染 |
| `a777c75` | feat | 首页「项目欠料 TOP10」项目名称改为可点击链接，点击后切到「项目汇总」并自动带入该项目 |

**本期核心变化**：本地 APP 由「单机」演进为「本地 + 云端双形态」；同步链路、后台常驻、解析鲁棒性集中修复；看板表格字段持续补齐；在线表合并单元格解析问题得到兜底；总览与项目汇总之间新增导航跳转。

---

## v1.0 · 2026-08-11 · 初版 + 云端部署准备

| 提交 | 类型 | 说明 |
|---|---|---|
| `8c1b0ef` | feat | 初始版本：数据层 sync.py/db.py、查询汇总 logic.py、Web 服务 app.py、前端 static、测试、启动脚本 |
| `6bdef0c` | fix | start.bat 去中文、加 `chcp 65001`，pythonw 加固 |
| `21e0bec` | feat | 部署就绪：bind 0.0.0.0、读 `PORT` 环境变量、requirements.txt |
| `40c2734` | chore | 准备 Render 部署（Procfile / render.yaml，保留 shortage.db 快照，弃用 HF Dockerfile） |
| `7abb190` | feat | 云端从 seed.sql 初始化（无 wecom-cli 在线拉取）；新增 Render Procfile/render.yaml |
| `4306b80` | chore | 移除运行时 db/err 日志，云端改用 seed.sql 初始化；修正 README |
| `5a6dd87` / `2a07b80` | feat | 自动同步 + 自动推送 seed.sql 到 GitHub，环境变量驱动配置 |
| `1786404` | fix | 默认 PORT 对齐 8765（匹配 start.bat/README） |
| `863b9e8` | feat | 前端自动刷新 + wecom-cli 路径探测（上线优化） |

**本期核心变化**：从聊天机器人重做为本地浏览器 APP，建立数据层/查询/Web/前端/测试完整骨架，并完成云端 Render 部署准备。

---

## 维护约定
- **提交规则**：每次人工代码 / 文档修改由助手提交并推送到 `main`（中文简述），触发 Render 自动重部署。
- **数据同步**：app.py 后台自动导出 `seed.sql` 并推送（节流：仅数据变化时），属机制产物，不列入人工变更。
- **统计口径**：已归档数据不统计（看板 / 汇总统一过滤）。
- **版本号**：PRD（`docs/PRD.md`）与本文档同步在每次结构性变更时升版（当前 v1.6.6）。
