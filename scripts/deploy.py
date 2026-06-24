import boto3
import subprocess
import os
import time
import zipfile
import string
import random
import sys

# Setup AWS Clients
session = boto3.Session()
region = 'eu-central-1'
print(f"Using AWS Region: {region}")

cf_client = session.client('cloudformation', region_name=region)
s3_client = session.client('s3', region_name=region)
sns_client = session.client('sns', region_name=region)
sts_client = session.client('sts', region_name=region)
budgets_client = session.client('budgets', region_name=region)

STACK_NAME = 'finops-gov-prod-stack'
BUCKET_NAME = f"finops-gov-prod-lambda-bucket-{random.randint(10000, 99999)}"

def generate_random_password(length=16):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for i in range(length))

def create_lambda_package():
    print("Packaging Lambda function...")
    os.chdir('app')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '-t', '.'], check=True)
    
    zip_name = '../lambda_package.zip'
    if os.path.exists(zip_name):
        os.remove(zip_name)
        
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            for file in files:
                zipf.write(os.path.join(root, file),
                           os.path.relpath(os.path.join(root, file), '.'))
    os.chdir('..')
    print("Lambda package created successfully.")
    return 'lambda_package.zip'

def setup_s3_and_upload(zip_file):
    print(f"Creating S3 bucket: {BUCKET_NAME}")
    try:
        if region == 'us-east-1':
            s3_client.create_bucket(Bucket=BUCKET_NAME)
        else:
            s3_client.create_bucket(Bucket=BUCKET_NAME, CreateBucketConfiguration={'LocationConstraint': region})
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        print("Bucket already exists and owned by you.")
        
    print(f"Uploading {zip_file} to S3...")
    s3_client.upload_file(zip_file, BUCKET_NAME, 'lambda_function.zip')
    print("Upload complete.")

def deploy_cloudformation():
    print("Deploying CloudFormation stack...")
    with open('infra/template.yaml', 'r') as f:
        template_body = f.read()
        
    db_password = generate_random_password()
    print("Generated random DB password.")
    
    try:
        stack_info = cf_client.describe_stacks(StackName=STACK_NAME)
        status = stack_info['Stacks'][0]['StackStatus']
        if status == 'ROLLBACK_COMPLETE':
            print(f"Stack is in {status}. Deleting it before recreation...")
            cf_client.delete_stack(StackName=STACK_NAME)
            waiter_del = cf_client.get_waiter('stack_delete_complete')
            waiter_del.wait(StackName=STACK_NAME, WaiterConfig={'Delay': 15, 'MaxAttempts': 120})
            print("Stack deleted successfully.")
    except cf_client.exceptions.ClientError as e:
        # Stack does not exist, safe to proceed
        pass

    try:
        response = cf_client.create_stack(
            StackName=STACK_NAME,
            TemplateBody=template_body,
            Parameters=[
                {'ParameterKey': 'DBPassword', 'ParameterValue': db_password},
                {'ParameterKey': 'LambdaCodeS3Bucket', 'ParameterValue': BUCKET_NAME},
                {'ParameterKey': 'LambdaCodeS3Key', 'ParameterValue': 'lambda_function.zip'}
            ],
            Capabilities=['CAPABILITY_NAMED_IAM']
        )
        print(f"Stack creation initiated. Stack ID: {response['StackId']}")
    except cf_client.exceptions.AlreadyExistsException:
        print("Stack already exists. Updating...")
        response = cf_client.update_stack(
            StackName=STACK_NAME,
            TemplateBody=template_body,
            Parameters=[
                {'ParameterKey': 'DBPassword', 'ParameterValue': db_password},
                {'ParameterKey': 'LambdaCodeS3Bucket', 'ParameterValue': BUCKET_NAME},
                {'ParameterKey': 'LambdaCodeS3Key', 'ParameterValue': 'lambda_function.zip'}
            ],
            Capabilities=['CAPABILITY_NAMED_IAM']
        )
        print(f"Stack update initiated.")

    print("Waiting for stack to complete... This will take 10-15 minutes due to RDS creation.")
    waiter = cf_client.get_waiter('stack_create_complete')
    try:
        waiter.wait(StackName=STACK_NAME, WaiterConfig={'Delay': 30, 'MaxAttempts': 120})
        print("Stack deployment successful!")
    except Exception as e:
        print(f"Stack deployment failed or timed out: {e}")
        # Fetch events
        events = cf_client.describe_stack_events(StackName=STACK_NAME)['StackEvents']
        for event in events:
            if 'FAILED' in event['ResourceStatus']:
                print(f"Resource {event['LogicalResourceId']} failed: {event.get('ResourceStatusReason')}")
        sys.exit(1)

def create_budget():
    print("Creating AWS Budget...")
    account_id = sts_client.get_caller_identity()['Account']
    
    # Get SNS Topic ARN
    response = cf_client.describe_stacks(StackName=STACK_NAME)
    outputs = response['Stacks'][0]['Outputs']
    sns_arn = None
    for output in outputs:
        if output['OutputKey'] == 'SNSTopicArn':
            sns_arn = output['OutputValue']
            
    if not sns_arn:
        print("Could not find SNS Topic ARN in outputs.")
        return

    try:
        budgets_client.create_budget(
            AccountId=account_id,
            Budget={
                'BudgetName': 'finops-gov-prod-monthly-budget',
                'BudgetLimit': {'Amount': '10', 'Unit': 'USD'},
                'TimeUnit': 'MONTHLY',
                'BudgetType': 'COST'
            },
            NotificationsWithSubscribers=[
                {
                    'Notification': {
                        'NotificationType': 'ACTUAL',
                        'ComparisonOperator': 'GREATER_THAN',
                        'Threshold': 80
                    },
                    'Subscribers': [
                        {'SubscriptionType': 'SNS', 'Address': sns_arn}
                    ]
                }
            ]
        )
        print("AWS Budget created successfully.")
    except Exception as e:
        print(f"Failed to create budget or budget already exists: {e}")


def test_integration():
    print("Fetching CloudFormation outputs...")
    response = cf_client.describe_stacks(StackName=STACK_NAME)
    outputs = response['Stacks'][0]['Outputs']
    
    sns_arn = None
    for output in outputs:
        if output['OutputKey'] == 'SNSTopicArn':
            sns_arn = output['OutputValue']
            
    if not sns_arn:
        print("Could not find SNS Topic ARN in outputs.")
        return
        
    print(f"Publishing test budget alert to SNS Topic: {sns_arn}")
    sns_client.publish(
        TopicArn=sns_arn,
        Message='{"alert": "AWS Budget Threshold Exceeded", "amount": "$8.50", "limit": "$10.00"}',
        Subject='AWS Budget Alert'
    )
    print("Test alert published. The Lambda should now process it and insert to RDS.")
    print("Wait a minute for CloudWatch logs to propagate...")

if __name__ == "__main__":
    zip_file = create_lambda_package()
    setup_s3_and_upload(zip_file)
    deploy_cloudformation()
    create_budget()
    test_integration()
    print("Deployment and Test Phase complete.")
