import os
import json
import base64
import requests
import re
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

def main():
    # Load environment variables from .env file
    load_dotenv('../.env')
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
    
    # Parse the sales_reps file (one level up)
    sales_reps = parse_sales_reps_file("../sales_reps")
    
    if not sales_reps:
        print("ERROR: No sales reps found.")
        return
    
    # Calculate last month's date range
    today = datetime.now()
    first_day_of_current_month = datetime(today.year, today.month, 1)
    last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
    first_day_of_previous_month = datetime(last_day_of_previous_month.year, last_day_of_previous_month.month, 1)
    
    # Format dates for API
    start_date = first_day_of_previous_month.strftime("%Y-%m-%dT00:00:00.000000+00:00")
    end_date = first_day_of_current_month.strftime("%Y-%m-%dT00:00:00.000000+00:00")
    
    print(f"Analyzing data from {first_day_of_previous_month.strftime('%Y-%m-%d')} to {last_day_of_previous_month.strftime('%Y-%m-%d')}")
    
    # Process each sales rep
    rep_stats = []
    
    for rep_name, rep_id in sales_reps:
        print(f"Processing data for {rep_name}...")
        
        # Get call data for this rep (with minimal logging)
        call_data = get_call_data_for_rep(headers, rep_id, start_date, end_date)
        
        # Get won opportunities for this rep (with minimal logging)
        won_opps = get_won_opportunities_for_rep(headers, rep_id, start_date, end_date)
        
        # Add rep's stats to our collection
        rep_stats.append({
            'name': rep_name,
            'total_calls': call_data['total_calls'],
            'total_duration_seconds': call_data['total_duration'],
            'formatted_duration': format_duration(call_data['total_duration']),
            'won_opportunities': won_opps
        })
    
    # Print simplified summary report
    print("\nSales Rep Performance Summary")
    print("=" * 90)
    print(f"{'Name':<20} {'Total Calls':<15} {'Total Call Time':<20} {'Won Opportunities':<20}")
    print("-" * 90)
    
    # Sort by total call duration (highest first)
    for stat in sorted(rep_stats, key=lambda x: x['total_duration_seconds'], reverse=True):
        print(f"{stat['name']:<20} {stat['total_calls']:<15} {stat['formatted_duration']:<20} {stat['won_opportunities']:<20}")
    
    print("=" * 90)

def format_duration(seconds):
    """Format a duration in seconds as hours, minutes, seconds"""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

def get_won_opportunities_for_rep(headers, user_id, start_date, end_date):
    """Retrieve count of won opportunities for a specific sales rep"""
    url = "https://api.close.com/api/v1/report/activity/"
    
    # Format dates for API (removing microseconds component)
    start_date_formatted = start_date.split('.')[0] + 'Z'
    end_date_formatted = end_date.split('.')[0] + 'Z'
    
    # Create request payload
    payload = {
        "datetime_range": {
            "start": start_date_formatted,
            "end": end_date_formatted
        },
        "users": [user_id],
        "type": "comparison",
        "metrics": [
            "opportunities.won.all.count"  # Number of won opportunities
        ]
    }
    
    # Make the API request
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        # Check for rate limiting
        if response.status_code == 429:
            reset_time = int(response.headers.get('retry-after', 5))
            time.sleep(reset_time + 1)
            return get_won_opportunities_for_rep(headers, user_id, start_date, end_date)
            
        # Check for other errors
        if response.status_code != 200:
            return 0
        
        # Parse response
        response_data = response.json()
        
        # Extract the metrics for this user
        user_data = None
        for row in response_data.get('data', []):
            if row.get('user_id') == user_id:
                user_data = row
                break
        
        if not user_data:
            return 0
        
        # Return the won opportunities count
        won_opps = user_data.get('opportunities.won.all.count', 0) or 0
        return won_opps
            
    except requests.exceptions.RequestException:
        return 0

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

def get_call_data_for_rep(headers, user_id, start_date, end_date):
    """Retrieve call time metrics for a specific sales rep using the reporting API"""
    # Using the activity report API which is more efficient for this purpose
    url = "https://api.close.com/api/v1/report/activity/"
    
    # Format dates for API (removing microseconds component)
    start_date_formatted = start_date.split('.')[0] + 'Z'
    end_date_formatted = end_date.split('.')[0] + 'Z'
    
    # Create request payload
    payload = {
        "datetime_range": {
            "start": start_date_formatted,
            "end": end_date_formatted
        },
        "users": [user_id],
        "type": "comparison",  # Get per-user data
        "metrics": [
            "calls.outbound.all.count",  # Total number of outbound calls
            "calls.outbound.all.sum_duration",  # Total duration of outbound calls
            "calls.outbound.all.avg_duration",  # Average duration per outbound call
            "calls.inbound.all.count",  # Total number of inbound calls
            "calls.inbound.all.sum_duration",  # Total duration of inbound calls
            "calls.all.all.count",  # Total calls (both inbound and outbound)
            "calls.all.all.sum_duration"  # Total duration of all calls
        ]
    }
    
    # Make the API request
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        # Check for rate limiting
        if response.status_code == 429:
            # If rate limited, wait and retry
            reset_time = int(response.headers.get('retry-after', 5))
            time.sleep(reset_time + 1)
            return get_call_data_for_rep(headers, user_id, start_date, end_date)
            
        # Check for other errors
        if response.status_code != 200:
            return {
                'total_calls': 0,
                'connected_calls': 0,
                'total_duration': 0,
                'inbound_calls': 0,
                'outbound_calls': 0
            }
        
        # Parse response
        response_data = response.json()
        
        # Extract the metrics for this user
        user_data = None
        for row in response_data.get('data', []):
            if row.get('user_id') == user_id:
                user_data = row
                break
        
        if not user_data:
            return {
                'total_calls': 0,
                'connected_calls': 0,
                'total_duration': 0,
                'inbound_calls': 0,
                'outbound_calls': 0
            }
        
        # Return the call metrics
        outbound_calls = user_data.get('calls.outbound.all.count', 0) or 0
        inbound_calls = user_data.get('calls.inbound.all.count', 0) or 0
        total_calls = user_data.get('calls.all.all.count', 0) or 0
        total_duration = user_data.get('calls.all.all.sum_duration', 0) or 0
        
        # For connected calls, we'll use total calls
        connected_calls = total_calls
        
        return {
            'total_calls': total_calls,
            'connected_calls': connected_calls,
            'total_duration': total_duration,
            'inbound_calls': inbound_calls,
            'outbound_calls': outbound_calls
        }
            
    except requests.exceptions.RequestException:
        return {
            'total_calls': 0,
            'connected_calls': 0,
            'total_duration': 0,
            'inbound_calls': 0,
            'outbound_calls': 0
        }

if __name__ == "__main__":
    main()
