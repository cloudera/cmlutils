import sys
if sys.version_info < (3, 8):
  print("Python 3.8 or higher is required to run this script.")
  sys.exit(1)

import subprocess, argparse, logging

subprocess.call(['pip3', 'uninstall', '-y', "boto3"])
subprocess.call(['pip3', 'install', "boto3"])

import boto3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ListOrphanedEBSVolumes(object):

  def __init__(self):
    self.args = None
    self.parse_args()

  def parse_args(self):

    parser = argparse.ArgumentParser(description="This script lists orphaned EBS volumes "
                                                 "from your AWS account across specified EC2 regions.", )
    parser.add_argument('--access_key', type=str, required=True,
                        help='The access key for your AWS account')
    parser.add_argument('--secret_key', type=str, required=True,
                        help='The secret key for your AWS account')
    parser.add_argument('--ec2_regions', type=str, required=False,
                        help='A comma-separated list of AWS regions to list orphaned EBS volumes.'
                             'Example: us-east-1,us-west-2')
    self.args = parser.parse_args()
    
  def list_aws_ebs_volumes(self):
  
     access_key, secret_key, ec2_regions = self.args.access_key, self.args.secret_key, self.args.ec2_regions
     try:
       ec2_regions_from_aws = [region['RegionName'] for region in
                               boto3.client('ec2', aws_access_key_id=access_key,
                                            aws_secret_access_key=secret_key,
                                            region_name="us-west-2").describe_regions()['Regions']]
       ec2_regions = ec2_regions.split(",") if ec2_regions else ec2_regions_from_aws
     except Exception as e:
       logger.info("Failed to configure AWS account: %s" % e)
       sys.exit()
  
     for region in ec2_regions:
       try:
         if region not in ec2_regions_from_aws:
           raise Exception("Not a valid AWS region %s" % region)
       except Exception as e:
         logger.error("An error occurred: %s" % e)
         continue
       
       try:
         eks_client = boto3.client('eks', aws_access_key_id=access_key, aws_secret_access_key=secret_key,
                                   region_name=region)
       except Exception as e:
         logger.error("Error in AWS Login: %s" % e)
         continue
       try:
         active_liftie_clusters = [cluster for cluster in eks_client.list_clusters()['clusters']
                                   if "liftie" in cluster.split("-")]
       except Exception as e:
         logger.error("Error in fetching active EKS clusters: %s" % e)
         continue
       
       try:
         ec2_client = boto3.client('ec2', aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region)
         mlx_volumes = ec2_client.describe_volumes(Filters=[
           {'Name': "tag:kubernetes.io/created-for/pvc/namespace", 'Values': ['mlx']},
           {'Name': "status", 'Values': ['available']}])['Volumes']
         found = False
         for volume in mlx_volumes:
           tags = volume["Tags"]
           eks_cluster_name = None
           for tag in tags:
             if "kubernetes.io/cluster/" in tag["Key"]:
               eks_cluster_name = tag["Key"].split('/')[-1]
               break

           if eks_cluster_name and eks_cluster_name not in active_liftie_clusters:
             found = True
             pvc_name = next((item['Value'] for item in tags if item['Key'] == 'kubernetes.io/created-for/pvc/name'))
             logger.info("Volume Id: %s\t||\tEKS Cluster Name: %s\t||\tPVC Name: %s" %
                         (volume['VolumeId'], eks_cluster_name, pvc_name))
         if not found:
           logger.info("No orphan volumes found in %s" % region)
       except Exception as e:
         logger.error("Error in fetching EBS volumes %s" % e)


if __name__== "__main__":
 ListOrphanedEBSVolumes().list_aws_ebs_volumes()