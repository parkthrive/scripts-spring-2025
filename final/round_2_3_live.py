import os
import json
import time
import base64
import requests
from datetime import datetime

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

def main():
    # Load environment variables from .env file
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
    
    # Load the query from JSON file
    query_payload = load_query_from_json("./round_2_&_3_query.json")
    
    if not query_payload:
        print("ERROR: Could not load query data.")
        return
    
    # Define status updates mapping - set reset_dates to False for both transitions
    status_updates = {
        "stat_YM4zWiayFRmMPX81kVRtUc55bCONbHzCun81YvCU8xJ": {  # Status '1'
            "new_status": "stat_etKn0Polby4XpPZjd5JxhUjVqovplh5uv8HrWDnpClm",  # Change to '2'
            "template": "template_epFxkRdNuHXiR8mihVsUCe",  # Template for Round 2
            "reset_dates": False
        },
        "stat_etKn0Polby4XpPZjd5JxhUjVqovplh5uv8HrWDnpClm": {  # Status '2'
            "new_status": "stat_hrU7Gd0liwAfY3TCJ1IA5k5RxSzIKaBJYfNEbtmg3Yc",  # Change to '3'
            "template": "template_jQgW1CnJ9BdDikMPt1znox",  # Template for Round 3
            "reset_dates": False  # Changed to False to match behavior of status '1'
        }
    }
    
    # Get current date
    date_today = datetime.now().strftime('%m/%d/%Y')
    
    # Get all leads matching the query
    leads = get_all_leads(headers, query_payload)
    total_leads = len(leads)
    successful_updates = 0
    
    print(f"\n{'='*60}")
    print(f"PROCESSING {total_leads} LEADS")
    print(f"{'='*60}")
    
    # Process each lead
    for index, lead in enumerate(leads, 1):
        lead_id = lead.get('id')
        display_name = lead.get('display_name', 'Unknown')
        opportunities = lead.get('opportunities', [])
        
        # Clear previous line and show current progress
        print(f"\nProcessing lead {index}/{total_leads}")
        print(f"Lead ID: {lead_id}")
        
        updated = False
        
        for opportunity in opportunities:
            opportunity_id = opportunity.get('id')
            
            # Get full opportunity details
            opportunity_url = f"https://api.close.com/api/v1/opportunity/{opportunity_id}/"
            opp_details = make_api_request(headers, opportunity_url)
            
            if not isinstance(opp_details, dict) or 'status_id' not in opp_details:
                continue
                
            current_status_id = opp_details.get('status_id')
            # Check if we need to update this status
            if current_status_id in status_updates:
                status_info = status_updates[current_status_id]
                new_status_id = status_info["new_status"]
                template_id = status_info["template"]
                
                # Get current mailer dates
                current_mailer_dates = opp_details.get('custom.cf_JWPYpJQg1RLH2Z4wQw8mtdz8YyZTfF22mF97f1JDocf')
                
                # Always append the new date to existing dates, regardless of status
                new_mailer_dates = f"{current_mailer_dates},{date_today}" if current_mailer_dates else date_today
                
                # Create update data
                opportunity_update_data = {
                    'status_id': new_status_id,
                    'custom.cf_JWPYpJQg1RLH2Z4wQw8mtdz8YyZTfF22mF97f1JDocf': new_mailer_dates
                }
                
                # Add template if provided
                if template_id:
                    opportunity_update_data['custom.cf_NqmTys3HpgtKMa6OK3mc46kgbbGWwgWH2xAM3UcUObe'] = template_id
                
                # Update opportunity
                update_response = make_api_request(
                    headers,
                    opportunity_url,
                    opportunity_update_data,
                    method="PUT"
                )
                
                if update_response.get('success', True):
                    # Update lead with the last mail date
                    lead_url = f"https://api.close.com/api/v1/lead/{lead_id}/"
                    lead_update_data = {
                        'custom.cf_YgLBH6cihcQCc1DmjFSWARc7HlBcLgKevED1KUdh0Bm': date_today
                    }
                    
                    lead_update_response = make_api_request(
                        headers,
                        lead_url,
                        lead_update_data,
                        method="PUT"
                    )
                    
                    if lead_update_response.get('success', True):
                        successful_updates += 1
                        updated = True
                        print(f"Status: Success")
                    else:
                        print(f"Status: Error - Failed to update lead")
                else:
                    print(f"Status: Error - Failed to update opportunity")
        
        if not updated and opportunities:
            print(f"Status: Error - No eligible opportunities for update")
        elif not opportunities:
            print(f"Status: Error - No opportunities found")
            
        # Add a small delay to avoid hitting rate limits
        time.sleep(1)
    
    # Print summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Total leads processed: {total_leads}")
    print(f"Successfully processed: {successful_updates}")
    print(f"Failed to process: {total_leads - successful_updates}")
    if total_leads > 0:
        print(f"Success rate: {successful_updates/total_leads*100:.1f}%")
    print("="*60)

if __name__ == "__main__":
    main()
