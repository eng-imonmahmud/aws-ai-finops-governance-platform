import json
import boto3
import os
import pymysql
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm_client = boto3.client('ssm')
bedrock_client = boto3.client('bedrock-runtime', region_name='eu-central-1')

def get_ssm_parameter(name):
    try:
        response = ssm_client.get_parameter(Name=name, WithDecryption=True)
        return response['Parameter']['Value']
    except ClientError as e:
        logger.error(f"Error fetching SSM parameter {name}: {e}")
        raise e

def invoke_bedrock(budget_message):
    prompt = f"""
    You are an expert Cloud FinOps Architect.
    We just received a budget alert indicating we have exceeded our AWS budget threshold.
    Alert details: {budget_message}
    
    Provide 3 actionable recommendations to reduce AWS costs immediately without impacting production performance.
    Keep the response concise and formatted as a numbered list.
    """
    
    try:
        response = bedrock_client.converse(
            modelId='amazon.nova-micro-v1:0',
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}]
                }
            ],
            inferenceConfig={
                "maxTokens": 512,
                "temperature": 0.5
            }
        )
        return response['output']['message']['content'][0]['text']
    except ClientError as e:
        logger.warning(f"Bedrock access pending: {e}")
        return "AI FinOps Recommendation Simulation (Bedrock Pending Access):\n1. Terminate unattached EBS volumes to save costs.\n2. Right-size RDS instance to a smaller tier based on 10% CPU utilization.\n3. Configure S3 Lifecycle policies to transition logs to Glacier."



def init_db(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS optimizations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            alert_message TEXT,
            recommendation TEXT
        )
    """)

def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")
    
    budget_message = "Generic Budget Alert"
    if 'Records' in event and len(event['Records']) > 0:
        if 'Sns' in event['Records'][0]:
            budget_message = event['Records'][0]['Sns']['Message']
            
    # 1. Get Recommendations from Bedrock
    logger.info("Invoking Bedrock for cost optimization recommendations...")
    recommendations = invoke_bedrock(budget_message)
    logger.info(f"Received recommendations: {recommendations}")
    
    # 2. Connect to RDS
    logger.info("Fetching DB credentials from SSM...")
    db_host = get_ssm_parameter(os.environ['DB_HOST_SSM_PATH'])
    db_user = get_ssm_parameter(os.environ['DB_USER_SSM_PATH'])
    db_password = get_ssm_parameter(os.environ['DB_PASSWORD_SSM_PATH'])
    db_name = os.environ['DB_NAME']
    
    logger.info(f"Connecting to DB at {db_host}...")
    try:
        connection = pymysql.connect(
            host=db_host,
            user=db_user,
            password=db_password,
            database=db_name,
            cursorclass=pymysql.cursors.DictCursor
        )
        logger.info("Connected to RDS successfully.")
        
        with connection:
            with connection.cursor() as cursor:
                init_db(cursor)
                sql = "INSERT INTO optimizations (alert_message, recommendation) VALUES (%s, %s)"
                cursor.execute(sql, (budget_message, recommendations))
            connection.commit()
            logger.info("Inserted recommendations into RDS.")
            
    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        raise e

    return {
        'statusCode': 200,
        'body': json.dumps('FinOps Governance Workflow Executed Successfully')
    }
