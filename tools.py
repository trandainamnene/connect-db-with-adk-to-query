from .db import get_connection
from dotenv import load_dotenv
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal
import requests
import pandas as pd
import zipfile
import base64
import io
from PIL import Image
import http.server
import socketserver
import threading
import urllib.parse

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

# HTTP Server để serve ảnh từ thư mục instruction
_image_server = None
_image_server_port = None
_image_server_thread = None

class ImageHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, base_directory=None, **kwargs):
        self.base_directory = base_directory
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        try:
            # Parse URL để lấy tên file
            parsed_path = urllib.parse.urlparse(self.path)
            filename = os.path.basename(parsed_path.path)
            
            # Tìm file trong cả 2 thư mục instruction
            current_dir = os.path.dirname(os.path.abspath(__file__))
            ios_folder = os.path.join(current_dir, "IOS_Instruction")
            android_folder = os.path.join(current_dir, "Android_Instruction")
            
            file_path = None
            for folder in [ios_folder, android_folder]:
                potential_path = os.path.join(folder, filename)
                if os.path.exists(potential_path) and os.path.isfile(potential_path):
                    file_path = potential_path
                    break
            
            if file_path and os.path.exists(file_path):
                # Đọc và trả về file
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                # Xác định content type
                ext = os.path.splitext(filename)[1].lower()
                content_types = {
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.gif': 'image/gif',
                    '.bmp': 'image/bmp'
                }
                content_type = content_types.get(ext, 'application/octet-stream')
                
                self.send_response(200)
                self.send_header('Content-type', content_type)
                self.send_header('Content-length', len(content))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Image not found')
        except Exception as e:
            logging.error(f"Error serving image: {e}")
            self.send_response(500)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress default logging để tránh spam
        pass

def _start_image_server():
    """Khởi động HTTP server để serve ảnh"""
    global _image_server, _image_server_thread, _image_server_port
    
    if _image_server is not None:
        return _image_server_port
    
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Tạo handler với base directory
        handler = lambda *args, **kwargs: ImageHandler(*args, base_directory=current_dir, **kwargs)
        
        # Tìm port trống
        for port in range(8765, 8775):
            try:
                _image_server = socketserver.TCPServer(("", port), handler)
                _image_server_port = port
                _image_server.allow_reuse_address = True
                break
            except OSError:
                continue
        
        if _image_server is None:
            logging.error("Could not start image server - no available port")
            return None
        
        # Chạy server trong thread riêng
        _image_server_thread = threading.Thread(target=_image_server.serve_forever, daemon=True)
        _image_server_thread.start()
        
        logging.info(f"Image server started on port {_image_server_port}")
        return _image_server_port
    
    except Exception as e:
        logging.error(f"Error starting image server: {e}")
        return None

def get_all_instruction_images(folder_type: str = "IOS") -> dict:
    """
    Lấy tất cả hình ảnh từ thư mục instruction và trả về HTTP URLs để hiển thị.
    Agent sẽ sử dụng các URLs này để hiển thị ảnh thông qua HTTP server.
    
    Args:
        folder_type: Loại thư mục - "IOS" hoặc "Android" (mặc định: "IOS")
    
    Returns:
        dict: Chứa danh sách tất cả ảnh với HTTP URLs
    """
    try:
        # Khởi động HTTP server nếu chưa chạy
        server_port = _start_image_server()
        if server_port is None:
            logging.warning("Could not start image server, falling back to file paths")
            return {
                "status": "error",
                "message": "Could not start image server"
            }
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Xác định thư mục dựa trên folder_type
        if folder_type.upper() == "ANDROID":
            instruction_folder = os.path.join(current_dir, "Android_Instruction")
        else:
            instruction_folder = os.path.join(current_dir, "IOS_Instruction")
        
        if not os.path.exists(instruction_folder):
            logging.warning(f"Instruction folder not found: {instruction_folder}")
            return {
                "status": "error",
                "message": f"Instruction folder not found: {folder_type}"
            }
        
        # Tìm tất cả file hình ảnh trong thư mục
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
        image_files = []
        
        for file in os.listdir(instruction_folder):
            file_path = os.path.join(instruction_folder, file)
            if os.path.isfile(file_path):
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext in image_extensions:
                    image_files.append(file)
        
        # Sắp xếp theo tên file để đảm bảo thứ tự (1.jpg, 2.jpg, 3.jpg, ...)
        image_files = sorted(image_files, key=lambda x: (
            int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else float('inf'),
            x
        ))
        
        # Tạo URLs cho từng ảnh
        images_data = []
        base_url = f"http://localhost:{server_port}"
        
        for filename in image_files:
            try:
                # URL encode filename để xử lý ký tự đặc biệt
                encoded_filename = urllib.parse.quote(filename)
                image_url = f"{base_url}/{encoded_filename}"
                
                # Lấy thông tin file
                file_path = os.path.join(instruction_folder, filename)
                file_size = os.path.getsize(file_path)
                size_kb = file_size / 1024
                
                # Xác định MIME type
                ext = os.path.splitext(filename)[1].lower()
                mime_types = {
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.gif': 'image/gif',
                    '.bmp': 'image/bmp'
                }
                mime = mime_types.get(ext, 'image/jpeg')
                
                images_data.append({
                    "filename": filename,
                    "step_number": int(re.search(r'\d+', filename).group()) if re.search(r'\d+', filename) else 0,
                    "url": image_url,  # HTTP URL để hiển thị ảnh
                    "mime_type": mime,
                    "size_kb": round(size_kb, 2)
                })
                
            except Exception as e:
                logging.error(f"Error processing image {filename}: {e}")
                continue
        
        logging.info(f"Found {len(images_data)} images from {instruction_folder}, serving via HTTP on port {server_port}")
        
        return {
            "status": "success",
            "count": len(images_data),
            "folder_type": folder_type,
            "folder_path": instruction_folder,
            "base_url": base_url,
            "images": images_data  # Danh sách tất cả ảnh với HTTP URLs
        }
        
    except Exception as e:
        logging.error(f"Error reading instruction folder: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Error reading images: {str(e)}"
        }

def read_instruction_image(filename: str, folder_type: str = "IOS") -> dict:
    """
    Trả về HTTP URL của hình ảnh từ thư mục instruction.
    Agent sẽ sử dụng URL này để hiển thị ảnh thông qua HTTP server.
    
    Args:
        filename: Tên file ảnh (ví dụ: "1.jpg", "2.jpg")
        folder_type: Loại thư mục - "IOS" hoặc "Android" (mặc định: "IOS")
    
    Returns:
        dict: Chứa url (HTTP URL), mime type, và metadata
    """
    try:
        # Khởi động HTTP server nếu chưa chạy
        server_port = _start_image_server()
        if server_port is None:
            logging.warning("Could not start image server")
            return {
                "status": "error",
                "message": "Could not start image server"
            }
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Xác định thư mục dựa trên folder_type
        if folder_type.upper() == "ANDROID":
            instruction_folder = os.path.join(current_dir, "Android_Instruction")
        else:
            instruction_folder = os.path.join(current_dir, "IOS_Instruction")
        
        file_path = os.path.join(instruction_folder, filename)
        
        if not os.path.exists(file_path):
            logging.warning(f"Image file not found: {file_path}")
            return {
                "status": "error",
                "message": f"Image file not found: {filename}"
            }
        
        # Tạo HTTP URL
        encoded_filename = urllib.parse.quote(filename)
        image_url = f"http://localhost:{server_port}/{encoded_filename}"
        
        # Xác định MIME type
        ext = os.path.splitext(filename)[1].lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp'
        }
        mime = mime_types.get(ext, 'image/jpeg')
        
        # Lấy file size
        file_size = os.path.getsize(file_path)
        size_kb = file_size / 1024
        
        logging.info(f"Image URL: {image_url}, size: {size_kb:.2f} KB")
        
        return {
            "status": "success",
            "filename": filename,
            "url": image_url,  # HTTP URL để hiển thị ảnh
            "mime_type": mime,
            "size_kb": round(size_kb, 2)
        }
        
    except Exception as e:
        logging.error(f"Error reading image {filename}: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Error reading image: {str(e)}"
        }

def get_pictures_from_instruction_folder(model_name: str, model_code: str = None) -> dict:
    """
    Lấy metadata về hình ảnh từ thư mục instruction (IOS_Instruction hoặc Android_Instruction).
    Trả về danh sách filename để agent có thể gọi read_instruction_image tool.
    
    Args:
        model_name: Tên model thiết bị
        model_code: Mã model thiết bị (optional)
    
    Returns:
        dict: Chứa metadata về hình ảnh (filename, step_number) để agent gọi tool
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Xác định thiết bị là Android hay iOS
        model_lower = str(model_name).lower() if model_name else ""
        is_ios = any(keyword in model_lower for keyword in ['iphone', 'ios'])
        
        # Chọn thư mục instruction tương ứng
        if is_ios:
            instruction_folder = os.path.join(current_dir, "IOS_Instruction")
            folder_type = "IOS"
        else:
            instruction_folder = os.path.join(current_dir, "Android_Instruction")
            folder_type = "Android"
        
        if not os.path.exists(instruction_folder):
            logging.warning(f"Thư mục instruction không tìm thấy: {instruction_folder}")
            return {
                "count": 0,
                "folder_type": folder_type,
                "folder_path": instruction_folder,
                "images": []
            }
        
        # Tìm tất cả file hình ảnh trong thư mục
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
        image_files = []
        
        for file in os.listdir(instruction_folder):
            file_path = os.path.join(instruction_folder, file)
            if os.path.isfile(file_path):
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext in image_extensions:
                    image_files.append(file)
        
        # Sắp xếp theo tên file để đảm bảo thứ tự (1.jpg, 2.jpg, 3.jpg, ...)
        image_files = sorted(image_files, key=lambda x: (
            int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else float('inf'),
            x
        ))
        
        # Tạo metadata cho từng ảnh
        images_data = []
        for filename in image_files:
            try:
                file_path = os.path.join(instruction_folder, filename)
                file_size = os.path.getsize(file_path)
                size_kb = file_size / 1024
                
                images_data.append({
                    "filename": filename,
                    "step_number": int(re.search(r'\d+', filename).group()) if re.search(r'\d+', filename) else 0,
                    "size_kb": round(size_kb, 2)
                })
            except Exception as e:
                logging.error(f"Error processing image metadata {filename}: {e}")
                continue
        
        logging.info(f"Found {len(images_data)} images from {instruction_folder} for model {model_name}")
        
        return {
            "count": len(images_data),
            "folder_type": folder_type,
            "folder_path": instruction_folder,
            "images": images_data  # Danh sách metadata về ảnh (filename, step_number), đã sắp xếp
        }
        
    except Exception as e:
        logging.error(f"Error reading instruction folder: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "count": 0,
            "folder_type": "Unknown",
            "images": []
        }

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
            found_model_name = str(result.get('ModelName', ''))
            found_model_code = str(result.get('ModelCode', ''))
            
            # Lấy hình ảnh từ thư mục instruction (IOS_Instruction hoặc Android_Instruction)
            logging.info(f"Getting pictures for model: {found_model_name}")
            pictures_data = get_pictures_from_instruction_folder(found_model_name, found_model_code)
            logging.info(f"Found {pictures_data.get('count', 0)} images in {pictures_data.get('folder_type', 'Unknown')}_Instruction folder")
            
            return {
                "status": "success",
                "model_code": found_model_code,
                "model_name": found_model_name,
                "guide": guide_text,
                "pictures": pictures_data,  # Hình ảnh dưới dạng base64 data URLs và metadata
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
