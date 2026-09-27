# Learning Agent

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![SwiftUI](https://img.shields.io/badge/SwiftUI-F05138?style=for-the-badge&logo=swift&logoColor=white)

**Links:** [Repository](https://github.com/avieladika/learning-agent) · [Pipeline](backend/pipeline/orchestrator.py) · [Tests](tests)

Learning Agent is a personal assistant for exploring knowledge in YouTube videos. It retrieves transcript passages, builds a bounded context, and generates answers with video links and timestamps through a Python API and a SwiftUI macOS client.

## The Challenge

Finding a specific explanation in long videos takes time. Keyword matches can miss related ideas, isolated transcript passages can lose context, and answers without source references are difficult to check.

## The Solution

The application combines keyword and vector retrieval, reranks candidate videos, and expands relevant passages with neighboring transcript chunks. It checks whether the retrieved evidence covers the question and can perform one targeted follow-up retrieval pass before generating an answer.

## Highlights

### Hybrid retrieval: BM25, embeddings, and Reciprocal Rank Fusion

Transcript search combines two complementary signals. SQLite FTS5 ranks lexical matches with BM25, while Chroma retrieves semantically similar passages using cosine distance over `all-MiniLM-L6-v2` sentence embeddings. The application merges their ranked lists using **Reciprocal Rank Fusion (RRF)**: each appearance adds `1 / (60 + rank)` to a passage's score. Rank-based fusion avoids treating BM25 scores and vector distances as directly comparable. Query-expansion coverage and a small video-title ranking boost also influence passage selection.

See [transcript search](backend/storage/transcript_store.py), [vector storage](backend/storage/vector_store.py), and [fusion logic](backend/pipeline/layers/content_layer.py).

### Context expansion and evidence-driven retrieval

Selected passages are expanded with adjacent chunks from the same video, then deduplicated. This preserves explanations that span chunk boundaries. Video candidates can be reranked by the language model, and the orchestrator can request one additional retrieval pass for missing concepts. Explicit video requests remain restricted to that video. Timestamped sources are constructed from the chunks selected for the answer context.

### Token budgeting and conversational follow-ups

Questions, history, transcripts, and answer generation have separate budgets. Follow-up questions are rewritten into standalone queries, while history trimming retains recent complete turns. Token counting uses a locally cached Hugging Face tokenizer when available and a conservative UTF-8-based estimate otherwise. [Regression tests](tests) cover budget limits, source selection, and retrieval boundaries; these checks do not measure answer accuracy.

### Technologies and third-party components

| Component | How it is used |
| --- | --- |
| **Chroma + Sentence Transformers** | Persistent title/transcript indexes and local embedding generation with `all-MiniLM-L6-v2`. |
| **SQLite FTS5** | Canonical transcript storage, lexical search with BM25, and retrieval of neighboring chunks. Accessed through Python's `sqlite3` module. |
| **Groq + OpenAI Python SDK** | Groq provides model inference; the OpenAI-compatible client handles query analysis, reranking, evidence assessment, and answer generation. |
| **Hugging Face Transformers** | Loads a cached model tokenizer for request-budget calculations. |
| **yt-dlp** | Retrieves video metadata and available subtitles for ingestion. |
| **FastAPI, Pydantic, and Uvicorn** | HTTP endpoints, typed request/data models, and the Python API server. |
| **SwiftUI, Combine, and AppKit** | Apple's frameworks for the macOS interface, observable application state, and desktop integration. |


## What It Includes

- Video and transcript ingestion with `yt-dlp`.
- SQLite metadata and transcript storage alongside Chroma vector indexes.
- Query analysis, channel selection, video reranking, and contextual passage retrieval.
- Explicit budgets for questions, conversation history, transcript context, and answers.
- FastAPI endpoints and a SwiftUI macOS client.
- Regression tests for retrieval boundaries, source selection, and token budgets.

## System Model

Ingestion prepares searchable video and transcript data. Storage modules own persistence, pipeline layers own retrieval and generation, and the API connects the workflow to the desktop client.

## Core Technical Flow

Question → query analysis → channel/video retrieval → transcript context → evidence check → answer and sources.

```mermaid
flowchart LR
    Q[Question] --> R[Hybrid retrieval]
    R --> C[Transcript context]
    C --> E[Evidence check]
    E --> A[Answer and timestamped sources]
```

## Why This Design

Separate pipeline stages make retrieval decisions easier to inspect. Context windows retain surrounding explanations, while source selection follows the passages that fit the context budget.

## Run the backend

Use Python 3.11+ with a compatible dependency environment. From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
# Fill in your own configuration in backend/.env.
python -m uvicorn backend.api.server:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` to add channels and use the API. The repository starts with an empty channel list; local indexes and databases are generated as you ingest content.

Configuration notes:

- `GROK_API_KEY` is the current variable name for a **Groq** key, not an xAI key.
- The current server requires a nonempty `YOUTUBE_API_KEY` even though the ingestion adapter uses `yt-dlp`.
- First use of embedding models may download model weights; provider requests require network access.

Example question after indexing suitable videos:

```sh
curl http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Summarize the main ideas in the indexed videos","history":[]}'
```

## macOS client

Open `frontend/learning tool/learning tool.xcodeproj` in Xcode. The client uses AppKit and local process management, so it is a macOS application. Before using its server launcher, update `projectPath` and `pythonPath` in `ServerManager.swift` for your checkout. The API can also be used independently.

## Tests

```sh
python -m unittest discover -s tests -v
```

These regression tests use local fixtures and mocked model responses. They do not establish end-to-end answer accuracy; a curated retrieval and citation evaluation set remains future work.

## Current limitations

YouTube transcript availability and rate limits affect ingestion. Model answers may be incomplete or incorrect, so source links are provided for review. The local API has no production authentication or deployment configuration. Dependencies are not yet locked. The desktop launcher still needs per-machine paths.

## Author

Aviel Adika. Personal software project.
