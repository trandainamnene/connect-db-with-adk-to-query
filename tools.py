from .db import get_connection
from dotenv import load_dotenv
import logging
import os
import re
import json
import io
import urllib.parse
import threading
import http.server
import socketserver
import pdfplumber
import sys 
import xml.etree.ElementTree as ET
from PIL import Image
from datetime import date, datetime
from decimal import Decimal
import pandas as pd

# Load Env
load_dotenv()
config = {
    'SERVER': os.getenv('SERVER'),
    'DATABASE': os.getenv('DATABASE'),
    'UID': os.getenv('UID'),
    'PWD': os.getenv('PWD'),
    'TABLE': os.getenv('TABLE')
}

# Image Server Globals
_image_server = None
_image_server_port = None
_image_server_thread = None

# --- UTILS ---
def convert_value_to_json_serializable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    elif isinstance(value, Decimal):
        return float(value)
    elif value is None:
        return None
    return value

def determine_folder_type_from_device_name(device_name: str) -> str:
    if not device_name:
        return "Android"
    device_lower = str(device_name).lower()
    is_ios = any(keyword in device_lower for keyword in ['iphone', 'ios', 'ipad'])
    return "IOS" if is_ios else "Android"

def _get_mime_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', 
        '.png': 'image/png', '.gif': 'image/gif', 
        '.bmp': 'image/bmp'
    }.get(ext, 'image/jpeg')

# --- IMAGE SERVER ---
class ImageHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            clean_path = urllib.parse.unquote(parsed.path).lstrip('/')
            
            # Prevent directory traversal
            if '..' in clean_path or clean_path.startswith('/'):
                 self.send_error(403, "Forbidden")
                 return
                 
            # Logic to find file:
            # 1. Check if relative to current dir
            current_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(current_dir, clean_path)
            
            if not os.path.exists(file_path):
                # 2. If it's just a filename, look in known image folders
                filename = os.path.basename(clean_path)
                folders = [
                    os.path.join(current_dir, "IOS_Instruction"),
                    os.path.join(current_dir, "Android_Instruction"),
                    os.path.join(current_dir, "extracted_images")
                ]
                for fld in folders:
                    potential_path = os.path.join(fld, filename)
                    if os.path.exists(potential_path):
                        file_path = potential_path
                        break
            
            if file_path and os.path.exists(file_path) and os.path.isfile(file_path):
                with open(file_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', _get_mime_type(file_path))
                self.send_header('Content-Length', len(content))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, "File not found")
        except Exception:
            self.send_error(500, "Server Error")

    def log_message(self, format, *args):
        pass

def _start_image_server():
    global _image_server, _image_server_thread, _image_server_port
    if _image_server: return _image_server_port
    
    for port in range(8765, 8775):
        try:
            _image_server = socketserver.TCPServer(("", port), ImageHandler)
            _image_server_port = port
            _image_server_thread = threading.Thread(target=_image_server.serve_forever, daemon=True)
            _image_server_thread.start()
            logging.info(f"Image server started on port {_image_server_port}")
            return port
        except OSError:
            continue
    logging.error("Could not start image server")
    return None

# --- DOC PARSING HELPERS (DOCX) ---
try:
    from docx import Document
    from docx.document import Document as _Document
    from docx.oxml.text.paragraph import CT_P
    from docx.oxml.table import CT_Tbl
    from docx.table import _Cell, Table
    from docx.text.paragraph import Paragraph
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    logging.warning("python-docx not installed.")

def _iter_block_items(parent):
    if isinstance(parent, _Document): parent_elm = parent.element.body
    elif isinstance(parent, _Cell): parent_elm = parent._tc
    elif isinstance(parent, CT_P): parent_elm = parent
    else: return
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P): yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl): yield Table(child, parent)

def _get_images_from_paragraph(paragraph, doc, output_folder, image_counter):
    images_found = []
    if not paragraph.runs: return images_found, image_counter
    
    for run in paragraph.runs:
        if run._element.xml:
            try:
                root = ET.fromstring(run._element.xml)
                blips = root.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
                for blip in blips:
                    r_embed = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                    if r_embed and r_embed in doc.part.rels:
                        rel = doc.part.rels[r_embed]
                        if "image" in rel.target_ref:
                             image_path = os.path.join(output_folder, f"image_{image_counter}.jpg")
                             _save_image_data(rel.target_part.blob, image_path)
                             images_found.append(image_path)
                             image_counter += 1
            except Exception: continue
    return images_found, image_counter

def _save_image_data(image_data, filepath):
    try:
        image = Image.open(io.BytesIO(image_data))
        if image.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P': image = image.convert('RGBA')
            bg.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
            image = bg
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(filepath, "JPEG", quality=85)
    except Exception as e:
        logging.error(f"Error saving image {filepath}: {e}")

def _extract_docx_data(docx_path, output_folder, folder_type_label):
    if not HAS_DOCX: return []
    doc = Document(docx_path)
    if not os.path.exists(output_folder): os.makedirs(output_folder)
    
    results = []
    current_step = 1
    current_text_buffer = []
    image_counter = 1
    
    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            
            # Step detection
            step_match = re.search(r'^(?:Bước|Step)\s*(\d+)', text, re.IGNORECASE)
            number_match = re.match(r'^(\d+)[\.\)]\s+', text)
            
            if step_match:
                current_step = int(step_match.group(1))
            elif number_match:
                try:
                    val = int(number_match.group(1))
                    if val == current_step + 1 or val == 1: current_step = val
                except: pass
            
            # Image extraction
            images, image_counter = _get_images_from_paragraph(block, doc, output_folder, image_counter)
            
            if text: current_text_buffer.append(text)
            
            if images:
                for img_path in images:
                    full_text = "\n".join(current_text_buffer).strip()
                    results.append({
                        "step_number": current_step,
                        "text": full_text,
                        "image_path": img_path,
                        "folder_type": folder_type_label
                    })
                    current_text_buffer = []
                    
    if current_text_buffer:
         full_text = "\n".join(current_text_buffer).strip()
         if full_text:
             results.append({
                "step_number": current_step,
                "text": full_text,
                "image_path": "",
                "folder_type": folder_type_label
             })
    return results

# --- DOC PARSING HELPERS (PDF) ---
def process_pdf_files() -> dict:
    """Extract location guides from PDF."""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        pdf_path = os.path.join(current_dir, "Location_Instruction.pdf")
        if not os.path.exists(pdf_path): return {"status": "error", "message": "PDF not found"}
        
        tables = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_tables()
                for table in extracted: tables.extend(table[1:])
        
        if not tables: return {"status": "error", "message": "No tables in PDF"}
        
        df = pd.DataFrame(tables, columns=["ModelCode", "ModelName", "How_to_Enable_Location"]).dropna(subset=['How_to_Enable_Location'])
        
        # Process logic (Shortened for brevity but keeping core logic)
        # Assuming one common guide for IOS and one for Android for simplicity if specific model mapping isn't perfect
        ios_rows = df[df['ModelCode'].astype(str).str.startswith('iPhone')]
        android_rows = df[~df['ModelCode'].astype(str).str.startswith('iPhone')]
        
        # ... (Image extraction logic from original tool) ...
        # For brevity, implementing a simplified version that just extracts images and maps them blindly 
        # as the original logic was doing specific slicing [0:5] and [5:8].
        
        # Re-implementing exact logic to ensure no regression
        all_images = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for img in page.images:
                    bbox = (img['x0'], img['top'], img['x1'], img['bottom'])
                    all_images.append(page.within_bbox(bbox).to_image().original)
        
        ios_imgs = all_images[0:5] if len(all_images) >= 5 else []
        android_imgs = all_images[5:8] if len(all_images) >= 8 else []
        
        # Save images
        ios_folder = os.path.join(current_dir, "IOS_Instruction")
        android_folder = os.path.join(current_dir, "Android_Instruction")
        os.makedirs(ios_folder, exist_ok=True)
        os.makedirs(android_folder, exist_ok=True)
        
        ios_paths = []
        for i, img in enumerate(ios_imgs, 1):
             p = os.path.join(ios_folder, f"{i}.jpg")
             img.convert('RGB').save(p, "JPEG")
             ios_paths.append(os.path.relpath(p, current_dir))
             
        android_paths = []
        for i, img in enumerate(android_imgs, 1):
             p = os.path.join(android_folder, f"{i}.jpg")
             img.convert('RGB').save(p, "JPEG")
             android_paths.append(os.path.relpath(p, current_dir))
             
        # Create Steps (Simplified parsing logic from original)
        def _make_steps(text, img_paths, type_):
            parts = [p.strip() for p in re.split(r'\s*>\s*|\s*→\s*', text) if p.strip()]
            steps = []
            for i, part in enumerate(parts, 1):
                img = img_paths[i-1] if i-1 < len(img_paths) else None
                steps.append({"step_number": i, "text": part, "image_path": img, "folder_type": type_})
            return steps

        ios_steps = _make_steps(ios_rows.iloc[0]['How_to_Enable_Location'] if not ios_rows.empty else "", ios_paths, "IOS")
        android_steps = _make_steps(android_rows.iloc[0]['How_to_Enable_Location'] if not android_rows.empty else "", android_paths, "Android")
        
        with open(os.path.join(current_dir, "ios_instructions.json"), 'w', encoding='utf-8') as f: json.dump(ios_steps, f, indent=2)
        with open(os.path.join(current_dir, "android_instructions.json"), 'w', encoding='utf-8') as f: json.dump(android_steps, f, indent=2)
        
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- CORE TOOLS ---

def query_DeviceInfo(userid: str) -> dict:
    """Get device info from DB."""
    if not config.get('TABLE'): return {"status": "error", "message": "Missing TABLE env var"}
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {config['TABLE']} WHERE UserID = ?", (str(userid),))
        columns = [c[0] for c in cursor.description]
        rows = cursor.fetchall()
        data = [{columns[i]: convert_value_to_json_serializable(row[i]) for i in range(len(columns))} for row in rows]
        return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_complete_location_guide(userid: str) -> dict:
    """Get location enable guide for user's device."""
    # 1. Get Device Info
    dev_info = query_DeviceInfo(userid)
    if dev_info.get("status") != "success" or not dev_info.get("data"):
         return {"status": "error", "message": "Device info not found"}
    
    device_name = dev_info['data'][0].get('DeviceName', '')
    folder_type = determine_folder_type_from_device_name(device_name)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Get Guide (Check JSON, generate if needed)
    json_path = os.path.join(current_dir, "ios_instructions.json" if folder_type == "IOS" else "android_instructions.json")
    
    if not os.path.exists(json_path):
        process_pdf_files()
        
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f: steps = json.load(f)
    else:
        steps = []
        
    # 3. Format Response
    port = _start_image_server()
    base_url = f"http://localhost:{port}" if port else ""
    
    images_data = []
    guide_parts = []
    
    for step in sorted(steps, key=lambda x: x.get('step_number', 0)):
        txt = step.get('text', '').strip()
        img_rel = step.get('image_path')
        if txt: guide_parts.append(f"Bước {step.get('step_number')}: {txt}")
        
        if img_rel:
            images_data.append({
                "step_number": step.get('step_number'),
                "url": f"{base_url}/{img_rel.replace(os.sep, '/')}" if base_url else img_rel,
                "filename": os.path.basename(img_rel)
            })
            
    return {
        "status": "success",
        "device_name": device_name,
        "guide": " -> ".join(guide_parts),
        "images": images_data
    }

def get_poverty_app_download_guide() -> dict:
    """
    Get instructions for downloading "Hộ Nghèo" app (Quản lý hộ nghèo).
    Automagically extracts from DOCX if JSON not present.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(current_dir, "help_rasoathongheo_ai.json")
    docx_path = os.path.join(current_dir, "HELP_RASOATHONGHEO_AI.docx")
    images_dir = os.path.join(current_dir, "extracted_images")
    
    # Check if we need to extract
    needs_extraction = False
    if not os.path.exists(json_path):
        needs_extraction = True
    elif not os.path.exists(images_dir) or not os.listdir(images_dir):
        needs_extraction = True
        
    if needs_extraction:
        logging.info("Extracting data from HELP_RASOATHONGHEO_AI.docx...")
        if not os.path.exists(docx_path):
            return {"status": "error", "message": "Source DOCX file not found."}
            
        try:
            data = _extract_docx_data(docx_path, images_dir, "RASOATHONGHEO")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"status": "error", "message": f"Extraction failed: {str(e)}"}
            
    # Read Data
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            steps = json.load(f)
            
        port = _start_image_server()
        base_url = f"http://localhost:{port}" if port else ""
        
        formatted_steps = []
        for step in steps:
            img_path = step.get("image_path")
            img_url = None
            if img_path:
                # Handle absolute paths from previous extraction script
                if os.path.isabs(img_path):
                    rel_path = os.path.relpath(img_path, current_dir)
                else:
                    rel_path = img_path
                img_url = f"{base_url}/{rel_path.replace(os.sep, '/')}" if base_url else rel_path

            formatted_steps.append({
                "step": step.get("step_number"),
                "instruction": step.get("text"),
                "image_url": img_url
            })
            
        return {
            "status": "success",
            "app_name": "Quản lý Hộ Nghèo",
            "steps": formatted_steps
        }
    except Exception as e:
        return {"status": "error", "message": f"Error reading guide: {str(e)}"}