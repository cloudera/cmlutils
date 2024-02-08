import logging
import os
from abc import ABCMeta, abstractmethod
from string import Template
from typing import List

from requests import HTTPError

from cmlutils.constants import ApiV1Endpoints
from cmlutils.directory_utils import (
    does_directory_exist,
    get_project_data_dir_path,
    get_project_metadata_file_path,
)
from cmlutils.projects import (
    get_rsync_enabled_runtime_id,
    is_project_configured_with_runtimes,
)
from cmlutils.script_models import ValidationResponse, ValidationResponseStatus
from cmlutils.utils import call_api_v1


class ImportValidators(metaclass=ABCMeta):
    @abstractmethod
    def validate(self) -> ValidationResponse:
        pass


class DirectoriesAndFilesValidator(ImportValidators):
    def __init__(self, username: str, project_name: str, top_level_directory: str):
        self.username = username
        self.project_name = project_name
        self.tld = top_level_directory
        self.validation_name = "Validation to check if data and metadata files exist"

    def _data_directory_present(self) -> bool:
        data_dir = get_project_data_dir_path(
            top_level_dir=self.tld, project_name=self.project_name
        )
        return does_directory_exist(data_dir)

    def _metadata_files_present(self) -> bool:
        return os.path.exists(
            get_project_metadata_file_path(
                top_level_dir=self.tld, project_name=self.project_name
            )
        )

    def validate(self) -> ValidationResponse:
        if not self._data_directory_present():
            return ValidationResponse(
                validation_name=self.validation_name,
                validation_msg="Data directory not present",
                validation_status=ValidationResponseStatus.FAILED,
            )
        if not self._metadata_files_present():
            return ValidationResponse(
                validation_name=self.validation_name,
                validation_msg="Metadata files not present",
                validation_status=ValidationResponseStatus.FAILED,
            )
        return ValidationResponse(
            validation_name=self.validation_name,
            validation_msg="Expected files and directories present",
            validation_status=ValidationResponseStatus.PASSED,
        )


class UserNameImportValidator(ImportValidators):
    def __init__(
        self, host: str, username: str, apiv1_key: str, project_name: str, ca_path: str
    ):
        self.validation_name = "check if user is present"
        self.host = host
        self.username = username
        self.apiv1_key = apiv1_key
        self.project_name = project_name
        self.ca_path = ca_path

    def validate(self) -> ValidationResponse:
        endpoint = Template(ApiV1Endpoints.USER_INFO.value).substitute(
            username=self.username
        )
        try:
            response = call_api_v1(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                api_key=self.apiv1_key,
                ca_path=self.ca_path,
            )
            return ValidationResponse(
                validation_name=self.validation_name,
                validation_msg="The user name exists.",
                validation_status=ValidationResponseStatus.PASSED,
            )
        except HTTPError as e:
            logging.info("e", e.response.status_code)
            if e.response.status_code == 404:
                logging.error("Username does not exist %s", e.response.json())
                return ValidationResponse(
                    validation_name=self.validation_name,
                    validation_msg="The user name does not exist. Ensure that the user name provided for the project {} is correct.".format(
                        self.project_name
                    ),
                    validation_status=ValidationResponseStatus.FAILED,
                )
            elif e.response.status_code == 401:
                logging.error("Unauthorized for url %s", e.response.json())
                return ValidationResponse(
                    validation_name=self.validation_name,
                    validation_msg="The user is unauthorised. Ensure that the API key for the project {} is correct".format(
                        self.project_name
                    ),
                    validation_status=ValidationResponseStatus.FAILED,
                )
            else:
                logging.error(e.response.json())
                return ValidationResponse(
                    validation_name=self.validation_name,
                    validation_msg="Exception occurred while validating username",
                    validation_status=ValidationResponseStatus.FAILED,
                )

class ImportFieldValidator(ImportValidators):
    def __init__(
        self, target_owner: str
    ):
        self.target_owner = target_owner
        self.validation_name = "Check if field is present"
    
    def validate(self) -> ValidationResponse:
        if self.target_owner:
            return ValidationResponse(
                    validation_name=self.validation_name,
                    validation_msg="The target owner exists.",
                    validation_status=ValidationResponseStatus.PASSED,
            )
        return ValidationResponse(
                    validation_name=self.validation_name,
                    validation_msg="target_owner is a mandatory field in the import-config.ini file. It should contain the username of the project owner in target workspace. If the owner is migrating the project, keep the field value the same as the username.",
                    validation_status=ValidationResponseStatus.FAILED,
                )

class RsyncRuntimeAddonExistsImportValidator(ImportValidators):
    def __init__(
        self, host: str, username: str, apiv1_key: str, project_name: str, ca_path: str
    ):
        self.validation_name = "check if rsync is present"
        self.host = host
        self.username = username
        self.apiv1_key = apiv1_key
        self.project_name = project_name
        self.ca_path = ca_path

    def validate(self) -> ValidationResponse:
        rsync_enabled_runtime_id = -1
        rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
            host=self.host, api_key=self.apiv1_key, ca_path=self.ca_path
        )
        if rsync_enabled_runtime_id != -1:
            return ValidationResponse(
                validation_name=self.validation_name,
                validation_msg="validation passed",
                validation_status=ValidationResponseStatus.PASSED,
            )
        return ValidationResponse(
            validation_name=self.validation_name,
            validation_msg="rsync enabled runtime is not added",
            validation_status=ValidationResponseStatus.FAILED,
        )


class ExportValidators(metaclass=ABCMeta):
    @abstractmethod
    def validate(self) -> ValidationResponse:
        pass


class UsernameValidator(ExportValidators):
    def __init__(
        self, host: str, username: str, apiv1_key: str, project_name: str, ca_path: str
    ):
        self.validation_name = "check if user is present"
        self.host = host
        self.username = username
        self.apiv1_key = apiv1_key
        self.project_name = project_name
        self.ca_path = ca_path

    def validate(self) -> ValidationResponse:
        endpoint = Template(ApiV1Endpoints.USER_INFO.value).substitute(
            username=self.username
        )
        try:
            response = call_api_v1(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                api_key=self.apiv1_key,
                ca_path=self.ca_path,
            )
            return ValidationResponse(
                validation_name=self.validation_name,
                validation_msg="The user name exists.",
                validation_status=ValidationResponseStatus.PASSED,
            )
        except HTTPError as e:
            logging.info("e", e.response.status_code)
            if e.response.status_code == 404:
                logging.error("Username does not exist %s", e.response.json())
                return ValidationResponse(
                    validation_name=self.validation_name,
                    validation_msg="The user name does not exist. Ensure that the user name provided for the project {} is correct.".format(
                        self.project_name
                    ),
                    validation_status=ValidationResponseStatus.FAILED,
                )
            elif e.response.status_code == 401:
                logging.error("Unauthorized for url %s", e.response.json())
                return ValidationResponse(
                    validation_name=self.validation_name,
                    validation_msg="The user is unauthorised. Ensure that the API key for the project {} is correct ".format(
                        self.project_name
                    ),
                    validation_status=ValidationResponseStatus.FAILED,
                )
            else:
                logging.error(e.response.json())
                return ValidationResponse(
                    validation_name=self.validation_name,
                    validation_msg="Exception occurred while validating username",
                    validation_status=ValidationResponseStatus.FAILED,
                )


class ProjectBelongsToUserValidator(ExportValidators):
    def __init__(
        self,
        host: str,
        username: str,
        apiv1_key: str,
        project_name: str,
        ca_path: str,
        project_slug: str,
    ):
        self.validation_name = "Validate if the project {} belongs to user {}".format(
            project_name, username
        )
        self.validation_name = "Check if user is present"
        self.host = host
        self.username = username
        self.apiv1_key = apiv1_key
        self.project_name = project_name
        self.ca_path = ca_path
        self.project_slug = project_slug

    def validate(self) -> ValidationResponse:
        endpoint = Template(ApiV1Endpoints.PROJECT.value).substitute(
            username=self.username, project_name=self.project_slug
        )
        try:
            response = call_api_v1(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                api_key=self.apiv1_key,
                ca_path=self.ca_path,
            )
            return ValidationResponse(
                validation_name=self.validation_name,
                validation_msg="Project is present",
                validation_status=ValidationResponseStatus.PASSED,
            )
        except HTTPError:
            logging.error("Project does not exist")
            return ValidationResponse(
                validation_name=self.validation_name,
                validation_msg="Project - {} does not exist. Ensure that the project name provided is correct.".format(
                    self.project_name
                ),
                validation_status=ValidationResponseStatus.FAILED,
            )


class TopLevelDirectoryValidator(ExportValidators):
    def __init__(self, top_level_directory: str):
        self.validation_name = "validate if output directory exists"
        self.top_level_dir = top_level_directory

    def validate(self) -> ValidationResponse:
        if does_directory_exist(self.top_level_dir):
            return ValidationResponse(
                validation_name=self.validation_name,
                validation_msg="validation passed",
                validation_status=ValidationResponseStatus.PASSED,
            )
        return ValidationResponse(
            validation_name=self.validation_name,
            validation_msg="Directory {} does not exist".format(self.top_level_dir),
            validation_status=ValidationResponseStatus.FAILED,
        )


class RsyncRuntimeAddonExistsExportValidator(ExportValidators):
    def __init__(
        self,
        host: str,
        username: str,
        apiv1_key: str,
        project_name: str,
        ca_path: str,
        project_slug: str,
    ):
        self.validation_name = "check if rsync is present"
        self.host = host
        self.username = username
        self.apiv1_key = apiv1_key
        self.project_name = project_name
        self.ca_path = ca_path
        self.project_slug = project_slug

    def validate(self) -> ValidationResponse:
        rsync_enabled_runtime_id = -1
        if is_project_configured_with_runtimes(
            host=self.host,
            username=self.username,
            project_name=self.project_name,
            api_key=self.apiv1_key,
            ca_path=self.ca_path,
            project_slug=self.project_slug,
        ):
            rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
                host=self.host, api_key=self.apiv1_key, ca_path=self.ca_path
            )
            if rsync_enabled_runtime_id != -1:
                return ValidationResponse(
                    validation_name=self.validation_name,
                    validation_msg="validation passed",
                    validation_status=ValidationResponseStatus.PASSED,
                )
        else:
            return ValidationResponse(
                validation_name=self.validation_name,
                validation_msg="Project {} is not configured with runtime".format(
                    self.project_name
                ),
                validation_status=ValidationResponseStatus.SKIPPED,
            )
        return ValidationResponse(
            validation_name=self.validation_name,
            validation_msg="Rsync enabled runtime is not added in the project {}.".format(
                self.project_name
            ),
            validation_status=ValidationResponseStatus.FAILED,
        )


def initialize_import_validators(
    host: str,
    username: str,
    project_name: str,
    top_level_directory: str,
    apiv1_key: str,
    ca_path: str,
    target_owner: str
) -> List[ImportValidators]:
    return [
        DirectoriesAndFilesValidator(
            username=username,
            project_name=project_name,
            top_level_directory=top_level_directory,
        ),
        UserNameImportValidator(
            host=host,
            username=username,
            apiv1_key=apiv1_key,
            project_name=project_name,
            ca_path=ca_path,
        ),
        RsyncRuntimeAddonExistsImportValidator(
            host=host,
            username=username,
            apiv1_key=apiv1_key,
            project_name=project_name,
            ca_path=ca_path,
        ),
        ImportFieldValidator(
            target_owner=target_owner
        )
    ]


def initialize_export_validators(
    host: str,
    username: str,
    project_name: str,
    top_level_directory: str,
    apiv1_key: str,
    ca_path: str,
    project_slug: str,
) -> List[ExportValidators]:
    return [
        TopLevelDirectoryValidator(top_level_directory=top_level_directory),
        UsernameValidator(
            host=host,
            username=username,
            apiv1_key=apiv1_key,
            project_name=project_name,
            ca_path=ca_path,
        ),
        ProjectBelongsToUserValidator(
            host=host,
            username=username,
            apiv1_key=apiv1_key,
            project_name=project_name,
            ca_path=ca_path,
            project_slug=project_slug,
        ),
        RsyncRuntimeAddonExistsExportValidator(
            host=host,
            username=username,
            apiv1_key=apiv1_key,
            project_name=project_name,
            ca_path=ca_path,
            project_slug=project_slug,
        ),
    ]
