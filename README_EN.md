# VoiceShop AI

[简体中文](README.md) | [English](README_EN.md)

VoiceShop AI is a Python shopping assistant built with LangGraph, DeepSeek, and local streaming speech recognition. Shoppers can describe what they need by text or voice; the system uses conversation context, a product catalog, knowledge retrieval, and business tools to support recommendations, policy questions, and order workflows.

## Product UI

![VoiceShop AI catalog and conversation UI](docs/images/voiceshop-dialogue.png)

## Capabilities

- Multi-turn conversations orchestrated as a LangGraph state machine, with model-led intent classification, rule-based slot extraction, clarification, and tool execution
- Product catalog and details, budget filtering, recommendation explanations, browsing events, and order records
- Chinese semantic retrieval using BGE-small-zh-v1.5, with answers grounded in source documents
- PostgreSQL for application data and pgvector for 512-dimensional embeddings, searched by cosine distance with an HNSW index
- FunASR Paraformer Streaming for speech input and browser speech synthesis for spoken responses
- Model-call traces, token/latency/cost records, versioned prompts, and input/output safety checks
- Offline conversation evaluation and a separate RAG abstention-threshold evaluation set

## Conversation Flow

```text
Voice or text input
  -> Load conversation context
  -> Model-led intent classification + rule-based slot extraction
  -> Schema validation and business constraints
  -> Product retrieval / pgvector knowledge retrieval / order tools
  -> Evidence-grounded response with source citations
  -> Persist messages, behavior, model calls, and traces
```

## Technology

Python, LangGraph, SQLAlchemy, Alembic, PostgreSQL, pgvector, Pydantic, DeepSeek API, BGE embeddings, FunASR, WebSocket, and optional Redis.

## PostgreSQL and Vector Search

Application tables and knowledge embeddings live in PostgreSQL. Alembic migrations enable the `vector` extension and create a `vector(512)` column with an HNSW cosine index. Index rebuilds replace the old vectors in a transaction. Model revision, corpus fingerprint, and record count are tracked in an index-state table. Existing `data/voiceshop.db` and SQLite vector files are retained and are not migrated or deleted automatically.

The project includes a Docker Compose configuration. PostgreSQL data is bind-mounted under `data/postgres/` in the repository, while Docker image storage follows the local Docker Desktop data-disk setting. `.env` and `.env.database` are excluded from Git.

### Start PostgreSQL

If the local environment is configured:

```powershell
cd G:\ai-agent-show\voiceshop-ai
docker compose --env-file .env.database up -d
```

For a fresh setup, use `.env.example` as a template for your local `.env.database` and set your own `POSTGRES_PASSWORD`. The application reads `.env` first, then loads database values missing there from `.env.database`.

### Install Dependencies and Migrate

Python packages, pip cache, and temporary files stay in the project environment on G:.

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

`migrate_sqlite_to_postgres` opens the legacy `data/voiceshop.db` read-only and copies users, sessions, messages, orders, behaviors, FAQs, and audit records into empty PostgreSQL tables. It stops if the target already contains application data rather than merging or overwriting records. The original SQLite file is left untouched. The first vector-index build uses the local model in `models/embeddings/bge-small-zh-v1.5`; model files are not committed.

## Run the Application

```powershell
cd G:\ai-agent-show\voiceshop-ai
$env:MODELSCOPE_CACHE = "G:\ai-agent-show\voiceshop-ai\models\modelscope"
$env:HF_HOME = "G:\ai-agent-show\voiceshop-ai\models\huggingface"
& ".\.venv\python.exe" -m app.web
```

Open <http://127.0.0.1:7860>. The browser requests microphone permission when voice input is first used. Speech recognition runs locally; spoken replies use browser speech synthesis.

## Knowledge and Evaluation

`data/knowledge/` contains shipping, after-sales, product-service, and imported reference documents. Retrieved chunks preserve source, page, and collection metadata. Rebuild the vector index after changing knowledge files with `python -m app.index_knowledge`.

- `data/eval_cases.json`: Agent intent, product filtering, multi-turn context, and business-flow cases
- `data/retrieval_threshold_eval.json`: 35 answerable/unanswerable RAG cases with expected chunk IDs for abstention-threshold analysis

Run the offline Agent evaluation:

```powershell
$env:EVAL_OFFLINE = "1"
& ".\.venv\python.exe" -m app.eval
```

Similarity is not a universal relevance probability. A semantically related question with no supported answer can still score highly, so calibrate the abstention threshold against this evaluation set, the cost of incorrect answers, and real user queries.

## Project Layout

```text
app/
├── graph.py                 # LangGraph workflow
├── agent_nodes.py           # Intent, retrieval, tool, and response nodes
├── database.py              # PostgreSQL connection pools and sessions
├── vector_store.py          # pgvector storage and search
├── migrate_sqlite_to_postgres.py # One-time legacy data copy
├── rag.py                   # Chunk loading, retrieval, and context assembly
├── index_knowledge.py       # Build the knowledge vector index
├── voice/                   # FunASR streaming recognition
└── prompts/                 # Versioned prompts
alembic/                     # Database migrations
data/knowledge/              # Knowledge documents and imported corpus
web/                         # Shopping assistant frontend
tests/                       # Automated tests
```

## Security

Keep model keys, database passwords, and JWT secrets in local `.env`/`.env.database` files or environment variables. `.env`, database files, model weights, and local runtime data are excluded by `.gitignore`; always inspect the Git staging area before pushing.
