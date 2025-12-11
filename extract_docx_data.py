
import os
import json
import logging
import io
import re
import sys
import xml.etree.ElementTree as ET

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Import dependencies
try:
    from PIL import Image
    from docx import Document
    from docx.document import Document as _Document
    from docx.oxml.text.paragraph import CT_P
    from docx.oxml.table import CT_Tbl
    from docx.table import _Cell, Table
    from docx.text.paragraph import Paragraph
except ImportError:
    print("Missing 'python-docx' or 'Pillow'. Please install: pip install python-docx Pillow")
    sys.exit(1)

def iter_block_items(parent):
    """
    Generate a reference to each paragraph and table child within parent, in document order.
    Each returned value is an instance of either Table or Paragraph.
    """
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    elif isinstance(parent, CT_P):
        parent_elm = parent
    else:
        # Fallback for unexpected types
        return

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)

def get_images_from_paragraph(paragraph, doc, output_folder, image_counter_start):
    """
    Finds images within a specific paragraph.
    Returns a list of (image_filename, image_path) and the new counter.
    """
    images_found = []
    current_counter = image_counter_start
    
    if not paragraph.runs:
        return images_found, current_counter

    for run in paragraph.runs:
        if run._element.xml:
            try:
                # Find drawing elements
                root = ET.fromstring(run._element.xml)
                # Helper to find blip with or without namespace (sometimes namespace handling is tricky)
                # We search broadly for blip
                blips = root.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
                
                for blip in blips:
                    r_embed = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                    
                    if r_embed and r_embed in doc.part.rels:
                        rel = doc.part.rels[r_embed]
                        if "image" in rel.target_ref:
                            # Found an image
                            image_data = rel.target_part.blob
                            
                            # Save it
                            image_filename = f"image_{current_counter}.jpg"
                            image_path = os.path.join(output_folder, image_filename)
                            
                            _save_image_data(image_data, image_path)
                            
                            images_found.append(image_path)
                            current_counter += 1
            except Exception as e:
                # Malformed XML or other issue
                continue

    return images_found, current_counter

def _save_image_data(image_data, filepath):
    try:
        image = Image.open(io.BytesIO(image_data))
        # Normalize
        if image.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            bg.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
            image = bg
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        image.save(filepath, "JPEG", quality=85)
    except Exception as e:
        logging.error(f"Error saving image {filepath}: {e}")

def extract_content_sequential(docx_path, output_folder, folder_type_label):
    doc = Document(docx_path)
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    results = []
    
    current_step = 1
    current_text_buffer = []
    image_counter = 1
    
    # Iterate through all block elements (Paragraphs)
    # We ignore tables for now unless requested, as instructions usually in paragraphs
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            
            # Check for Step Header
            # Regex: "Bước X", "Step X", "X." at start
            step_match = re.search(r'^(?:Bước|Step)\s*(\d+)', text, re.IGNORECASE)
            number_match = re.match(r'^(\d+)[\.\)]\s+', text)
            
            is_header = False
            if step_match:
                current_step = int(step_match.group(1))
                is_header = True
            elif number_match:
                # Sometimes lists are just "1. Do this", "2. Do that"
                # But careful not to mistake bullet points for main steps if they are sub-steps
                # Heuristic: If we are already inside Step 1, "1.1" might be substep. "2." might be next step.
                # Let's assume top level numbers are steps.
                try:
                    val = int(number_match.group(1))
                    # Only update if it looks sequential or logical (e.g. not jumping from 1 to 100)
                    if val == current_step + 1 or val == 1:
                        current_step = val
                        is_header = True
                except:
                    pass

            # Extract Images from this Paragraph
            images, new_counter = get_images_from_paragraph(block, doc, output_folder, image_counter)
            image_counter = new_counter
            
            # Logic:
            # If we have text, add to buffer.
            # If we have images, dump buffer + image as a JSON entry.
            # If is_header, we treat it as text too.
            
            if text:
                current_text_buffer.append(text)
            
            if images:
                # For each image found in this paragraph (usually 1, rarely more)
                for img_path in images:
                    # Flush buffer to this step
                    # If buffer is empty (rare, unless image is alone in paragraph)
                    # we might want to attach previous text? 
                    # Actually, if buffer is valid, use it.
                    
                    full_text = "\n".join(current_text_buffer).strip()
                    
                    entry = {
                        "step_number": current_step,
                        "text": full_text,
                        "image_path": img_path,
                        "folder_type": folder_type_label
                    }
                    results.append(entry)
                    
                    # Clear buffer after consuming it for an image?
                    # "Tiểu bước con": The text usually describes the image.
                    # So once assigned to an image, we probably clear it so the next text is for next image.
                    current_text_buffer = []
                    
    # Handle any remaining text that didn't have an image (optional)
    if current_text_buffer:
         full_text = "\n".join(current_text_buffer).strip()
         if full_text:
             # Just text step? Or user only wants steps with images?
             # User format has "image_path", does not say it is optional.
             # However, often there's a final conclusion or tip.
             # Let's add it with image_path = None or ""
             results.append({
                "step_number": current_step,
                "text": full_text,
                "image_path": "",
                "folder_type": folder_type_label
             })

    return results

if __name__ == "__main__":
    # Configuration
    target_file = "HELP_RASOATHONGHEO_AI.docx"
    output_json = "help_rasoathongheo_ai.json"
    folder_type_label = "RASOATHONGHEO" 
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    target_path = os.path.join(current_dir, target_file)
    output_json_path = os.path.join(current_dir, output_json)
    images_dir = os.path.join(current_dir, "extracted_images")
    
    print(f"Processing {target_path}...")
    
    data = extract_content_sequential(target_path, images_dir, folder_type_label)
    
    # Save
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Done. Saved {len(data)} entries.")
