from .db import get_connection
from dotenv import load_dotenv
import logging
import os
import re
import json
from datetime import date, datetime
from decimal import Decimal
import pandas as pd
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


def determine_folder_type_from_device_name(device_name: str) -> str:
    """
    Xác định folder_type (IOS hoặc Android) dựa trên DeviceName.
    
    Args:
        device_name: Tên thiết bị từ database (ví dụ: "iPhone XS Max", "Samsung Galaxy J7 (2016)")
    
    Returns:
        str: "IOS" hoặc "Android"
    """
    if not device_name:
        return "Android"
    
    device_lower = str(device_name).lower()
    is_ios = any(keyword in device_lower for keyword in ['iphone', 'ios', 'ipad'])
    
    folder_type = "IOS" if is_ios else "Android"
    logging.info(f"Determined folder_type for device '{device_name}': {folder_type}")
    return folder_type


# HTTP Server để serve ảnh từ thư mục instruction
_image_server = None
_image_server_port = None
_image_server_thread = None


class ImageHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler để serve ảnh từ paths trong JSON."""
    
    def do_GET(self):
        try:
            parsed_path = urllib.parse.urlparse(self.path)
            path_parts = [p for p in parsed_path.path.split('/') if p]
            current_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = None
            
            if len(path_parts) > 1:
                relative_path = '/'.join(path_parts)
                file_path = os.path.join(current_dir, relative_path)
                if not os.path.exists(file_path):
                    file_path = None
            else:
                filename = path_parts[0] if path_parts else None
                if not filename:
                    self.send_response(404)
                    self.end_headers()
                    return
                
                json_files = [
                    os.path.join(current_dir, "ios_instructions.json"),
                    os.path.join(current_dir, "android_instructions.json")
                ]
                
                for json_file in json_files:
                    if not os.path.exists(json_file):
                        continue
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            steps = json.load(f)
                        
                        for step in steps:
                            image_path = step.get("image_path")
                            if image_path and (os.path.basename(image_path) == filename or 
                                             image_path.endswith(filename)):
                                if os.path.exists(image_path):
                                    file_path = image_path
                                    break
                        
                        if file_path:
                            break
                    except Exception as e:
                        logging.error(f"Error reading JSON file {json_file}: {e}")
                        continue
            
            if file_path and os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                filename = os.path.basename(file_path)
                ext = os.path.splitext(filename)[1].lower()
                content_types = {
                    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                    '.gif': 'image/gif', '.bmp': 'image/bmp'
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
        pass


def _start_image_server():
    """Khởi động HTTP server để serve ảnh."""
    global _image_server, _image_server_thread, _image_server_port
    
    if _image_server is not None:
        return _image_server_port
    
    try:
        for port in range(8765, 8775):
            try:
                _image_server = socketserver.TCPServer(("", port), ImageHandler)
                _image_server_port = port
                _image_server.allow_reuse_address = True
                break
            except OSError:
                continue
        
        if _image_server is None:
            logging.error("Could not start image server - no available port")
            return None
        
        _image_server_thread = threading.Thread(target=_image_server.serve_forever, daemon=True)
        _image_server_thread.start()
        
        logging.info(f"Image server started on port {_image_server_port}")
        return _image_server_port
    
    except Exception as e:
        logging.error(f"Error starting image server: {e}")
        return None


def _get_mime_type(filename: str) -> str:
    """Xác định MIME type từ extension của file."""
    ext = os.path.splitext(filename)[1].lower()
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp'
    }
    return mime_types.get(ext, 'image/jpeg')


def get_all_instruction_images(folder_type: str = "IOS") -> dict:
    """
    Lấy tất cả hình ảnh từ JSON (đã parse từ docx) và trả về HTTP URLs.
    
    Args:
        folder_type: Loại - "IOS" hoặc "Android" (mặc định: "IOS")
    
    Returns:
        dict: Chứa danh sách tất cả ảnh với HTTP URLs
    """
    try:
        server_port = _start_image_server()
        if server_port is None:
            return {
                "status": "error",
                "message": "Could not start image server"
            }
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Chọn file JSON tương ứng
        if folder_type.upper() == "ANDROID":
            json_path = os.path.join(current_dir, "android_instructions.json")
        else:
            json_path = os.path.join(current_dir, "ios_instructions.json")
        
        if not os.path.exists(json_path):
            logging.warning(f"JSON file not found: {json_path}")
            return {
                "status": "error",
                "message": f"JSON file not found for {folder_type}"
            }
        
        # Đọc JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            steps = json.load(f)
        
        # Sắp xếp steps theo step_number
        steps = sorted(steps, key=lambda x: x.get("step_number", 0))
        
        images_data = []
        base_url = f"http://localhost:{server_port}"
        
        for step in steps:
            image_path = step.get("image_path")
            if image_path and os.path.exists(image_path):
                try:
                    filename = os.path.basename(image_path)
                    encoded_filename = urllib.parse.quote(filename)
                    image_url = f"{base_url}/{encoded_filename}"
                    
                    file_size = os.path.getsize(image_path)
                    size_kb = file_size / 1024
                    
                    images_data.append({
                        "filename": filename,
                        "step_number": step.get("step_number", 0),
                        "url": image_url,
                        "mime_type": _get_mime_type(filename),
                        "size_kb": round(size_kb, 2)
                    })
                except Exception as e:
                    logging.error(f"Error processing image {image_path}: {e}")
                    continue
        
        # Sắp xếp images_data theo step_number
        images_data = sorted(images_data, key=lambda x: x.get("step_number", 0))
        
        logging.info(f"Found {len(images_data)} images from JSON for {folder_type}, serving via HTTP on port {server_port}")
        
        return {
            "status": "success",
            "count": len(images_data),
            "folder_type": folder_type,
            "base_url": base_url,
            "images": images_data
        }
        
    except Exception as e:
        logging.error(f"Error reading images from JSON: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Error reading images: {str(e)}"
        }


def get_pictures_from_instruction_folder(model_name: str, model_code: str = None) -> dict:
    """
    Lấy metadata về hình ảnh từ JSON (đã parse từ docx).
    
    Args:
        model_name: Tên model thiết bị
        model_code: Mã model thiết bị (optional)
    
    Returns:
        dict: Chứa metadata về hình ảnh (filename, step_number)
    """
    try:
        folder_type = determine_folder_type_from_device_name(model_name)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Chọn file JSON tương ứng
        if folder_type.upper() == "ANDROID":
            json_path = os.path.join(current_dir, "android_instructions.json")
        else:
            json_path = os.path.join(current_dir, "ios_instructions.json")
        
        if not os.path.exists(json_path):
            logging.warning(f"JSON file not found: {json_path}")
            return {
                "count": 0,
                "folder_type": folder_type,
                "images": []
            }
        
        # Đọc JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            steps = json.load(f)
        
        # Sắp xếp steps theo step_number
        steps = sorted(steps, key=lambda x: x.get("step_number", 0))
        
        images_data = []
        
        for step in steps:
            image_path = step.get("image_path")
            if image_path and os.path.exists(image_path):
                try:
                    filename = os.path.basename(image_path)
                    file_size = os.path.getsize(image_path)
                    size_kb = file_size / 1024
                    
                    images_data.append({
                        "filename": filename,
                        "step_number": step.get("step_number", 0),
                        "size_kb": round(size_kb, 2)
                    })
                except Exception as e:
                    logging.error(f"Error processing image metadata {image_path}: {e}")
                    continue
        
        # Sắp xếp images_data theo step_number
        images_data = sorted(images_data, key=lambda x: x.get("step_number", 0))
        
        logging.info(f"Found {len(images_data)} images from JSON for model {model_name}")
        
        return {
            "count": len(images_data),
            "folder_type": folder_type,
            "images": images_data
        }
        
    except Exception as e:
        logging.error(f"Error reading images from JSON: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "count": 0,
            "folder_type": "Unknown",
            "images": []
        }


def query_DeviceInfo(userid: str) -> dict:
    """
    Lấy thông tin thiết bị từ database dựa trên userid.
    
    Args:
        userid: Tên đăng nhập của user
    
    Returns:
        dict: Chứa thông tin thiết bị hoặc lỗi
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
        cursor.execute(query, (userid,))
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        
        data = [
            {columns[i]: convert_value_to_json_serializable(row[i]) for i in range(len(columns))}
            for row in rows
        ]
        
        return {"status": "success", "data": data}
    
    except Exception as e:
        logging.error(f"Error querying device info: {e}")
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
        current_dir = os.path.dirname(os.path.abspath(__file__))
        excel_path = os.path.join(current_dir, "device_models_with_location.xlsx")
        
        if not os.path.exists(excel_path):
            return {
                "status": "error",
                "message": f"File Excel không tìm thấy tại: {excel_path}"
            }
        
        df = pd.read_excel(excel_path)
        df = df.dropna(subset=['How_to_Enable_Location'])
        
        result = None
        
        # Tìm kiếm theo ModelCode trước (nếu có)
        if model_code:
            model_code = str(model_code).strip()
            matches = df[df['ModelCode'].astype(str).str.contains(model_code, case=False, na=False, regex=False)]
            if not matches.empty:
                result = matches.iloc[0]
        
        # Nếu không tìm thấy theo ModelCode, tìm theo ModelName
        if result is None and model_name:
            model_name = str(model_name).strip()
            matches = df[df['ModelName'].astype(str).str.contains(model_name, case=False, na=False, regex=False)]
            if not matches.empty:
                result = matches.iloc[0]
        
        # Nếu vẫn không tìm thấy, thử tìm kiếm linh hoạt hơn
        if result is None:
            search_term = model_name or model_code or ""
            if search_term:
                search_term = str(search_term).strip().lower()
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
            
            logging.info(f"Getting pictures for model: {found_model_name}")
            pictures_data = get_pictures_from_instruction_folder(found_model_name, found_model_code)
            logging.info(f"Found {pictures_data.get('count', 0)} images in {pictures_data.get('folder_type', 'Unknown')}_Instruction folder")
            
            return {
                "status": "success",
                "model_code": found_model_code,
                "model_name": found_model_name,
                "guide": guide_text,
                "pictures": pictures_data,
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


def process_docx_files() -> dict:
    """
    Chạy script process_docx.py để extract images từ Word và tạo JSON files.
    Tool này sẽ tự động xử lý IOS.docx và Android.docx.
    
    Yêu cầu dependencies:
    - Pillow (pip install Pillow)
    - unstructured[docx] (pip install unstructured[docx])
    - python-docx (pip install python-docx)
    
    Hoặc chạy: pip install -r requirements.txt
    
    Returns:
        dict: Kết quả xử lý với thông tin về số steps và images đã tạo
    """
    try:
        # Import và chạy process_docx
        import sys
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        import process_docx
        
        logging.info("Running process_docx_files()")
        process_docx.process_docx_files()
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        ios_json = os.path.join(current_dir, "ios_instructions.json")
        android_json = os.path.join(current_dir, "android_instructions.json")
        
        result = {
            "status": "success",
            "message": "Đã xử lý file Word và tạo JSON thành công"
        }
        
        # Đếm steps trong JSON files
        if os.path.exists(ios_json):
            try:
                with open(ios_json, 'r', encoding='utf-8') as f:
                    ios_data = json.load(f)
                result["ios_steps"] = len(ios_data)
                result["ios_images"] = sum(1 for s in ios_data if s.get("image_path") and os.path.exists(s.get("image_path")))
            except:
                pass
        
        if os.path.exists(android_json):
            try:
                with open(android_json, 'r', encoding='utf-8') as f:
                    android_data = json.load(f)
                result["android_steps"] = len(android_data)
                result["android_images"] = sum(1 for s in android_data if s.get("image_path") and os.path.exists(s.get("image_path")))
            except:
                pass
        
        logging.info(f"process_docx completed: {result}")
        return result
        
    except ImportError as e:
        error_msg = str(e)
        logging.error(f"Missing dependencies for process_docx: {error_msg}")
        
        return {
            "status": "error",
            "message": f"Thiếu dependencies: {error_msg}. Chạy: pip install -r requirements.txt",
            "error_type": "ImportError",
            "error_details": error_msg,
            "suggestion": "pip install -r requirements.txt",
            "install_commands": ["pip install -r requirements.txt", "pip install Pillow unstructured[docx] python-docx"]
        }
    except Exception as e:
        logging.error(f"Error running process_docx: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Lỗi khi xử lý file Word: {str(e)}"
        }


def get_location_guide_from_json(device_name: str) -> dict:
    """
    Lấy hướng dẫn từ file JSON (đã được parse từ Word).
    TỰ ĐỘNG chạy process_docx_files() nếu JSON không tồn tại hoặc rỗng.
    
    Args:
        device_name: Tên thiết bị (ví dụ: "iPhone XS Max", "Samsung Galaxy J7")
    
    Returns:
        dict: Chứa guide text và images với URLs
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        folder_type = determine_folder_type_from_device_name(device_name)
        
        if folder_type == "IOS":
            json_path = os.path.join(current_dir, "ios_instructions.json")
            image_folder = os.path.join(current_dir, "IOS_Instruction")
        else:
            json_path = os.path.join(current_dir, "android_instructions.json")
            image_folder = os.path.join(current_dir, "Android_Instruction")
        
        json_exists = os.path.exists(json_path)
        image_folder_exists = os.path.exists(image_folder) and os.path.isdir(image_folder)
        has_images = False
        if image_folder_exists:
            has_images = any(f.lower().endswith(('.jpg', '.jpeg', '.png')) 
                           for f in os.listdir(image_folder))
        
        should_run_process_docx = not json_exists or not image_folder_exists or not has_images
        
        if should_run_process_docx:
            reasons = []
            if not json_exists:
                reasons.append(f"JSON file not found: {json_path}")
            if not image_folder_exists:
                reasons.append(f"Image folder not found: {image_folder}")
            elif not has_images:
                reasons.append(f"Image folder exists but has no images: {image_folder}")
            
            logging.warning(f"{'; '.join(reasons)}, automatically running process_docx...")
            try:
                process_result = process_docx_files()
                logging.info(f"process_docx result: {process_result}")
                
                if process_result.get("status") != "success" and not os.path.exists(json_path):
                    error_msg = process_result.get('message', 'Unknown error')
                    if process_result.get("error_type") == "ImportError":
                        return {
                            "status": "error",
                            "message": process_result.get("message", error_msg),
                            "process_result": process_result,
                            "error_type": "ImportError",
                            "suggestion": process_result.get("suggestion", "pip install -r requirements.txt"),
                            "install_commands": process_result.get("install_commands", [])
                        }
                    return {
                        "status": "error",
                        "message": f"Không thể tạo file JSON: {error_msg}",
                        "process_result": process_result,
                        "suggestion": "pip install -r requirements.txt"
                    }
            except ImportError as e:
                if not os.path.exists(json_path):
                    return {
                        "status": "error",
                        "message": f"Thiếu dependencies: {str(e)}",
                        "error_type": "ImportError",
                        "suggestion": "pip install -r requirements.txt",
                        "install_commands": ["pip install -r requirements.txt", "pip install Pillow unstructured[docx] python-docx"]
                    }
            except Exception as e:
                logging.error(f"Exception while running process_docx: {e}")
                import traceback
                logging.error(traceback.format_exc())
                if not os.path.exists(json_path):
                    return {
                        "status": "error",
                        "message": f"Lỗi khi chạy process_docx: {str(e)}",
                        "suggestion": "pip install -r requirements.txt"
                    }
        
        steps = []
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content and content not in ('{}', 'null'):
                    steps = json.loads(content)
                    if not isinstance(steps, list):
                        logging.warning(f"JSON file is not a list, got {type(steps)}")
                        steps = []
        except (json.JSONDecodeError, ValueError, FileNotFoundError) as e:
            logging.warning(f"JSON file is invalid: {e}")
            steps = []
        except Exception as e:
            logging.error(f"Error reading JSON: {e}")
            import traceback
            logging.error(traceback.format_exc())
            steps = []
        
        if not steps:
            logging.warning(f"JSON file is empty, automatically running process_docx...")
            process_result = process_docx_files()
            
            if process_result.get("status") == "success":
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        steps = json.load(f)
                except Exception as e:
                    logging.error(f"Error reading JSON after process_docx: {e}")
                    return {
                        "status": "error",
                        "message": f"Không thể đọc file JSON sau khi chạy process_docx: {str(e)}",
                        "process_result": process_result
                    }
            
            if not steps:
                return {
                    "status": "error",
                    "message": f"Không có dữ liệu hướng dẫn trong file JSON sau khi chạy process_docx",
                    "process_result": process_result
                }
        
        # Khởi động HTTP server nếu chưa chạy
        server_port = _start_image_server()
        if server_port is None:
            return {
                "status": "error",
                "message": "Could not start image server"
            }
        
        # Sắp xếp steps theo step_number để đảm bảo thứ tự đúng
        steps = sorted(steps, key=lambda x: x.get("step_number", 0))
        logging.info(f"Sorted {len(steps)} steps by step_number: {[s.get('step_number') for s in steps]}")
        
        # Tạo guide text và images với URLs
        current_dir = os.path.dirname(os.path.abspath(__file__))
        guide_parts = []
        images_data = []
        base_url = f"http://localhost:{server_port}"
        
        images_by_step = {}
        
        for step in steps:
            step_text = step.get("text", "").strip()
            image_path = step.get("image_path")
            step_number = step.get("step_number", 0)
            
            if step_text:
                step_text = step_text.replace("→", "->")
                guide_parts.append(f"Bước {step_number}: {step_text}")
            
            if image_path:
                if not os.path.isabs(image_path):
                    image_path = os.path.join(current_dir, image_path)
                image_path = os.path.normpath(image_path)
            
            if image_path and os.path.exists(image_path):
                filename = os.path.basename(image_path)
                
                try:
                    rel_path = os.path.relpath(image_path, current_dir)
                    encoded_parts = [urllib.parse.quote(part) for part in rel_path.split(os.sep)]
                    encoded_path = '/'.join(encoded_parts)
                    image_url = f"{base_url}/{encoded_path}"
                except ValueError:
                    encoded_filename = urllib.parse.quote(filename)
                    image_url = f"{base_url}/{encoded_filename}"
                    logging.warning(f"Could not create relative path for {image_path}, using filename only")
                
                images_by_step[step_number] = {
                    "filename": filename,
                    "step_number": step_number,
                    "url": image_url,
                    "mime_type": _get_mime_type(filename),
                    "size_kb": round(os.path.getsize(image_path) / 1024, 2)
                }
        
        # Tạo images_data theo đúng thứ tự step_number từ steps đã sort
        for step in steps:
            step_number = step.get("step_number", 0)
            if step_number in images_by_step:
                images_data.append(images_by_step[step_number])
        
        # Sort lại để đảm bảo thứ tự đúng (phòng trường hợp steps không được sort đúng)
        images_data = sorted(images_data, key=lambda x: x.get("step_number", 0))
        
        # Log để debug
        logging.info(f"Steps order: {[s.get('step_number') for s in steps]}")
        logging.info(f"Images order BEFORE return: {[(img['step_number'], img['filename']) for img in images_data]}")
        
        # Nếu agent framework đang reverse, ta cần reverse lại trước khi trả về
        # Test: reverse lại để xem agent có reverse không
        images_data_final = list(reversed(images_data))
        logging.info(f"Images order AFTER reverse (for agent): {[(img['step_number'], img['filename']) for img in images_data_final]}")
        
        guide_text = " -> ".join(guide_parts)
        
        verified_folder_type = determine_folder_type_from_device_name(device_name)
        if folder_type != verified_folder_type:
            logging.warning(f"Folder type mismatch: {folder_type} → {verified_folder_type}")
            folder_type = verified_folder_type
        
        logging.info(f"Retrieved guide for {device_name}: {len(images_data_final)} images, folder_type: {folder_type}")
        
        return {
            "status": "success",
            "device_name": device_name,
            "guide": guide_text,
            "pictures_count": len(images_data_final),
            "folder_type": folder_type,
            "images": images_data_final,
            "message": f"Đã tìm thấy {len(images_data_final)} hình ảnh hướng dẫn" if images_data_final else "Không có hình ảnh"
        }
        
    except Exception as e:
        logging.error(f"Error reading JSON guide: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Lỗi khi đọc hướng dẫn từ JSON: {str(e)}"
        }


def get_complete_location_guide(userid: str) -> dict:
    """
    Tool gộp tất cả các bước: lấy device info, guide từ JSON (đã parse từ Word), và images.
    Giảm số lần gọi tool từ 4 xuống còn 1 để tiết kiệm quota.
    
    Flow: Word → JSON (process_docx.py) → Agent (tool này)
    
    Args:
        userid: Tên đăng nhập của user
    
    Returns:
        dict: Chứa device info, guide text, và tất cả images với URLs
    """
    try:
        # Bước 1: Lấy device info từ database
        device_info = query_DeviceInfo(userid)
        
        if device_info.get("status") != "success" or not device_info.get("data"):
            return {
                "status": "error",
                "message": f"Không tìm thấy thông tin thiết bị cho user: {userid}",
                "device_info": device_info
            }
        
        device_data = device_info["data"][0] if device_info.get("data") else {}
        device_name = device_data.get("DeviceName", "")
        status_message = device_data.get("StatusMessage", "")
        
        if not device_name:
            return {
                "status": "error",
                "message": "Không tìm thấy DeviceName trong database",
                "device_info": device_info
            }
        
        guide_result = get_location_guide_from_json(device_name=device_name)
        
        if guide_result.get("status") != "success":
            error_msg = guide_result.get("message", "")
            is_json_error = "JSON" in error_msg or "json" in error_msg.lower() or "không tìm thấy hướng dẫn" in error_msg
            
            return {
                "status": "error",
                "message": f"Không tìm thấy hướng dẫn cho thiết bị: {device_name}",
                "device_info": device_info,
                "guide_result": guide_result,
                "suggestion": "Call process_docx_files() to regenerate JSON files" if is_json_error else None
            }
        
        # Lấy dữ liệu từ JSON
        guide_text = guide_result.get("guide", "")
        images_data = guide_result.get("images", [])
        pictures_count = len(images_data)
        
        calculated_folder_type = determine_folder_type_from_device_name(device_name)
        folder_type = guide_result.get("folder_type", calculated_folder_type)
        
        if folder_type != calculated_folder_type:
            logging.warning(f"Folder type mismatch: {folder_type} → {calculated_folder_type}")
            folder_type = calculated_folder_type
        
        return {
            "status": "success",
            "userid": userid,
            "device_name": device_name,
            "status_message": status_message,
            "device_info": device_data,
            "guide": guide_text,
            "pictures_count": pictures_count,
            "folder_type": folder_type,
            "images": images_data
        }
        
    except Exception as e:
        logging.error(f"Error in get_complete_location_guide: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Lỗi khi lấy hướng dẫn: {str(e)}"
        }
