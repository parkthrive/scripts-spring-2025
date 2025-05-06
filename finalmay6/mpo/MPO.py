import os
import json
import time
import base64
import requests
import re

def main():

    api_key = os.getenv('close_lead_assigner_api')
    
    if not api_key:
        # Try alternative variable names silently
        alternative_names = ['CLOSE_API_KEY', 'CLOSE_API', 'API_KEY']
        for name in alternative_names:
            api_key = os.getenv(name)
            if api_key:
                break
        
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
    
    # Load the smart view queries with updated file paths
    counting_payload = load_query_from_json("la_mpo.json")
    reservoir_payload = load_query_from_json("mpo_reservoir.json")
    
    if not counting_payload:
        # Try to use the uploaded paste.txt content
        counting_payload = create_query_from_paste()
        
        if not counting_payload:
            print("ERROR: Could not load lead counting query data.")
            return
    
    if not reservoir_payload:
        print("ERROR: Could not load reservoir leads query data.")
        return
    
    # Parse the sales_reps file (one level up)
    sales_reps = parse_sales_reps_file("./sales_reps.txt")
    
    if not sales_reps:
        print("ERROR: No sales reps found.")
        return
    
    # Set target leads per AE
    target_leads = 400
    
    # Count leads for each sales rep
    lead_counts = []
    
    for i, (rep_name, rep_id) in enumerate(sales_reps):
        print(f"Processing {rep_name}...")
        lead_count = count_leads_for_rep(headers, counting_payload, rep_name, rep_id)
        
        # Calculate needed leads
        needed_leads = max(0, target_leads - lead_count)
        # Calculate work percentage based on the ratio of needed leads to the target
        work_percentage = round((needed_leads / target_leads) * 100)
        
        # Assign leads if needed
        assigned_count = 0
        if needed_leads > 0:
            print(f"Assigning {needed_leads} leads to {rep_name}...")
            assigned_count = assign_leads_to_rep(headers, reservoir_payload, rep_name, rep_id, needed_leads)
            print(f"Successfully assigned {assigned_count} leads to {rep_name}")
        
        lead_counts.append((rep_name, rep_id, lead_count, needed_leads, assigned_count, work_percentage))
        
        if i < len(sales_reps) - 1:
            time.sleep(1)  # Small delay between reps to avoid rate limiting
    
    # Print enhanced summary
    print("\nSummary")
    print("-" * 70)
    print(f"{'Name':<20} {'Has':<8} {'Needs':<8} {'Assigned':<10} {'Worked':<8}")
    print("-" * 70)
    
    for rep_name, rep_id, count, needed, assigned, worked in lead_counts:
        print(f"{rep_name:<20} {count:<8} {needed:<8} {assigned:<10} {worked}%")
    
    print("-" * 70)

def load_query_from_json(filename):
    """Load and parse a JSON query file"""
    try:
        with open(filename, 'r') as file:
            return json.load(file)
    except Exception as error:
        print(f"Error loading {filename}: {error}")
        return None

def create_query_from_paste():
    """Create a query payload from the uploaded paste content"""
    try:
        # Since we're in a subfolder now, need to check for paste.txt in parent dir
        # Try current directory first
        if os.path.exists('paste.txt'):
            with open('paste.txt', 'r') as file:
                return json.load(file)
        # Then try parent directory
        elif os.path.exists('../paste.txt'):
            with open('../paste.txt', 'r') as file:
                return json.load(file)
        else:
            print("paste.txt not found in current or parent directory")
            return None
    except Exception as error:
        print(f"Error creating query from paste content: {error}")
        return None

def parse_sales_reps_file(filename):
    """Parse the sales_reps file which has JSON-like format with names and user IDs"""
    sales_reps = []
    
    try:
        with open(filename, 'r') as file:
            content = file.read()
            
            pattern = r'"([^"]+)",\s*"([^"]+)"'
            matches = re.findall(pattern, content)
            
            for name, user_id in matches:
                sales_reps.append((name.strip(), user_id.strip()))
    except Exception as error:
        print(f"Error reading sales_reps file: {error}")
    
    return sales_reps

def make_api_request(headers, url, payload, method="POST"):
    """Make an API request with rate limit handling"""
    while True:
        try:
            if method.upper() == "POST":
                response = requests.post(url, headers=headers, json=payload)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, json=payload)
            else:
                print(f"Unsupported method: {method}")
                return {"data": [], "cursor": None}
            
            # Check if rate limited
            if response.status_code == 429:
                # Get rate reset time - check different possible header formats
                reset_time = None
                
                # Try retry-after header first (most reliable)
                if 'retry-after' in response.headers:
                    try:
                        reset_time = float(response.headers['retry-after'])
                    except (ValueError, TypeError):
                        pass
                
                # Try to parse ratelimit header if available
                if reset_time is None and 'ratelimit' in response.headers:
                    try:
                        rate_limit_header = response.headers['ratelimit']
                        
                        # Try different parsing approaches
                        parts = rate_limit_header.split(',')
                        for part in parts:
                            if 'reset=' in part:
                                reset_value = part.split('=')[1].strip()
                                # Sometimes it might have additional text after semicolon
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
                time.sleep(reset_time + 0.5)  # Add a small buffer
                continue
            
            # Check for other errors
            if response.status_code not in [200, 201, 204]:
                print(f"API Error: {response.status_code} - {response.text}")
                return {"data": [], "cursor": None, "success": False}
            
            # Return the JSON data if it's a search request
            if method.upper() == "POST" and url.endswith("/search"):
                return response.json()
            elif method.upper() == "PUT":
                # For PUT requests, consider any successful status code as success
                # Even if there's no JSON response or empty response
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
            time.sleep(5)  # Wait before retry
            continue
        except json.JSONDecodeError:
            print("Error decoding API response")
            return {"data": [], "cursor": None}

def count_leads_for_rep(headers, payload, rep_name, rep_id):
    """Count the leads for a specific sales rep"""
    # Create a copy of the payload
    rep_payload = json.loads(json.dumps(payload))
    
    # Replace the user_id placeholder in the query
    update_user_id_in_query(rep_payload, rep_id)
    
    # Handle pagination
    all_leads = []
    has_more = True
    cursor = None
    
    while has_more:
        payload_copy = rep_payload.copy()
        if cursor:
            payload_copy["cursor"] = cursor
        
        # Make the API request
        response = make_api_request(headers, "https://api.close.com/api/v1/data/search", payload_copy)
        
        # Add leads to our collection
        if 'data' in response:
            all_leads.extend(response['data'])
        
        # Check for more pages
        cursor = response.get('cursor')
        has_more = bool(cursor)
    
    return len(all_leads)

def update_user_id_in_query(payload, user_id):
    """Update the user ID in the query payload"""
    # Custom field ID for Sales Owner
    custom_field_id = 'cf_QN63hvQpK9qCVBFwQxI19MeGro3AgUqzk8cR887j4RP'
    
    def update_in_queries(queries_list):
        for query in queries_list:
            if query.get('type') == 'field_condition' and query.get('field', {}).get('custom_field_id') == custom_field_id:
                query['condition']['object_ids'] = [user_id]
                return True
            elif 'queries' in query:
                if update_in_queries(query['queries']):
                    return True
        return False
    
    try:
        # Start at the top level
        if 'query' in payload:
            update_in_queries([payload['query']])
    except Exception as e:
        print(f"Error updating user ID in query: {e}")
        pass

def assign_leads_to_rep(headers, payload, rep_name, rep_id, needed_leads):
    """Assign leads from the reservoir to a sales rep"""
    # Create a copy of the payload
    rep_payload = json.loads(json.dumps(payload))
    
    # Custom field ID for Sales Owner
    custom_field_id = 'cf_QN63hvQpK9qCVBFwQxI19MeGro3AgUqzk8cR887j4RP'
    
    # Handle pagination to get leads
    all_leads = []
    has_more = True
    cursor = None
    
    # Retrieve leads from reservoir
    while has_more and len(all_leads) < needed_leads:
        payload_copy = rep_payload.copy()
        if cursor:
            payload_copy["cursor"] = cursor
        
        # Set limit to avoid excessive API calls
        if "limit" not in payload_copy:
            payload_copy["limit"] = min(100, needed_leads - len(all_leads))
        
        # Make the API request
        response = make_api_request(headers, "https://api.close.com/api/v1/data/search", payload_copy)
        
        # Add leads to our collection
        if 'data' in response:
            all_leads.extend(response['data'])
        
        # Check for more pages
        cursor = response.get('cursor')
        has_more = bool(cursor) and len(all_leads) < needed_leads
    
    # Limit to the number needed
    leads_to_assign = all_leads[:needed_leads]
    
    # Assign leads to the sales rep
    assigned_count = 0
    for lead in leads_to_assign:
        lead_id = lead.get('id')
        if not lead_id:
            continue
        
        # Prepare update payload for the custom field
        # Using the correct format for the custom field update
        update_payload = {
            f"custom.{custom_field_id}": rep_id
        }
        
        # Make the API request to update the lead
        response = make_api_request(
            headers, 
            f"https://api.close.com/api/v1/lead/{lead_id}/", 
            update_payload,
            method="PUT"
        )
        
        # Check for success - now PUT responses will always have success:True for 2xx status codes
        if response.get("success", False):
            assigned_count += 1
        
        # Small delay to avoid rate limiting
        time.sleep(0.2)
    
    return assigned_count

if __name__ == "__main__":
    main()


