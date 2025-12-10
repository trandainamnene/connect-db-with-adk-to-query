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
import pdfplumber
from PIL import Image

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
    Lấy tất cả hình ảnh từ JSON (đã parse từ PDF) và trả về HTTP URLs.
    
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
    Lấy metadata về hình ảnh từ JSON (đã parse từ pdf).
    
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


def get_location_guide_from_pdf(model_name: str = None, model_code: str = None) -> dict:
    """
    Tìm kiếm hướng dẫn cách bật định vị từ file PDF dựa trên tên model hoặc model code.
    
    Args:
        model_name: Tên model thiết bị (ví dụ: "iPhone 6", "Samsung Galaxy S21")
        model_code: Mã model thiết bị (ví dụ: "iPhone7,2", "SM-G991B")
    
    Returns:
        dict: Chứa thông tin hướng dẫn hoặc lỗi nếu không tìm thấy
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        pdf_path = os.path.join(current_dir, "Location_Instruction.pdf")
        
        if not os.path.exists(pdf_path):
            return {
                "status": "error",
                "message": f"File PDF không tìm thấy tại: {pdf_path}"
            }
        
        # Sử dụng pdfplumber để parse bảng từ PDF
        tables = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                extracted_tables = page.extract_tables()
                for table in extracted_tables:
                    tables.extend(table[1:])  # Bỏ header
        
        if not tables:
            return {
                "status": "error",
                "message": "Không tìm thấy bảng dữ liệu trong PDF"
            }
        
        # Chuyển thành DataFrame
        df = pd.DataFrame(tables, columns=["ModelCode", "ModelName", "How_to_Enable_Location"])
        df = df.dropna(subset=['How_to_Enable_Location'])
        
        mask = False
        if model_name:
            mask |= df['ModelName'].astype(str).str.contains(model_name, case=False, na=False)
        if model_code:
            mask |= df['ModelCode'].astype(str).str.contains(model_code, case=False, na=False)
        
        matches = df[mask]
        
        if matches.empty:
            return {
                "status": "error",
                "message": f"Không tìm thấy hướng dẫn cho model: {model_name or model_code}"
            }
        
        result = matches.iloc[0]
        guide_text_raw = result.get('How_to_Enable_Location', '')
        guide_text = "" if pd.isna(guide_text_raw) else str(guide_text_raw).strip()
        
        if not guide_text:
            return {
                "status": "error",
                "message": f"Không có hướng dẫn chi tiết cho model: {model_name or model_code}"
            }
        
        logging.info(f"Found guide from PDF for {model_name or model_code}")
        
        return {
            "status": "success",
            "model_name": result.get('ModelName', ''),
            "model_code": result.get('ModelCode', ''),
            "guide": guide_text
        }
        
    except ImportError as e:
        return {
            "status": "error",
            "message": f"Thiếu thư viện: {str(e)}. Hãy cài đặt pdfplumber: pip install pdfplumber"
        }
    except Exception as e:
        logging.error(f"Error reading PDF: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Lỗi khi đọc PDF: {str(e)}"
        }


def process_pdf_files() -> dict:
    """
    Xử lý file PDF để trích xuất text và hình ảnh thành JSON và folder ảnh.
    
    Returns:
        dict: Kết quả xử lý
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        pdf_path = os.path.join(current_dir, "Location_Instruction.pdf")
        
        if not os.path.exists(pdf_path):
            return {
                "status": "error",
                "message": f"PDF file not found: {pdf_path}"
            }
        
        # Extract table using pdfplumber
        tables = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                extracted_tables = page.extract_tables()
                for table in extracted_tables:
                    tables.extend(table[1:])  # Skip header
        
        if not tables:
            return {
                "status": "error",
                "message": "Không tìm thấy bảng dữ liệu trong PDF"
            }
        
        df = pd.DataFrame(tables, columns=["ModelCode", "ModelName", "How_to_Enable_Location"])
        df = df.dropna(subset=['How_to_Enable_Location'])
        
        # Separate iOS and Android
        ios_df = df[df['ModelCode'].astype(str).str.startswith('iPhone')]
        android_df = df[~df['ModelCode'].astype(str).str.startswith('iPhone')]
        
        # Get guide for iOS and clean
        if not ios_df.empty:
            ios_guide_raw = ios_df['How_to_Enable_Location'].iloc[0].strip()
            match = re.search(r'vào (.+?) ở ứng dụng HỘ NGHÈO và bật lên\.', ios_guide_raw)
            ios_guide = match.group(1) if match else ios_guide_raw
            ios_parts = re.split(r'\s*>\s*', ios_guide)
            ios_parts = [p.strip() for p in ios_parts if p.strip()]
            if len(ios_parts) > 1 and 'ở ứng dụng HỘ NGHÈO và bật lên' in ios_parts[-1]:
                ios_parts[-1] = ios_parts[-1].replace('ở ứng dụng HỘ NGHÈO và bật lên', '')
                ios_parts.append('ứng dụng HỘ NGHÈO')
                ios_parts.append('bật lên')
        else:
            ios_parts = []
        
        # Get guide for Android and clean
        if not android_df.empty:
            android_guide_raw = android_df['How_to_Enable_Location'].iloc[0].strip()
            match = re.search(r'(Bước 1: .+? Cho phép)', android_guide_raw, re.DOTALL)
            android_guide = match.group(1) if match else android_guide_raw
            android_parts = re.split(r'\s*→\s*', android_guide)
            android_parts = [p.strip() for p in android_parts if p.strip()]
        else:
            android_parts = []
        
        # Extract images using pdfplumber
        all_images = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for img in page.images:
                    bbox = (img['x0'], img['top'], img['x1'], img['bottom'])
                    cropped_page = page.within_bbox(bbox)
                    pil_img = cropped_page.to_image().original
                    all_images.append(pil_img)
        
        # Slice images: 0-4 for iOS, 5-7 for Android (assuming 8 images)
        ios_image_data = all_images[0:5]
        android_image_data = all_images[5:8]
        
        # Save iOS images
        ios_folder = os.path.join(current_dir, "IOS_Instruction")
        os.makedirs(ios_folder, exist_ok=True)
        ios_images = []
        for i, pil_img in enumerate(ios_image_data, 1):
            image_filename = f"{i}.jpg"
            image_path = os.path.join(ios_folder, image_filename)
            pil_img = pil_img.convert('RGB')
            pil_img.save(image_path, "JPEG")
            rel_image_path = os.path.relpath(image_path, current_dir)
            ios_images.append(rel_image_path)
        
        # Save Android images
        android_folder = os.path.join(current_dir, "Android_Instruction")
        os.makedirs(android_folder, exist_ok=True)
        android_images = []
        for i, pil_img in enumerate(android_image_data, 1):
            image_filename = f"{i}.jpg"
            image_path = os.path.join(android_folder, image_filename)
            pil_img = pil_img.convert('RGB')
            pil_img.save(image_path, "JPEG")
            rel_image_path = os.path.relpath(image_path, current_dir)
            android_images.append(rel_image_path)
        
        # Create steps for iOS
        ios_steps = []
        for i, part in enumerate(ios_parts, 1):
            image_path = ios_images[i-1] if i-1 < len(ios_images) else None
            ios_steps.append({
                "step_number": i,
                "text": part,
                "image_path": image_path,
                "folder_type": "IOS"
            })
        
        # Create steps for Android
        android_steps = []
        for i, part in enumerate(android_parts, 1):
            image_path = android_images[i-1] if i-1 < len(android_images) else None
            android_steps.append({
                "step_number": i,
                "text": part,
                "image_path": image_path,
                "folder_type": "Android"
            })
        
        # Save to JSON
        ios_json_path = os.path.join(current_dir, "ios_instructions.json")
        with open(ios_json_path, 'w', encoding='utf-8') as f:
            json.dump(ios_steps, f, ensure_ascii=False, indent=2)
        
        android_json_path = os.path.join(current_dir, "android_instructions.json")
        with open(android_json_path, 'w', encoding='utf-8') as f:
            json.dump(android_steps, f, ensure_ascii=False, indent=2)
        
        logging.info(f"Processed PDF: IOS steps {len(ios_steps)}, images {len(ios_images)}; Android steps {len(android_steps)}, images {len(android_images)}")
        return {
            "status": "success",
            "ios_steps_count": len(ios_steps),
            "android_steps_count": len(android_steps),
            "ios_images_count": len(ios_images),
            "android_images_count": len(android_images),
            "message": "PDF processed successfully"
        }
        
    except Exception as e:
        logging.error(f"Error processing PDF: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Lỗi khi xử lý PDF: {str(e)}"
        }


def get_location_guide_from_json(device_name: str) -> dict:
    """
    Lấy hướng dẫn từ file JSON (đã được parse từ PDF).
    TỰ ĐỘNG chạy process_pdf_files() nếu JSON không tồn tại hoặc rỗng.
    
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
        
        should_run_process_pdf = not json_exists or not image_folder_exists or not has_images
        
        if should_run_process_pdf:
            reasons = []
            if not json_exists:
                reasons.append(f"JSON file not found: {json_path}")
            if not image_folder_exists:
                reasons.append(f"Image folder not found: {image_folder}")
            elif not has_images:
                reasons.append(f"Image folder exists but has no images: {image_folder}")
            
            logging.warning(f"{'; '.join(reasons)}, automatically running process_pdf_files...")
            process_result = process_pdf_files()
            if process_result.get("status") != "success":
                return process_result
        
        # Đọc JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            steps = json.load(f)
        
        if not steps:
            logging.warning(f"JSON file is empty, automatically running process_pdf_files...")
            process_result = process_pdf_files()
            if process_result.get("status") == "success":
                with open(json_path, 'r', encoding='utf-8') as f:
                    steps = json.load(f)
            if not steps:
                return {
                    "status": "error",
                    "message": "Không có dữ liệu hướng dẫn trong file JSON"
                }
        
        # Khởi động HTTP server nếu chưa chạy
        server_port = _start_image_server()
        if server_port is None:
            return {
                "status": "error",
                "message": "Could not start image server"
            }
        
        # Sắp xếp steps theo step_number
        steps = sorted(steps, key=lambda x: x.get("step_number", 0))
        
        # Tạo guide text và images với URLs
        guide_parts = []
        images_data = []
        base_url = f"http://localhost:{server_port}"
        
        for step in steps:
            step_text = step.get("text", "").strip()
            image_path_rel = step.get("image_path")
            image_path_abs = os.path.join(current_dir, image_path_rel) if image_path_rel else None
            step_number = step.get("step_number", 0)
            
            if step_text:
                guide_parts.append(f"Bước {step_number}: {step_text}")
            
            if image_path_abs and os.path.exists(image_path_abs):
                encoded_parts = [urllib.parse.quote(part) for part in image_path_rel.split(os.sep)]
                encoded_path = '/'.join(encoded_parts)
                image_url = f"{base_url}/{encoded_path}"
                
                filename = os.path.basename(image_path_abs)
                file_size = os.path.getsize(image_path_abs)
                size_kb = round(file_size / 1024, 2)
                
                images_data.append({
                    "filename": filename,
                    "step_number": step_number,
                    "url": image_url,
                    "mime_type": _get_mime_type(filename),
                    "size_kb": size_kb
                })
        
        guide_text = " -> ".join(guide_parts)
        
        logging.info(f"Retrieved guide for {device_name}: {len(images_data)} images, folder_type: {folder_type}")
        
        return {
            "status": "success",
            "device_name": device_name,
            "guide": guide_text,
            "pictures_count": len(images_data),
            "folder_type": folder_type,
            "images": images_data,
            "message": f"Đã tìm thấy {len(images_data)} hình ảnh hướng dẫn" if images_data else "Không có hình ảnh"
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
    Tool gộp tất cả các bước: lấy device info, guide từ JSON (đã parse từ PDF), và images.
    Giảm số lần gọi tool từ 4 xuống còn 1 để tiết kiệm quota.
    
    Flow: PDF → JSON (process_pdf_files.py) → Agent (tool này)
    
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
                "suggestion": "Call process_pdf_files() to regenerate JSON files" if is_json_error else None
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