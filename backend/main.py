
# ---------------------------------------------------------
# IMPORTS
# ---------------------------------------------------------

# FastAPI is used to create our backend API
from fastapi import FastAPI, HTTPException

# FileResponse is used to display HTML files
from fastapi.responses import FileResponse

# Allows frontend and backend to communicate
from fastapi.middleware.cors import CORSMiddleware

# Used to work with folder/file paths
from pathlib import Path

# Used to validate login data
from pydantic import BaseModel

# PostgreSQL database connection
import psycopg2


# ---------------------------------------------------------
# CREATE FASTAPI APPLICATION
# ---------------------------------------------------------

app = FastAPI()


# ---------------------------------------------------------
# FIND PROJECT FOLDERS
# ---------------------------------------------------------

# Get the main project folder
#
# If main.py is:
# YourProject/backend/main.py
#
# parent       = backend
# parent.parent = YourProject

BASE_DIR = Path(__file__).resolve().parent.parent

# Frontend folder
FRONTEND_DIR = BASE_DIR / "Frontend"


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

# Allows the frontend to communicate with the backend

app.add_middleware(
    CORSMiddleware,

    # During development, allow all origins
    allow_origins=["*"],

    # Allow cookies/authentication
    allow_credentials=True,

    # Allow GET, POST, PUT, DELETE, etc.
    allow_methods=["*"],

    # Allow all headers
    allow_headers=["*"]
)


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

def get_db_connection():

    return psycopg2.connect(

        # PostgreSQL is running on your computer
        host="localhost",

        # Default PostgreSQL port
        port="5432",

        # Your database name
        database="bc",

        # Your PostgreSQL username
        user="postgres",

        # Your PostgreSQL password
        password="Karani@2006"
    )


# ---------------------------------------------------------
# ADMIN LOGIN DATA
# ---------------------------------------------------------

# This defines what data the frontend must send
# when the admin logs in.

class AdminLogin(BaseModel):

    # Admin email
    email: str

    # Admin password
    password: str


# ---------------------------------------------------------
# USER SIGNUP DATA
# ---------------------------------------------------------

# This defines what data the frontend must send
# when a new user creates an account.

class UserRegister(BaseModel):

    # User name
    name: str

    # User email
    email: str

    # User password
    password: str


# ---------------------------------------------------------
# USER LOGIN DATA
# ---------------------------------------------------------

# This defines what data the frontend must send
# when an existing user signs in.

class UserLogin(BaseModel):

    # User email
    email: str

    # User password
    password: str


# ---------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------

# When you open:
#
# http://127.0.0.1:8000/
#
# FastAPI will display index.html

@app.get("/")
def home():

    return FileResponse(
        FRONTEND_DIR / "index.html"
    )


# ---------------------------------------------------------
# INDEX.HTML PAGE
# ---------------------------------------------------------

# When you open:
#
# http://127.0.0.1:8000/index.html
#
# FastAPI will display index.html

@app.get("/index.html")
def index():

    return FileResponse(
        FRONTEND_DIR / "index.html"
    )


# ---------------------------------------------------------
# ADMIN LOGIN PAGE
# ---------------------------------------------------------

# When you open:
#
# http://127.0.0.1:8000/ad_login.html
#
# FastAPI will display ad_login.html

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
# USER LOGIN PAGE
# ---------------------------------------------------------

@app.get("/user_login.html")
async def user_login():

    return FileResponse(
        FRONTEND_DIR / "user_login.html"
    )


# ---------------------------------------------------------
# USER SIGNUP API
# ---------------------------------------------------------

# This API receives:
#
# Name
# Email
# Password
#
# and stores them in the user_access table.

@app.post("/api/auth/register")
def user_register(data: UserRegister):

    connection = None
    cursor = None

    try:

        # -------------------------------------------------
        # CONNECT TO POSTGRESQL
        # -------------------------------------------------

        connection = get_db_connection()

        # Create database cursor
        cursor = connection.cursor()


        # -------------------------------------------------
        # CHECK IF EMAIL ALREADY EXISTS
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT user_id
            FROM user_access
            WHERE email = %s
            """,
            (data.email,)
        )


        # Get existing user
        existing_user = cursor.fetchone()


        # -------------------------------------------------
        # EMAIL ALREADY EXISTS
        # -------------------------------------------------

        if existing_user:

            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )


        # -------------------------------------------------
        # INSERT NEW USER
        # -------------------------------------------------

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


        # Get newly created user
        user = cursor.fetchone()


        # Save changes to database
        connection.commit()


        # -------------------------------------------------
        # SIGNUP SUCCESSFUL
        # -------------------------------------------------

        return {

            "success": True,

            "message": "Account created successfully",

            "user_id": user[0],

            "name": user[1],

            "email": user[2]

        }


    # -----------------------------------------------------
    # HANDLE FASTAPI ERRORS
    # -----------------------------------------------------

    except HTTPException:

        if connection:

            connection.rollback()

        raise


    # -----------------------------------------------------
    # HANDLE DATABASE ERRORS
    # -----------------------------------------------------

    except Exception:

        if connection:

            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to create account"
        )


    # -----------------------------------------------------
    # CLOSE DATABASE CONNECTION
    # -----------------------------------------------------

    finally:

        if cursor:

            cursor.close()

        if connection:

            connection.close()


# ---------------------------------------------------------
# USER LOGIN API
# ---------------------------------------------------------

# This API receives:
#
# Email
# Password
#
# and checks them against the user_access table.

@app.post("/api/auth/login")
def user_login_api(data: UserLogin):

    connection = None
    cursor = None

    try:

        # -------------------------------------------------
        # CONNECT TO POSTGRESQL
        # -------------------------------------------------

        connection = get_db_connection()

        # Create database cursor
        cursor = connection.cursor()


        # -------------------------------------------------
        # FIND USER BY EMAIL
        # -------------------------------------------------

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


        # Get the user record
        user = cursor.fetchone()


        # -------------------------------------------------
        # CHECK IF EMAIL EXISTS
        # -------------------------------------------------

        if not user:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )


        # -------------------------------------------------
        # GET USER DATA
        # -------------------------------------------------

        user_id = user[0]

        name = user[1]

        email = user[2]

        password = user[3]

        active_status = user[4]


        # -------------------------------------------------
        # CHECK IF USER IS ACTIVE
        # -------------------------------------------------

        if not active_status:

            raise HTTPException(
                status_code=403,
                detail="User account is inactive"
            )


        # -------------------------------------------------
        # CHECK PASSWORD
        # ---------------------------------------------------------

        # Here the database contains the normal password
        # in the "password" column.
        #
        # So we directly compare:
        #
        # password entered by user
        #        ==
        # password stored in database

        if data.password != password:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )


        # -------------------------------------------------
        # UPDATE LOGIN TIME
        # -------------------------------------------------

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


        # Save changes
        connection.commit()


        # -------------------------------------------------
        # LOGIN SUCCESSFUL
        # -------------------------------------------------

        return {

            "success": True,

            "message": "User login successful",

            "user_id": user_id,

            "name": name,

            "username": name,

            "email": email

        }


    # -----------------------------------------------------
    # HANDLE FASTAPI ERRORS
    # -----------------------------------------------------

    except HTTPException:

        if connection:

            connection.rollback()

        raise


    # -----------------------------------------------------
    # HANDLE DATABASE ERRORS
    # -----------------------------------------------------

    except Exception:

        if connection:

            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to login"
        )


    # -----------------------------------------------------
    # CLOSE DATABASE CONNECTION
    # -----------------------------------------------------

    finally:

        if cursor:

            cursor.close()

        if connection:

            connection.close()


# ---------------------------------------------------------
# ADMIN LOGIN API
# ---------------------------------------------------------

# This API receives:
#
# Email
# Password
#
# and checks them against the admin_access table.

@app.post("/api/admin/login")
def admin_login(data: AdminLogin):

    connection = None
    cursor = None

    try:

        # -------------------------------------------------
        # CONNECT TO POSTGRESQL
        # -------------------------------------------------

        connection = get_db_connection()

        # Create database cursor
        cursor = connection.cursor()


        # -------------------------------------------------
        # FIND ADMIN BY EMAIL
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT admin_id, email, password, active_status
            FROM admin_access
            WHERE email = %s
            """,

            # %s safely passes the email
            # and helps prevent SQL injection
            (data.email,)
        )


        # Get the admin record
        admin = cursor.fetchone()


        # -------------------------------------------------
        # CHECK IF EMAIL EXISTS
        # -------------------------------------------------

        if not admin:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )


        # -------------------------------------------------
        # GET ADMIN DATA
        # -------------------------------------------------

        admin_id = admin[0]
        email = admin[1]
        password = admin[2]
        active_status = admin[3]


        # -------------------------------------------------
        # CHECK IF ADMIN IS ACTIVE
        # -------------------------------------------------

        if not active_status:

            raise HTTPException(
                status_code=403,
                detail="Admin account is inactive"
            )


        # -------------------------------------------------
        # CHECK PASSWORD
        # ---------------------------------------------------------

        # Here the database contains the normal password
        # in the "password" column.
        #
        # So we directly compare:
        #
        # password entered by admin
        #        ==
        # password stored in database

        if data.password != password:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )


        # -------------------------------------------------
        # LOGIN SUCCESSFUL
        # -------------------------------------------------

        return {

            "success": True,

            "message": "Admin login successful",

            "admin_id": admin_id,

            "email": email
        }


    # -----------------------------------------------------
    # CLOSE DATABASE CONNECTION
    # -----------------------------------------------------

    finally:

        if cursor:

            cursor.close()

        if connection:

            connection.close()
