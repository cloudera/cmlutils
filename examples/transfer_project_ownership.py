# Copyright (c) 2023 Cloudera, Inc. All rights reserved.
# Author: Cloudera
# Description: An example script to change ownership of the project .


"""
    To Install cmlapi
    pip install <Target-CML-DOMAIN>/api/v2/python.tar.gz
    Please refer <Target-CML-DOMAIN>/api/v2/python
"""
import cmlapi

api_url = "<Target-CML-DOMAIN>"
api_key = "<Target-CML-api-v2-key>"
projectId = "project-public-identifier"

# client setup
config = cmlapi.Configuration()
config.host = api_url
config.verify_ssl = False
client = cmlapi.ApiClient(config)
client.set_default_header("authorization", "Bearer " + api_key)
api = cmlapi.CMLServiceApi(client)

# get details of the project you want to update and print current owner

proj = api.get_project(projectId)
print(
    "================================================BEFORE==========================================="
)
print(proj.owner.username)  # OWNER1 owns the project
print(
    "================================================================================================"
)

# Update the project's ownership
proj.owner.username = "OWNER2"
api.update_project(proj, projectId)

# get details of the updated project
projUpdated = api.get_project(projectId)
print(
    "================================================AFTER==========================================="
)
print(projUpdated.owner.username)  # onwer2 owns the project now
print(
    "================================================================================================"
)
