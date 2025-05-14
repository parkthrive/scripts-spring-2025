import os
import json
import time
import base64
import requests
import re
import csv
from datetime import datetime

def lambda_handler(event, context):
    
    # Get required API keys and configurations
    close_api_key = get_env_var(['close_lead_assigner_api', 'CLOSE_API_KEY', 'CLOSE_API', 'API_KEY'])
    slack_token = get_env_var(['slack_oath_token_find_owner'])
    slack_channel_id = get_env_var(['slack_channel_id_find_owner'])
    sales_team_user_group_id = get_env_var(['sales_team_user_group_id'])
    omer_lead_id = get_env_var(['omer_lead_id'])
    omer_contact_id = get_env_var(['omer_contact_id'])
    
    # Check if any required variable is missing
    if not all([close_api_key, slack_token, slack_channel_id, omer_lead_id, omer_contact_id]):
        missing = []
        if not close_api_key: missing.append("Close API key")
        if not slack_token: missing.append("Slack OAuth token")
        if not slack_channel_id: missing.append("Slack channel ID")
        if not omer_lead_id: missing.append("Omer's lead ID in Close")
        if not omer_contact_id: missing.append("Omer's contact ID in Close")
        
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        return
    
    # Base64 encode the Close API key for authentication
    encoded_api_key = base64.b64encode(f"{close_api_key}:".encode()).decode()
    
    # Set up headers for Close API requests
    close_headers = {
        'Authorization': f'Basic {encoded_api_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Set up headers for Slack API requests
    slack_headers = {
        'Authorization': f'Bearer {slack_token}',
        'Content-Type': 'application/json'
    }
    
    # Get email account ID (needed for sending emails)
    print("Getting email account ID...")
    email_accounts_url = "https://api.close.com/api/v1/email_account/"
    email_accounts_response = make_api_request(close_headers, email_accounts_url, {}, method="GET")
    
    email_account_id = None
    if email_accounts_response and 'data' in email_accounts_response:
        for account in email_accounts_response['data']:
            if account.get('email') == "joshua@parkthrive.com":
                email_account_id = account.get('id')
                print(f"Found email account ID: {email_account_id}")
                break
    
    if not email_account_id:
        print("Could not find email account for joshua@parkthrive.com")
        print("Email will be created but may not be sent properly")
    
    # Load the find_owner query
    find_owner_payload = load_query_from_json("find_owner.json")
    
    if not find_owner_payload:
        print("ERROR: Could not load find_owner.json query data.")
        return
    
    # Set target leads
    target_leads = 300
    
    # Count leads in the find_owner query
    print("Counting leads in Find Owner queue...")
    leads = get_leads_with_data(close_headers, find_owner_payload, target_leads)
    lead_count = len(leads)
    
    print(f"Found {lead_count} leads in Find Owner queue.")
    
    # Send slack message based on lead count
    if lead_count < target_leads:
        # Need more leads
        needed_leads = target_leads - lead_count
        
        # Construct message with mention if available
        if sales_team_user_group_id:
            message = f"<!subteam^{sales_team_user_group_id}> We currently have {lead_count} leads in the Find Owner queue. We need {needed_leads} more to reach our goal of {target_leads} before sending to Omer."
        else:
            message = f"We currently have {lead_count} leads in the Find Owner queue. We need {needed_leads} more to reach our goal of {target_leads} before sending to Omer."
        
        send_slack_message(slack_headers, slack_channel_id, message)
        print(f"Sent Slack message about needing more leads")
    else:
        # Have reached or exceeded target
        if sales_team_user_group_id:
            message = f"<!subteam^{sales_team_user_group_id}> We've reached our goal in the Find Owner queue and have sent all leads over to Omer."
        else:
            message = f"We've reached our goal in the Find Owner queue and have sent all leads over to Omer."
        
        send_slack_message(slack_headers, slack_channel_id, message)
        print(f"Sent Slack message about reaching goal")
        
        # Download lead data
        print(f"Downloading data for {lead_count} leads...")
        csv_filename = download_lead_data(leads)
        
        # Step 5: Upload file to Close
        print("Uploading file to Close...")
        
        # Step 5.1: Request upload URL
        upload_request_url = "https://api.close.com/api/v1/files/upload/"
        upload_payload = {
            "filename": csv_filename,
            "content_type": "text/csv"
        }
        
        upload_response = make_api_request(close_headers, upload_request_url, upload_payload)
        
        if not upload_response or 'upload' not in upload_response or 'download' not in upload_response:
            print("Failed to get upload URL. Please manually create an email in Close and attach the CSV file.")
            return
        
        # Step 5.2: Upload file to S3
        s3_url = upload_response['upload']['url']
        s3_fields = upload_response['upload']['fields']
        
        print(f"Uploading file to S3 at {s3_url}...")
        
        try:
            # Prepare file for upload
            with open(csv_filename, 'rb') as file_data:
                files = {
                    'file': (csv_filename, file_data, 'text/csv')
                }
                
                # Upload to S3
                s3_response = requests.post(
                    s3_url,
                    data=s3_fields,
                    files=files
                )
                
                if s3_response.status_code != 201:
                    print(f"S3 upload failed: {s3_response.status_code} - {s3_response.text}")
                    print("Please manually create an email in Close and attach the CSV file.")
                    return
                
                print("File uploaded successfully to S3")
        except Exception as e:
            print(f"Error uploading to S3: {e}")
            print("Please manually create an email in Close and attach the CSV file.")
            return
        
        # Step 5.3: Create email with attachment
        download_url = upload_response['download']['url']
        file_size = os.path.getsize(csv_filename)
        
        # Get recipient email
        recipient_email = get_contact_email(close_headers, omer_contact_id)
        if not recipient_email:
            recipient_email = "ops@parkthrive.com"  # Fallback email
            print(f"Using fallback email for recipient: {recipient_email}")
        
        # Create today's date for subject
        today = datetime.now().strftime('%m/%d/%y')
        
        # Create email signature
        signature = """
Joshua Knarich
Operations Manager
Park Thrive
e: joshua@parkthrive.com | p: (704) 899-1705
Unlock Your Parking Revenue | www.parkthrive.com
"""
        
        # Create email body with signature
        body = f"""Hi Omer,

We have another list of Find Owners for you to process. Please see the attached file and let us know when you are ready for our review and payment.

Best,
{signature}"""
        
        # Prepare email payload
        email_url = "https://api.close.com/api/v1/activity/email/"
        email_payload = {
            "lead_id": omer_lead_id,
            "contact_id": omer_contact_id,
            "direction": "outbound",
            "status": "outbox",  # Use outbox to send immediately
            "subject": f"{today} Find Owners",
            "created_by_name": "Joshua Knarich",
            "sender": "\"Joshua Knarich\" <joshua@parkthrive.com>",
            "to": [recipient_email],
            "body_text": body,
            "attachments": [{
                "url": download_url,
                "filename": csv_filename,
                "content_type": "text/csv",
                "size": file_size
            }]
        }
        
        # Add email account ID if found
        if email_account_id:
            email_payload["email_account_id"] = email_account_id
        
        print("Sending email with attachment...")
        email_response = make_api_request(close_headers, email_url, email_payload)
        
        if email_response and 'id' in email_response:
            print(f"Email sent successfully with ID: {email_response['id']}")
            print("Process completed successfully!")
        else:
            print("Failed to send email. Please manually create an email in Close and attach the CSV file.")
        
def get_env_var(possible_names):
    """Try multiple possible environment variable names and return the first found value"""
    for name in possible_names:
        value = os.getenv(name)
        if value:
            return value
    return None

def load_query_from_json(filename):
    """Load and parse a JSON query file"""
    try:
        with open(filename, 'r') as file:
            return json.load(file)
    except Exception as error:
        print(f"Error loading {filename}: {error}")
        return None

def make_api_request(headers, url, payload, method="POST"):
    """Make an API request with rate limit handling"""
    while True:
        try:
            if method.upper() == "POST":
                response = requests.post(url, headers=headers, json=payload)
            elif method.upper() == "GET":
                if method == "GET" and isinstance(payload, dict) and payload:
                    # For GET requests with parameters
                    response = requests.get(url, headers=headers, params=payload)
                else:
                    # For GET requests without parameters
                    response = requests.get(url, headers=headers)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, json=payload)
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
                
                # If retry-after isn't available, check ratelimit header
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
                time.sleep(reset_time + 0.5)  # Add a small buffer
                continue
            
            # Check for other errors
            if response.status_code not in [200, 201, 204]:
                print(f"API Error: {response.status_code} - {response.text}")
                return None
            
            # For 204 responses (no content)
            if response.status_code == 204:
                return {"success": True}
                
            # Return the JSON data
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            time.sleep(5)  # Wait before retry
            continue
        except json.JSONDecodeError:
            print("Error decoding API response")
            return {"data": [], "cursor": None}

def get_leads_with_data(headers, payload, target_count=300):
    """Get leads with their data (ID, address, city, state, zipcode)"""
    # Handle pagination
    all_leads = []
    has_more = True
    cursor = None
    
    while has_more:
        payload_copy = payload.copy()
        if cursor:
            payload_copy["cursor"] = cursor
        
        # Make the API request
        response = make_api_request(headers, "https://api.close.com/api/v1/data/search", payload_copy)
        
        # Extract leads with needed data
        if response and 'data' in response:
            for lead in response['data']:
                # Fetch full lead details to get address
                lead_url = f"https://api.close.com/api/v1/lead/{lead.get('id')}/"
                full_lead = make_api_request(headers, lead_url, {}, method="GET")
                
                if full_lead:
                    lead_data = {
                        'id': full_lead.get('id'),
                        'address': '',
                        'city': '',
                        'state': '',
                        'zipcode': ''
                    }
                    
                    # Extract address info from the lead
                    addresses = full_lead.get('addresses', [])
                    if addresses:
                        # Get the first address
                        first_address = addresses[0]
                        lead_data['address'] = first_address.get('address_1', '')
                        lead_data['city'] = first_address.get('city', '')
                        lead_data['state'] = first_address.get('state', '')
                        lead_data['zipcode'] = first_address.get('zipcode', '')
                    
                    all_leads.append(lead_data)
        
        # Check for more pages
        cursor = response.get('cursor') if response else None
        has_more = bool(cursor)
        
        # Break early if we've already exceeded the target and we're downloading leads
        if len(all_leads) >= target_count:
            break
    
    return all_leads

def get_contact_email(headers, contact_id):
    """Get email address from contact ID"""
    contact_url = f"https://api.close.com/api/v1/contact/{contact_id}/"
    contact_response = make_api_request(headers, contact_url, {}, method="GET")
    
    if not contact_response:
        return None
    
    # Extract email from contact
    for email in contact_response.get('emails', []):
        if email.get('email'):
            print(f"Found contact email: {email.get('email')}")
            return email.get('email')
    
    return None

def download_lead_data(leads):
    """Download lead data as CSV"""
    today = datetime.now().strftime('%m_%d_%Y')
    filename = f"find_owner_leads_{today}.csv"
    
    with open(filename, 'w', newline='') as csvfile:
        fieldnames = ['id', 'address', 'city', 'state', 'zipcode']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)
    
    print(f"Downloaded lead data to {filename}")
    return filename

def send_slack_message(headers, channel_id, message):
    """Send a text message to a Slack channel"""
    url = "https://slack.com/api/chat.postMessage"
    payload = {
        "channel": channel_id,
        "text": message
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code != 200 or not response.json().get('ok'):
        print(f"Error sending Slack message: {response.text}")
        return False
    
    return True
