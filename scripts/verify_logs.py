import boto3
import time
from datetime import datetime, timedelta

def get_latest_log_stream(log_group_name):
    client = boto3.client('logs', region_name='eu-central-1')
    try:
        response = client.describe_log_streams(
            logGroupName=log_group_name,
            orderBy='LastEventTime',
            descending=True,
            limit=1
        )
        if response['logStreams']:
            return response['logStreams'][0]['logStreamName']
    except Exception as e:
        print(f"Error fetching log streams: {e}")
    return None

def fetch_logs():
    client = boto3.client('logs', region_name='eu-central-1')
    log_group_name = '/aws/lambda/finops-gov-prod-processor'
    
    # Wait for logs to be available
    print("Waiting for logs to populate...")
    time.sleep(10)
    
    log_stream = get_latest_log_stream(log_group_name)
    if not log_stream:
        print("No log streams found yet. Trying again...")
        time.sleep(10)
        log_stream = get_latest_log_stream(log_group_name)
        
    if not log_stream:
        print("Still no log streams. Lambda might have failed to start or logs are delayed.")
        return
        
    print(f"Found log stream: {log_stream}")
    try:
        response = client.get_log_events(
            logGroupName=log_group_name,
            logStreamName=log_stream,
            startFromHead=False,
            limit=50
        )
        print("--- LAMBDA LOGS ---")
        for event in response['events']:
            print(event['message'].strip())
        print("-------------------")
    except Exception as e:
        print(f"Error fetching log events: {e}")

if __name__ == "__main__":
    fetch_logs()
