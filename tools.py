from .db import get_connection
from dotenv import load_dotenv
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal
import requests

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

def search_location_guide(device_name: str) -> dict:
    """
    Search for location/GPS enabling guide URLs on the web using Exa API.
    Returns tutorial/guide links in Vietnamese language with instructions for enabling location on the device.
    
    The tool searches for:
    - Vietnamese tutorial/guide websites
    - Vietnamese support pages
    - Step-by-step instructions in Vietnamese
    
    Args:
        device_name: Name/brand of the device (e.g., "Samsung Galaxy S21", "iPhone 14")
    
    Returns:
        dict: Search results with:
            - primary_url: Best matching Vietnamese guide URL
            - guide_urls: List of Vietnamese guide URLs (up to 5)
            - results: List of search results with instructions and URLs (Vietnamese only)
    """
    api_key = config.get('EXA_API_KEY')
    if not api_key:
        return {
            "status": "error",
            "message": "EXA_API_KEY not found in .env file. Please add EXA_API_KEY=your_api_key"
        }
    
    # Construct search query - optimized for Vietnamese tutorial/guide pages
    # Focus on Vietnamese language content
    queries = [
        f"{device_name} bật định vị GPS hướng dẫn tiếng việt",
        f"cách bật định vị {device_name} hướng dẫn chi tiết",
        f"{device_name} bật dịch vụ vị trí GPS hướng dẫn",
        f"hướng dẫn bật định vị {device_name} tiếng việt"
    ]
    query = queries[0]  # Use first query for main search
    
    try:
        # Exa API endpoint
        url = "https://api.exa.ai/search"
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        # Request both text content and images - explicitly request images
        payload = {
            "query": query,
            "num_results": 5,
            "contents": {
                "text": {"max_characters": 1500},
                "highlights": {"num_sentences": 5}
            },
            "use_autoprompt": True,
            "text": {"max_characters": 1500}
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Format results with URLs and instructions - Vietnamese only
        results = []
        guide_urls = []
        
        # Process first query results
        for result in data.get('results', []):
            # Get the URL - this is the most important
            page_url = result.get('url', '')
            
            # Get text content
            text_content = result.get('text', '')
            if 'contents' in result and 'text' in result['contents']:
                text_content = result['contents']['text']
            
            # Get highlights
            highlights = result.get('highlights', [])
            if 'contents' in result and 'highlights' in result['contents']:
                highlights = result['contents']['highlights']
            
            # Check if this is a Vietnamese page
            is_vietnamese = False
            is_priority_site = False
            
            if page_url:
                # Check Vietnamese domains and keywords
                vietnamese_domains = [
                    '.vn', 'vnexpress', 'dantri', 'vietnamnet', 'vnreview',
                    'tinhte', 'thegioididong', 'fpt', 'fptshop', 'cellphones',
                    'hướng-dẫn', 'huong-dan', 'tin-tuc'
                ]
                
                # Check if URL contains Vietnamese domain/keywords
                url_lower = page_url.lower()
                is_vietnamese = any(domain in url_lower for domain in vietnamese_domains)
                
                # Check if title or content contains Vietnamese keywords
                title_lower = result.get('title', '').lower()
                text_lower = text_content.lower()
                
                vietnamese_keywords = [
                    'bật', 'hướng dẫn', 'cách', 'định vị', 'gps', 'vị trí',
                    'tiếng việt', 'vietnam', 'việt nam'
                ]
                
                if not is_vietnamese:
                    is_vietnamese = any(keyword in title_lower or keyword in text_lower 
                                      for keyword in vietnamese_keywords)
                
                # Priority Vietnamese sites
                priority_vn_domains = [
                    'vnexpress', 'dantri', 'vietnamnet', 'thegioididong',
                    'fptshop', 'cellphones', '.vn'
                ]
                is_priority_site = any(domain in url_lower for domain in priority_vn_domains)
            
            # Only include Vietnamese results
            if not is_vietnamese:
                continue  # Skip non-Vietnamese results
            
            # Create result item with URL and instructions
            result_item = {
                "title": result.get('title', ''),
                "url": page_url,
                "instructions": text_content,
                "highlights": highlights if isinstance(highlights, list) else [highlights] if highlights else [],
                "is_priority_site": is_priority_site,
                "is_vietnamese": is_vietnamese,
                "is_tutorial": any(keyword in page_url.lower() for keyword in ['tutorial', 'guide', 'how-to', 'help', 'support', 'huong-dan', 'hướng-dẫn'])
            }
            
            results.append(result_item)
            
            # Collect guide URLs (Vietnamese only)
            if page_url:
                guide_urls.append(page_url)
        
        # If no Vietnamese results found, try alternative queries
        if not results and len(queries) > 1:
            for alt_query in queries[1:]:
                try:
                    alt_payload = {
                        "query": alt_query,
                        "num_results": 5,
                        "contents": {
                            "text": {"max_characters": 1500},
                            "highlights": {"num_sentences": 5}
                        },
                        "use_autoprompt": True
                    }
                    alt_response = requests.post(url, json=alt_payload, headers=headers, timeout=20)
                    alt_response.raise_for_status()
                    alt_data = alt_response.json()
                    
                    # Process alternative query results
                    for result in alt_data.get('results', []):
                        page_url = result.get('url', '')
                        text_content = result.get('text', '')
                        if 'contents' in result and 'text' in result['contents']:
                            text_content = result['contents']['text']
                        
                        # Check if Vietnamese
                        url_lower = page_url.lower()
                        title_lower = result.get('title', '').lower()
                        text_lower = text_content.lower()
                        
                        vietnamese_domains = ['.vn', 'vnexpress', 'dantri', 'vietnamnet', 'vnreview',
                                             'tinhte', 'thegioididong', 'fpt', 'fptshop', 'cellphones']
                        vietnamese_keywords = ['bật', 'hướng dẫn', 'cách', 'định vị', 'gps', 'vị trí']
                        
                        is_vietnamese = (any(domain in url_lower for domain in vietnamese_domains) or
                                       any(keyword in title_lower or keyword in text_lower 
                                           for keyword in vietnamese_keywords))
                        
                        if is_vietnamese and page_url:
                            is_priority = any(domain in url_lower for domain in 
                                            ['vnexpress', 'dantri', 'vietnamnet', 'thegioididong', '.vn'])
                            
                            result_item = {
                                "title": result.get('title', ''),
                                "url": page_url,
                                "instructions": text_content,
                                "highlights": result.get('highlights', []),
                                "is_priority_site": is_priority,
                                "is_vietnamese": True,
                                "is_tutorial": any(kw in url_lower for kw in ['huong-dan', 'hướng-dẫn', 'guide', 'tutorial'])
                            }
                            
                            # Check if URL already exists in results
                            if not any(r.get('url') == page_url for r in results):
                                results.append(result_item)
                                guide_urls.append(page_url)
                    
                    if results:
                        break  # Stop if we found Vietnamese results
                except:
                    continue
        
        # Sort results to prioritize Vietnamese priority sites and tutorials
        results.sort(key=lambda x: (
            not x.get('is_priority_site', False),  # Vietnamese priority sites first
            not x.get('is_tutorial', False),       # Tutorials next
            -len(x.get('instructions', ''))        # Longer instructions preferred
        ))
        
        # Get the best/primary URL - prioritize official support and tutorial sites
        primary_url = None
        for result in results:
            if result.get('url') and (result.get('is_priority_site') or result.get('is_tutorial')):
                primary_url = result['url']
                break
        
        # If no priority URL found, use the first result URL
        if not primary_url and results:
            primary_url = results[0].get('url')
        
        # Remove duplicates from guide_urls
        seen_urls = set()
        unique_guide_urls = []
        for url in guide_urls:
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_guide_urls.append(url)
        
        # Limit to top 5 guide URLs
        guide_urls = unique_guide_urls[:5]
        
        # Ensure we always have at least one Vietnamese URL
        if not primary_url:
            logging.warning(f"No Vietnamese URLs found for device: {device_name}")
        else:
            logging.info(f"Found primary Vietnamese URL for {device_name}: {primary_url}")
        
        return {
            "status": "success",
            "query": query,
            "device_info": {
                "device_name": device_name,
            },
            "primary_url": primary_url,  # Best guide URL
            "guide_urls": guide_urls,    # List of guide URLs
            "results": results,
            "total_results": len(results),
            "tutorial_count": sum(1 for r in results if r.get('is_tutorial'))
        }
        
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"Error calling Exa API: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Unexpected error: {str(e)}"
        }
