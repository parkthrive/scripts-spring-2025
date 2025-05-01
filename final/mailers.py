import requests
import json
import csv
from datetime import datetime, timedelta
import time
import re
import sys
import os



def load_query(query_file="mailers.json"):
    """Load query from JSON file"""
    try:
        # Try both relative and absolute paths
        if os.path.exists(query_file):
            with open(query_file, 'r') as f:
                return json.load(f)
        else:
            absolute_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), query_file)
            if os.path.exists(absolute_path):
                with open(absolute_path, 'r') as f:
                    return json.load(f)
            else:
                print(f"Error: {query_file} not found in either location")
                sys.exit(1)
    except Exception as e:
        print(f"Error loading {query_file}: {str(e)}")
        sys.exit(1)

def format_monetary_value(value):
    """
    Format monetary values consistently:
    - If value has decimal part (e.g., 65.75), display with 2 decimal places (65.75)
    - If value is a whole number (e.g., 50), display without decimal places (50)
    - If value is 0, display as 0 not 0.0
    """
    if value is None or value == '':
        return ''
        
    try:
        # Convert to float first to handle different input types
        float_val = float(value)
        
        # Check if it's a whole number
        if float_val == 0:
            return '0'  # Return just '0' for zero values
        elif float_val.is_integer():
            return str(int(float_val))  # Return without decimal for whole numbers
        else:
            # Format with 2 decimal places for non-whole numbers
            return f"{float_val:.2f}"
    except (ValueError, TypeError):
        # Return the original value if conversion fails
        return str(value)

def convert_date_format(date_str):
    """
    Convert date from YYYY-MM-DD to M/D/YYYY format
    """
    if not date_str:
        return ''
    
    try:
        # Parse the date string
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        # Format to M/D/YYYY
        return date_obj.strftime("%m/%d/%Y")
    except ValueError:
        # Return original if not in expected format
        return date_str

class CloseFetcher:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.close.com/api/v1"
        
        # Field ID mappings based on the API response
        self.field_mappings = {
            'citation number': 'cf_d2z5OWkrrq9ePYmioTPu1zvKolS37gNtnzwWHnekZ3i',
            'citation date': 'cf_wlmTmD6U8hk3Br48unSR2Z8sIs4sDNRQPG9f0cByLdk',
            'citation time': 'cf_nKY3NsNFLbwW9XQWOMZ8NP9GMW8DweFbYi8bsQRaakd',
            # Use the Lot Address field for lot location instead of Lot Name
            'lot location': 'cf_xDLglpyPXow2sw4n4Fayizbu8rviuZaPSwy1wk5foKe',
            'citation image url': 'cf_xA5GMk9tnuQTHhrlMUxSVF0pBEstwntwQFJA1UZ6tGB',
            'fine amount': 'cf_HyE1MBU2E747k9YUnUmlVnYFTXUU3Bb1BvhLClPYZE8',
            'service fee': 'cf_HOmP6eCjgTvwXQOBe9ZBfZP8L4nGeQP5OR5lFjarlLy',
            'mailer dates': 'cf_JWPYpJQg1RLH2Z4wQw8mtdz8YyZTfF22mF97f1JDocf',
            'template': 'cf_NqmTys3HpgtKMa6OK3mc46kgbbGWwgWH2xAM3UcUObe'  # Added the template field
        }
    
    def _make_request(self, url, method='GET', data=None):
        """Make a rate-limited request to the Close.io API with consistent rate limit handling"""
        headers = {
            'Content-Type': 'application/json'
        }
        
        while True:
            try:
                if method == 'GET':
                    response = requests.get(
                        url,
                        auth=(self.api_key, ''),
                        headers=headers,
                        params=data if method == 'GET' else None
                    )
                elif method == 'POST':
                    response = requests.post(
                        url,
                        auth=(self.api_key, ''),
                        headers=headers,
                        json=data
                    )
                elif method == 'PUT':
                    response = requests.put(
                        url,
                        auth=(self.api_key, ''),
                        headers=headers,
                        json=data
                    )
                
                # Only print status code for errors, but keep it minimal
                if response.status_code not in [200, 201, 204]:
                    print(f"API Error: {response.status_code}")
                
                # Check if rate limited
                if response.status_code == 429:
                    # Try to get reset time from various sources
                    reset_time = None
                    
                    # First try retry-after header
                    if 'retry-after' in response.headers:
                        try:
                            reset_time = float(response.headers['retry-after'])
                        except (ValueError, TypeError):
                            pass
                    
                    # Next try RateLimit header
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
                    
                    # If we have response JSON, try to get reset time from there
                    if reset_time is None and hasattr(response, 'json'):
                        try:
                            response_data = response.json()
                            reset_time = response_data.get('rate_reset', 60)
                        except:
                            pass
                    
                    # Default to 5 seconds if all else fails
                    if not reset_time:
                        reset_time = 5
                    
                    # Wait silently
                    time.sleep(reset_time + 0.5)
                    continue
                
                response.raise_for_status()
                
                # Try to parse JSON response
                try:
                    return response.json()
                except json.JSONDecodeError as json_err:
                    print(f"JSON Decode Error: {str(json_err)}")
                    raise
                    
            except requests.exceptions.RequestException as e:
                print(f"Request failed: {str(e)}")
                time.sleep(5)  # Wait 5 seconds before retrying
                continue
    
    def get_opportunity_custom_fields(self):
        """Get a list of all opportunity custom fields and their IDs"""
        custom_fields_url = f"{self.base_url}/custom_field/opportunity/"
        response = self._make_request(custom_fields_url)
        
        fields = {}
        if response and 'data' in response:
            for field in response['data']:
                fields[field.get('name')] = field.get('id')
        
        # Minimal logging
        return fields
    
    def search_leads(self, query):
        """Search for leads using the Close.io API with pagination"""
        search_url = f"{self.base_url}/data/search/"
        all_leads = []

        try:
            has_more = True
            cursor = None
            total_batches = 0
            
            # Initial message
            print("Fetching leads: 0", end="", flush=True)
            
            while has_more:
                # Create a copy of the query to avoid modifying the original
                payload_copy = query.copy()
                if cursor:
                    payload_copy["cursor"] = cursor
                    
                response = self._make_request(search_url, method='POST', data=payload_copy)
                
                if not isinstance(response, dict):
                    print(f"\nUnexpected response type")
                    break
                    
                batch_leads = response.get('data', [])
                all_leads.extend(batch_leads)

                cursor = response.get("cursor")
                has_more = bool(cursor)
                
                # Update the count in place (overwrite previous number)
                print(f"\rFetching leads: {len(all_leads)}", end="", flush=True)
                
                # Add a small delay to avoid hitting rate limits
                time.sleep(0.5)
            
            # Print final count with a newline
            print(f"\rFetched {len(all_leads)} leads.")
            
            return all_leads
            
        except Exception as e:
            print(f"\nError in search_leads: {str(e)}")
            raise

    def get_lead_data(self, lead_id):
        """Fetch a single lead and its related data"""
        lead_url = f"{self.base_url}/lead/{lead_id}/"
        lead_response = self._make_request(lead_url)
        
        if not lead_response:
            raise Exception(f"Failed to fetch lead data")
        
        lead_data = lead_response
        
        opps_url = f"{self.base_url}/opportunity/?lead_id={lead_id}"
        opps_response = self._make_request(opps_url)
        
        if not opps_response:
            raise Exception(f"Failed to fetch opportunities data")
        
        opps_data = opps_response
        
        # Initialize all fields to empty strings to ensure they are present in the output
        result = {
            'citation number': '',
            'last mail date': '',
            'value': '',
            'plate number': '',
            'plate location': '',
            'make': '',
            'model': '',
            'citation date': '',
            'citation time': '',
            'lot location': '',
            'first name': '',
            'last name': '',
            'address': '',
            'address 2': '',
            'city': '',
            'province or state': '',
            'postal or zip': '',
            'country code': '',
            'citation image url': '',
            'fine amount': '',
            'service fee': '',
            'first mailer': '',
            'second mailer': '',
            'template': ''  # Added template field
        }
        
        # Parse contact name (display_name)
        if lead_data.get('contacts'):
            contact = lead_data['contacts'][0]
            full_name = contact.get('display_name', '')
            name_parts = full_name.split(' ', 1)  # Split on first space only
            result['first name'] = name_parts[0] if name_parts else ''
            result['last name'] = name_parts[1] if len(name_parts) > 1 else ''
        
        # Parse lead name into plate and state plate
        lead_name = lead_data.get('name', '')
        name_parts = lead_name.split(' ', 1)  # Split on first space only
        result['plate number'] = name_parts[0] if name_parts else ''
        result['plate location'] = name_parts[1] if len(name_parts) > 1 else ''
        
        # Get address information from the Current Mailing Address custom field
        custom_fields = lead_data.get('custom', {})
        
        # Use the field name instead of ID
        mailing_address = custom_fields.get('Current Mailing Address', '')
        if mailing_address:
            # Split by comma first
            address_parts = [part.strip() for part in mailing_address.split(',')]
            
            if len(address_parts) >= 3:  # If we have street, city, and state/zip
                result['address'] = address_parts[0]
                result['address 2'] = ''  # Always blank as requested
                result['city'] = address_parts[1]
                
                # The last part contains state and zip separated by space
                state_zip = address_parts[2].strip().split(' ', 1)
                if len(state_zip) >= 2:
                    result['province or state'] = state_zip[0]
                    result['postal or zip'] = state_zip[1]
                else:
                    result['province or state'] = state_zip[0] if state_zip else ''
                    result['postal or zip'] = ''
                
                result['country code'] = 'US'  # Default to US
            elif len(address_parts) == 2:  # If we only have street and city
                result['address'] = address_parts[0]
                result['address 2'] = ''
                result['city'] = address_parts[1]
                result['province or state'] = ''
                result['postal or zip'] = ''
                result['country code'] = 'US'
            else:
                result['address'] = mailing_address
                result['address 2'] = ''
                result['city'] = ''
                result['province or state'] = ''
                result['postal or zip'] = ''
                result['country code'] = 'US'
        
        # Get lead custom fields - use the NAMES instead of IDs
        result['last mail date'] = custom_fields.get('Last Mail Date', '')
        # Convert date format if needed
        if result['last mail date']:
            result['last mail date'] = convert_date_format(result['last mail date'])
            
        result['make'] = custom_fields.get('Make', '')
        result['model'] = custom_fields.get('Model', '')
        
        # Get opportunity custom fields
        if opps_data.get('data'):
            # Filter opportunities based on status
            valid_statuses = [
                "stat_YM4zWiayFRmMPX81kVRtUc55bCONbHzCun81YvCU8xJ",  # 1
                "stat_etKn0Polby4XpPZjd5JxhUjVqovplh5uv8HrWDnpClm",  # 2
                "stat_hrU7Gd0liwAfY3TCJ1IA5k5RxSzIKaBJYfNEbtmg3Yc"   # 3
            ]
            
            filtered_opps = [opp for opp in opps_data['data'] if opp.get('status_id') in valid_statuses]
            
            if filtered_opps:
                opp = filtered_opps[0]  # Take the first matching opportunity
                opp_id = opp.get('id')
                
                # Get the value and remove $ sign if present
                value_formatted = opp.get('value_formatted', '')
                if isinstance(value_formatted, str) and value_formatted.startswith('$'):
                    result['value'] = value_formatted[1:]  # Strip the $ sign
                else:
                    result['value'] = value_formatted
                
                status_id = opp.get('status_id', '')
                
                # Get detailed opportunity data (including custom fields)
                opp_url = f"{self.base_url}/opportunity/{opp_id}/"
                opp_detailed = self._make_request(opp_url)
                
                if opp_detailed:
                            
                    # Look for custom fields using the correct dot notation format
                    for field_name, field_id in self.field_mappings.items():
                        custom_key = f"custom.{field_id}"
                        if custom_key in opp_detailed:
                            value = opp_detailed[custom_key]
                            
                            # Map the values to our output fields
                            if field_name == 'citation number':
                                result['citation number'] = value
                            elif field_name == 'citation date':
                                # Convert date format
                                result['citation date'] = convert_date_format(value) if value else ''
                            elif field_name == 'citation time':
                                result['citation time'] = value
                            elif field_name == 'lot location':
                                # Use the lot address value for lot location
                                result['lot location'] = value
                            elif field_name == 'citation image url':
                                result['citation image url'] = value
                            elif field_name == 'fine amount':
                                result['fine amount'] = value
                            elif field_name == 'service fee':
                                result['service fee'] = value
                            elif field_name == 'template':
                                result['template'] = value  # Added template field handling
                            elif field_name == 'mailer dates' and value:
                                # Process mailer dates differently based on status
                                dates = [d.strip() for d in str(value).split(',')]
                                
                                # Status 2: Only take first date
                                if status_id == "stat_etKn0Polby4XpPZjd5JxhUjVqovplh5uv8HrWDnpClm":  # Status 2
                                    result['first mailer'] = convert_date_format(dates[0]) if len(dates) > 0 else ''
                                    result['second mailer'] = ''
                                
                                # Status 3: Take first two dates
                                elif status_id == "stat_hrU7Gd0liwAfY3TCJ1IA5k5RxSzIKaBJYfNEbtmg3Yc":  # Status 3
                                    result['first mailer'] = convert_date_format(dates[0]) if len(dates) > 0 else ''
                                    result['second mailer'] = convert_date_format(dates[1]) if len(dates) > 1 else ''
                
                # Format monetary fields with consistent formatting
                result['value'] = format_monetary_value(result['value'])
                result['fine amount'] = format_monetary_value(result['fine amount'])
                result['service fee'] = format_monetary_value(result['service fee'])
        
        return result

def send_to_postgrid(lead_data):
    """
    Send lead data to PostGrid API to create a letter
    Returns the PostGrid response or None if failed
    """
    postgrid_api_key = os.getenv("live_postgrid_api_key")
    if not postgrid_api_key:
        print("ERROR: PostGrid API key not found in .env file")
        return None
    
    # Set up the API endpoint - using the correct endpoint URL
    url = "https://api.postgrid.com/print-mail/v1/letters"
    
    # Format today's date for description - changed to m/d/yyyy format
    today = datetime.now().strftime("%m/%d/%Y")
    
    # Prepare the payload with to/from contact info and merge variables
    payload = {
        # Address information
        'to[firstName]': lead_data.get('first name', ''),
        'to[lastName]': lead_data.get('last name', ''),
        'to[addressLine1]': lead_data.get('address', ''),
        'to[addressLine2]': lead_data.get('address 2', ''),
        'to[city]': lead_data.get('city', ''),
        'to[provinceOrState]': lead_data.get('province or state', ''),
        'to[postalOrZip]': lead_data.get('postal or zip', ''),
        'to[countryCode]': lead_data.get('country code', 'US'),
        
        # From address (using the fixed ID you provided)
        'from': 'contact_4wcKbnQqDwkLkFCRutSkLy',
        
        # Letter configuration
        'template': lead_data.get('template', ''),
        'size': 'us_letter',
        'addressPlacement': 'top_first_page',
        'doubleSided': 'false',
        'color': 'true',
        'mailingClass': 'first_class',
        'description': f"Invoice {lead_data.get('citation number', '')} ({today})",
        
        # Merge variables for the template - monetary values already formatted
        'mergeVariables[citation number]': lead_data.get('citation number', ''),
        'mergeVariables[last mail date]': lead_data.get('last mail date', ''),
        'mergeVariables[value]': lead_data.get('value', ''),
        'mergeVariables[plate number]': lead_data.get('plate number', ''),
        'mergeVariables[plate location]': lead_data.get('plate location', ''),
        'mergeVariables[make]': lead_data.get('make', ''),
        'mergeVariables[model]': lead_data.get('model', ''),
        'mergeVariables[citation date]': lead_data.get('citation date', ''),
        'mergeVariables[citation time]': lead_data.get('citation time', ''),
        'mergeVariables[lot location]': lead_data.get('lot location', ''),
        'mergeVariables[first mailer]': lead_data.get('first mailer', ''),
        'mergeVariables[second mailer]': lead_data.get('second mailer', ''),
        'mergeVariables[fine amount]': lead_data.get('fine amount', ''),
        'mergeVariables[service fee]': lead_data.get('service fee', ''),
        'mergeVariables[citation image url]': lead_data.get('citation image url', ''),
    }
    
    # Set up request headers
    headers = {
        'x-api-key': postgrid_api_key
    }
    
    try:
        # Send the request - simplified logging
        response = requests.post(url, data=payload, headers=headers)
        
        if response.status_code >= 400:
            # Extract meaningful error message
            error_message = "Unknown error"
            try:
                error_data = response.json()
                if 'error' in error_data and 'message' in error_data['error']:
                    error_message = error_data['error']['message']
                elif 'error' in error_data and 'type' in error_data['error']:
                    error_message = error_data['error']['type']
            except:
                error_message = response.text[:100] if response.text else f"HTTP {response.status_code}"
                
            return {"success": False, "status_code": response.status_code, "error": error_message}
        
        response.raise_for_status()
        
        # If successful, return the response with success flag
        try:
            result = response.json()
            return {"success": True, "data": result}
        except json.JSONDecodeError:
            # Handle case where response might not be JSON
            return {"success": True, "data": response.text}
            
    except requests.exceptions.RequestException as e:
        error_message = str(e)
        status_code = None
        
        if hasattr(e, 'response') and e.response:
            status_code = e.response.status_code
            try:
                error_data = e.response.json()
                if 'error' in error_data and 'message' in error_data['error']:
                    error_message = error_data['error']['message']
            except:
                error_message = e.response.text[:100] if e.response.text else error_message
                
        return {"success": False, "status_code": status_code, "error": error_message}

def update_postgrid_send_date(fetcher, lead_id):
    """
    Update the 'PostGrid Send Date' field for a lead in Close
    """
    # Change date format to m/d/yyyy
    today = datetime.now().strftime("%m/%d/%Y")
    
    # Set up the API endpoint
    url = f"{fetcher.base_url}/lead/{lead_id}/"
    
    # Create the payload to update the PostGrid Send Date custom field
    payload = {
        "custom.cf_9iBTbWy34YhXjzER2hwJTMRmknKNBtHxQwMgKYmh2k5": today
    }
    
    # Make the request to update the lead
    response = fetcher._make_request(url, method='PUT', data=payload)
    
    return response

def update_lead_status_to_error(fetcher, lead_id, error_message):
    """
    Update lead status to Error and add a note with the error details
    """
    # Set up the API endpoint for updating lead status
    lead_url = f"{fetcher.base_url}/lead/{lead_id}/"
    
    # Create the payload to update the lead status to Error
    status_payload = {
        "status_id": "stat_j2Fj190JXd0WWx1UnMyuVd57SeplIVNnvt9DKyfSNSb"  # Error status
    }
    
    # Make the request to update the lead status
    status_response = fetcher._make_request(lead_url, method='PUT', data=status_payload)
    
    # Now add a note with the error message
    notes_url = f"{fetcher.base_url}/activity/note/"
    
    # Format today's date for the note
    today = datetime.now().strftime("%m/%d/%Y")
    
    # Create the payload for the note using note_html for proper formatting
    note_html = f"<body><p><strong>PostGrid Error ({today}):</strong> {error_message}</p></body>"
    note_payload = {
        "lead_id": lead_id,
        "note_html": note_html
    }
    
    # Make the request to add the note
    note_response = fetcher._make_request(notes_url, method='POST', data=note_payload)
    
    return status_response, note_response

def main():
    # Get API key from environment variable
    CLOSE_API_KEY = os.getenv("pc_close_api_key")
    if not CLOSE_API_KEY:
        print("ERROR: No Close API key found in .env file.")
        
        # Check if API key was provided as command line argument
        if len(sys.argv) > 1:
            CLOSE_API_KEY = sys.argv[1]
        else:
            return
    
    # Check for PostGrid API key
    POSTGRID_API_KEY = os.getenv("test_postgrid_api_key")
    if not POSTGRID_API_KEY:
        print("ERROR: No PostGrid API key found in .env file.")
        return
    
    fetcher = CloseFetcher(CLOSE_API_KEY)
    
    try:
        # Load query from file
        query = load_query()
        
        # Pre-fetch opportunity custom fields
        field_definitions = fetcher.get_opportunity_custom_fields()
        
        # Fetch all leads
        leads = fetcher.search_leads(query)
        total_leads = len(leads)
 
        print(f"\n{'='*60}")
        print(f"PROCESSING {total_leads} LEADS")
        print(f"{'='*60}")
        
        successful_count = 0
        failed_count = 0
        
        for index, lead in enumerate(leads, 1):
            try:
                lead_id = lead.get('id', 'Unknown ID')
                
                # Clear previous line and show current progress
                print(f"\nProcessing lead {index}/{total_leads}")
                print(f"Lead ID: {lead_id}")
                
                # Get lead data
                lead_data = fetcher.get_lead_data(lead_id)
                
                if not lead_data:
                    error_msg = "No data found"
                    print(f"Status: Error - {error_msg}")
                    update_lead_status_to_error(fetcher, lead_id, error_msg)
                    failed_count += 1
                    continue
                
                # Check if template ID is available
                if not lead_data.get('template'):
                    error_msg = "No template ID found"
                    print(f"Status: Error - {error_msg}")
                    update_lead_status_to_error(fetcher, lead_id, error_msg)
                    failed_count += 1
                    continue
                
                # Validate required fields
                if not lead_data.get('first name') or not lead_data.get('last name') or not lead_data.get('address'):
                    error_msg = "Missing required contact information"
                    print(f"Status: Error - {error_msg}")
                    update_lead_status_to_error(fetcher, lead_id, error_msg)
                    failed_count += 1
                    continue
                
                # Send to PostGrid
                postgrid_response = send_to_postgrid(lead_data)
                
                if postgrid_response and postgrid_response.get("success", False):
                    # Extract letter ID from response (could be JSON object or string)
                    response_data = postgrid_response.get("data", {})
                    letter_id = None
                    
                    if isinstance(response_data, dict):
                        letter_id = response_data.get('id')
                    else:
                        # If it's a string response, try to extract ID
                        letter_id = str(response_data).strip()
                    
                    print(f"Status: Success")
                    
                    # Update the PostGrid Send Date field in Close with new date format
                    today = datetime.now().strftime("%m/%d/%Y")
                    update_result = update_postgrid_send_date(fetcher, lead_id)
                    
                    successful_count += 1
                else:
                    # Get error details
                    status_code = postgrid_response.get("status_code", "Unknown") if postgrid_response else "Unknown"
                    error_msg = postgrid_response.get("error", "Unknown error") if postgrid_response else "Failed to connect"
                    error_display = f"Error {status_code} - {error_msg}"
                    
                    # Display simplified error message
                    print(f"Status: {error_display}")
                    
                    # Update lead status to Error and add note
                    update_lead_status_to_error(fetcher, lead_id, error_display)
                    
                    failed_count += 1
                
                # Add a small delay to avoid hitting rate limits
                time.sleep(1)
                
            except Exception as e:
                error_msg = str(e)
                print(f"Status: Error - {error_msg}")
                try:
                    update_lead_status_to_error(fetcher, lead_id, error_msg)
                except:
                    # If we can't update the lead status, just continue
                    pass
                failed_count += 1
                continue
        
        # Print summary
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        print(f"Total leads processed: {total_leads}")
        print(f"Successfully processed: {successful_count}")
        print(f"Failed to process: {failed_count}")
        print(f"Success rate: {successful_count/total_leads*100:.1f}%")
        print("="*60)
        
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
