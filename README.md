# VoiceShop AI

[简体中文](README.md) | [English](README_EN.md)

基于 Python、LangGraph、DeepSeek 和本地语音识别构建的智能导购系统。用户可以通过文字或语音表达购物需求，系统结合多轮上下文、商品目录、知识检索和业务工具完成商品推荐、售后问答及订单服务。

## 页面展示

![VoiceShop AI 商品目录与对话界面](docs/images/voiceshop-dialogue.png)

## 核心能力

- LangGraph 状态图编排多轮对话、模型意图识别、规则槽位抽取、澄清与工具执行
- 商品目录、商品详情、预算过滤、推荐理由、浏览行为及订单记录
- 基于 BGE-small-zh-v1.5 的中文文本向量化和语义检索，答案关联原始来源
- PostgreSQL 持久化业务数据，pgvector 存储 512 维向量并使用 HNSW 做余弦距离检索
- FunASR Paraformer Streaming 流式语音识别，浏览器语音合成回复
- 模型调用 Trace、token/延迟/成本记录、版本化 Prompt、输入输出安全检查
- 离线对话评测与独立 RAG 拒答阈值评测集

## 对话流程

```text
语音或文字输入
  -> 加载会话上下文
  -> 模型判断主要意图 + 规则抽取槽位
  -> 结构化校验与业务约束
  -> 商品检索 / pgvector 知识检索 / 订单工具
  -> 证据约束回答与来源引用
  -> 保存消息、行为、模型调用与 Trace
```

## 技术栈

Python、LangGraph、SQLAlchemy、Alembic、PostgreSQL、pgvector、Pydantic、DeepSeek API、BGE Embedding、FunASR、WebSocket、Redis（可选）。

## PostgreSQL 与向量检索

业务表和知识向量统一存储在 PostgreSQL。Alembic 迁移会启用 `vector` 扩展、创建 `vector(512)` 向量列和 HNSW cosine 索引。知识索引重建在事务中替换旧向量；模型版本、语料指纹和文档数量保存在索引状态表中。旧的 `data/voiceshop.db` 和 SQLite 向量索引不会自动删除或迁移。

项目提供 Docker Compose 配置，PostgreSQL 数据目录绑定到仓库下的 `data/postgres/`，Docker Desktop 镜像缓存沿用其本机数据盘配置。`.env` 和 `.env.database` 均不提交到 Git。

### 本地启动数据库

已配置好本机环境时：

```powershell
cd G:\ai-agent-show\voiceshop-ai
docker compose --env-file .env.database up -d
```

新环境可以参考 `.env.example` 配置本地 `.env.database`，并设置自己的 `POSTGRES_PASSWORD`。应用会先读取 `.env`，未配置的数据库变量再从 `.env.database` 读取。

### 安装 Python 依赖与迁移

依赖安装到项目 G 盘虚拟环境，缓存和临时目录也设置在 G 盘：

```powershell
cd G:\ai-agent-show\voiceshop-ai
$env:PIP_CACHE_DIR = "G:\ai-agent-show\voiceshop-ai\.pip-cache"
$env:TEMP = "G:\ai-agent-show\voiceshop-ai\.tmp-install"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
& ".\.venv\python.exe" -m pip install -r requirements.txt
& ".\.venv\python.exe" -m alembic upgrade head
& ".\.venv\python.exe" -m app.migrate_sqlite_to_postgres
& ".\.venv\python.exe" -m app.index_knowledge
```

`migrate_sqlite_to_postgres` 只读打开旧 `data/voiceshop.db`，将用户、会话、消息、订单、行为、FAQ 和审计记录复制到空的 PostgreSQL 表中；目标库已有业务数据时会停止，不会合并覆盖。旧 SQLite 文件保留不动。首次向量索引构建会使用 `models/embeddings/bge-small-zh-v1.5` 中的本地模型，模型文件不会提交到 Git。

## 运行应用

```powershell
cd G:\ai-agent-show\voiceshop-ai
$env:MODELSCOPE_CACHE = "G:\ai-agent-show\voiceshop-ai\models\modelscope"
$env:HF_HOME = "G:\ai-agent-show\voiceshop-ai\models\huggingface"
& ".\.venv\python.exe" -m app.web
```

打开 <http://127.0.0.1:7860>。语音输入首次使用时需要授予浏览器麦克风权限；识别模型在本机运行，回复语音使用浏览器语音合成。

## 知识库与评测

`data/knowledge/` 包含配送、售后、商品服务及导入的参考文档。文档切分结果保留来源、页码和集合信息。修改知识文档后运行 `python -m app.index_knowledge` 重建向量索引。

- `data/eval_cases.json`：Agent 意图、商品筛选、多轮上下文和业务流程评测
- `data/retrieval_threshold_eval.json`：35 条有答案/无答案 RAG 样本，并标注应命中的 chunk，用于拒答阈值分析

离线运行 Agent 评测：

```powershell
$env:EVAL_OFFLINE = "1"
& ".\.venv\python.exe" -m app.eval
```

相似度分数不是通用相关性概率。易混淆的无答案问题可能取得较高相似度，因此拒答阈值需要结合该评测集、误答代价和真实用户查询共同校准。

## 项目结构

```text
app/
├── graph.py                 # LangGraph 工作流
├── agent_nodes.py           # 意图、检索、工具与回答节点
├── database.py              # PostgreSQL 连接池与会话
├── vector_store.py          # pgvector 向量存取与检索
├── rag.py                   # 知识切分、召回与上下文组装
├── index_knowledge.py       # 本地向量索引构建
├── voice/                   # FunASR 流式识别
└── prompts/                 # 版本化 Prompt
alembic/                     # 数据库版本迁移
data/knowledge/              # 知识文档与导入语料
web/                         # 导购前端
tests/                       # 自动化测试
```

## 安全说明

模型密钥、数据库口令和 JWT 密钥只放在本地 `.env`/`.env.database` 或环境变量中。`.env`、数据库目录、向量模型权重和本地运行数据均由 `.gitignore` 排除；推送前仍应检查 Git 暂存区。
