from .db import get_connection
from dotenv import load_dotenv
import logging
import os
from datetime import date, datetime
from decimal import Decimal

load_dotenv()
config = {
    'SERVER': os.getenv('SERVER'),
    'DATABASE': os.getenv('DATABASE'),
    'UID': os.getenv('UID'),
    'PWD': os.getenv('PWD'),
    'TABLE': os.getenv('TABLE')
}

def convert_value_to_json_serializable(value):
    """Convert non-JSON serializable objects (date, datetime, Decimal) to JSON compatible types."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    elif isinstance(value, Decimal):
        return float(value)
    elif value is None:
        return None
    else:
        return value

def query_DeviceInfo(userid : str) -> dict:
    """
    Execute a SELECT query on MSSQL and return results.
    """
    table_name = config.get('TABLE')
    if not table_name:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        return {
            "status": "error",
            "message": f"TABLE configuration not found in .env file. Please add TABLE=your_table_name to your .env file at {env_path}"
        }
    
    query = f"SELECT * FROM {table_name} WHERE UserID = ?"
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(query , (userid,))
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

        data = [
            {columns[i]: convert_value_to_json_serializable(row[i]) for i in range(len(columns))}
            for row in rows
        ]

        return {"status": "success", "data": data}

    except Exception as e:
        return {"status": "error", "message": str(e)}