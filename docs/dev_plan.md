# 欠料看板本地 APP — 开发计划

> 给 AI 自看的可执行计划。技术栈：Python 3 标准库（http.server + sqlite3），无第三方依赖。
> 原则：每完成一个阶段都跑测试，失败先定位修复再继续；不删测试、不降级标准。

---

## 阶段 0：项目骨架（已完成）
- 文件夹 `D:\InvoiceTool\shortage_app\`，子目录 `docs/ static/ data/ tests/fixtures/`。
- 已写入 `docs/PRD.md`。

## 阶段 1：数据层 `sync.py` + `db.py`
**目标**：从企微拉取 markdown 并解析，写入本地 SQLite。
- `sync.py`：
  - 复制原 `refresh_data.py` 的 `COL_ALIASES`、`_classify_eta`、`_is_material_code`、`_resolve_columns`、`parse_markdown`（多子表自适应、列名别名、状态列、期望交期独立字段）。
  - 复制 wecom-cli 调用：`_run_wecom` / `_start_task` / `_poll_task` / `fetch_markdown`（保留重试、空输出继续轮询逻辑）。
  - `sync_to_db(db, offline_md=None)`：拉取(或离线)→解析→返回 items 列表（不直接写 json）。
- `db.py`：
  - `init_db(path)`：建表 `shortage_items`（字段见 PRD 第 8 节 + `sheet`、`owner`、`eta_status`、`synced_at`）。
  - `upsert_items(items, synced_at)`：先清空再批量插入（或按 sheet+物料编码 upsert；v1 用清库重插，简单可靠）。
  - `get_all()`、`get_meta()`（上次同步时间、分表条数）。
  - 所有写操作在同一连接、事务提交；失败回滚，保留旧数据。
- **测试** `tests/test_sync.py`：用 fixture markdown（含多子表/列名差异/状态列/期望交期）验证 parse_markdown 计数与字段；验证 db upsert 后 get_all 数量一致。
- **完成判据**：`python tests/run_tests.py` 中 sync/db 用例全绿。

## 阶段 2：查询汇总逻辑 `logic.py`
**目标**：纯函数汇总，便于单测。
- 复制原 `bot_logic.py`：`RESOLVED_KEYWORDS`、`is_resolved`、`filter_active`、`_parse_date`、`cmd_search`、`cmd_project_summary`、`cmd_material_summary`、`cmd_eta_check`、`cmd_all`（总览聚合）。
- **新增** `cmd_brand_summary(items, kw)`：按品牌过滤 → 合计数量 + 按物料编码分布(同编码跨项目加总) + 按项目分布 + 明细。
- 函数统一接收 `items` 列表（由 db 读出后先 `filter_active`）。
- **测试** `tests/test_logic.py`：
  - filter_active 排除已解决/归档；
  - search 剥离尾缀（富士金品牌/巨茂项目）；
  - project_summary 巨茂 数量与明细一致；
  - material_summary B07-05-00-03-10 跨项目合计；
  - brand_summary 富士金 合计 + 分布；
  - eta_check 预计晚于期望给出⚠️及天数；预计不读期望交期列。
- **完成判据**：logic 用例全绿。

## 阶段 3：Web 服务 `app.py`
**目标**：本地 HTTP 服务，JSON API + 静态托管。
- 用 `http.server.BaseHTTPRequestHandler`：
  - `GET /api/overview` → cmd_all 聚合结果(JSON)
  - `GET /api/search?kw=&type=` → cmd_search
  - `GET /api/project?kw=` → cmd_project_summary
  - `GET /api/material?kw=` → cmd_material_summary
  - `GET /api/brand?kw=` → cmd_brand_summary（新增）
  - `GET /api/eta?kw=` → cmd_eta_check
  - `GET /api/sync_status` → 上次同步时间/分表条数/同步中标记
  - `POST /api/sync` → 触发 sync_to_db（后台线程，避免阻塞）；返回 accepted
  - 静态：`GET /` 及 `/static/*` 返回 html/js/css
- 端口默认 8765，可用环境变量 `PORT` 覆盖。
- 所有 API 统一：读 db → filter_active → 调 logic → 返回 JSON；捕获异常返回 500 + 错误信息。
- **测试** `tests/test_api.py`：用 `unittest.mock` 或直接起 handler 调 do_GET，校验各路由返回结构（可用离线 fixture 预先入库）。
- **完成判据**：API 冒烟用例全绿。

## 阶段 4：前端 `static/`
**目标**：左侧导航 + 顶部工具栏 + 内容区，8 个页面。
- `index.html`：布局骨架 + 导航。
- `style.css`：经典布局（左侧固定宽、顶部栏、内容滚动）。
- `app.js`：
  - 导航切换显示对应 section；
  - 总览：调 /api/overview 渲染指标卡 + 简易条形（纯 CSS/文字，不引第三方图表库）；
  - 查询：输入+类型下拉→/api/search→渲染表格（排序、行展开）；
  - 项目/物料/品牌汇总：输入→对应 API→渲染（合计+分布+明细表）；
  - 交期对比：输入→/api/eta→渲染判定列表；
  - 数据同步：按钮→POST /api/sync，轮询 /api/sync_status 显示进度/时间；
  - 设置：读取展示数据源/DB 路径/状态关键词（只读为主）。
- 不引入外部 CDN/框架，纯原生 JS，保证离线可用。
- **完成判据**：启动 app 后浏览器打开各页面无 JS 报错（人工验收 + 控制台检查）。

## 阶段 5：启动/停止脚本
- `start.bat`：用 venv python 起 `app.py`，并用 `start` 打开默认浏览器到 `http://localhost:8765`；最小化窗口。
- `stop.bat`：按端口/进程名结束 `app.py` 进程。
- 说明文档 `README.md`：如何启动、同步、数据位置。

## 阶段 6：Git 存档
- `git init`；`.gitignore`（忽略 `data/*.db`？——不，db 需持久化且纳入备份；忽略 `__pycache__`、`*.log`、`wecom_debug.log`）；
- 首次提交全部源码 + PRD + 计划。

## 阶段 7：第一版验收（Step 7）
- 启动 APP → 浏览器打开 → 点同步 → 各页面查询/汇总正确 → 重启 APP 数据仍在 → 状态过滤生效。
- 输出验收清单（对照 PRD 第 7 节）。

## 关键约束（贯穿全程）
- 不触碰 `D:\InvoiceTool\2026-08-06-13-52-26\shortage_tool\` 任何文件（只读复制逻辑）。
- 仅用 Python 标准库，避免 pip 依赖问题。
- 每阶段测试通过才进下一阶段。
