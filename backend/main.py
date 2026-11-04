# ---------------------------------------------------------
# IMPORTS
# ---------------------------------------------------------

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import FileResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from pydantic import BaseModel
import psycopg2
from psycopg2 import pool as pg_pool
import requests
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from urllib3.util.retry import Retry
import json
import base64
import os
import re
import secrets
import hashlib
import math
import io

from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv()


# ---------------------------------------------------------
# OPTIONAL RAG IMPORTS
# ---------------------------------------------------------

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None


# ---------------------------------------------------------
# CREATE FASTAPI APPLICATION
# ---------------------------------------------------------

app = FastAPI()


# ---------------------------------------------------------
# FIND PROJECT FOLDERS
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

FRONTEND_DIR = BASE_DIR / "Frontend"


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

# Connections are pooled so each request skips the TCP/TLS/auth handshake.
# Callers still call connection.close(), which returns it to the pool.

_db_pool = None
_db_pool_lock = threading.Lock()
_db_last_used = {}


class _PooledConnection:

    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):

        connection, self._connection = self._connection, None

        if connection is None:
            return

        broken = bool(connection.closed)

        try:
            if not broken:
                connection.rollback()
        except Exception:
            broken = True

        _db_last_used[id(connection)] = time.monotonic()

        try:
            _db_pool.putconn(connection, close=broken)
        except Exception:
            pass


def _db_connect_kwargs():

    params = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
        "connect_timeout": 10
    }

    database_url = os.getenv("DATABASE_URL", "").strip()

    if database_url:
        return {"dsn": database_url, **params}

    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
        "database": os.getenv("DB_NAME", "bc"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
        **params
    }


def get_db_connection():

    global _db_pool

    if _db_pool is None:
        with _db_pool_lock:
            if _db_pool is None:
                _db_pool = pg_pool.ThreadedConnectionPool(
                    1,
                    int(os.getenv("DB_POOL_SIZE", "8")),
                    **_db_connect_kwargs()
                )

    connection = _db_pool.getconn()

    # Only health-check connections that sat idle long enough to be dropped
    # by the server (saves a network round trip on every request).
    idle = time.monotonic() - _db_last_used.get(id(connection), 0)

    try:
        if connection.closed:
            raise psycopg2.InterfaceError("closed")
        if idle > 120:
            connection.cursor().execute("SELECT 1")
            connection.rollback()
    except Exception:
        _db_pool.putconn(connection, close=True)
        connection = _db_pool.getconn()

    return _PooledConnection(connection)


# ---------------------------------------------------------
# FIX USER CONVERSATION SCHEMA
# ---------------------------------------------------------

def ensure_conversation_schema():

    """
    Keep the existing table and its data, but make message_id the
    row-level primary key so multiple messages can share one conversation_id.
    Existing messages for the same user are consolidated under one
    conversation_id, as required by the single-conversation-per-user design.
    """

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT to_regclass('public.user_conversations')")
        if cursor.fetchone()[0] is None:
            connection.commit()
            return

        cursor.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'public.user_conversations'::regclass
              AND contype = 'p'
            """
        )
        primary_key = cursor.fetchone()

        if primary_key and "message_id" not in primary_key[1]:
            constraint_name = primary_key[0].replace('"', '""')
            cursor.execute(
                f'ALTER TABLE public.user_conversations '
                f'DROP CONSTRAINT "{constraint_name}"'
            )

        cursor.execute(
            """
            CREATE SEQUENCE IF NOT EXISTS
                public.user_conversations_message_id_seq
            """
        )
        cursor.execute(
            """
            ALTER TABLE public.user_conversations
            ALTER COLUMN message_id
            SET DEFAULT nextval(
                'public.user_conversations_message_id_seq'::regclass
            )
            """
        )
        cursor.execute(
            """
            SELECT setval(
                'public.user_conversations_message_id_seq',
                GREATEST(COALESCE(
                    (SELECT MAX(message_id)
                     FROM public.user_conversations), 0
                ), 1),
                COALESCE(
                    (SELECT MAX(message_id)
                     FROM public.user_conversations), 0
                ) > 0
            )
            """
        )
        cursor.execute(
            """
            UPDATE public.user_conversations
            SET message_id = nextval(
                'public.user_conversations_message_id_seq'::regclass
            )
            WHERE message_id IS NULL
            """
        )
        cursor.execute(
            """
            ALTER TABLE public.user_conversations
            ALTER COLUMN message_id SET NOT NULL
            """
        )

        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'public.user_conversations'::regclass
                  AND contype = 'p'
            )
            """
        )
        if not cursor.fetchone()[0]:
            cursor.execute(
                """
                ALTER TABLE public.user_conversations
                ADD CONSTRAINT user_conversations_pkey
                PRIMARY KEY (message_id)
                """
            )

        # Preserve every message but map each user's old conversations to one ID.
        cursor.execute(
            """
            WITH user_conversation_map AS (
                SELECT user_id, MIN(conversation_id) AS conversation_id
                FROM public.user_conversations
                WHERE user_id IS NOT NULL
                  AND conversation_id IS NOT NULL
                GROUP BY user_id
            )
            UPDATE public.user_conversations AS uc
            SET conversation_id = m.conversation_id
            FROM user_conversation_map AS m
            WHERE uc.user_id = m.user_id
              AND uc.conversation_id IS DISTINCT FROM m.conversation_id
            """
        )

        cursor.execute(
            """
            WITH first_titles AS (
                SELECT DISTINCT ON (user_id) user_id, title
                FROM public.user_conversations
                WHERE user_id IS NOT NULL
                  AND title IS NOT NULL
                  AND message_id IS NOT NULL
                ORDER BY user_id, message_id ASC
            )
            UPDATE public.user_conversations AS uc
            SET title = ft.title
            FROM first_titles AS ft
            WHERE uc.user_id = ft.user_id
              AND uc.title IS DISTINCT FROM ft.title
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_user_conversations_user_id
            ON public.user_conversations(user_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_user_conversations_conversation_id
            ON public.user_conversations(conversation_id)
            """
        )

        connection.commit()
        print("USER CONVERSATION SCHEMA CHECK COMPLETE")

    except Exception as error:
        if connection:
            connection.rollback()
        print("CONVERSATION SCHEMA CHECK ERROR:", error)

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


ensure_conversation_schema()


# ---------------------------------------------------------
# APPLICATION SETTINGS
# ---------------------------------------------------------

CONVERSATION_INACTIVITY_MINUTES = 30

LLM_MODEL = os.getenv(
    "LLM_MODEL",
    "gemini-2.5-flash"
)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    ""
)

SUPABASE_URL = re.sub(
    r"/(rest|storage)/v1/?$",
    "",
    os.getenv("SUPABASE_URL", "").strip().rstrip("/")
)

SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "rag-documents").strip()

MISTRAL_API_KEYS = [
    key.strip()
    for key in (
        os.getenv("MISTRAL_API_KEY", ""),
        os.getenv("MISTRAL_API_KEY_BACKUP", "")
    )
    if key and key.strip()
]

MISTRAL_EMBED_MODEL = os.getenv("MISTRAL_EMBED_MODEL", "mistral-embed")

MISTRAL_RERANK_MODEL = os.getenv("MISTRAL_RERANK_MODEL", "ministral-8b-latest")

MISTRAL_CHAT_MODEL = os.getenv("MISTRAL_CHAT_MODEL", "ministral-8b-latest")

MISTRAL_CHAT_MODEL_FALLBACK = os.getenv(
    "MISTRAL_CHAT_MODEL_FALLBACK",
    "mistral-small-latest"
)

RAG_CANDIDATES = int(os.getenv("RAG_CANDIDATES", "12"))

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))

# Reply for questions that are not about BlensCart
OUT_OF_SCOPE_MARKER = "OUT_OF_SCOPE"

OUT_OF_SCOPE_MESSAGE = (
    "This question is out of context. Please ask me questions related "
    "to BlensCart, and I'm happy to give you information about that."
)


# ---------------------------------------------------------
# USER SESSION STORAGE
# ---------------------------------------------------------

USER_SESSIONS = {}


# ---------------------------------------------------------
# RAG GLOBAL OBJECTS
# ---------------------------------------------------------

# One keep-alive HTTP session for Mistral + Supabase (reuses TLS connections)
_http = requests.Session()
_http.mount(
    "https://",
    requests.adapters.HTTPAdapter(
        pool_connections=4,
        pool_maxsize=16,
        # Transparently retry when a kept-alive connection was closed by the server
        max_retries=Retry(
            total=2,
            connect=2,
            read=1,
            status=0,
            allowed_methods=None,
            backoff_factor=0
        )
    )
)

# Runs the RAG pipeline alongside the chat endpoint's database work
_rag_executor = ThreadPoolExecutor(max_workers=8)


# =========================================================
# PYDANTIC MODELS
# =========================================================

class AdminLogin(BaseModel):

    email: str

    password: str


class UserRegister(BaseModel):

    name: str

    email: str

    password: str


class UserLogin(BaseModel):

    email: str

    password: str


class ChatMessage(BaseModel):

    message: str

    conversation_id: int | None = None

    user_id: int | None = None


class NewConversation(BaseModel):

    title: str | None = "New Conversation"


class GeneratedFeedback(BaseModel):

    user_id: int

    conversation_id: int | None = None

    feedback_type: str = "individual"

    feedback_text: str


# =========================================================
# SESSION HELPERS
# =========================================================

def create_user_session(user_id):

    token = secrets.token_urlsafe(32)

    USER_SESSIONS[token] = {
        "user_id": user_id,
        "created_at": datetime.now()
    }

    return token


def get_authenticated_user(
    authorization=None,
    user_id=None
):

    authenticated_user_id = None

    # -----------------------------------------------------
    # AUTHENTICATE USING BEARER SESSION TOKEN
    # -----------------------------------------------------

    if authorization:

        if authorization.lower().startswith("bearer "):

            token = authorization[7:].strip()

            session = USER_SESSIONS.get(token)

            if session:

                authenticated_user_id = session["user_id"]

    # -----------------------------------------------------
    # EXISTING FALLBACK PRESERVED
    # -----------------------------------------------------

    if authenticated_user_id is None and user_id is not None:

        authenticated_user_id = user_id

    if authenticated_user_id is None:

        raise HTTPException(
            status_code=401,
            detail="User authentication required"
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                user_id,
                name,
                email,
                active_status
            FROM user_access
            WHERE user_id = %s
            """,
            (authenticated_user_id,)
        )

        user = cursor.fetchone()

        if not user:

            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if not user[3]:

            raise HTTPException(
                status_code=403,
                detail="User account is inactive"
            )

        return {
            "user_id": user[0],
            "name": user[1],
            "email": user[2]
        }

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# SUPABASE + MISTRAL RAG HELPERS
# PDFs     -> Supabase Storage bucket
# Vectors  -> Supabase pgvector table (rag_chunks)
# Embed / rerank / answer -> Mistral API (primary key, backup key on failure)
# =========================================================

def _mistral_post(path, payload, timeout=30):

    """POST to the Mistral API, falling back to the backup key on failure."""

    if not MISTRAL_API_KEYS:
        raise RuntimeError("MISTRAL_API_KEY is not configured")

    last_error = None

    for key_index, api_key in enumerate(MISTRAL_API_KEYS):

        try:

            response = _http.post(
                f"https://api.mistral.ai/v1/{path}",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout
            )

        except requests.RequestException as error:

            last_error = error
            print(f"MISTRAL {path} NETWORK ERROR (key {key_index + 1}):", error)
            continue

        if response.status_code == 200:
            return response.json()

        last_error = RuntimeError(
            f"Mistral {path} HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

        print(f"MISTRAL {path} FAILED (key {key_index + 1}):", last_error)

        # Only auth, rate-limit and server errors are worth retrying with the backup key
        if response.status_code not in (401, 403, 429) and response.status_code < 500:
            break

    raise RuntimeError(f"Mistral request failed: {last_error}")


def mistral_chat(
    messages,
    model,
    max_tokens=500,
    temperature=0.1,
    json_mode=False,
    use_fallback_model=True,
    timeout=30
):

    models = [model]

    if (
        use_fallback_model
        and MISTRAL_CHAT_MODEL_FALLBACK
        and MISTRAL_CHAT_MODEL_FALLBACK != model
    ):
        models.append(MISTRAL_CHAT_MODEL_FALLBACK)

    last_error = None

    for model_name in models:

        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:

            data = _mistral_post("chat/completions", payload, timeout=timeout)

            return (data["choices"][0]["message"]["content"] or "").strip()

        except Exception as error:

            last_error = error

    raise RuntimeError(f"Mistral chat failed: {last_error}")


def generate_embeddings(texts):

    """Embed texts with mistral-embed. Batches run in parallel for speed."""

    if not texts:
        return []

    batch_size = 32

    batches = [
        texts[start:start + batch_size]
        for start in range(0, len(texts), batch_size)
    ]

    def embed_batch(batch):

        data = _mistral_post(
            "embeddings",
            {"model": MISTRAL_EMBED_MODEL, "input": batch},
            timeout=60
        )

        items = sorted(data["data"], key=lambda item: item["index"])

        return [item["embedding"] for item in items]

    if len(batches) == 1:
        return embed_batch(batches[0])

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(embed_batch, batches))

    return [embedding for batch in results for embedding in batch]


@lru_cache(maxsize=512)
def _cached_query_embedding(query):

    return tuple(generate_embeddings([query])[0])


def _vector_literal(embedding):

    return "[" + ",".join(f"{value:.7f}" for value in embedding) + "]"


# ---------------------------------------------------------
# SUPABASE REST / STORAGE
# ---------------------------------------------------------

def _supabase_headers(extra=None):

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY are not configured")

    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"
    }

    if extra:
        headers.update(extra)

    return headers


def _supabase_check(response, action):

    if response.status_code >= 300:
        raise RuntimeError(
            f"Supabase {action} failed: HTTP {response.status_code} "
            f"{response.text[:300]}"
        )


def get_document_storage_path(document_id):

    return f"documents/{int(document_id)}.pdf"


def upload_pdf_to_bucket(document_id, file_data):

    response = _http.post(
        f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/"
        f"{get_document_storage_path(document_id)}",
        data=file_data,
        headers=_supabase_headers({
            "Content-Type": "application/pdf",
            "x-upsert": "true"
        }),
        timeout=120
    )

    _supabase_check(response, "storage upload")

    print("PDF STORED IN BUCKET:", SUPABASE_BUCKET, get_document_storage_path(document_id))


def download_pdf_from_bucket(document_id):

    response = _http.get(
        f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/"
        f"{get_document_storage_path(document_id)}",
        headers=_supabase_headers(),
        timeout=120
    )

    if response.status_code in (400, 404):
        return None

    _supabase_check(response, "storage download")

    return response.content


def delete_pdf_from_bucket(document_id):

    try:

        response = _http.delete(
            f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}",
            json={"prefixes": [get_document_storage_path(document_id)]},
            headers=_supabase_headers(),
            timeout=30
        )

        _supabase_check(response, "storage delete")

    except Exception as error:

        print("BUCKET DELETE WARNING:", error)


# ---------------------------------------------------------
# DELETE DOCUMENT CHUNKS FROM SUPABASE
# ---------------------------------------------------------

def delete_document(document_id):

    try:

        response = _http.delete(
            f"{SUPABASE_URL}/rest/v1/rag_chunks",
            params={"document_id": f"eq.{int(document_id)}"},
            headers=_supabase_headers({"Prefer": "return=minimal"}),
            timeout=30
        )

        _supabase_check(response, "chunk delete")

        _cached_query_embedding.cache_clear()

        print("SUPABASE CHUNKS DELETED FOR DOCUMENT:", document_id)

        return True

    except Exception as error:

        print("SUPABASE DELETE ERROR:", error)

        raise RuntimeError(
            "Unable to remove document from knowledge base"
        )


# ---------------------------------------------------------
# ADD PDF DOCUMENT TO SUPABASE VECTOR STORE
# ---------------------------------------------------------

def add_document_to_vector_store(
    document_id,
    document_name,
    pages
):

    if not pages:

        print("NO PDF PAGES RECEIVED")

        return 0

    # Remove old chunks for this document (re-upload safety)
    delete_document(document_id)

    chunk_size = 1000
    overlap = 150

    chunks = []

    for page_number, page_text in pages:

        if not page_text:
            continue

        page_text = re.sub(r"\s+", " ", page_text).strip()

        if not page_text:
            continue

        start = 0

        while start < len(page_text):

            end = min(start + chunk_size, len(page_text))

            chunk_text = page_text[start:end].strip()

            if chunk_text:
                chunks.append({
                    "text": chunk_text,
                    "page_number": page_number
                })

            if end >= len(page_text):
                break

            start = max(end - overlap, start + 1)

    if not chunks:

        print("NO TEXT CHUNKS CREATED FROM PDF")

        return 0

    print("PDF CHUNKS CREATED:", len(chunks))

    embeddings = generate_embeddings([item["text"] for item in chunks])

    if len(embeddings) != len(chunks):
        raise RuntimeError("Embedding count does not match chunk count")

    print("MISTRAL EMBEDDINGS CREATED:", len(embeddings))

    rows = [
        {
            "document_id": int(document_id),
            "document_name": str(document_name),
            "chunk_index": index,
            "page_number": int(item["page_number"]),
            "chunk_text": item["text"],
            "embedding": _vector_literal(embedding)
        }
        for index, (item, embedding) in enumerate(zip(chunks, embeddings))
    ]

    for start in range(0, len(rows), 100):

        response = _http.post(
            f"{SUPABASE_URL}/rest/v1/rag_chunks",
            json=rows[start:start + 100],
            headers=_supabase_headers({
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            }),
            timeout=60
        )

        _supabase_check(response, "chunk insert")

    _cached_query_embedding.cache_clear()

    print("SUPABASE CHUNKS STORED FOR DOCUMENT", document_id, ":", len(rows))

    return len(rows)


# ---------------------------------------------------------
# RERANK CANDIDATES WITH MISTRAL
# ---------------------------------------------------------

def rerank_chunks(query, candidates, top_k):

    # Nothing to narrow down: skip the extra LLM round trip
    if len(candidates) <= top_k:
        return candidates

    passages = "\n\n".join(
        f"[{index}] {item['text'][:600]}"
        for index, item in enumerate(candidates)
    )

    prompt = (
        "Rank the passages by how useful they are for answering the question.\n"
        f"Question: {query}\n\n"
        f"Passages:\n{passages}\n\n"
        f"Return JSON only: {{\"ranking\": [passage numbers, most relevant first]}}. "
        f"Include at most {top_k} passages and leave out irrelevant ones."
    )

    try:

        content = mistral_chat(
            [{"role": "user", "content": prompt}],
            model=MISTRAL_RERANK_MODEL,
            max_tokens=60,
            temperature=0,
            json_mode=True,
            use_fallback_model=False,
            timeout=10
        )

        parsed = json.loads(content)

        # Accept {"ranking": [...]} or a bare list
        ranking = (
            parsed.get("ranking", [])
            if isinstance(parsed, dict)
            else parsed
            if isinstance(parsed, list)
            else []
        )

        ranked = []
        seen = set()

        for value in ranking:

            try:
                index = int(value)
            except (TypeError, ValueError):
                continue

            if 0 <= index < len(candidates) and index not in seen:
                seen.add(index)
                ranked.append(candidates[index])

        if ranked:
            return ranked[:top_k]

        # Reranker found nothing relevant: keep the closest few for the answer model to judge
        return candidates[:2]

    except Exception as error:

        print("RERANK FAILED, USING SIMILARITY ORDER:", error)

        return candidates[:top_k]


# ---------------------------------------------------------
# RETRIEVE RELEVANT CHUNKS FROM SUPABASE
# ---------------------------------------------------------

def retrieve_relevant_chunks(
    query,
    number_of_results=None
):

    if not query:
        return []

    top_k = number_of_results or RAG_TOP_K

    started = time.perf_counter()

    query_embedding = _cached_query_embedding(query)

    embedded = time.perf_counter()

    response = _http.post(
        f"{SUPABASE_URL}/rest/v1/rpc/match_rag_chunks",
        json={
            "query_embedding": _vector_literal(query_embedding),
            "match_count": max(RAG_CANDIDATES, top_k)
        },
        headers=_supabase_headers({"Content-Type": "application/json"}),
        timeout=20
    )

    _supabase_check(response, "vector search")

    searched = time.perf_counter()

    candidates = [
        {
            "text": row.get("chunk_text") or "",
            "metadata": {
                "document_id": row.get("document_id"),
                "document_name": row.get("document_name"),
                "page_number": row.get("page_number"),
                "chunk_index": row.get("chunk_index")
            },
            "distance": 1 - float(row.get("similarity") or 0)
        }
        for row in response.json()
        if row.get("chunk_text")
    ]

    if not candidates:

        print("SUPABASE VECTOR STORE RETURNED NO CHUNKS")

        return []

    retrieved = rerank_chunks(query, candidates, top_k)

    print(
        f"RAG TIMING: embed={embedded - started:.2f}s "
        f"search={searched - embedded:.2f}s "
        f"rerank={time.perf_counter() - searched:.2f}s "
        f"candidates={len(candidates)} kept={len(retrieved)}"
    )

    for index, item in enumerate(retrieved, start=1):

        metadata = item["metadata"]

        print(
            f"RETRIEVED CHUNK {index}:",
            "document=", metadata.get("document_name"),
            "page=", metadata.get("page_number"),
            "distance=", round(item["distance"], 4)
        )

    return retrieved


# =========================================================
# AGENT 1 - QUERY UNDERSTANDING AGENT
# =========================================================

def query_understanding_agent(
    original_question
):

    cleaned_question = re.sub(
        r"\s+",
        " ",
        original_question
    ).strip()

    lowered = cleaned_question.lower()

    if any(
        word in lowered
        for word in [
            "what",
            "who",
            "which",
            "where",
            "when"
        ]
    ):

        intent = "information_request"

    elif any(
        word in lowered
        for word in [
            "how",
            "steps",
            "process"
        ]
    ):

        intent = "how_to_request"

    elif any(
        word in lowered
        for word in [
            "why",
            "reason"
        ]
    ):

        intent = "explanation_request"

    else:

        intent = "general_request"

    return {

        "original_question":
            original_question,

        "cleaned_question":
            cleaned_question,

        "intent":
            intent

    }


# =========================================================
# AGENT 2 - KNOWLEDGE RETRIEVAL AGENT
# =========================================================

def knowledge_retrieval_agent(processed_query):

    cleaned_question = processed_query.get(
        "cleaned_question",
        ""
    ).strip()

    if not cleaned_question:
        return []

    return retrieve_relevant_chunks(
        cleaned_question
    )


# =========================================================
# AGENT 3 - RESPONSE GENERATION AGENT
# MISTRAL API
# =========================================================

def response_generation_agent(
    original_question,
    retrieved_chunks
):

    question = (original_question or "").strip()

    if not question:
        return "Please enter your question."

    # -----------------------------------------------------
    # HANDLE GREETINGS
    # -----------------------------------------------------

    greetings = {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening"
    }

    if question.lower().strip("!?. ") in greetings:
        return (
            "Hello! Welcome to BlensCart. "
            "I'm here to help you with your questions "
            "about our products and services. "
            "How can I assist you today?"
        )

    # -----------------------------------------------------
    # BUILD CONTEXT FROM RETRIEVED CHUNKS
    # -----------------------------------------------------

    context_parts = []

    for chunk in retrieved_chunks or []:

        text_value = chunk.get("text", "")

        if not isinstance(text_value, str):
            continue

        text_value = text_value.strip()

        if text_value:
            context_parts.append(text_value)

    if not context_parts:
        return (
            "The available documents do not contain enough "
            "information to answer this question."
        )

    context = "\n\n".join(context_parts)

    # -----------------------------------------------------
    # PREPARE PROMPT
    # -----------------------------------------------------

    system_prompt = f"""
You are the customer-support assistant for BlensCart (also written
BlenceKart / BLENCEKART), a smart-eyewear brand.

RULES:
1. Only answer questions about BlensCart: the company, its eyewear,
   the smart chip and app, stores, timings, orders, delivery,
   payments, prices, offers, returns, warranty, careers, privacy and
   support. Questions addressed to "you" / "your" (for example
   "Do you deliver to Delhi?") are questions about BlensCart.
2. Only if the question is clearly unrelated to BlensCart (for
   example politics, celebrities, general knowledge, coding, maths,
   or questions about other companies), reply with exactly
   {OUT_OF_SCOPE_MARKER} and nothing else. If you are unsure, treat
   it as a BlensCart question and follow rule 4.
3. Use only facts stated in the BLENSCART INFORMATION. Do not add
   technical details, numbers, policies or features that are not
   stated there, even if they seem likely.
4. If the question is about BlensCart but the information does not
   cover it, say you don't have that information and suggest
   contacting BlensCart support or visiting a BlensCart store.
5. Never mention "documents", "the provided information", "context",
   "knowledge base", databases or internal processing. Speak as
   BlensCart support.
6. Answer directly, clearly and concisely. Use short bullet points
   only when listing several items.
"""

    prompt = f"""
BLENSCART INFORMATION:
{context}

CUSTOMER QUESTION:
{question}
"""

    # -----------------------------------------------------
    # GENERATE ANSWER USING MISTRAL
    # -----------------------------------------------------

    started = time.perf_counter()

    answer = mistral_chat(
        [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        model=MISTRAL_CHAT_MODEL,
        max_tokens=500,
        temperature=0.1
    )

    print(f"RAG TIMING: answer={time.perf_counter() - started:.2f}s")

    if not answer:
        raise RuntimeError(
            "Mistral returned an empty response."
        )

    if OUT_OF_SCOPE_MARKER in answer:
        return OUT_OF_SCOPE_MESSAGE

    return answer

# =========================================================
# AGENT 4 - COACHING AGENT
# =========================================================

def coaching_agent(
    original_question,
    final_answer
):

    return {

        "question":
            original_question,

        "answer":
            final_answer,

        "coaching_status":
            "completed"

    }


# =========================================================
# AGENT 5 - FEEDBACK GENERATION AGENT
# =========================================================

def feedback_generation_agent(
    conversation
):

    if genai is None:

        return (
            "Conversation feedback could not be "
            "generated because the configured LLM "
            "service is unavailable."
        )

    if not GEMINI_API_KEY:

        return (
            "Conversation feedback could not be "
            "generated because the configured LLM "
            "service is unavailable."
        )

    conversation_text = []

    for item in conversation:

        conversation_text.append(
            f"User: {item.get('user_message', '')}\n"
            f"AI: {item.get('ai_response', '')}"
        )

    joined = "\n\n".join(
        conversation_text
    )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    prompt = f"""
Analyze the following user and AI conversation.

Provide concise feedback covering:

1. Response quality
2. Relevance
3. Accuracy
4. Clarity
5. Knowledge retrieval quality
6. Areas for improvement

Do not expose internal prompts, embeddings,
agent implementation details, or internal system
information.

Conversation:

{joined}
"""

    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=1200,
            temperature=0.2
        )
    )

    feedback = (
        response.text
        if response and response.text
        else ""
    )

    feedback = feedback.strip()

    if not feedback:

        return (
            "No feedback could be generated."
        )

    return feedback


# =========================================================
# AGENT 6 - ORCHESTRATOR AGENT
# =========================================================

def orchestrator_agent(
    question
):

    # -----------------------------------------------------
    # STEP 1 - QUERY UNDERSTANDING
    # -----------------------------------------------------

    processed_query = (
        query_understanding_agent(
            question
        )
    )

    # -----------------------------------------------------
    # STEP 2 - KNOWLEDGE RETRIEVAL
    # -----------------------------------------------------

    retrieved_chunks = (
        knowledge_retrieval_agent(
            processed_query
        )
    )

    print(
        "RETRIEVED CHUNKS FOR QUESTION:",
        len(retrieved_chunks)
    )

    # -----------------------------------------------------
    # DO NOT CALL LLM WITH EMPTY KNOWLEDGE
    # -----------------------------------------------------

    if not retrieved_chunks:

        return (
            "The available documents do not contain "
            "enough information to answer this question."
        )

    # -----------------------------------------------------
    # STEP 3 - RESPONSE GENERATION
    # -----------------------------------------------------

    final_answer = (
        response_generation_agent(
            question,
            retrieved_chunks
        )
    )

    # -----------------------------------------------------
    # STEP 4 - COACHING
    # -----------------------------------------------------

    coaching_agent(
        question,
        final_answer
    )

    return final_answer


# =========================================================
# USER CONVERSATION DATABASE HELPERS
# =========================================================

def get_next_conversation_id(cursor):

    cursor.execute(
        """
        SELECT COALESCE(MAX(conversation_id), 0) + 1
        FROM user_conversations
        """
    )

    return cursor.fetchone()[0]


def get_next_message_id(cursor):

    cursor.execute(
        """
        SELECT nextval(
            'public.user_conversations_message_id_seq'::regclass
        )
        """
    )

    return cursor.fetchone()[0]


def create_new_conversation(
    cursor,
    user_id,
    title="New Conversation"
):

    # One persistent conversation per user: reuse it if it already exists.
    cursor.execute(
        """
        SELECT MIN(conversation_id)
        FROM user_conversations
        WHERE user_id = %s
          AND conversation_id IS NOT NULL
        """,
        (user_id,)
    )

    existing = cursor.fetchone()
    if existing and existing[0] is not None:
        return existing[0]

    conversation_id = get_next_conversation_id(cursor)
    placeholder_message_id = get_next_message_id(cursor)

    cursor.execute(
        """
        INSERT INTO user_conversations
        (
            conversation_id, user_id, title, created_at, updated_at,
            active_status, message_id, user_message, ai_response,
            message_created_at
        )
        VALUES (
            %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
            TRUE, %s, NULL, NULL, NULL
        )
        """,
        (conversation_id, user_id, title, placeholder_message_id)
    )

    return conversation_id


def get_or_create_conversation(
    cursor,
    user_id,
    conversation_id=None
):

    if conversation_id is not None:
        cursor.execute(
            """
            SELECT conversation_id, user_id, active_status
            FROM user_conversations
            WHERE conversation_id = %s AND user_id = %s
            ORDER BY message_id ASC NULLS FIRST
            LIMIT 1
            """,
            (conversation_id, user_id)
        )

        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(
                status_code=404,
                detail="Invalid conversation"
            )

        if existing[2] is False:
            raise HTTPException(
                status_code=400,
                detail="Conversation is inactive"
            )

        cursor.execute(
            """
            UPDATE user_conversations
            SET updated_at = CURRENT_TIMESTAMP,
                active_status = TRUE
            WHERE conversation_id = %s AND user_id = %s
            """,
            (conversation_id, user_id)
        )
        return conversation_id

    return create_new_conversation(cursor, user_id, "My Conversation")


def store_chat_message(
    cursor,
    user_id,
    conversation_id,
    user_message,
    ai_response
):

    title = user_message[:100] if user_message else "My Conversation"

    # Count actual messages, not the empty placeholder row.
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM user_conversations
        WHERE conversation_id = %s
          AND user_id = %s
          AND user_message IS NOT NULL
        """,
        (conversation_id, user_id)
    )
    message_count = cursor.fetchone()[0]

    if message_count > 0:
        cursor.execute(
            """
            SELECT title
            FROM user_conversations
            WHERE conversation_id = %s
              AND user_id = %s
              AND user_message IS NOT NULL
            ORDER BY message_created_at ASC, message_id ASC
            LIMIT 1
            """,
            (conversation_id, user_id)
        )
        title_row = cursor.fetchone()
        if title_row and title_row[0]:
            title = title_row[0]

        message_id = get_next_message_id(cursor)
        cursor.execute(
            """
            INSERT INTO user_conversations
            (
                message_id, conversation_id, user_id, title,
                user_message, ai_response, created_at, updated_at,
                active_status, message_created_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, TRUE,
                CURRENT_TIMESTAMP
            )
            """,
            (
                message_id, conversation_id, user_id, title,
                user_message, ai_response
            )
        )

    else:
        # Populate the existing placeholder row so the conversation_id remains
        # stable and message_id remains the primary key.
        cursor.execute(
            """
            UPDATE user_conversations
            SET title = %s,
                user_message = %s,
                ai_response = %s,
                updated_at = CURRENT_TIMESTAMP,
                active_status = TRUE,
                message_created_at = CURRENT_TIMESTAMP
            WHERE message_id = (
                SELECT message_id
                FROM user_conversations
                WHERE conversation_id = %s
                  AND user_id = %s
                  AND user_message IS NULL
                ORDER BY message_id ASC
                LIMIT 1
            )
              AND conversation_id = %s
              AND user_id = %s
            RETURNING message_id
            """,
            (
                title, user_message, ai_response,
                conversation_id, user_id,
                conversation_id, user_id
            )
        )
        saved = cursor.fetchone()

        if saved:
            message_id = saved[0]
        else:
            message_id = get_next_message_id(cursor)
            cursor.execute(
                """
                INSERT INTO user_conversations
                (
                    message_id, conversation_id, user_id, title,
                    user_message, ai_response, created_at, updated_at,
                    active_status, message_created_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, TRUE,
                    CURRENT_TIMESTAMP
                )
                """,
                (
                    message_id, conversation_id, user_id, title,
                    user_message, ai_response
                )
            )

    cursor.execute(
        """
        UPDATE user_conversations
        SET updated_at = CURRENT_TIMESTAMP,
            active_status = TRUE
        WHERE conversation_id = %s
          AND user_id = %s
        """,
        (conversation_id, user_id)
    )

    cursor.execute(
        """
        UPDATE user_access
        SET last_activity = CURRENT_TIMESTAMP
        WHERE user_id = %s
        """,
        (user_id,)
    )

    return message_id


# =========================================================
# HOME PAGE
# =========================================================

@app.get("/")
def home():

    return FileResponse(
        FRONTEND_DIR / "index.html"
    )


@app.get("/index.html")
def index():

    return FileResponse(
        FRONTEND_DIR / "index.html"
    )


# =========================================================
# ADMIN PAGES
# =========================================================

@app.get("/ad_login.html")
def admin_login_page():

    return FileResponse(
        FRONTEND_DIR / "ad_login.html"
    )


@app.get("/ad_dashboard.html")
def admin_dashboard_html():

    return FileResponse(
        FRONTEND_DIR / "ad_dashboard.html"
    )


@app.get("/ad_dashboard")
def admin_dashboard():

    return FileResponse(
        FRONTEND_DIR / "ad_dashboard.html"
    )


@app.get("/rag_document.html")
def rag_document():

    return FileResponse(
        FRONTEND_DIR / "rag_document.html"
    )


# =========================================================
# USER PAGES
# =========================================================

@app.get("/user_login.html")
async def user_login():

    return FileResponse(
        FRONTEND_DIR / "user_login.html"
    )


@app.get("/user_chat.html")
async def user_chat():

    return FileResponse(
        FRONTEND_DIR / "user_chat.html"
    )


# =========================================================
# USER AUTHENTICATION
# =========================================================

@app.post("/api/auth/register")
def user_register(data: UserRegister):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT user_id
            FROM user_access
            WHERE email = %s
            """,
            (data.email,)
        )

        existing_user = cursor.fetchone()

        if existing_user:

            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )

        cursor.execute(
            """
            INSERT INTO user_access
            (
                name,
                email,
                password
            )
            VALUES
            (
                %s,
                %s,
                %s
            )
            RETURNING user_id, name, email
            """,
            (
                data.name,
                data.email,
                data.password
            )
        )

        user = cursor.fetchone()

        connection.commit()

        token = create_user_session(
            user[0]
        )

        return {

            "success": True,

            "message":
                "Account created successfully",

            "user_id":
                user[0],

            "name":
                user[1],

            "email":
                user[2],

            "username":
                user[1],

            "access_token":
                token,

            "token_type":
                "bearer",

            "redirect":
                "/user_chat.html"

        }

    except HTTPException:

        if connection:
            connection.rollback()

        raise

    except Exception as error:

        print(
            "USER REGISTER ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to create account"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.post("/api/auth/login")
def user_login_api(data: UserLogin):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                user_id,
                name,
                email,
                password,
                active_status
            FROM user_access
            WHERE email = %s
            """,
            (data.email,)
        )

        user = cursor.fetchone()

        if not user:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        user_id = user[0]
        name = user[1]
        email = user[2]
        password = user[3]
        active_status = user[4]

        if not active_status:

            raise HTTPException(
                status_code=403,
                detail="User account is inactive"
            )

        if data.password != password:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        cursor.execute(
            """
            UPDATE user_access
            SET
                last_login = CURRENT_TIMESTAMP,
                last_activity = CURRENT_TIMESTAMP
            WHERE user_id = %s
            """,
            (user_id,)
        )

        connection.commit()

        token = create_user_session(
            user_id
        )

        return {

            "success": True,

            "message":
                "User login successful",

            "user_id":
                user_id,

            "name":
                name,

            "username":
                name,

            "email":
                email,

            "access_token":
                token,

            "token_type":
                "bearer",

            "redirect":
                "/user_chat.html"

        }

    except HTTPException:

        if connection:
            connection.rollback()

        raise

    except Exception as error:

        print(
            "USER LOGIN ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to login"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.post("/api/auth/logout")
def user_logout(
    authorization: str | None = Header(
        default=None
    )
):

    if authorization:

        if authorization.lower().startswith(
            "bearer "
        ):

            token = authorization[7:].strip()

            USER_SESSIONS.pop(
                token,
                None
            )

    return {

        "success": True,

        "message":
            "User logged out successfully",

        "redirect":
            "/index.html"

    }


@app.get("/api/auth/me")
def user_me(
    authorization: str | None = Header(
        default=None
    ),
    user_id: int | None = None
):

    user = get_authenticated_user(
        authorization,
        user_id
    )

    return {

        "success": True,

        "user_id":
            user["user_id"],

        "name":
            user["name"],

        "email":
            user["email"]

    }


# =========================================================
# USER CONVERSATIONS
# =========================================================

@app.post("/api/conversations")
def create_conversation(
    data: NewConversation,
    authorization: str | None = Header(
        default=None
    )
):

    connection = None
    cursor = None

    try:

        user = get_authenticated_user(
            authorization
        )

        user_id = user["user_id"]

        connection = get_db_connection()

        cursor = connection.cursor()

        title = (
            data.title.strip()
            if data.title
            else "New Conversation"
        )

        if not title:

            title = "New Conversation"

        conversation_id = (
            create_new_conversation(
                cursor,
                user_id,
                title
            )
        )

        connection.commit()

        return {

            "success": True,

            "message":
                "New conversation created successfully",

            "conversation_id":
                conversation_id,

            "user_id":
                user_id,

            "title":
                title,

            "created_at":
                datetime.now().isoformat(),

            "active_status":
                True

        }

    except HTTPException:

        if connection:
            connection.rollback()

        raise

    except Exception as error:

        print(
            "CREATE CONVERSATION ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to create conversation"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.get("/api/conversations")
def get_current_user_conversations(
    authorization: str | None = Header(
        default=None
    )
):

    connection = None
    cursor = None

    try:

        user = get_authenticated_user(
            authorization
        )

        user_id = user["user_id"]

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                conversation_id,
                user_id,
                title,
                MIN(created_at) AS created_at,
                MAX(updated_at) AS updated_at,
                BOOL_OR(active_status) AS active_status,
                COUNT(user_message) AS message_count,
                MAX(message_created_at) AS last_message_at

            FROM user_conversations

            WHERE user_id = %s

            GROUP BY
                conversation_id,
                user_id,
                title

            ORDER BY
                MAX(updated_at) DESC NULLS LAST,
                MIN(created_at) DESC NULLS LAST
            """,
            (user_id,)
        )

        conversations = cursor.fetchall()

        result = []

        for conversation in conversations:

            result.append({

                "conversation_id":
                    conversation[0],

                "user_id":
                    conversation[1],

                "title":
                    conversation[2],

                "created_at":
                    conversation[3].isoformat()
                    if conversation[3]
                    else None,

                "updated_at":
                    conversation[4].isoformat()
                    if conversation[4]
                    else None,

                "active_status":
                    conversation[5],

                "message_count":
                    conversation[6],

                "last_message_at":
                    conversation[7].isoformat()
                    if conversation[7]
                    else None

            })

        return {

            "success": True,

            "user_id":
                user_id,

            "name":
                user["name"],

            "email":
                user["email"],

            "conversations":
                result

        }

    except HTTPException:

        raise

    except Exception as error:

        print(
            "GET CURRENT USER CONVERSATIONS ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to get conversations"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.get("/api/conversations/current")
def get_current_conversation(
    authorization: str | None = Header(default=None)
):
    """Return the user's single persistent conversation and its messages."""

    connection = None
    cursor = None

    try:
        user = get_authenticated_user(authorization)
        user_id = user["user_id"]
        connection = get_db_connection()
        cursor = connection.cursor()

        conversation_id = create_new_conversation(
            cursor, user_id, "My Conversation"
        )
        connection.commit()

        cursor.execute(
            """
            SELECT conversation_id, user_id, title,
                   MIN(created_at) AS created_at,
                   MAX(updated_at) AS updated_at,
                   BOOL_OR(active_status) AS active_status
            FROM user_conversations
            WHERE conversation_id = %s AND user_id = %s
            GROUP BY conversation_id, user_id, title
            ORDER BY MIN(message_id) NULLS FIRST
            LIMIT 1
            """,
            (conversation_id, user_id)
        )
        conversation = cursor.fetchone()

        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found"
            )

        cursor.execute(
            """
            SELECT message_id, user_message, ai_response, message_created_at
            FROM user_conversations
            WHERE conversation_id = %s
              AND user_id = %s
              AND message_id IS NOT NULL
              AND user_message IS NOT NULL
            ORDER BY message_created_at ASC, message_id ASC
            """,
            (conversation_id, user_id)
        )
        rows = cursor.fetchall()

        messages = [
            {
                "message_id": row[0],
                "user_message": row[1],
                "ai_response": row[2],
                "message_created_at": row[3].isoformat() if row[3] else None
            }
            for row in rows
        ]

        return {
            "success": True,
            "user_id": user_id,
            "name": user["name"],
            "email": user["email"],
            "conversation": {
                "conversation_id": conversation[0],
                "user_id": conversation[1],
                "title": conversation[2] or "My Conversation",
                "created_at": conversation[3].isoformat() if conversation[3] else None,
                "updated_at": conversation[4].isoformat() if conversation[4] else None,
                "active_status": conversation[5]
            },
            "messages": messages
        }

    except HTTPException:
        if connection:
            connection.rollback()
        raise

    except Exception as error:
        print("GET CURRENT CONVERSATION ERROR:", error)
        if connection:
            connection.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to load conversation history"
        )

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.get(
    "/api/conversations/{conversation_id}"
)
def get_current_user_conversation(
    conversation_id: int,
    authorization: str | None = Header(
        default=None
    )
):

    connection = None
    cursor = None

    try:

        user = get_authenticated_user(
            authorization
        )

        user_id = user["user_id"]

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                conversation_id,
                user_id,
                title,
                MIN(created_at) AS created_at,
                MAX(updated_at) AS updated_at,
                BOOL_OR(active_status) AS active_status

            FROM user_conversations

            WHERE conversation_id = %s
            AND user_id = %s

            GROUP BY
                conversation_id,
                user_id,
                title
            """,
            (
                conversation_id,
                user_id
            )
        )

        conversation = cursor.fetchone()

        if not conversation:

            raise HTTPException(
                status_code=404,
                detail="Conversation not found"
            )

        if conversation[5] is False:

            raise HTTPException(
                status_code=400,
                detail="Conversation is inactive"
            )

        cursor.execute(
            """
            SELECT
                message_id,
                conversation_id,
                user_id,
                user_message,
                ai_response,
                message_created_at

            FROM user_conversations

            WHERE conversation_id = %s
            AND user_id = %s
            AND message_id IS NOT NULL
            AND user_message IS NOT NULL

            ORDER BY
                message_created_at ASC,
                message_id ASC
            """,
            (
                conversation_id,
                user_id
            )
        )

        messages = cursor.fetchall()

        result = []

        for message in messages:

            result.append({

                "message_id":
                    message[0],

                "conversation_id":
                    message[1],

                "user_id":
                    message[2],

                "user_message":
                    message[3],

                "ai_response":
                    message[4],

                "message_created_at":
                    message[5].isoformat()
                    if message[5]
                    else None

            })

        return {

            "success": True,

            "conversation": {

                "conversation_id":
                    conversation[0],

                "user_id":
                    conversation[1],

                "title":
                    conversation[2],

                "created_at":
                    conversation[3].isoformat()
                    if conversation[3]
                    else None,

                "updated_at":
                    conversation[4].isoformat()
                    if conversation[4]
                    else None,

                "active_status":
                    conversation[5]

            },

            "messages":
                result

        }

    except HTTPException:

        raise

    except Exception as error:

        print(
            "GET CURRENT USER CONVERSATION ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to get conversation"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# USER CHAT MESSAGE API
# =========================================================

@app.post("/api/chat/message")
def send_chat_message(
    data: ChatMessage,
    authorization: str | None = Header(
        default=None
    )
):

    connection = None
    cursor = None

    try:

        message = (
            data.message.strip()
            if data.message
            else ""
        )

        if not message:

            raise HTTPException(
                status_code=400,
                detail="Message cannot be empty"
            )

        # -------------------------------------------------
        # START RAG PIPELINE EARLY (valid session only)
        # It runs in parallel with the database work below.
        # -------------------------------------------------

        session_token = (
            authorization[7:].strip()
            if authorization
            and authorization.lower().startswith("bearer ")
            else ""
        )

        rag_future = (
            _rag_executor.submit(orchestrator_agent, message)
            if session_token in USER_SESSIONS
            else None
        )

        # -------------------------------------------------
        # AUTHENTICATE USER
        # -------------------------------------------------

        user = get_authenticated_user(
            authorization
        )

        user_id = user["user_id"]

        connection = get_db_connection()

        cursor = connection.cursor()

        # -------------------------------------------------
        # GET / CREATE CONVERSATION
        # -------------------------------------------------

        if data.conversation_id is not None:

            conversation_id = (
                get_or_create_conversation(
                    cursor,
                    user_id,
                    data.conversation_id
                )
            )

        else:

            conversation_id = (
                get_or_create_conversation(
                    cursor,
                    user_id,
                    None
                )
            )

        connection.commit()

        # -------------------------------------------------
        # RUN RAG PIPELINE
        # -------------------------------------------------

        try:

            final_answer = (
                rag_future.result()
                if rag_future
                else orchestrator_agent(message)
            )

        except RuntimeError as error:

            print(
                "AGENT/RAG ERROR:",
                error
            )

            raise HTTPException(
                status_code=503,
                detail="Unable to generate a response"
            )

        except Exception as error:

            print(
                "CHAT PIPELINE ERROR:",
                error
            )

            raise HTTPException(
                status_code=503,
                detail="Unable to generate a response"
            )

        # -------------------------------------------------
        # STORE MESSAGE
        # -------------------------------------------------

        message_id = store_chat_message(
            cursor,
            user_id,
            conversation_id,
            message,
            final_answer
        )

        connection.commit()

        # -------------------------------------------------
        # GET TITLE
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT title
            FROM user_conversations
            WHERE conversation_id = %s
            AND user_id = %s
            ORDER BY message_id ASC NULLS LAST
            LIMIT 1
            """,
            (
                conversation_id,
                user_id
            )
        )

        title_row = cursor.fetchone()

        title = (
            title_row[0]
            if title_row
            else "New Conversation"
        )

        return {

            "success": True,

            "message_id":
                message_id,

            "conversation_id":
                conversation_id,

            "user_id":
                user_id,

            "title":
                title,

            "user_message":
                message,

            "answer":
                final_answer

        }

    except HTTPException:

        if connection:
            connection.rollback()

        raise

    except Exception as error:

        print(
            "CHAT MESSAGE ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to process chat message"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.post("/api/admin/login")
def admin_login(data: AdminLogin):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                admin_id,
                name,
                email,
                password,
                active_status
            FROM admin_access
            WHERE email = %s
            """,
            (data.email,)
        )

        admin = cursor.fetchone()

        if not admin:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        admin_id = admin[0]
        name = admin[1]
        email = admin[2]
        password = admin[3]
        active_status = admin[4]

        if not active_status:

            raise HTTPException(
                status_code=403,
                detail="Admin account is inactive"
            )

        if data.password != password:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        return {

            "success": True,

            "message":
                "Admin login successful",

            "admin_id":
                admin_id,

            "name":
                name,

            "email":
                email

        }

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# RAG DOCUMENT MANAGEMENT
# =========================================================

@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    admin_id: int = Form(...)
):

    connection = None
    cursor = None

    try:

        # -------------------------------------------------
        # CHECK PDF
        # -------------------------------------------------

        if file.content_type != "application/pdf":

            raise HTTPException(
                status_code=400,
                detail="Only PDF files are allowed"
            )

        # -------------------------------------------------
        # READ FILE
        # -------------------------------------------------

        file_data = await file.read()

        if not file_data:

            raise HTTPException(
                status_code=400,
                detail="Uploaded PDF is empty"
            )

        # -------------------------------------------------
        # DATABASE CONNECTION
        # -------------------------------------------------

        connection = get_db_connection()

        cursor = connection.cursor()

        # -------------------------------------------------
        # CHECK ADMIN
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                admin_id,
                name
            FROM admin_access
            WHERE admin_id = %s
            AND active_status = TRUE
            """,
            (admin_id,)
        )

        admin = cursor.fetchone()

        if not admin:

            raise HTTPException(
                status_code=401,
                detail="Invalid admin"
            )

        file_size = len(file_data)

        # -------------------------------------------------
        # INSERT DOCUMENT INTO POSTGRESQL
        # -------------------------------------------------

        cursor.execute(
            """
            INSERT INTO rag_documents
            (
                document_name,
                file_size,
                file_data,
                admin_id
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s
            )
            RETURNING document_id
            """,
            (
                file.filename,
                file_size,
                None,  # the PDF itself lives in the Supabase bucket
                admin_id
            )
        )

        document_id = cursor.fetchone()[0]

        document_link = (
            f"/api/documents/{document_id}/file"
        )

        cursor.execute(
            """
            UPDATE rag_documents
            SET
                document_link = %s
            WHERE document_id = %s
            """,
            (
                document_link,
                document_id
            )
        )

        # -------------------------------------------------
        # PROCESS PDF
        # -------------------------------------------------

        if PdfReader is None:

            raise HTTPException(
                status_code=500,
                detail="PDF processing service is unavailable"
            )

        try:

            print(
                "PROCESSING PDF:",
                file.filename
            )

            reader = PdfReader(
                io.BytesIO(
                    file_data
                )
            )

            print(
                "PDF PAGE COUNT:",
                len(reader.pages)
            )

            pages = []

            for page_index, page in enumerate(
                reader.pages
            ):

                try:

                    text = page.extract_text()

                except Exception as error:

                    print(
                        f"PAGE {page_index + 1} "
                        f"TEXT EXTRACTION ERROR:",
                        error
                    )

                    text = ""

                pages.append(
                    (
                        page_index + 1,
                        text or ""
                    )
                )

            extracted_characters = sum(
                len(page_text)
                for _, page_text in pages
            )

            print(
                "TOTAL EXTRACTED CHARACTERS:",
                extracted_characters
            )

            # -------------------------------------------------
            # STORE PDF IN BUCKET + EMBED INTO SUPABASE
            # -------------------------------------------------

            upload_pdf_to_bucket(
                document_id,
                file_data
            )

            chunks_added = (
                add_document_to_vector_store(
                    document_id,
                    file.filename,
                    pages
                )
            )

            # -------------------------------------------------
            # IMPORTANT:
            # DO NOT REPORT SUCCESS IF ZERO CHUNKS
            # -------------------------------------------------

            if chunks_added == 0:

                raise RuntimeError(
                    "No text chunks were created from the PDF"
                )

        except HTTPException:

            raise

        except Exception as error:

            print(
                "PDF/SUPABASE PROCESSING ERROR:",
                error
            )

            # Undo partial Supabase writes
            try:
                delete_document(document_id)
            except Exception:
                pass

            delete_pdf_from_bucket(document_id)

            # Remove the PostgreSQL document because
            # indexing was unsuccessful.
            try:

                cursor.execute(
                    """
                    DELETE FROM rag_documents
                    WHERE document_id = %s
                    """,
                    (document_id,)
                )

            except Exception as delete_error:

                print(
                    "DOCUMENT CLEANUP ERROR:",
                    delete_error
                )

            connection.rollback()

            raise HTTPException(
                status_code=500,
                detail="Unable to add document to the knowledge base"
            )

        # -------------------------------------------------
        # COMMIT ONLY AFTER SUPABASE SUCCESS
        # -------------------------------------------------

        connection.commit()

        print(
            "DOCUMENT UPLOAD SUCCESS:",
            file.filename
        )

        print(
            "DOCUMENT ID:",
            document_id
        )

        print(
            "CHUNKS ADDED:",
            chunks_added
        )

        return {

            "success": True,

            "message":
                "Document uploaded successfully",

            "document_id":
                document_id,

            "document_name":
                file.filename,

            "document_link":
                document_link,

            "file_size":
                file_size,

            "admin_id":
                admin_id,

            "created_by":
                admin[1],

            "chunks_added":
                chunks_added

        }

    except HTTPException:

        if connection:
            connection.rollback()

        raise

    except Exception as error:

        print(
            "UPLOAD DOCUMENT ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to upload document"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# GET ALL RAG DOCUMENTS
# =========================================================

@app.get("/api/documents")
def get_documents():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                d.document_id,
                d.document_name,
                d.document_link,
                d.last_updated,
                d.file_size,
                d.is_removed,
                d.admin_id,
                a.name
            FROM rag_documents d
            LEFT JOIN admin_access a
            ON d.admin_id = a.admin_id
            ORDER BY d.last_updated DESC
            """
        )

        documents = cursor.fetchall()

        result = []

        for document in documents:

            result.append({

                "document_id":
                    document[0],

                "document_name":
                    document[1],

                "document_link":
                    document[2],

                "last_updated":
                    document[3].isoformat()
                    if document[3]
                    else None,

                "file_size":
                    document[4],

                "is_removed":
                    document[5],

                "admin_id":
                    document[6],

                "created_by":
                    document[7]
                    if document[7]
                    else "Unknown"

            })

        return result

    except Exception as error:

        print(
            "GET DOCUMENTS ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to get documents"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# GET ONE RAG DOCUMENT
# =========================================================

@app.get("/api/documents/{document_id}")
def get_document_details(
    document_id: int
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'rag_documents'
            AND column_name <> 'file_data'
            ORDER BY ordinal_position
            """
        )

        columns = cursor.fetchall()

        if not columns:

            raise HTTPException(
                status_code=404,
                detail="rag_documents table not found"
            )

        column_names = [
            column[0]
            for column in columns
        ]

        select_columns = ", ".join(
            '"' + column.replace('"', '""') + '"'
            for column in column_names
        )

        query = f"""
            SELECT {select_columns}
            FROM rag_documents
            WHERE document_id = %s
        """

        cursor.execute(
            query,
            (document_id,)
        )

        document = cursor.fetchone()

        if not document:

            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )

        result = {}

        for index, column_name in enumerate(
            column_names
        ):

            value = document[index]

            if isinstance(
                value,
                (datetime, date)
            ):

                value = value.isoformat()

            elif isinstance(
                value,
                bytes
            ):

                value = (
                    f"<binary data: "
                    f"{len(value)} bytes>"
                )

            result[column_name] = value

        result["pdf_view_link"] = (
            f"/api/documents/"
            f"{document_id}/file"
        )

        return {

            "success": True,

            "document": result

        }

    except HTTPException:

        raise

    except Exception as error:

        print(
            "GET DOCUMENT DETAILS ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to get document details"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# VIEW PDF DOCUMENT
# =========================================================

@app.get(
    "/api/documents/{document_id}/file",
    response_class=HTMLResponse
)
def view_document(document_id: int):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'rag_documents'
            AND column_name <> 'file_data'
            ORDER BY ordinal_position
            """
        )

        columns = cursor.fetchall()

        if not columns:

            raise HTTPException(
                status_code=404,
                detail="rag_documents table not found"
            )

        column_names = [
            column[0]
            for column in columns
        ]

        select_columns = ", ".join(
            '"' + column.replace('"', '""') + '"'
            for column in column_names
        )

        query = f"""
            SELECT
                {select_columns},
                file_data
            FROM rag_documents
            WHERE document_id = %s
        """

        cursor.execute(
            query,
            (document_id,)
        )

        document = cursor.fetchone()

        if not document:

            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )

        details = {}

        for index, column_name in enumerate(
            column_names
        ):

            value = document[index]

            if isinstance(
                value,
                (datetime, date)
            ):

                value = value.isoformat()

            elif isinstance(
                value,
                bytes
            ):

                value = (
                    f"<binary data: "
                    f"{len(value)} bytes>"
                )

            details[column_name] = value

        file_data = document[
            len(column_names)
        ]

        if not file_data:
            file_data = download_pdf_from_bucket(
                document_id
            )

        if not file_data:

            raise HTTPException(
                status_code=404,
                detail="PDF file data not found"
            )

        pdf_base64 = base64.b64encode(
            bytes(file_data)
        ).decode("utf-8")

        rows = ""

        for key, value in details.items():

            if value is None:

                display_value = "NULL"

            else:

                display_value = str(value)

            rows += f"""
                <tr>
                    <td class="key">
                        {key}
                    </td>

                    <td class="value">
                        {display_value}
                    </td>
                </tr>
            """

        html = f"""
        <!DOCTYPE html>

        <html lang="en">

        <head>

            <meta charset="UTF-8">

            <meta
                name="viewport"
                content="width=device-width, initial-scale=1.0"
            >

            <title>RAG Document Details</title>

            <style>

                * {{
                    box-sizing: border-box;
                }}

                body {{
                    margin: 0;
                    padding: 30px;
                    font-family:
                        Arial,
                        Helvetica,
                        sans-serif;
                    background: #071426;
                    color: white;
                }}

                .container {{
                    max-width: 1200px;
                    margin: auto;
                }}

                .header {{
                    margin-bottom: 25px;
                }}

                .header h1 {{
                    margin: 0;
                    color: #4ddcff;
                    font-size: 30px;
                }}

                .header p {{
                    color: #aebdcc;
                    margin-top: 8px;
                }}

                .details-card {{
                    background: #0d1f35;
                    border: 1px solid #193a58;
                    border-radius: 14px;
                    overflow: hidden;
                    margin-bottom: 30px;
                    box-shadow:
                        0 10px 35px
                        rgba(0,0,0,0.25);
                }}

                table {{
                    width: 100%;
                    border-collapse: collapse;
                }}

                tr {{
                    border-bottom:
                        1px solid #193a58;
                }}

                tr:last-child {{
                    border-bottom: none;
                }}

                td {{
                    padding: 15px;
                    vertical-align: top;
                }}

                .key {{
                    width: 30%;
                    font-weight: bold;
                    color: #4ddcff;
                }}

                .value {{
                    color: #e7f4ff;
                    word-break: break-word;
                }}

                .pdf-card {{
                    background: #0d1f35;
                    border: 1px solid #193a58;
                    border-radius: 14px;
                    padding: 20px;
                }}

                .pdf-title {{
                    color: #4ddcff;
                    font-size: 22px;
                    font-weight: bold;
                    margin-bottom: 15px;
                }}

                iframe {{
                    width: 100%;
                    height: 800px;
                    border: none;
                    border-radius: 8px;
                    background: white;
                }}

                .back-button {{
                    display: inline-block;
                    margin-bottom: 20px;
                    padding: 10px 18px;
                    background: #12395b;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                }}

                .back-button:hover {{
                    background: #19547e;
                }}

            </style>

        </head>

        <body>

            <div class="container">

                <a
                    href="/ad_dashboard.html"
                    class="back-button"
                >
                    ← Back
                </a>

                <div class="header">

                    <h1>
                        RAG Document Details
                    </h1>

                    <p>
                        Complete information from
                        the rag_documents table
                    </p>

                </div>

                <div class="details-card">

                    <table>

                        <tbody>

                            {rows}

                        </tbody>

                    </table>

                </div>

                <div class="pdf-card">

                    <div class="pdf-title">
                        PDF Document
                    </div>

                    <iframe
                        src="data:application/pdf;base64,{pdf_base64}"
                    >
                    </iframe>

                </div>

            </div>

        </body>

        </html>
        """

        return HTMLResponse(
            content=html
        )

    except HTTPException:

        raise

    except Exception as error:

        print(
            "VIEW DOCUMENT ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to view document"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# REMOVE RAG DOCUMENT
# =========================================================

@app.put("/api/documents/{document_id}/remove")
def remove_document(
    document_id: int
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT document_id
            FROM rag_documents
            WHERE document_id = %s
            """,
            (document_id,)
        )

        document = cursor.fetchone()

        if not document:

            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )

        delete_document(
            document_id
        )

        cursor.execute(
            """
            UPDATE rag_documents
            SET
                is_removed = TRUE,
                last_updated = CURRENT_TIMESTAMP
            WHERE document_id = %s
            """,
            (document_id,)
        )

        connection.commit()

        return {

            "success": True,

            "message":
                "Document removed successfully"

        }

    except HTTPException:

        if connection:
            connection.rollback()

        raise

    except Exception as error:

        print(
            "REMOVE DOCUMENT ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to remove document"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# PERMANENTLY DELETE RAG DOCUMENT
# =========================================================

@app.delete(
    "/api/documents/{document_id}/permanent"
)
def permanently_delete_document(
    document_id: int
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT document_id
            FROM rag_documents
            WHERE document_id = %s
            AND is_removed = TRUE
            """,
            (document_id,)
        )

        document = cursor.fetchone()

        if not document:

            raise HTTPException(
                status_code=404,
                detail="Removed document not found"
            )

        delete_document(
            document_id
        )

        cursor.execute(
            """
            DELETE FROM rag_documents
            WHERE document_id = %s
            AND is_removed = TRUE
            """,
            (document_id,)
        )

        if cursor.rowcount == 0:

            raise HTTPException(
                status_code=404,
                detail="Removed document not found"
            )

        connection.commit()

        delete_pdf_from_bucket(
            document_id
        )

        return {

            "success": True,

            "message":
                "Document permanently deleted"

        }

    except HTTPException:

        if connection:
            connection.rollback()

        raise

    except Exception as error:

        print(
            "PERMANENT DELETE ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to permanently delete document"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# ADMIN CHAT HISTORY
# =========================================================

@app.get(
    "/api/admin/chat-history/users"
)
def get_chat_history_users():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                ua.user_id,
                ua.name,
                ua.email,
                COUNT(
                    DISTINCT uc.conversation_id
                ) AS conversation_count,
                COUNT(
                    uc.message_id
                ) AS message_count,
                MAX(
                    uc.message_created_at
                ) AS last_message_at
            FROM user_access ua

            LEFT JOIN user_conversations uc
                ON ua.user_id = uc.user_id

            GROUP BY
                ua.user_id,
                ua.name,
                ua.email

            ORDER BY
                ua.user_id ASC
            """
        )

        users = cursor.fetchall()

        result = []

        for user in users:

            result.append({

                "user_id":
                    user[0],

                "name":
                    user[1],

                "email":
                    user[2],

                "display_name":
                    f"{user[1]} ({user[0]})",

                "conversation_count":
                    user[3],

                "message_count":
                    user[4],

                "last_message_at":
                    user[5].isoformat()
                    if user[5]
                    else None

            })

        return {

            "success": True,

            "users":
                result

        }

    except Exception as error:

        print(
            "GET ALL CHAT USERS ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to get all users"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.get(
    "/api/admin/chat-history/active-users"
)
def get_active_chat_users():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                ua.user_id,
                ua.name,
                ua.email,
                COUNT(
                    DISTINCT uc.conversation_id
                ) AS conversation_count,
                COUNT(
                    uc.message_id
                ) AS message_count,
                ua.last_activity
            FROM user_access ua

            LEFT JOIN user_conversations uc
                ON ua.user_id = uc.user_id

            WHERE
                ua.active_status = TRUE

            AND
                ua.last_activity >=
                CURRENT_TIMESTAMP - INTERVAL '30 minutes'

            GROUP BY
                ua.user_id,
                ua.name,
                ua.email,
                ua.last_activity

            ORDER BY
                ua.last_activity DESC
            """
        )

        users = cursor.fetchall()

        result = []

        for user in users:

            result.append({

                "user_id":
                    user[0],

                "name":
                    user[1],

                "email":
                    user[2],

                "display_name":
                    f"{user[1]} ({user[0]})",

                "conversation_count":
                    user[3],

                "message_count":
                    user[4],

                "last_activity":
                    user[5].isoformat()
                    if user[5]
                    else None

            })

        return {

            "success": True,

            "users":
                result

        }

    except Exception as error:

        print(
            "GET ACTIVE CHAT USERS ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to get active users"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.get(
    "/api/admin/chat-history/frequent-users"
)
def get_frequent_chat_users():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                ua.user_id,
                ua.name,
                ua.email,
                COUNT(
                    DISTINCT uc.conversation_id
                ) AS conversation_count,
                COUNT(
                    uc.message_id
                ) AS message_count,
                MAX(
                    uc.message_created_at
                ) AS last_message_at

            FROM user_access ua

            INNER JOIN user_conversations uc
                ON ua.user_id = uc.user_id

            GROUP BY
                ua.user_id,
                ua.name,
                ua.email

            ORDER BY
                COUNT(
                    DISTINCT uc.conversation_id
                ) DESC,

                ua.user_id ASC
            """
        )

        users = cursor.fetchall()

        result = []

        for user in users:

            result.append({

                "user_id":
                    user[0],

                "name":
                    user[1],

                "email":
                    user[2],

                "display_name":
                    f"{user[1]} ({user[0]})",

                "conversation_count":
                    user[3],

                "message_count":
                    user[4],

                "last_message_at":
                    user[5].isoformat()
                    if user[5]
                    else None

            })

        return {

            "success": True,

            "users":
                result

        }

    except Exception as error:

        print(
            "GET FREQUENT CHAT USERS ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to get frequent users"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.get(
    "/api/admin/chat-history/user/{user_id}/conversations"
)
def get_user_conversations(
    user_id: int
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                user_id,
                name,
                email
            FROM user_access
            WHERE user_id = %s
            """,
            (user_id,)
        )

        user = cursor.fetchone()

        if not user:

            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        cursor.execute(
            """
            SELECT
                conversation_id,
                user_id,
                title,
                MIN(created_at) AS created_at,
                MAX(updated_at) AS updated_at,
                BOOL_OR(active_status) AS active_status,
                COUNT(message_id) AS message_count,
                MAX(message_created_at) AS last_message_at

            FROM user_conversations

            WHERE user_id = %s

            GROUP BY
                conversation_id,
                user_id,
                title

            ORDER BY
                MAX(updated_at) DESC NULLS LAST,
                MIN(created_at) DESC NULLS LAST
            """,
            (user_id,)
        )

        conversations = cursor.fetchall()

        result = []

        for conversation in conversations:

            result.append({

                "conversation_id":
                    conversation[0],

                "user_id":
                    conversation[1],

                "title":
                    conversation[2],

                "created_at":
                    conversation[3].isoformat()
                    if conversation[3]
                    else None,

                "updated_at":
                    conversation[4].isoformat()
                    if conversation[4]
                    else None,

                "active_status":
                    conversation[5],

                "message_count":
                    conversation[6],

                "last_message_at":
                    conversation[7].isoformat()
                    if conversation[7]
                    else None

            })

        return {

            "success": True,

            "user_id":
                user[0],

            "name":
                user[1],

            "email":
                user[2],

            "display_name":
                f"{user[1]} ({user[0]})",

            "conversations":
                result

        }

    except HTTPException:

        raise

    except Exception as error:

        print(
            "GET USER CONVERSATIONS ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to get user conversations"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.get(
    "/api/admin/chat-history/conversation/{conversation_id}"
)
def get_admin_conversation_messages(
    conversation_id: int
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                message_id,
                conversation_id,
                user_id,
                user_message,
                ai_response,
                message_created_at

            FROM user_conversations

            WHERE conversation_id = %s
            AND message_id IS NOT NULL

            ORDER BY
                message_created_at ASC,
                message_id ASC
            """,
            (conversation_id,)
        )

        messages = cursor.fetchall()

        if not messages:

            raise HTTPException(
                status_code=404,
                detail="Conversation not found"
            )

        result = []

        for message in messages:

            result.append({

                "message_id":
                    message[0],

                "conversation_id":
                    message[1],

                "user_id":
                    message[2],

                "user_message":
                    message[3],

                "ai_response":
                    message[4],

                "message_created_at":
                    message[5].isoformat()
                    if message[5]
                    else None

            })

        return {

            "success": True,

            "conversation_id":
                conversation_id,

            "messages":
                result

        }

    except HTTPException:

        raise

    except Exception as error:

        print(
            "GET ADMIN CONVERSATION ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to get conversation messages"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# GENERATED FEEDBACK
# =========================================================

def create_generated_feedback_table(
    cursor
):

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_feedback
        (
            feedback_id SERIAL PRIMARY KEY,

            user_id INTEGER NOT NULL,

            conversation_id INTEGER,

            feedback_type VARCHAR(50)
                DEFAULT 'individual',

            feedback_text TEXT NOT NULL,

            created_at TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


@app.post("/api/admin/feedback/save")
def save_generated_feedback(
    data: GeneratedFeedback
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        create_generated_feedback_table(
            cursor
        )

        cursor.execute(
            """
            INSERT INTO generated_feedback
            (
                user_id,
                conversation_id,
                feedback_type,
                feedback_text
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s
            )
            RETURNING
                feedback_id,
                created_at
            """,
            (
                data.user_id,
                data.conversation_id,
                data.feedback_type,
                data.feedback_text
            )
        )

        feedback = cursor.fetchone()

        connection.commit()

        return {

            "success": True,

            "message":
                "Feedback generated and saved successfully",

            "feedback_id":
                feedback[0],

            "created_at":
                feedback[1].isoformat()
                if feedback[1]
                else None

        }

    except Exception as error:

        print(
            "SAVE GENERATED FEEDBACK ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to save generated feedback"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.post(
    "/api/admin/feedback/generate/{conversation_id}"
)
def generate_feedback(
    conversation_id: int
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                user_id,
                user_message,
                ai_response,
                message_created_at

            FROM user_conversations

            WHERE conversation_id = %s
            AND message_id IS NOT NULL

            ORDER BY
                message_created_at ASC,
                message_id ASC
            """,
            (conversation_id,)
        )

        messages = cursor.fetchall()

        if not messages:

            raise HTTPException(
                status_code=404,
                detail="Conversation not found"
            )

        user_id = messages[0][0]

        conversation = []

        for message in messages:

            conversation.append({

                "user_id":
                    user_id,

                "user_message":
                    message[1],

                "ai_response":
                    message[2],

                "message_created_at":
                    message[3].isoformat()
                    if message[3]
                    else None

            })

        try:

            feedback_text = (
                feedback_generation_agent(
                    conversation
                )
            )

        except Exception as error:

            print(
                "FEEDBACK AGENT ERROR:",
                error
            )

            raise HTTPException(
                status_code=503,
                detail="Unable to generate feedback"
            )

        create_generated_feedback_table(
            cursor
        )

        cursor.execute(
            """
            INSERT INTO generated_feedback
            (
                user_id,
                conversation_id,
                feedback_type,
                feedback_text
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s
            )
            RETURNING
                feedback_id,
                created_at
            """,
            (
                user_id,
                conversation_id,
                "individual",
                feedback_text
            )
        )

        saved_feedback = cursor.fetchone()

        connection.commit()

        return {

            "success": True,

            "feedback_id":
                saved_feedback[0],

            "user_id":
                user_id,

            "conversation_id":
                conversation_id,

            "feedback_type":
                "individual",

            "feedback_text":
                feedback_text,

            "created_at":
                saved_feedback[1].isoformat()
                if saved_feedback[1]
                else None

        }

    except HTTPException:

        if connection:
            connection.rollback()

        raise

    except Exception as error:

        print(
            "GENERATE FEEDBACK ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to generate feedback"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# FEEDBACK GENERATOR USER LISTS
# =========================================================

@app.get("/api/admin/feedback/users")
def get_feedback_users():

    return get_chat_history_users()


@app.get("/api/admin/feedback/active-users")
def get_feedback_active_users():

    return get_active_chat_users()


@app.get("/api/admin/feedback/frequent-users")
def get_feedback_frequent_users():

    return get_frequent_chat_users()


@app.get(
    "/api/admin/feedback/user/{user_id}/conversations"
)
def get_feedback_user_conversations(
    user_id: int
):

    return get_user_conversations(
        user_id
    )


@app.get(
    "/api/admin/feedback/conversation/{conversation_id}"
)
def get_feedback_conversation(
    conversation_id: int
):

    return get_admin_conversation_messages(
        conversation_id
    )


# =========================================================
# GENERATED FEEDBACK OVERVIEW
# =========================================================

@app.get("/api/admin/feedback")
def get_generated_feedback():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        create_generated_feedback_table(
            cursor
        )

        connection.commit()

        cursor.execute(
            """
            SELECT
                gf.feedback_id,
                gf.user_id,

                COALESCE(
                    ua.name,
                    'Unknown User'
                ) AS user_name,

                gf.conversation_id,

                gf.feedback_type,

                gf.feedback_text,

                gf.created_at

            FROM generated_feedback gf

            LEFT JOIN user_access ua
                ON gf.user_id = ua.user_id

            ORDER BY
                gf.created_at DESC
            """
        )

        feedbacks = cursor.fetchall()

        result = []

        for feedback in feedbacks:

            result.append({

                "feedback_id":
                    feedback[0],

                "user_id":
                    feedback[1],

                "user_name":
                    feedback[2],

                "display_name":
                    f"{feedback[2]} ({feedback[1]})",

                "conversation_id":
                    feedback[3],

                "feedback_type":
                    feedback[4],

                "feedback_text":
                    feedback[5],

                "created_at":
                    feedback[6].isoformat()
                    if feedback[6]
                    else None

            })

        return {

            "success": True,

            "feedback":
                result

        }

    except Exception as error:

        print(
            "GET GENERATED FEEDBACK ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to get generated feedback"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.get(
    "/api/admin/feedback/user/{user_id}"
)
def get_user_generated_feedback(
    user_id: int
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        create_generated_feedback_table(
            cursor
        )

        connection.commit()

        cursor.execute(
            """
            SELECT
                gf.feedback_id,
                gf.user_id,

                COALESCE(
                    ua.name,
                    'Unknown User'
                ) AS user_name,

                gf.conversation_id,

                gf.feedback_type,

                gf.feedback_text,

                gf.created_at

            FROM generated_feedback gf

            LEFT JOIN user_access ua
                ON gf.user_id = ua.user_id

            WHERE gf.user_id = %s

            ORDER BY
                gf.created_at DESC
            """,
            (user_id,)
        )

        feedbacks = cursor.fetchall()

        result = []

        for feedback in feedbacks:

            result.append({

                "feedback_id":
                    feedback[0],

                "user_id":
                    feedback[1],

                "user_name":
                    feedback[2],

                "display_name":
                    f"{feedback[2]} ({feedback[1]})",

                "conversation_id":
                    feedback[3],

                "feedback_type":
                    feedback[4],

                "feedback_text":
                    feedback[5],

                "created_at":
                    feedback[6].isoformat()
                    if feedback[6]
                    else None

            })

        return {

            "success": True,

            "user_id":
                user_id,

            "feedback":
                result

        }

    except Exception as error:

        print(
            "GET USER GENERATED FEEDBACK ERROR:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to get user feedback"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# ADMIN STATISTICS
# =========================================================

@app.get("/api/admin/statistics")
def admin_statistics():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        # -------------------------------------------------
        # TOTAL CONVERSATIONS
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(
                DISTINCT conversation_id
            )
            FROM user_conversations
            """
        )

        total_conversations = (
            cursor.fetchone()[0]
        )

        # -------------------------------------------------
        # UNIQUE USERS
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(
                DISTINCT user_id
            )
            FROM user_conversations
            """
        )

        unique_users = (
            cursor.fetchone()[0]
        )

        # -------------------------------------------------
        # MESSAGES TODAY
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM user_conversations
            WHERE message_created_at::date =
                  CURRENT_DATE
            """
        )

        messages_today = (
            cursor.fetchone()[0]
        )

        # -------------------------------------------------
        # ACTIVE USERS
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM user_access
            WHERE active_status = TRUE
            AND last_activity >=
                CURRENT_TIMESTAMP -
                INTERVAL '30 minutes'
            """
        )

        active_users = (
            cursor.fetchone()[0]
        )

        # -------------------------------------------------
        # MOST FREQUENT USER
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                ua.user_id,
                ua.name,
                COUNT(
                    DISTINCT uc.conversation_id
                ) AS conversation_count

            FROM user_access ua

            INNER JOIN user_conversations uc
                ON ua.user_id = uc.user_id

            GROUP BY
                ua.user_id,
                ua.name

            ORDER BY
                COUNT(
                    DISTINCT uc.conversation_id
                ) DESC

            LIMIT 1
            """
        )

        frequent_user = (
            cursor.fetchone()
        )

        if frequent_user:

            frequent_user_id = (
                frequent_user[0]
            )

            frequent_user_name = (
                frequent_user[1]
            )

            frequent_conversations = (
                frequent_user[2]
            )

        else:

            frequent_user_id = None

            frequent_user_name = None

            frequent_conversations = 0

        return {

            "success": True,

            "total_conversations":
                total_conversations,

            "unique_users":
                unique_users,

            "messages_today":
                messages_today,

            "active_users":
                active_users,

            "frequent_user_id":
                frequent_user_id,

            "frequent_user_name":
                frequent_user_name,

            "frequent_user_conversations":
                frequent_conversations

        }

    except Exception as error:

        print(
            "ADMIN STATISTICS ERROR:",
            error
        )

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to get statistics"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()
