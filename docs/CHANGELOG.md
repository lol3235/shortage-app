# 欠料看板（shortage_app）变更日志 CHANGELOG

> 记录所有**人工功能 / 修复 / 部署**提交。自动数据同步产生的 `sync: update seed.sql ...` 提交不列入（由 app.py 后台周期推送，仅时间戳，易刷屏）。
> 仓库：github.com/lol3235/shortage-app ｜ 线上：https://shortage-app.onrender.com/

---

## v1.3 · 2026-08-12 · 在线表写回（方案 B）

| 提交 | 类型 | 说明 |
|---|---|---|
| `66fde6d` | feat | 标记到货时**回写企业微信在线表**状态列：`sync.py` 封装 `sheet_get_info`/`sheet_update_range_data`；新增 `writeback.py`（`plan_online_write` 只读定位 + `apply_online_write` 写入，含单表连续/无断层/唯一命中/坐标界内/状态列存在 多重安全闸）；前端加确认弹窗预览将改哪些子表/行/旧值→新值 |
| `66fde6d` | docs | PRD 升 v1.3，新增 §10「在线表写回」，说明权限要求（智能机器人需在线表【编辑】权限，否则 `851003 no authority`）与已知限制 |

**本期核心变化**：确认到货不再只在本地看板生效，可一键同步改写在线表对应单元格；写前强制预览确认，最大限度避免误改生产数据。当前实测写入被权限拦截（`851003`），需先在企业微信给智能机器人授予该在线表编辑权限后方可生效。

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
- **版本号**：PRD（`docs/PRD.md`）与本文档同步在每次结构性变更时升版（当前 v1.1）。
