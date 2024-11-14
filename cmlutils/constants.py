# constants.py

"""This module defines project-level constants."""

from enum import Enum

CDSW_PROJECTS_ROOT_DIR = "cdsw@localhost:/home/cdsw/"
CDSW_ROOT_USER = "cdsw@localhost"
EXCLUDE_FILE_ROOT_PATH = "/home/cdsw/.exportignore"
FILE_NAME = ".exportignore"
IGNORE_FILE_PATH = ".exportignore"
LOG_FILE = "/migration.log"
EXPORT_METRIC_FILE = "/export_metrics.json"
IMPORT_METRIC_FILE = "/import_metrics.json"
BASE_PATH_CDSWCTL = "/tmp/cdswctls"
DEFAULT_ENTRIES = [".cache", ".local"]
USERNAME_KEY = "username"
URL_KEY = "url"
API_V1_KEY = "apiv1_key"
OUTPUT_DIR_KEY = "output_dir"
PROJECT_NAME_KEY = "project_name"
CA_PATH_KEY = "ca_path"
MAX_API_PAGE_LENGTH = 30


class ApiV2Endpoints(Enum):
    PROJECTS = "/api/v2/projects"
    GET_PROJECT = "/api/v2/projects/$project_id"
    CREATE_MODEL = "/api/v2/projects/$project_id/models"
    BUILD_MODEL = "/api/v2/projects/$project_id/models/$model_id/builds"
    CREATE_APP = "/api/v2/projects/$project_id/applications"
    STOP_APP = "/api/v2/projects/$project_id/applications/$application_id:stop"
    CREATE_JOB = "/api/v2/projects/$project_id/jobs"
    UPDATE_JOB = "/api/v2/projects/$project_id/jobs/$job_id"
    MODELS_LIST = "/api/v2/projects/$project_id/models"
    JOBS_LIST = "/api/v2/projects/$project_id/jobs"
    APPS_LIST = "/api/v2/projects/$project_id/applications"
    SEARCH_PROJECT = "/api/v2/projects?search_filter=$search_option&include_public_projects=true&page_size=100000"
    SEARCH_MODEL = "/api/v2/projects/$project_id/models?search_filter=$search_option&page_size=100000"
    SEARCH_JOB = "/api/v2/projects/$project_id/jobs?search_filter=$search_option&page_size=100000"
    SEARCH_APP = "/api/v2/projects/$project_id/applications?search_filter=$search_option&page_size=100000"
    RUNTIME_ADDONS = "/api/v2/runtimeaddons?search_filter=$search_option"
    RUNTIMES = "/api/v2/runtimes?page_size=$page_size&page_token=$page_token"
    COLLABORATORS = "/api/v2/projects/$project_id/collaborators?page_size=$page_size&page_token=$page_token"
    ADD_COLLABORATOR = "/api/v2/projects/$project_id/collaborators/$user_name"


class ApiV1Endpoints(Enum):
    PROJECT = "api/v1/projects/$username/$project_name"
    PROJECT_ENV = "api/v1/projects/$username/$project_name/environment"
    PROJECT_FILE = "api/v1/projects/$username/$project_name/files/$filename"
    MODELS_LIST = "/api/altus-ds-1/models/list-models"
    JOBS_LIST = "/api/v1/projects/$username/$project_name/jobs"
    APPS_LIST = "/api/v1/projects/$username/$project_name/applications"
    MODEL_INFO = "/api/altus-ds-1/models/get-model"
    JOB_INFO = "/api/v1/projects/$username/$project_name/jobs/$job_id"
    APP_INFO = "/api/v1/projects/$username/$project_name/applications/$app_id"
    API_KEY = "/api/v1/users/$username/apikey"
    RUNTIMES = "/api/v1/runtimes"
    USER_INFO = "/api/v1/users/$username"
    PROJECTS_SUMMARY = "/api/v1/users/$username/projects-summary?all=true&context=$username&sortColumn=updated_at&projectName=$projectName&limit=$limit&offset=$offset"


"""Mapping of old fields v1 to new fields of v2"""
PROJECT_MAP = {
    "name": "name",
    "description": "description",
    "shared_memory_limit": "shared_memory_limit",
    "project_visibility": "visibility",
}
PROJECT_MAPV2 = {
    "name": "name",
    "description": "description",
    "shared_memory_limit": "shared_memory_limit",
    "visibility": "visibility",
}

MODEL_MAP = {
    "name": "name",
    "description": "description",
    "authEnabled": "disable_authentication",
    "latestModelBuild.comment": "comment",
    "latestModelBuild.targetFilePath": "file_path",
    "latestModelBuild.targetFunctionName": "function_name",
}

MODEL_MAPV2 = {
    "comment": "comment",
    "file_path": "file_path",
    "function_name": "function_name",
}

APPLICATION_MAP = {
    "bypass_authentication": "bypass_authentication",
    "currentDashboard.cpu": "cpu",
    "description": "description",
    "environment": "environment",
    "currentDashboard.memory": "memory",
    "name": "name",
    "currentDashboard.nvidiaGpu": "nvidia_gpu",
    "currentDashboard.runtime.kernel": "runtime_kernel",
    "currentDashboard.runtime.editor": "runtime_editor",
    "currentDashboard.runtime.edition": "runtime_edition",
    "currentDashboard.runtime.shortVersion": "runtime_shortversion",
    "currentDashboard.runtime.fullVersion": "runtime_fullversion",
    "script": "script",
    "subdomain": "subdomain",
}
APPLICATION_MAPV2 = {
    "bypass_authentication": "bypass_authentication",
    "cpu": "cpu",
    "description": "description",
    "environment": "environment",
    "memory": "memory",
    "name": "name",
    "nvidiaGpu": "nvidia_gpu",
    "runtime.kernel": "runtime_kernel",
    "runtime.editor": "runtime_editor",
    "runtime.edition": "runtime_edition",
    "runtime.shortVersion": "runtime_shortversion",
    "runtime.fullVersion": "runtime_fullversion",
    "script": "script",
    "subdomain": "subdomain",
}

JOB_MAP = {
    "arguments": "arguments",
    "cpu": "cpu",
    "timeout_kill": "kill_on_timeout",
    "memory": "memory",
    "name": "name",
    "nvidia_gpu": "nvidia_gpu",
    "schedule": "schedule",
    "script": "script",
    "timeout": "timeout",
    "parent.id": "parent_jobid",
    "id": "source_jobid",
    "timezone": "timezone",
    "report.failure_recipients": "failure_recipients",
    "report.stopped_recipients": "stopped_recipients",
    "report.success_recipients": "success_recipients",
    "report.timeout_recipients": "timeout_recipients",
}
LEGACY_ENGINE = "legacy_engine"
SPARK_ADDON = "spark3"
ORGANIZATION_TYPE = "organization"
USER_TYPE = "user"
