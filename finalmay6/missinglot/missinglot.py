import os
import json
import time
import base64
import requests
import logging
from datetime import datetime


def lambda_handler(event, context):
    pc_api_key = os.getenv('pc_close_api_key')
    pt_api_key = os.getenv('pt_close_api_key')
    
    if not pc_api_key or not pt_api_key:
        print("ERROR: API keys not found in .env file.")
        return
    
    # Base64 encode the API keys for authentication
    pc_encoded_key = base64.b64encode(f"{pc_api_key}:".encode()).decode()
    pt_encoded_key = base64.b64encode(f"{pt_api_key}:".encode()).decode()
    
    # Set up headers for requests
    pc_headers = {
        'Authorization': f'Basic {pc_encoded_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    pt_headers = {
        'Authorization': f'Basic {pt_encoded_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Load the query from JSON file
    query_payload = load_query_from_json("./missing_address_query.json")
    
    if not query_payload:
        print("ERROR: Could not load missing address query data.")
        return
    
    update_missing_lot_addresses(pc_headers, pt_headers, query_payload)

def load_query_from_json(filename):
    """Load and parse a JSON query file"""
    try:
        with open(filename, 'r') as file:
            return json.load(file)
    except Exception as error:
        print(f"Error loading {filename}: {error}")
        return None

def make_api_request(headers, url, payload=None, method="GET"):
    """Make an API request with rate limit handling"""
    while True:
        try:
            if method.upper() == "POST":
                response = requests.post(url, headers=headers, json=payload)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, json=payload)
            elif method.upper() == "GET":
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
                
                print(f"Rate limited. Waiting {reset_time} seconds...")
                time.sleep(reset_time + 0.5)
                continue
            
            # Check for other errors
            if response.status_code not in [200, 201, 204]:
                logging.error(f"API Error: {response.status_code} - {response.text}")
                return {"data": [], "cursor": None, "success": False}
            
            # Return the JSON data
            if method.upper() == "POST" and "/search" in url:
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
            logging.error(f"Request failed: {e}")
            time.sleep(5)
            continue
        except json.JSONDecodeError:
            logging.error("Error decoding API response")
            return {"data": [], "cursor": None}

def get_business_address_from_pt(pt_headers, lot_uid, pt_lot_uid_field_id):
    """Get the business address from the PT account using the Lot UID"""
    if not lot_uid or lot_uid.strip() == '':
        return None
    
    base_url = "https://api.close.com/api/v1/"
    
    pt_search_query = {
        "limit": 10,
        "query": {
            "negate": False,
            "queries": [
                {
                    "negate": False,
                    "object_type": "lead",
                    "type": "object_type"
                },
                {
                    "negate": False,
                    "queries": [
                        {
                            "negate": False,
                            "queries": [
                                {
                                    "condition": {
                                        "mode": "beginning_of_words",
                                        "type": "text",
                                        "value": lot_uid
                                    },
                                    "field": {
                                        "custom_field_id": pt_lot_uid_field_id,
                                        "type": "custom_field"
                                    },
                                    "negate": False,
                                    "type": "field_condition"
                                }
                            ],
                            "type": "and"
                        }
                    ],
                    "type": "and"
                }
            ],
            "type": "and"
        },
        "results_limit": None,
        "sort": []
    }
    
    search_url = f"{base_url}data/search"
    response = make_api_request(pt_headers, search_url, pt_search_query, method="POST")
    
    if not response.get('success', True):
        logging.error("Failed to search PT account")
        return None
        
    results = response.get('data', [])
    
    if not results:
        return None
        
    # Get the first lead
    lead_id = results[0].get('id')
    
    # Get lead details to find addresses
    lead_url = f"{base_url}lead/{lead_id}/"
    lead_response = make_api_request(pt_headers, lead_url)
    
    if not lead_response.get('success', True):
        logging.error("Failed to get lead details")
        return None
        
    lead = lead_response
    
    # Look for business address in addresses
    addresses = lead.get('addresses', [])
    
    for address in addresses:
        if address.get('label', '').lower() == 'business':
            # Format the address
            address_parts = []
            if address.get('address_1'):
                address_parts.append(address.get('address_1'))
            if address.get('address_2'):
                address_parts.append(address.get('address_2'))
            if address.get('city'):
                city_state_zip = []
                city_state_zip.append(address.get('city'))
                if address.get('state'):
                    city_state_zip.append(address.get('state'))
                if address.get('zipcode'):
                    city_state_zip.append(address.get('zipcode'))
                address_parts.append(', '.join(city_state_zip))
            
            return ' '.join(address_parts)
            
    # If no business address found, return first address if available
    if addresses:
        address = addresses[0]
        address_parts = []
        if address.get('address_1'):
            address_parts.append(address.get('address_1'))
        if address.get('address_2'):
            address_parts.append(address.get('address_2'))
        if address.get('city'):
            city_state_zip = []
            city_state_zip.append(address.get('city'))
            if address.get('state'):
                city_state_zip.append(address.get('state'))
            if address.get('zipcode'):
                city_state_zip.append(address.get('zipcode'))
            address_parts.append(', '.join(city_state_zip))
        
        return ' '.join(address_parts)
        
    return None

def update_missing_lot_addresses(pc_headers, pt_headers, query_payload):
    """
    Search for leads with opportunities missing the 'Lot Address' custom field,
    then find the correct business address from a second Close account using the Lot UID.
    """
    base_url = "https://api.close.com/api/v1/"
    
    # Custom field IDs
    lot_address_field_id = "cf_xDLglpyPXow2sw4n4Fayizbu8rviuZaPSwy1wk5foKe"  # Lot Address
    lot_uid_field_id = "cf_Lu4RA5aPZCkuIhiyHgZkRIrASNZy9Q5IuWT4mY53zoh"     # Lot UID
    pt_lot_uid_field_id = "cf_y5hbrSG2aU0c0v3IOWx4fvGfRykNf2Unn6HzDJmNZWN"  # Lot UID in PT account
    
    # Process leads with missing lot addresses
    total_found = 0
    updated_count = 0
    
    try:
        # Handle pagination with cursor
        all_leads = []
        has_more = True
        cursor = None
        
        # Paginate through all search results
        while has_more:
            payload_copy = query_payload.copy()
            if cursor:
                payload_copy["cursor"] = cursor
                
            # Add fields to get opportunities
            if "_fields" not in payload_copy:
                payload_copy["_fields"] = {
                    "lead": ["id", "display_name", "opportunities"]
                }
            
            search_url = f"{base_url}data/search"
            response = make_api_request(pc_headers, search_url, payload_copy, method="POST")
            
            # Add leads to our collection
            if 'data' in response:
                batch_leads = response['data']
                all_leads.extend(batch_leads)
                print(f"Fetched batch of {len(batch_leads)} leads (Total found so far: {len(all_leads)})")
            
            # Check for more pages
            cursor = response.get('cursor')
            has_more = bool(cursor)
        
        total_found = len(all_leads)
        print(f"Processing a total of {total_found} leads with opportunities missing lot addresses")
        
        # Process each lead
        for lead in all_leads:
            lead_id = lead.get('id')
            display_name = lead.get('display_name', 'Unknown')
            opportunities = lead.get('opportunities', [])
            
            print(f"Processing lead: {display_name}")
            
            # Process each opportunity
            for opp_ref in opportunities:
                opp_id = opp_ref.get('id')
                
                # Fetch the full opportunity data
                opp_detail_url = f"{base_url}opportunity/{opp_id}/"
                opp_detail_response = make_api_request(pc_headers, opp_detail_url)
                
                if not opp_detail_response.get('success', True):
                    logging.error(f"Failed to get opportunity details for {opp_id}")
                    continue
                
                # Check if lot address is missing
                lot_address = opp_detail_response.get(f'custom.{lot_address_field_id}')
                
                if lot_address is None or lot_address.strip() == '':
                    # Get the Lot UID
                    lot_uid = opp_detail_response.get(f'custom.{lot_uid_field_id}')
                    
                    if lot_uid and lot_uid.strip() != '':
                        # Look up the business address in the PT account
                        business_address = get_business_address_from_pt(pt_headers, lot_uid, pt_lot_uid_field_id)
                        
                        if business_address:
                            # Update the opportunity with the business address
                            update_data = {
                                f'custom.{lot_address_field_id}': business_address
                            }
                            
                            update_response = make_api_request(
                                pc_headers, 
                                opp_detail_url, 
                                update_data, 
                                method="PUT"
                            )
                            
                            if update_response.get("success", False):
                                updated_count += 1
                                print(f"Updated opportunity {opp_id} with Lot UID {lot_uid} - Added lot address: {business_address}")
                            else:
                                logging.error(f"Failed to update opportunity: {opp_id}")
                        else:
                            print(f"No business address found for Lot UID: {lot_uid}")
                    else:
                        print(f"Opportunity {opp_id} is missing both Lot Address and Lot UID")
        
        # Print summary
        print("\nSummary")
        print("-" * 70)
        print(f"Total leads found: {total_found}")
        print(f"Successfully updated: {updated_count}")
        print(f"Failed to update: {total_found - updated_count}")
        print("-" * 70)
            
    except Exception as e:
        logging.error(f"Exception occurred: {str(e)}")

