# 欠料看板（Shortage Board）

本地化欠料跟踪看板。支持总览、按项目 / 物料 / 品牌汇总、交期对比、状态过滤。
数据源为企微欠料在线表，本地 SQLite 持久化（重启不丢）。

## 技术栈
- 后端：`app.py`（Python 标准库 `http.server`，零第三方依赖）
- 数据库：`data/shortage.db`（SQLite）
- 前端：`static/`（原生 HTML / CSS / JS）
- 同步：`sync.py`（调用 wecom-cli 拉取企微欠料表并解析入库）

## 本地运行
1. 双击 `start.bat` 启动（自动打开浏览器 http://localhost:8765 ）
2. 点右上角「🔄 同步」从企微拉取最新数据
3. 双击 `stop.bat` 停止

## 部署到 Render（公网访问）
1. 把本仓库推到 GitHub（已推送：`github.com/lol3235/shortage-app`）
2. 打开 https://dashboard.render.com → New → Blueprint
3. 连接你的 GitHub 仓库 `lol3235/shortage-app`
4. Render 读取 `render.yaml` 自动构建，启动命令 `python app.py`（监听 `$PORT`）
5. 部署完成后得到公网 URL，任何人浏览器打开即用

> 注意：云端环境没有 wecom-cli，无法在线同步企微表。
> 仓库内置的 `data/shortage.db` 是本地同步的快照，作为云端初始数据；
> 如需更新，请在本机同步后重新推送该文件到 GitHub 并触发 Render 重新部署。

## 文档
- `docs/PRD.md`：产品需求文档
- `docs/dev_plan.md`：开发计划
