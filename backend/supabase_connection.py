import os
from dotenv import load_dotenv
from supabase import create_client
import psycopg2

load_dotenv()

SUPABASE_URL=os.getenv("SUPABASE_URL")
SUPABASE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY")
DATABASE_URL=os.getenv("DATABASE_URL")

# Supabase Storage connection
supabase=create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

# PostgreSQL connection
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)