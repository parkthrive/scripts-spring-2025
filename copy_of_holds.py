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
    
    # Define citation date custom field ID
    citation_date_field_id = "cf_wlmTmD6U8hk3Br48unSR2Z8sIs4sDNRQPG9f0cByLdk"
    
    # Load the query from JSON file (in current directory)
    query_payload = load_query_from_json("./holds_query.json")
    
    if not query_payload:
        print("ERROR: Could not load holds query data.")
        return
    
    # Process the leads one by one
    process_leads(headers, query_payload, citation_date_field_id)

def make_api_request(headers, url, payload=None, method="GET"):
    """Make an API request with rate limit handling"""
    while True:
        try:
            if method.upper() == "POST":
                response = requests.post(url, headers=headers, json=payload)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, json=payload)
            elif method.upper() == "GET":
                if payload:
                    response = requests.get(url, headers=headers, params=payload)
                else:
                    response = requests.get(url, headers=headers)
            else:
                print(f"Unsupported method: {method}")
                return {"data": [], "cursor": None}
            
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
                
                # Wait silently
                time.sleep(reset_time + 0.5)
                continue
            
            # Check for other errors
            if response.status_code not in [200, 201, 204]:
                print(f"API Error: {response.status_code} - {response.text}")
                return {"data": [], "cursor": None, "success": False}
            
            # Return the JSON data
            if method.upper() == "POST" and url.endswith("/search"):
                return response.json()
            elif method.upper() == "PUT":
                return {"success": True}
            elif response.text:
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

def process_leads(headers, query_payload, citation_date_field_id):
    """Process leads one by one, updating the oldest Hold opportunity for each lead"""
    successful_updates = 0
    failed_updates = 0
    total_hold_opportunities = 0
    
    # Step 1: Get leads using the provided query
    all_leads = []
    has_more = True
    cursor = None
    
    # Get leads using cursor-based pagination
    while has_more:
        payload_copy = query_payload.copy()
        if cursor:
            payload_copy["cursor"] = cursor
        
        # Make the API request
        response = make_api_request(headers, "https://api.close.com/api/v1/data/search", payload_copy, method="POST")
        
        # Add leads to our collection
        if 'data' in response:
            batch_leads = response['data']
            all_leads.extend(batch_leads)
            print(f"Fetched batch of {len(batch_leads)} leads (Total found so far: {len(all_leads)})")
        
        # Check for more pages
        cursor = response.get('cursor')
        has_more = bool(cursor)
    
    total_leads = len(all_leads)
    print(f"Processing a total of {total_leads} leads")
    
    # Step 2: Process each lead individually
    for lead in all_leads:
        lead_id = lead.get('id')
        display_name = lead.get('display_name', 'Unknown')
        
        print(f"Processing lead: {display_name}")
        
        # Get complete lead details to access opportunities
        lead_details = make_api_request(headers, f"https://api.close.com/api/v1/lead/{lead_id}/")
        
        # Get opportunities for this lead
        opportunities = lead_details.get('opportunities', [])
        
        # Find opportunities in "Hold" status for this lead
        hold_status_id = "stat_fB3saONDWZTs4JVRhLe6bq310jNaTJonrPKAlclzzOy"
        hold_opportunities = []
        
        for opp in opportunities:
            opp_id = opp.get('id')
            opp_status_id = opp.get('status_id')
            
            # If it's in hold status, get complete opportunity details
            if opp_status_id == hold_status_id:
                # Get full opportunity details to access custom fields
                opp_details = make_api_request(headers, f"https://api.close.com/api/v1/opportunity/{opp_id}/")
                hold_opportunities.append(opp_details)
        
        lead_hold_count = len(hold_opportunities)
        total_hold_opportunities += lead_hold_count
        
        if lead_hold_count == 0:
            print(f"No opportunities in 'Hold' status for this lead")
            continue
        
        # Find the opportunity with the oldest citation date for this lead
        oldest_opportunity = None
        oldest_date = None
        citation_date_key = f"custom.{citation_date_field_id}"
        
        for opportunity in hold_opportunities:
            # Get citation date from custom field
            if citation_date_key not in opportunity:
                continue
                
            citation_date_str = opportunity[citation_date_key]
            if not citation_date_str:
                continue
            
            try:
                # Try to parse date in various formats
                citation_date = None
                date_formats = ['%m/%d/%Y', '%Y-%m-%d', '%m-%d-%Y', '%d/%m/%Y']
                
                for date_format in date_formats:
                    try:
                        citation_date = datetime.strptime(citation_date_str, date_format)
                        break
                    except ValueError:
                        continue
                
                if citation_date is None:
                    continue
                    
                # Check if this is the oldest date
                if oldest_date is None or citation_date < oldest_date:
                    oldest_date = citation_date
                    oldest_opportunity = opportunity
                    
            except Exception as e:
                continue
        
        if not oldest_opportunity:
            print(f"No opportunities with valid citation dates found for this lead")
            continue
        
        # Update the oldest opportunity to "Unpaid" status
        opp_id = oldest_opportunity['id']
        opp_name = oldest_opportunity.get('display_name', 'Unknown')
        
        print(f"Updating oldest opportunity for this lead: {opp_name}")
        
        # Update status to "Unpaid"
        unpaid_status_id = "stat_IhSstcuVR2EhiaHesQwowu9Y0JkjQfVV6BvBhXQxBnT"
        update_payload = {
            'status_id': unpaid_status_id
        }
        
        update_response = make_api_request(
            headers,
            f"https://api.close.com/api/v1/opportunity/{opp_id}/",
            update_payload,
            method="PUT"
        )
        
        if update_response.get("success", False) or isinstance(update_response, dict) and update_response.get("status_id") == unpaid_status_id:
            successful_updates += 1
            print(f"Successfully updated opportunity status to 'Unpaid' for: {opp_name}")
        else:
            failed_updates += 1
            print(f"Failed to update opportunity status for: {opp_name}")
    
    # Print summary
    print("\nSummary")
    print("-" * 70)
    print(f"Total leads found: {total_leads}")
    print(f"Total 'Hold' opportunities: {total_hold_opportunities}")
    print(f"Successfully updated: {successful_updates}")
    print(f"Failed to update: {failed_updates}")
    print("-" * 70)

if __name__ == "__main__":
    main()
