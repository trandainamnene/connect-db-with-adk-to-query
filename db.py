import pyodbc
from dotenv import load_dotenv
import os

load_dotenv()

config = {
    'SERVER': os.getenv('SERVER'),
    'DATABASE': os.getenv('DATABASE'),
    'UID': os.getenv('UID'),
    'PWD': os.getenv('PWD')
}

def get_connection():
    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={config['SERVER']};"
        f"DATABASE={config['DATABASE']};"
        f"UID={config['UID']};"
        f"PWD={config['PWD']};"
    )
    return conn