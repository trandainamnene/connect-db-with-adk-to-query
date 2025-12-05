from .db import get_connection
from dotenv import load_dotenv
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal
import requests
import pandas as pd

load_dotenv()
config = {
    'SERVER': os.getenv('SERVER'),
    'DATABASE': os.getenv('DATABASE'),
    'UID': os.getenv('UID'),
    'PWD': os.getenv('PWD'),
    'TABLE': os.getenv('TABLE'),
    'EXA_API_KEY': os.getenv('EXA_API_KEY')
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
    userid = str(userid)
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

def get_location_guide_from_excel(model_name: str = None, model_code: str = None) -> dict:
    """
    Tìm kiếm hướng dẫn cách bật định vị từ file Excel dựa trên tên model hoặc model code.
    
    Args:
        model_name: Tên model thiết bị (ví dụ: "iPhone 6", "Samsung Galaxy S21")
        model_code: Mã model thiết bị (ví dụ: "iPhone7,2", "SM-G991B")
    
    Returns:
        dict: Chứa thông tin hướng dẫn hoặc lỗi nếu không tìm thấy
    """
    try:
        # Đường dẫn đến file Excel (file nằm ở cùng thư mục với tools.py)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        excel_path = os.path.join(current_dir, "device_models_with_location.xlsx")
        
        # Kiểm tra file có tồn tại không
        if not os.path.exists(excel_path):
            return {
                "status": "error",
                "message": f"File Excel không tìm thấy tại: {excel_path}"
            }
        
        # Đọc file Excel
        df = pd.read_excel(excel_path)
        
        # Loại bỏ các giá trị NaN và làm sạch dữ liệu
        df = df.dropna(subset=['How_to_Enable_Location'])
        
        result = None
        
        # Tìm kiếm theo ModelCode trước (nếu có)
        if model_code:
            model_code = str(model_code).strip()
            # Sử dụng regex=False để tránh lỗi với các ký tự đặc biệt
            matches = df[df['ModelCode'].astype(str).str.contains(model_code, case=False, na=False, regex=False)]
            if not matches.empty:
                result = matches.iloc[0]
        
        # Nếu không tìm thấy theo ModelCode, tìm theo ModelName
        if result is None and model_name:
            model_name = str(model_name).strip()
            # Tìm kiếm exact match hoặc partial match
            # Sử dụng regex=False để tránh lỗi với dấu ngoặc đơn và các ký tự đặc biệt
            matches = df[df['ModelName'].astype(str).str.contains(model_name, case=False, na=False, regex=False)]
            if not matches.empty:
                result = matches.iloc[0]
        
        # Nếu vẫn không tìm thấy, thử tìm kiếm linh hoạt hơn
        if result is None:
            search_term = model_name or model_code or ""
            if search_term:
                search_term = str(search_term).strip().lower()
                # Tìm trong cả ModelCode và ModelName
                # Sử dụng regex=False để tránh lỗi với các ký tự đặc biệt
                mask = (
                    df['ModelCode'].astype(str).str.lower().str.contains(search_term, na=False, regex=False) |
                    df['ModelName'].astype(str).str.lower().str.contains(search_term, na=False, regex=False)
                )
                matches = df[mask]
                if not matches.empty:
                    result = matches.iloc[0]
        
        if result is not None:
            guide_text = str(result.get('How_to_Enable_Location', ''))
            
            return {
                "status": "success",
                "model_code": str(result.get('ModelCode', '')),
                "model_name": str(result.get('ModelName', '')),
                "guide": guide_text,
                "message": "Hướng dẫn đã được tìm thấy"
            }
        else:
            return {
                "status": "not_found",
                "message": f"Không tìm thấy hướng dẫn cho model: {model_name or model_code}",
                "available_models_count": len(df)
            }
            
    except Exception as e:
        logging.error(f"Error reading Excel file: {e}")
        return {
            "status": "error",
            "message": f"Lỗi khi đọc file Excel: {str(e)}"
        }
