# ---------------------------------------------------------
# IMPORTS
# ---------------------------------------------------------

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from pydantic import BaseModel

import psycopg2
import json
import base64

from datetime import datetime, date


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

def get_db_connection():

    return psycopg2.connect(

        host="localhost",

        port="5432",

        database="bc",

        user="postgres",

        password="Karani@2006"
    )


# ---------------------------------------------------------
# ADMIN LOGIN DATA
# ---------------------------------------------------------

class AdminLogin(BaseModel):

    email: str

    password: str


# ---------------------------------------------------------
# USER SIGNUP DATA
# ---------------------------------------------------------

class UserRegister(BaseModel):

    name: str

    email: str

    password: str


# ---------------------------------------------------------
# USER LOGIN DATA
# ---------------------------------------------------------

class UserLogin(BaseModel):

    email: str

    password: str


# ---------------------------------------------------------
# GENERATED FEEDBACK DATA
# ---------------------------------------------------------

class GeneratedFeedback(BaseModel):

    user_id: int

    conversation_id: int | None = None

    feedback_type: str = "individual"

    feedback_text: str


# ---------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------

@app.get("/")
def home():

    return FileResponse(
        FRONTEND_DIR / "index.html"
    )


# ---------------------------------------------------------
# INDEX.HTML PAGE
# ---------------------------------------------------------

@app.get("/index.html")
def index():

    return FileResponse(
        FRONTEND_DIR / "index.html"
    )


# ---------------------------------------------------------
# ADMIN LOGIN PAGE
# ---------------------------------------------------------

@app.get("/ad_login.html")
def admin_login_page():

    return FileResponse(
        FRONTEND_DIR / "ad_login.html"
    )


# ---------------------------------------------------------
# ADMIN DASHBOARD PAGE
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# RAG DOCUMENTATION PAGE
# ---------------------------------------------------------

@app.get("/rag_document.html")
def rag_document():

    return FileResponse(
        FRONTEND_DIR / "rag_document.html"
    )


# ---------------------------------------------------------
# USER LOGIN PAGE
# ---------------------------------------------------------

@app.get("/user_login.html")
async def user_login():

    return FileResponse(
        FRONTEND_DIR / "user_login.html"
    )


# =========================================================
# USER AUTHENTICATION
# =========================================================


# ---------------------------------------------------------
# USER SIGNUP API
# ---------------------------------------------------------

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


        return {

            "success": True,

            "message": "Account created successfully",

            "user_id": user[0],

            "name": user[1],

            "email": user[2]

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


# ---------------------------------------------------------
# USER LOGIN API
# ---------------------------------------------------------

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


        return {

            "success": True,

            "message": "User login successful",

            "user_id": user_id,

            "name": name,

            "username": name,

            "email": email

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


# =========================================================
# ADMIN LOGIN
# =========================================================


# ---------------------------------------------------------
# ADMIN LOGIN API
# ---------------------------------------------------------

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

            "message": "Admin login successful",

            "admin_id": admin_id,

            "name": name,

            "email": email

        }


    finally:

        if cursor:

            cursor.close()

        if connection:

            connection.close()


# =========================================================
# RAG DOCUMENT MANAGEMENT
# =========================================================


# ---------------------------------------------------------
# UPLOAD RAG DOCUMENT
# ---------------------------------------------------------

@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    admin_id: int = Form(...)
):

    connection = None
    cursor = None

    try:

        if file.content_type != "application/pdf":

            raise HTTPException(
                status_code=400,
                detail="Only PDF files are allowed"
            )


        file_data = await file.read()


        connection = get_db_connection()

        cursor = connection.cursor()


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


        connection.commit()


        return {

            "success": True,

            "message": "Document uploaded successfully",

            "document_id": document_id,

            "document_name": file.filename,

            "document_link": document_link,

            "file_size": file_size,

            "admin_id": admin_id,

            "created_by": admin[1]

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


# ---------------------------------------------------------
# GET ALL RAG DOCUMENTS
# ---------------------------------------------------------

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

                "document_id": document[0],

                "document_name": document[1],

                "document_link": document[2],

                "last_updated":
                    document[3].isoformat()
                    if document[3]
                    else None,

                "file_size": document[4],

                "is_removed": document[5],

                "admin_id": document[6],

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
# GET ALL DETAILS OF ONE RAG DOCUMENT
# =========================================================

@app.get("/api/documents/{document_id}")
def get_document_details(document_id: int):

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


        for index, column_name in enumerate(column_names):

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

                value = f"<binary data: {len(value)} bytes>"


            result[column_name] = value


        result["pdf_view_link"] = (
            f"/api/documents/{document_id}/file"
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


        for index, column_name in enumerate(column_names):

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

                value = f"<binary data: {len(value)} bytes>"


            details[column_name] = value


        file_data = document[len(column_names)]


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
                    href="http://127.0.0.1:8000/ad_dashboard.html"
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


# ---------------------------------------------------------
# REMOVE RAG DOCUMENT
# ---------------------------------------------------------

@app.put("/api/documents/{document_id}/remove")
def remove_document(document_id: int):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()


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


        if cursor.rowcount == 0:

            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )


        connection.commit()


        return {

            "success": True,

            "message": "Document removed successfully"

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


# ---------------------------------------------------------
# PERMANENTLY DELETE RAG DOCUMENT
# ---------------------------------------------------------

@app.delete("/api/documents/{document_id}/permanent")
def permanently_delete_document(document_id: int):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()


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

            "message": "Document permanently deleted"

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
#
# ALL USERS
#     -> user_access
#
# ACTIVE USERS
#     -> user_access
#     -> last_activity within last 30 minutes
#
# FREQUENT USERS
#     -> user_access
#     -> user_conversations
#     -> sorted by total conversations DESC
#
# CONVERSATIONS
#     -> user_conversations
# =========================================================


# ---------------------------------------------------------
# ALL USERS
# ---------------------------------------------------------

@app.get("/api/admin/chat-history/users")
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

                "user_id": user[0],

                "name": user[1],

                "email": user[2],

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

            "users": result

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


# ---------------------------------------------------------
# ACTIVE USERS
# ---------------------------------------------------------
#
# CURRENT TIME IS TAKEN BY POSTGRESQL USING
# CURRENT_TIMESTAMP.
#
# A USER IS ACTIVE WHEN:
#
# last_activity >= CURRENT_TIMESTAMP - 30 minutes
#
# AND active_status = TRUE
# ---------------------------------------------------------

@app.get("/api/admin/chat-history/active-users")
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

                "user_id": user[0],

                "name": user[1],

                "email": user[2],

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

            "users": result

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


# ---------------------------------------------------------
# FREQUENT USERS
# ---------------------------------------------------------
#
# USERS COME FROM user_access.
#
# CONVERSATION COUNT COMES FROM user_conversations.
#
# HIGHEST CONVERSATION COUNT
#       ↓
# FIRST
#
# LOWEST CONVERSATION COUNT
#       ↓
# LAST
# ---------------------------------------------------------

@app.get("/api/admin/chat-history/frequent-users")
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

                "user_id": user[0],

                "name": user[1],

                "email": user[2],

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

            "users": result

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


# ---------------------------------------------------------
# GET CONVERSATIONS OF SELECTED USER
# ---------------------------------------------------------

@app.get(
    "/api/admin/chat-history/user/{user_id}/conversations"
)
def get_user_conversations(user_id: int):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()


        # -------------------------------------------------
        # CHECK USER FROM USER_ACCESS
        # -------------------------------------------------

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


        # -------------------------------------------------
        # GET CONVERSATIONS FROM USER_CONVERSATIONS
        # -------------------------------------------------

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


# ---------------------------------------------------------
# GET MESSAGES OF ONE CONVERSATION
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# CREATE GENERATED_FEEDBACK TABLE
# ---------------------------------------------------------

def create_generated_feedback_table(cursor):

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


# ---------------------------------------------------------
# SAVE GENERATED FEEDBACK
# ---------------------------------------------------------

@app.post("/api/admin/feedback/save")
def save_generated_feedback(
    data: GeneratedFeedback
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()


        create_generated_feedback_table(cursor)


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


# ---------------------------------------------------------
# GENERATE FEEDBACK FOR ONE CONVERSATION
# ---------------------------------------------------------

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


        total_messages = len(messages)


        user_questions = []

        ai_answers = []


        for message in messages:

            if message[1]:

                user_questions.append(
                    str(message[1])
                )


            if message[2]:

                ai_answers.append(
                    str(message[2])
                )


        feedback_text = (
            f"Conversation Feedback\n\n"
            f"User ID: {user_id}\n"
            f"Conversation ID: {conversation_id}\n"
            f"Total messages: {total_messages}\n\n"
            f"User interaction:\n"
            f"The user asked {len(user_questions)} "
            f"question(s) in this conversation.\n\n"
            f"AI responses:\n"
            f"The system provided {len(ai_answers)} "
            f"response(s).\n\n"
            f"Feedback Summary:\n"
            f"The conversation contains an interaction "
            f"between the user and the AI system. "
            f"The conversation can be reviewed for "
            f"response accuracy, relevance, clarity, "
            f"and whether the user's questions were "
            f"successfully addressed."
        )


        create_generated_feedback_table(cursor)


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


# ---------------------------------------------------------
# ALL USERS
# ---------------------------------------------------------

@app.get("/api/admin/feedback/users")
def get_feedback_users():

    return get_chat_history_users()


# ---------------------------------------------------------
# ACTIVE USERS
# ---------------------------------------------------------

@app.get("/api/admin/feedback/active-users")
def get_feedback_active_users():

    return get_active_chat_users()


# ---------------------------------------------------------
# FREQUENT USERS
# ---------------------------------------------------------

@app.get("/api/admin/feedback/frequent-users")
def get_feedback_frequent_users():

    return get_frequent_chat_users()


# ---------------------------------------------------------
# FEEDBACK USER CONVERSATIONS
# ---------------------------------------------------------

@app.get(
    "/api/admin/feedback/user/{user_id}/conversations"
)
def get_feedback_user_conversations(
    user_id: int
):

    return get_user_conversations(user_id)


# ---------------------------------------------------------
# FEEDBACK CONVERSATION MESSAGES
# ---------------------------------------------------------

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
#
# IMPORTANT:
#
# This endpoint reads ONLY generated_feedback.
#
# It does NOT display raw conversations.
# It does NOT generate new feedback.
# It only displays feedback that was already generated
# and stored in generated_feedback.
# =========================================================

@app.get("/api/admin/feedback")
def get_generated_feedback():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()


        create_generated_feedback_table(cursor)

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


# ---------------------------------------------------------
# GENERATED FEEDBACK FOR ONE USER
# ---------------------------------------------------------

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


        create_generated_feedback_table(cursor)

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


# ---------------------------------------------------------
# ADMIN STATISTICS
# ---------------------------------------------------------

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


        total_conversations = cursor.fetchone()[0]


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


        unique_users = cursor.fetchone()[0]


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


        messages_today = cursor.fetchone()[0]


        # -------------------------------------------------
        # ACTIVE USERS
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM user_access
            WHERE active_status = TRUE
            AND last_activity >=
                CURRENT_TIMESTAMP - INTERVAL '30 minutes'
            """
        )


        active_users = cursor.fetchone()[0]


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


        frequent_user = cursor.fetchone()


        if frequent_user:

            frequent_user_id = frequent_user[0]

            frequent_user_name = frequent_user[1]

            frequent_conversations = frequent_user[2]

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

        raise HTTPException(
            status_code=500,
            detail="Unable to get statistics"
        )


    finally:

        if cursor:

            cursor.close()

        if connection:

            connection.close()