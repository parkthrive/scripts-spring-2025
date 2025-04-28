import os
import json
import time
import base64
import requests
from datetime import datetime
from dotenv import load_dotenv

def main():
    # Load environment variables from .env file (one level up)
    load_dotenv('../.env')
    api_key = os.getenv('pc_close_api_key')
    
    if not api_key:
        print("ERROR: No API key found in .env file.")
        return
    
    # Base64 encode the API key for authentication
    encoded_api_key = base64.b64encode(f"{api_key}:".encode()).decode()
    
    # Set up headers for requests
    headers = {
        'Authorization': f'Basic {encoded_api_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Load the query from JSON file (in current directory)
    query_payload = load_query_from_json("./round_1_query.json")
    
    if not query_payload:
        print("ERROR: Could not load Round 1 query data.")
        return
    
    # Get all leads matching the query
    leads = get_all_leads(headers, query_payload)
    process_leads(headers, leads)

def make_api_request(headers, url, payload=None, method="GET"):
    """Make an API request with rate limit handling"""
    while True:
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=payload)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, json=payload)
            else:
                print(f"Unsupported method: {method}")
                return {"data": [], "cursor": None, "success": False}
            
            # Check if rate limited
            if response.status_code == 429:
                # Get rate reset time
                reset_time = None
                
                # Try retry-after header first
                if 'retry-after' in response.headers:
                    try:
                        reset_time = float(response.headers['retry-after'])
                    except (ValueError, TypeError):
                        pass
                
                # Try to parse ratelimit header if available
                if reset_time is None and 'ratelimit' in response.headers:
                    try:
                        rate_limit_header = response.headers['ratelimit']
                        parts = rate_limit_header.split(',')
                        for part in parts:
                            if 'reset=' in part:
                                reset_value = part.split('=')[1].strip()
                                if ';' in reset_value:
                                    reset_value = reset_value.split(';')[0].strip()
                                reset_time = float(reset_value)
                                break
                    except Exception:
                        pass
                
                # If we still don't have a reset time, use default
                if not reset_time:
                    reset_time = 5
                
                # Silent waiting - removed the print statement
                time.sleep(reset_time + 0.5)
                continue
            
            # Check for other errors
            if response.status_code not in [200, 201, 204]:
                print(f"API Error: {response.status_code} - {response.text}")
                return {"data": [], "cursor": None, "success": False}
            
            # Return the JSON data
            if response.text:
                try:
                    return response.json()
                except json.JSONDecodeError:
                    return {"success": True}
            else:
                return {"success": True}
            
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            time.sleep(5)
            continue
        except json.JSONDecodeError:
            print("Error decoding API response")
            return {"data": [], "cursor": None}

def load_query_from_json(filename):
    """Load and parse a JSON query file"""
    try:
        with open(filename, 'r') as file:
            return json.load(file)
    except Exception as error:
        print(f"Error loading {filename}: {error}")
        return None

def get_all_leads(headers, query_payload):
    """Get all leads using cursor-based pagination"""
    all_leads = []
    has_more = True
    cursor = None
    base_url = "https://api.close.com/api/v1/data/search"
    
    # Create a copy of the payload
    payload_copy = query_payload.copy()
    
    # Add fields to get opportunities if not present
    if "_fields" not in payload_copy:
        payload_copy["_fields"] = {
            "lead": ["id", "display_name", "opportunities"]
        }
    
    # Initial message
    print("Fetching leads: 0", end="", flush=True)
    
    while has_more:
        # Update cursor if we have one
        if cursor:
            payload_copy["cursor"] = cursor
        
        # Make the API request
        response = make_api_request(headers, base_url, payload_copy, method="POST")
        
        # Add leads to our collection
        if 'data' in response:
            batch_leads = response["data"]
            all_leads.extend(batch_leads)
            # Update the count in place (overwrite previous number)
            print(f"\rFetching leads: {len(all_leads)}", end="", flush=True)
        
        # Update cursor and check if we have more pages
        cursor = response.get("cursor")
        has_more = bool(cursor)
        
        # Add a small delay to avoid hitting rate limits
        time.sleep(0.5)
    
    total_found = len(all_leads)
    # Print final count with a newline
    print(f"\rFetched {total_found} leads.")
    
    return all_leads

def process_leads(headers, leads):
    """Process leads based on the query"""
    successful_updates = 0
    total_found = len(leads)
    date_today = datetime.now().strftime('%m/%d/%Y')
    
    print(f"\n{'='*60}")
    print(f"PROCESSING {total_found} LEADS")
    print(f"{'='*60}")
    
    # Process each lead
    for index, lead in enumerate(leads, 1):
        lead_id = lead.get('id')
        display_name = lead.get('display_name', 'Unknown')
        
        # Clear previous line and show current progress
        print(f"\nProcessing lead {index}/{total_found}")
        print(f"Lead ID: {lead_id}")
        
        # Find the unpaid opportunity
        opportunities = lead.get('opportunities', [])
        unpaid_opportunity = None
        for opp in opportunities:
            if opp.get('status_label', '').lower() == 'unpaid':
                unpaid_opportunity = opp
                break
        
        updated = False
        
        if unpaid_opportunity:
            opportunity_id = unpaid_opportunity['id']
            
            # Update the opportunity
            opportunity_update = {
                'status_id': 'stat_YM4zWiayFRmMPX81kVRtUc55bCONbHzCun81YvCU8xJ',  # Status ID for '1'
                'custom.cf_JWPYpJQg1RLH2Z4wQw8mtdz8YyZTfF22mF97f1JDocf': date_today,  # Custom field for mailer dates
                'custom.cf_NqmTys3HpgtKMa6OK3mc46kgbbGWwgWH2xAM3UcUObe': 'template_8iK9EPaUVw8FeAMiNRS1LY'  # Template ID
            }
            
            opp_response = make_api_request(
                headers,
                f"https://api.close.com/api/v1/opportunity/{opportunity_id}/",
                opportunity_update,
                method="PUT"
            )
            
            if opp_response.get("success", True):
                # Now update the lead with the last mail date
                lead_update = {
                    'custom.cf_YgLBH6cihcQCc1DmjFSWARc7HlBcLgKevED1KUdh0Bm': date_today  # Custom field for last mail date
                }
                
                lead_response = make_api_request(
                    headers,
                    f"https://api.close.com/api/v1/lead/{lead_id}/",
                    lead_update,
                    method="PUT"
                )
                
                if lead_response.get("success", True):
                    successful_updates += 1
                    updated = True
                    print(f"Status: Success")
                else:
                    print(f"Status: Error - Failed to update lead")
            else:
                print(f"Status: Error - Failed to update opportunity")
        else:
            print(f"Status: Error - No unpaid opportunity found")
        
        # Add a small delay to avoid hitting rate limits
        time.sleep(1)
    
    # Print summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Total leads processed: {total_found}")
    print(f"Successfully processed: {successful_updates}")
    print(f"Failed to process: {total_found - successful_updates}")
    print(f"Success rate: {successful_updates/total_found*100:.1f}%")
    print("="*60)

if __name__ == "__main__":
    main()
