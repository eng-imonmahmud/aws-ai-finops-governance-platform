import boto3

def cleanup_region(region_name):
    print(f"Checking region: {region_name} for leftover resources...")
    # S3 buckets are global, but we can filter by name prefix
    s3 = boto3.client('s3', region_name=region_name)
    try:
        response = s3.list_buckets()
        for bucket in response['Buckets']:
            name = bucket['Name']
            if name.startswith('finops-gov-prod-lambda-bucket-'):
                try:
                    location = s3.get_bucket_location(Bucket=name)['LocationConstraint']
                    if location == region_name or (location is None and region_name == 'us-east-1'):
                        print(f"Found S3 bucket in {region_name}: {name}")
                        # Delete objects
                        objs = s3.list_objects_v2(Bucket=name)
                        if 'Contents' in objs:
                            for obj in objs['Contents']:
                                s3.delete_object(Bucket=name, Key=obj['Key'])
                        s3.delete_bucket(Bucket=name)
                        print(f"Deleted S3 bucket: {name}")
                except Exception as e:
                    print(f"Could not delete bucket {name}: {e}")
    except Exception as e:
        print(e)
        
    # Check CloudFormation
    cf = boto3.client('cloudformation', region_name=region_name)
    try:
        stacks = cf.describe_stacks()['Stacks']
        for stack in stacks:
            if stack['StackName'] == 'finops-gov-prod-stack':
                if stack['StackStatus'] != 'DELETE_COMPLETE':
                    print(f"Found CloudFormation stack in {region_name}: {stack['StackStatus']}")
                    cf.delete_stack(StackName=stack['StackName'])
                    print("Initiated deletion. Waiting...")
                    waiter = cf.get_waiter('stack_delete_complete')
                    waiter.wait(StackName=stack['StackName'])
                    print("Deleted stack.")
    except Exception as e:
        print(f"CloudFormation check: {e}")

if __name__ == "__main__":
    regions_to_clean = ['eu-north-1', 'us-east-1']
    for r in regions_to_clean:
        cleanup_region(r)
    print("Cleanup outside eu-central-1 complete.")
