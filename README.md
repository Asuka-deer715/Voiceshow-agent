# VoiceShop AI

基于 Python 与 LangGraph 构建的 AI 语音导购系统，面向商品咨询、智能推荐、知识问答与订单服务等购物场景。

## 项目定位

VoiceShop AI 面向在线购物中的自然语言导购场景。用户可以通过文字或语音描述商品需求，系统结合对话上下文、商品资料、预算、使用场景和历史行为，完成需求理解、商品筛选、推荐解释、知识问答和订单服务。

系统将大模型的自然语言理解能力与结构化业务工具结合：模型负责判断用户当前意图和对话状态，工具负责商品查询、订单查询、知识检索等确定性操作，避免仅依赖固定关键词或直接生成未经验证的答案。

## 页面展示

VoiceShop 提供面向用户的 AI 语音导购入口，支持多轮需求表达、商品推荐理由展示、语音输入和商品目录浏览。

![VoiceShop AI 商品目录](docs/images/voiceshop-dialogue.png)

## 核心能力

- 基于 LangGraph 编排多轮购物对话，支持意图识别、上下文理解、槽位提取与澄清
- 结合大模型判断用户主要意图，并通过结构化工具完成商品检索、价格查询、订单查询和偏好调整
- 支持商品目录、商品详情、浏览行为、购物车式订单创建与订单管理
- 支持产品手册、配送政策、售后规则等知识内容的解析、检索、答案生成与来源引用
- 支持多角度商品推荐、预算和场景匹配，以及推荐结果的解释生成
- 支持用户画像、购买行为、会话消息、FAQ、订单和 Trace 数据持久化
- 支持浏览器语音输入与语音回复，提供自然语言导购交互
- 支持离线问答评测、召回质量评估、工具调用记录和流程审计
- 对超出结构化业务流程的问题调用兼容 OpenAI API 的大模型进行处理

## 核心交互流程

```text
用户输入文字/语音
        |
        v
会话状态加载 -> 意图识别 -> 槽位提取与上下文合并
        |
        +--> 信息不足：生成澄清问题
        |
        +--> 商品需求：检索商品 -> 条件过滤 -> 多角度推荐 -> 解释原因
        |
        +--> 知识问题：检索知识库 -> 组装证据 -> 生成带来源答案
        |
        +--> 订单问题：调用订单工具 -> 校验用户权限 -> 返回订单信息
        |
        v
输入/输出合规检查 -> 保存会话、行为和 Trace -> 返回结果
```

### 意图识别与多轮上下文

意图识别由模型结合最近对话历史完成，规则层负责价格、品类、品牌、场景和否定偏好等槽位提取与业务校验。例如用户先说“我想买鞋子”，再说“预算 500 以内”，系统会将后续预算合并到原有商品需求中，而不是重新开始一轮对话。

### 商品推荐

商品推荐同时考虑语义相关度、预算范围、商品类别、使用场景、库存状态和用户偏好。推荐流程保留价格、场景、品质和多样性等不同评价视角，最终由聚合器生成排序结果和推荐理由。

### RAG 知识问答

知识库支持产品服务说明、配送政策和售后规则等内容。文档经过解析、清洗、切分和检索后，作为模型回答的上下文；回答同时保留来源文件和证据片段，降低脱离资料生成错误政策的风险。

### 订单与行为服务

系统记录用户的会话、商品浏览、推荐点击和订单信息，为订单查询、用户画像和后续推荐提供数据基础。订单相关操作通过结构化工具执行，并预留状态校验、权限检查和操作审计接口。

## Architecture

```text
app/
├── agent/          # 意图、澄清、情绪、推荐与多视角 Agent
├── compliance/     # 输入输出安全与证据校验
├── config/         # 模型、数据库、缓存和向量服务配置
├── controller/     # 对话、商品、订单和语音接口
├── dto/             # 请求、响应和 Agent 结果结构
├── entity/          # 用户、商品、订单、会话和知识实体
├── event/           # 用户行为、订单和 Trace 领域事件
├── listener/        # 异步画像、审计和事件处理
├── memory/          # 会话记忆、摘要和 Agent 记忆策略
├── repository/      # 商品、订单、知识库和向量数据访问
├── security/        # 登录认证、JWT 和资源权限校验
├── service/         # 对话编排、推荐、订单和知识服务
└── voice/           # ASR/TTS 流式通信
```

系统以 LangGraph 作为流程编排层，将意图识别、槽位更新、知识检索、商品工具、推荐聚合、合规检查和 Trace 记录组织为可追踪的状态流转。

## 数据与知识库

```text
data/
├── products.json                 # 商品目录、价格、库存和标签
├── eval_cases.json              # 离线评测样例
└── knowledge/
    ├── after_sales.md           # 售后与退换货知识
    ├── shipping.md              # 配送与物流知识
    └── product_service.md       # 商品服务与使用说明
```

知识检索接口：

```text
GET /api/rag/search?q=退换货规则
```

返回内容包含匹配文本、来源文件和相关度信息，可用于前端展示来源，也可作为后续模型回答的上下文。

## 主要接口

| 接口 | 作用 |
| --- | --- |
| `POST /api/recommend` | 提交用户需求并获取对话回复与推荐结果 |
| `GET /api/products` | 查询商品目录 |
| `GET /api/products/{id}` | 查看商品详情 |
| `POST /api/behavior` | 记录商品浏览、点击等行为 |
| `GET /api/orders` | 查询当前订单列表 |
| `POST /api/orders` | 创建订单记录 |
| `POST /api/orders/delete` | 删除订单记录 |
| `GET /api/faq` | 查询常见问题 |
| `GET /api/rag/search` | 检索知识库并返回来源 |
| `GET /api/eval` | 执行基础离线评测 |

## 技术栈

- **应用层**：Python、FastAPI
- **流程编排**：LangGraph
- **模型调用**：OpenAI-compatible API、DeepSeek
- **数据校验**：Pydantic
- **检索增强**：RAG、文本切分、相似度检索、来源引用
- **持久化**：SQLite，预留 PostgreSQL、Redis 和向量数据库适配层
- **语音交互**：Browser Speech Recognition、Browser Speech Synthesis
- **评测与观测**：离线评测集、Trace 记录、工具调用审计

## 安全与配置

API Key 只通过本地 `.env` 或环境变量注入，不写入源码和 Git。项目通过 `.gitignore` 排除 `.env`、本地数据库、Python 缓存和运行时文件；提交前应检查暂存区，避免把个人凭据或运行数据上传到远程仓库。

项目技术栈以 Python、FastAPI、LangGraph 和 Pydantic 为基础，结合 Embedding、Vector Database 与 RAG 完成商品和知识内容的语义检索。对话流程通过 LangGraph 进行状态编排，支持意图识别、槽位提取、工具调用、上下文组装、答案生成和来源追溯；语音交互采用浏览器语音输入与语音合成，配合 Trace 记录和离线评测分析 Agent 执行效果。

## Run

```bash
cd G:\ai-agent-show\voiceshop-ai
python -m app.web
```

Open `http://127.0.0.1:7860`.

## LLM configuration

The service uses a DeepSeek model through an OpenAI-compatible API for intent understanding and open-ended questions:

```text
LLM_API_KEY=your_api_key
LLM_MODEL=deepseek-chat
OPENAI_BASE_URL=https://api.deepseek.com/v1
```

`OPENAI_API_KEY` is also supported. Do not commit keys or the local `data/voiceshop.db` file.

## Conversation and FAQ

The browser stores a `session_id` and sends it with each request. The backend persists
messages and extracted slots, so a follow-up such as `预算 500 以内` can complete the
previous request for shoes. FAQ means frequently asked questions, such as delivery,
returns and exchanges. Those questions now enter the RAG flow: knowledge files are
split into chunks, locally ranked, assembled as context, and optionally summarized by
the configured DeepSeek model with a source filename.
