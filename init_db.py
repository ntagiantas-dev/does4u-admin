#!/usr/bin/env python3
"""Initialize database schema for Does4U"""

import os
import psycopg2
from config import DB_URL

def init_database():
    """Create database schema from schema.sql"""
    try:
        # Get absolute path to schema file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(script_dir, 'database', 'schema.sql')
        
        # Read schema file
        with open(schema_path, 'r') as f:
            schema = f.read()
        
        # Connect and execute
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute(schema)
        conn.commit()
        cur.close()
        conn.close()
        
        print("✅ Database schema initialized successfully!")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    init_database()