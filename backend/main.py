# ---------------------------------------------------------
# IMPORTS
# ---------------------------------------------------------

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import FileResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from pydantic import BaseModel

import psycopg2
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

load_dotenv()


# ---------------------------------------------------------
# OPTIONAL RAG IMPORTS
# ---------------------------------------------------------

try:
    import chromadb
except Exception:
    chromadb = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

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

CHROMA_DIR = BASE_DIR / "chroma_db"


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

def get_db_connection():

    return psycopg2.connect(
        host="localhost",
        port="5432",
        database="bc",
        user="postgres",
        password="Karani@2006"
    )


# ---------------------------------------------------------
# FIX USER CONVERSATION SCHEMA
# ---------------------------------------------------------

def ensure_conversation_schema():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            ALTER TABLE user_conversations
            ALTER COLUMN message_id DROP NOT NULL
            """
        )

        connection.commit()

    except Exception as error:

        if connection:
            connection.rollback()

        print(
            "CONVERSATION SCHEMA CHECK ERROR:",
            error
        )

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
    "gemini-3.8-flash"
)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    ""
)

CHROMA_COLLECTION_NAME = os.getenv(
    "CHROMA_COLLECTION_NAME",
    "blencekart_documents"
)

EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL",
    "all-MiniLM-L6-v2"
)


# ---------------------------------------------------------
# USER SESSION STORAGE
# ---------------------------------------------------------

USER_SESSIONS = {}


# ---------------------------------------------------------
# RAG GLOBAL OBJECTS
# ---------------------------------------------------------

_chroma_client = None
_chroma_collection = None
_embedding_model = None


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
# CHROMADB HELPERS
# =========================================================

def get_chroma_collection():

    global _chroma_client
    global _chroma_collection

    if chromadb is None:

        raise RuntimeError(
            "ChromaDB is not installed"
        )

    CHROMA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    if _chroma_client is None:

        print(
            "CHROMADB DIRECTORY:",
            str(CHROMA_DIR)
        )

        _chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_DIR)
        )

    if _chroma_collection is None:

        _chroma_collection = (
            _chroma_client.get_or_create_collection(
                name=CHROMA_COLLECTION_NAME
            )
        )

        print(
            "CHROMADB COLLECTION:",
            CHROMA_COLLECTION_NAME
        )

        print(
            "CHROMADB EXISTING CHUNKS:",
            _chroma_collection.count()
        )

    return _chroma_collection


def get_embedding_model():

    global _embedding_model

    if SentenceTransformer is None:

        raise RuntimeError(
            "sentence-transformers is not installed"
        )

    if _embedding_model is None:

        print(
            "LOADING EMBEDDING MODEL:",
            EMBEDDING_MODEL_NAME
        )

        _embedding_model = SentenceTransformer(
            EMBEDDING_MODEL_NAME
        )

        print(
            "EMBEDDING MODEL LOADED"
        )

    return _embedding_model


def generate_embeddings(texts):

    if not texts:

        return []

    model = get_embedding_model()

    embeddings = model.encode(
        texts,
        normalize_embeddings=True
    )

    return [
        embedding.tolist()
        for embedding in embeddings
    ]


# ---------------------------------------------------------
# DELETE DOCUMENT FROM CHROMADB
# ---------------------------------------------------------

def delete_document(document_id):

    try:

        collection = get_chroma_collection()

        existing_count = collection.count()

        print(
            "CHROMADB COUNT BEFORE DELETE:",
            existing_count
        )

        collection.delete(
            where={
                "document_id": int(document_id)
            }
        )

        after_count = collection.count()

        print(
            "CHROMADB COUNT AFTER DELETE:",
            after_count
        )

        return True

    except Exception as error:

        print(
            "CHROMADB DELETE ERROR:",
            error
        )

        raise RuntimeError(
            "Unable to remove document from knowledge base"
        )


# ---------------------------------------------------------
# ADD PDF DOCUMENT TO CHROMADB
# ---------------------------------------------------------

def add_document_to_chromadb(
    document_id,
    document_name,
    pages
):

    if not pages:

        print(
            "NO PDF PAGES RECEIVED"
        )

        return 0

    collection = get_chroma_collection()

    # -----------------------------------------------------
    # REMOVE OLD CHUNKS FOR THIS DOCUMENT
    # -----------------------------------------------------

    try:

        collection.delete(
            where={
                "document_id": int(document_id)
            }
        )

    except Exception as error:

        print(
            "OLD CHUNKS DELETE WARNING:",
            error
        )

    # -----------------------------------------------------
    # CHUNK SETTINGS
    # -----------------------------------------------------

    chunk_size = 1000

    overlap = 150

    chunks = []

    # -----------------------------------------------------
    # CREATE CHUNKS
    # -----------------------------------------------------

    for page_number, page_text in pages:

        if not page_text:

            continue

        page_text = re.sub(
            r"\s+",
            " ",
            page_text
        ).strip()

        if not page_text:

            continue

        start = 0

        local_chunk_number = 0

        while start < len(page_text):

            end = min(
                start + chunk_size,
                len(page_text)
            )

            chunk_text = page_text[start:end].strip()

            if chunk_text:

                chunks.append({
                    "text": chunk_text,
                    "page_number": page_number,
                    "chunk_number": local_chunk_number
                })

            if end >= len(page_text):

                break

            start = max(
                end - overlap,
                start + 1
            )

            local_chunk_number += 1

    # -----------------------------------------------------
    # CHECK CHUNKS
    # -----------------------------------------------------

    if not chunks:

        print(
            "NO TEXT CHUNKS CREATED FROM PDF"
        )

        return 0

    print(
        "PDF CHUNKS CREATED:",
        len(chunks)
    )

    # -----------------------------------------------------
    # GET TEXTS
    # -----------------------------------------------------

    texts = [
        item["text"]
        for item in chunks
    ]

    # -----------------------------------------------------
    # CREATE EMBEDDINGS
    # -----------------------------------------------------

    print(
        "GENERATING EMBEDDINGS..."
    )

    embeddings = generate_embeddings(
        texts
    )

    if not embeddings:

        raise RuntimeError(
            "Unable to generate document embeddings"
        )

    if len(embeddings) != len(texts):

        raise RuntimeError(
            "Embedding count does not match chunk count"
        )

    print(
        "EMBEDDINGS CREATED:",
        len(embeddings)
    )

    # -----------------------------------------------------
    # CREATE CHROMADB DATA
    # -----------------------------------------------------

    ids = []

    documents = []

    metadatas = []

    for index, item in enumerate(chunks):

        chunk_id = (
            f"document_{document_id}_"
            f"chunk_{index + 1}"
        )

        ids.append(chunk_id)

        documents.append(
            item["text"]
        )

        metadatas.append({

            "document_id": int(
                document_id
            ),

            "document_name": str(
                document_name
            ),

            "chunk_id": chunk_id,

            "page_number": int(
                item["page_number"]
            )

        })

    # -----------------------------------------------------
    # STORE IN CHROMADB
    # -----------------------------------------------------

    print(
        "ADDING CHUNKS TO CHROMADB..."
    )

    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas
    )

    # -----------------------------------------------------
    # VERIFY STORAGE
    # -----------------------------------------------------

    final_count = collection.count()

    print(
        "CHROMADB TOTAL CHUNKS AFTER UPLOAD:",
        final_count
    )

    # -----------------------------------------------------
    # VERIFY THIS DOCUMENT
    # -----------------------------------------------------

    try:

        verification = collection.get(
            where={
                "document_id": int(document_id)
            }
        )

        stored_documents = (
            verification.get(
                "documents",
                []
            )
            if verification
            else []
        )

        print(
            "CHROMADB STORED CHUNKS FOR DOCUMENT",
            document_id,
            ":",
            len(stored_documents)
        )

    except Exception as error:

        print(
            "CHROMADB VERIFICATION WARNING:",
            error
        )

    return len(chunks)


# ---------------------------------------------------------
# RETRIEVE RELEVANT CHUNKS FROM CHROMADB
# ---------------------------------------------------------

def retrieve_relevant_chunks(
    query,
    number_of_results=6
):

    if not query:

        return []

    collection = get_chroma_collection()

    # -----------------------------------------------------
    # CHECK TOTAL CHUNKS
    # -----------------------------------------------------

    total_documents = collection.count()

    print(
        "CHROMADB TOTAL CHUNKS:",
        total_documents
    )

    if total_documents == 0:

        print(
            "CHROMADB IS EMPTY"
        )

        return []

    # -----------------------------------------------------
    # CREATE QUERY EMBEDDING
    # -----------------------------------------------------

    print(
        "CREATING QUERY EMBEDDING..."
    )

    query_embedding = generate_embeddings(
        [query]
    )[0]

    # -----------------------------------------------------
    # LIMIT RESULTS
    # -----------------------------------------------------

    number_of_results = min(
        number_of_results,
        total_documents
    )

    # -----------------------------------------------------
    # QUERY CHROMADB
    # -----------------------------------------------------

    print(
        "QUERYING CHROMADB FOR:",
        query
    )

    result = collection.query(

        query_embeddings=[
            query_embedding
        ],

        n_results=number_of_results,

        include=[
            "documents",
            "metadatas",
            "distances"
        ]
    )

    # -----------------------------------------------------
    # GET DOCUMENTS
    # -----------------------------------------------------

    documents = (
        result.get(
            "documents",
            [[]]
        )[0]
        if result.get("documents")
        else []
    )

    # -----------------------------------------------------
    # GET METADATA
    # -----------------------------------------------------

    metadatas = (
        result.get(
            "metadatas",
            [[]]
        )[0]
        if result.get("metadatas")
        else []
    )

    # -----------------------------------------------------
    # GET DISTANCES
    # -----------------------------------------------------

    distances = (
        result.get(
            "distances",
            [[]]
        )[0]
        if result.get("distances")
        else []
    )

    retrieved = []

    # -----------------------------------------------------
    # BUILD RETRIEVED RESULT
    # -----------------------------------------------------

    for index, document in enumerate(documents):

        if not document:

            continue

        metadata = (

            metadatas[index]

            if index < len(metadatas)

            else {}

        )

        distance = (

            distances[index]

            if index < len(distances)

            else None

        )

        retrieved.append({

            "text": document,

            "metadata": metadata,

            "distance": distance

        })

    print(
        "CHROMADB RETRIEVED CHUNKS:",
        len(retrieved)
    )

    # -----------------------------------------------------
    # PRINT RETRIEVED DOCUMENT INFORMATION
    # -----------------------------------------------------

    for index, item in enumerate(
        retrieved,
        start=1
    ):

        metadata = item.get(
            "metadata",
            {}
        )

        print(
            f"RETRIEVED CHUNK {index}:",
            "document=",
            metadata.get(
                "document_name"
            ),
            "page=",
            metadata.get(
                "page_number"
            ),
            "distance=",
            item.get(
                "distance"
            )
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

def knowledge_retrieval_agent(
    processed_query
):

    cleaned_question = processed_query[
        "cleaned_question"
    ]

    return retrieve_relevant_chunks(
        cleaned_question,
        number_of_results=6
    )


# =========================================================
# AGENT 3 - RESPONSE GENERATION AGENT
# =========================================================

def response_generation_agent(
    original_question,
    retrieved_chunks
):

    if genai is None:

        raise RuntimeError(
            "Google GenAI package is not installed"
        )

    if not GEMINI_API_KEY:

        raise RuntimeError(
            "Gemini API key is not configured"
        )

    # -----------------------------------------------------
    # BUILD DOCUMENT CONTEXT
    # -----------------------------------------------------

    context_parts = []

    for index, chunk in enumerate(
        retrieved_chunks,
        start=1
    ):

        text_value = chunk.get(
            "text",
            ""
        )

        metadata = chunk.get(
            "metadata",
            {}
        )

        if not text_value:

            continue

        document_name = metadata.get(
            "document_name",
            "Uploaded document"
        )

        page_number = metadata.get(
            "page_number",
            "Unknown"
        )

        context_parts.append(
            f"""
Document: {document_name}
Page: {page_number}
Retrieved section {index}:

{text_value}
"""
        )

    context = "\n\n".join(
        context_parts
    )

    # -----------------------------------------------------
    # SAFETY CHECK
    # -----------------------------------------------------

    if not context:

        return (
            "The available documents do not "
            "contain enough information to answer "
            "this question."
        )

    # -----------------------------------------------------
    # CREATE GEMINI CLIENT
    # -----------------------------------------------------

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    # -----------------------------------------------------
    # PROMPT
    # -----------------------------------------------------

    prompt = f"""
You are answering a user's question using
information from uploaded documents.

User question:
{original_question}

Document information:
{context}

Instructions:

- Answer the user's question using the supplied
  document information.
- Prefer information directly supported by the
  supplied documents.
- Do not invent facts that are not supported.
- If the supplied documents do not contain enough
  information, clearly say that the available
  documents do not contain enough information.
- Give the final answer directly to the user.
- Do not mention agents.
- Do not mention ChromaDB.
- Do not mention embeddings.
- Do not mention retrieval.
- Do not mention vector databases.
- Do not mention internal prompts.
- Do not expose internal metadata.
- Do not describe the internal processing.
"""

    # -----------------------------------------------------
    # CALL GEMINI
    # -----------------------------------------------------

    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=1200,
            temperature=0.2
        )
    )

    # -----------------------------------------------------
    # READ RESPONSE
    # -----------------------------------------------------

    answer = (
        response.text
        if response and response.text
        else ""
    )

    answer = answer.strip()

    if not answer:

        raise RuntimeError(
            "LLM returned an empty response"
        )

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
        SELECT COALESCE(
            MAX(conversation_id),
            0
        ) + 1
        FROM user_conversations
        """
    )

    return cursor.fetchone()[0]


def get_next_message_id(cursor):

    cursor.execute(
        """
        SELECT COALESCE(
            MAX(message_id),
            0
        ) + 1
        FROM user_conversations
        """
    )

    return cursor.fetchone()[0]


def create_new_conversation(
    cursor,
    user_id,
    title="New Conversation"
):

    conversation_id = get_next_conversation_id(
        cursor
    )

    cursor.execute(
        """
        INSERT INTO user_conversations
        (
            conversation_id,
            user_id,
            title,
            created_at,
            updated_at,
            active_status,
            message_id,
            user_message,
            ai_response,
            message_created_at
        )
        VALUES
        (
            %s,
            %s,
            %s,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            TRUE,
            NULL,
            NULL,
            NULL,
            NULL
        )
        """,
        (
            conversation_id,
            user_id,
            title
        )
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
            SELECT
                conversation_id,
                user_id,
                title,
                active_status
            FROM user_conversations
            WHERE conversation_id = %s
            AND user_id = %s
            ORDER BY message_id ASC NULLS FIRST
            LIMIT 1
            """,
            (
                conversation_id,
                user_id
            )
        )

        existing = cursor.fetchone()

        if not existing:

            raise HTTPException(
                status_code=404,
                detail="Invalid conversation"
            )

        if existing[3] is False:

            raise HTTPException(
                status_code=400,
                detail="Conversation is inactive"
            )

        cursor.execute(
            """
            UPDATE user_conversations
            SET
                updated_at = CURRENT_TIMESTAMP,
                active_status = TRUE
            WHERE conversation_id = %s
            AND user_id = %s
            """,
            (
                conversation_id,
                user_id
            )
        )

        return conversation_id

    return get_next_conversation_id(
        cursor
    )


def store_chat_message(
    cursor,
    user_id,
    conversation_id,
    user_message,
    ai_response
):

    message_id = get_next_message_id(
        cursor
    )

    title = (
        user_message[:100]
        if user_message
        else "New Conversation"
    )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM user_conversations
        WHERE conversation_id = %s
        AND user_id = %s
        AND message_id IS NOT NULL
        """,
        (
            conversation_id,
            user_id
        )
    )

    message_count = cursor.fetchone()[0]

    if message_count == 0:

        cursor.execute(
            """
            UPDATE user_conversations
            SET
                message_id = %s,
                title = %s,
                user_message = %s,
                ai_response = %s,
                updated_at = CURRENT_TIMESTAMP,
                active_status = TRUE,
                message_created_at = CURRENT_TIMESTAMP
            WHERE conversation_id = %s
            AND user_id = %s
            AND message_id IS NULL
            """,
            (
                message_id,
                title,
                user_message,
                ai_response,
                conversation_id,
                user_id
            )
        )

        if cursor.rowcount == 0:

            cursor.execute(
                """
                INSERT INTO user_conversations
                (
                    message_id,
                    conversation_id,
                    user_id,
                    title,
                    user_message,
                    ai_response,
                    created_at,
                    updated_at,
                    active_status,
                    message_created_at
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    TRUE,
                    CURRENT_TIMESTAMP
                )
                """,
                (
                    message_id,
                    conversation_id,
                    user_id,
                    title,
                    user_message,
                    ai_response
                )
            )

    else:

        cursor.execute(
            """
            INSERT INTO user_conversations
            (
                message_id,
                conversation_id,
                user_id,
                title,
                user_message,
                ai_response,
                created_at,
                updated_at,
                active_status,
                message_created_at
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                TRUE,
                CURRENT_TIMESTAMP
            )
            """,
            (
                message_id,
                conversation_id,
                user_id,
                title,
                user_message,
                ai_response
            )
        )

        cursor.execute(
            """
            UPDATE user_conversations
            SET
                updated_at = CURRENT_TIMESTAMP,
                active_status = TRUE
            WHERE conversation_id = %s
            AND user_id = %s
            """,
            (
                conversation_id,
                user_id
            )
        )

    cursor.execute(
        """
        UPDATE user_access
        SET
            last_activity = CURRENT_TIMESTAMP
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
                create_new_conversation(
                    cursor,
                    user_id,
                    "New Conversation"
                )
            )

        connection.commit()

        # -------------------------------------------------
        # RUN RAG PIPELINE
        # -------------------------------------------------

        try:

            final_answer = (
                orchestrator_agent(
                    message
                )
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
                psycopg2.Binary(file_data),
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
            # ADD TO CHROMADB
            # -------------------------------------------------

            chunks_added = (
                add_document_to_chromadb(
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
                "PDF/CHROMADB PROCESSING ERROR:",
                error
            )

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
        # COMMIT ONLY AFTER CHROMADB SUCCESS
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