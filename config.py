# config.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor

# Δεν χρειάζεται python-dotenv! Manual load:
def load_env():
    if os.path.exists('.env'):
        with open('.env') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value

load_env()
DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise ValueError("❌ DATABASE_URL not found in .env")

def get_connection():
    return psycopg2.connect(DB_URL)

def execute_query(query, params=None, fetch=False):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        
        if fetch:
            result = cur.fetchall()
        else:
            result = None
        
        conn.commit()
        cur.close()
        return result
    except Exception as e:
        print(f"❌ Query Error: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()