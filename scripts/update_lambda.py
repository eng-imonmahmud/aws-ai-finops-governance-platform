import boto3
import zipfile
import os
import sys

def update_and_test():
    # Zip lambda function
    os.chdir('app')
    with zipfile.ZipFile('../lambda_package.zip', 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            for file in files:
                zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), '.'))
    os.chdir('..')
    
    with open('lambda_package.zip', 'rb') as f:
        zip_bytes = f.read()
        
    client = boto3.client('lambda', region_name='eu-central-1')
    print("Updating lambda code...")
    client.update_function_code(
        FunctionName='finops-gov-prod-processor',
        ZipFile=zip_bytes
    )
    
    print("Waiting 5 seconds for lambda to be ready...")
    import time
    time.sleep(5)
    
    # Get SNS
    cf_client = boto3.client('cloudformation', region_name='eu-central-1')
    response = cf_client.describe_stacks(StackName='finops-gov-prod-stack')
    outputs = response['Stacks'][0]['Outputs']
    sns_arn = next(out['OutputValue'] for out in outputs if out['OutputKey'] == 'SNSTopicArn')
    
    sns_client = boto3.client('sns', region_name='eu-central-1')
    print("Publishing test SNS message...")
    sns_client.publish(
        TopicArn=sns_arn,
        Message='{"alert": "AWS Budget Threshold Exceeded (Test 2)", "amount": "$9.50", "limit": "$10.00"}',
        Subject='AWS Budget Alert 2'
    )
    print("Update and test trigger completed.")

if __name__ == "__main__":
    update_and_test()
