import json
import logging
import os
import signal
import subprocess
import urllib.parse
from encodings import utf_8
from string import Template
from sys import stdout
from typing import Any

from requests import HTTPError

from cmlutils import constants, legacy_engine_runtime_constants
from cmlutils.base import BaseWorkspaceInteractor
from cmlutils.cdswctl import cdswctl_login, obtain_cdswctl
from cmlutils.constants import ApiV1Endpoints, ApiV2Endpoints
from cmlutils.directory_utils import (
    ensure_project_data_and_metadata_directory_exists,
    get_applications_metadata_file_path,
    get_jobs_metadata_file_path,
    get_models_metadata_file_path,
    get_project_data_dir_path,
    get_project_metadata_file_path,
)
from cmlutils.ssh import open_ssh_endpoint
from cmlutils.utils import (
    call_api_v1,
    call_api_v2,
    extract_fields,
    find_runtime,
    flatten_json_data,
    get_best_runtime,
    read_json_file,
    write_json_file,
)



def is_project_configured_with_runtimes(
    host: str,
    username: str,
    project_name: str,
    api_key: str,
    ca_path: str,
    project_slug: str,
) -> bool:
    endpoint = Template(ApiV1Endpoints.PROJECT.value).substitute(
        username=username, project_name=project_slug
    )
    response = call_api_v1(
        host=host, endpoint=endpoint, method="GET", api_key=api_key, ca_path=ca_path
    )
    response_dict = response.json()
    return (
        str(response_dict.get("default_project_engine_type", "")).lower()
        == "ml_runtime"
    )


def get_ignore_files(
    host: str,
    username: str,
    project_name: str,
    api_key: str,
    ca_path: str,
    ssh_port: str,
    project_slug: str,
    top_level_dir: str,
) -> str:
    endpoint = Template(ApiV1Endpoints.PROJECT_FILE.value).substitute(
        username=username, project_name=project_slug, filename=constants.FILE_NAME
    )
    try:
        logging.info(
            "The files included in %s will not be migrated for the project %s",
            constants.FILE_NAME,
            project_name,
        )
        response = call_api_v1(
            host=host, endpoint=endpoint, method="GET", api_key=api_key, ca_path=ca_path
        )
        a = response.text + "\n" + constants.FILE_NAME
        with open(
            os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH),
            "w",
            encoding=utf_8.getregentry().name,
        ) as f:
            f.writelines(a.strip())
        # Set file permissions to 600 (read and write only for the owner)
        os.chmod(
            os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH), 0o600
        )
        return os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH)
    except HTTPError as e:
        if e.response.status_code == 404:
            logging.warning(
                "Export ignore file does not exist. Hence, all files of the project %s will be migrated except .cache and .local.",
                project_name,
            )
            logging.info(
                "Since the %s file was not provided, a default file has been generated to exclude the directories .cache and .local from migration.",
                constants.FILE_NAME,
            )
            entries_content = "\n".join(constants.DEFAULT_ENTRIES)
            create_command = [
                "ssh",
                "-p",
                str(ssh_port),
                "-oStrictHostKeyChecking=no",
                constants.CDSW_ROOT_USER,
                f"echo -e '{entries_content}' > {constants.FILE_NAME}",
            ]
            subprocess.run(create_command)
            entries_content = entries_content + "\n" + constants.FILE_NAME
            with open(
                os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH),
                "w",
                encoding=utf_8.getregentry().name,
            ) as f:
                f.writelines(entries_content.strip())
            # Set file permissions to 600 (read and write only for the owner)
            os.chmod(
                os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH),
                0o600,
            )
            return os.path.join(top_level_dir, project_name, constants.IGNORE_FILE_PATH)
        else:
            logging.error("Failed to find ignore files due to network issues.")
            raise e


def get_rsync_enabled_runtime_id(host: str, api_key: str, ca_path: str) -> int:
    runtime_list = get_cdsw_runtimes(host=host, api_key=api_key, ca_path=ca_path)
    for runtime in runtime_list:
        if "rsync" in runtime["edition"].lower():
            logging.info("Rsync enabled runtime is available.")
            return runtime["id"]
    logging.info("Rsync enabled runtime is not available")
    return -1


def get_cdsw_runtimes(host: str, api_key: str, ca_path: str) -> list[dict[str, Any]]:
    endpoint = "api/v1/runtimes"
    response = call_api_v1(
        host=host, endpoint=endpoint, method="GET", api_key=api_key, ca_path=ca_path
    )
    response_dict = response.json()
    return response_dict["runtimes"]


def transfer_project_files(
    sshport: int,
    source: str,
    destination: str,
    retry_limit: int,
    project_name: str,
    log_filedir: str,
    exclude_file_path: str = None,
):
    log_filename = log_filedir + constants.LOG_FILE
    logging.info("Transfering files over ssh from sshport %s", sshport)
    ssh_directive = f"ssh -p {sshport} -oStrictHostKeyChecking=no"
    subprocess_arguments = [
        "rsync",
        "--delete",
        "-P",
        "-r",
        "-v",
        "-i",
        "-a",
        "-e",
        ssh_directive,
        "--log-file",
        log_filename,
    ]
    if exclude_file_path is not None:
        logging.info("Exclude file path is provided for file transfer")
        subprocess_arguments.append(f"--exclude-from={exclude_file_path}")
    subprocess_arguments.extend([source, destination])
    for i in range(retry_limit):
        return_code = subprocess.call(subprocess_arguments)
        if return_code == 0:
            logging.info("Project files transfered successfully")
            return
        logging.warning("Got non zero return code. Retrying...")
    if return_code != 0:
        logging.error(
            "Retries exhausted for rsync.. Failing script for project %s", project_name
        )
        raise RuntimeError("Retries exhausted for rsync.. Failing script")


def verify_files(
    sshport: int,
    source: str,
    destination: str,
    retry_limit: int,
    project_name: str,
    log_filedir: str,
    exclude_file_path: str = None,
):
    log_filename = log_filedir + constants.LOG_FILE
    logging.info("Validating files over ssh from sshport %s", sshport)
    ssh_directive = f"ssh -p {sshport} -oStrictHostKeyChecking=no"
    subprocess_arguments = [
        "rsync",
        "-n",
        "-r",
        "-c",
        "-a",
        "--delete",
        "--itemize-changes",
        "--out-format=%n",
        "-e",
        ssh_directive,
        "--log-file",
        log_filename,
    ]
    if exclude_file_path is not None:
        logging.info("Exclude file path is provided for file Verification")
        subprocess_arguments.append(f"--exclude-from={exclude_file_path}")
    subprocess_arguments.extend([source, destination])
    for i in range(retry_limit):
        result = subprocess.run(
            subprocess_arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if result.returncode == 0:
            # Removing any . files
            file_list = (
                result.stdout.decode("utf-8")
                .strip()
                .replace(" ", "")
                .replace("./", "")
                .replace("deleting", "")
                .replace("\t", "")
                .split("\n")
            )
            # Use list comprehension to remove empty strings and .local and ,cache files
            filtered_list = [
                file
                for file in file_list
                if (file != "" and
                    not file.startswith('.'))
                 ]
            return filtered_list
        logging.warning("Got non zero return code. Retrying...")
    if result.returncode != 0:
        logging.error(
            "Retries exhausted for rsync.. Failing script for project %s", project_name
        )
        raise RuntimeError("Retries exhausted for rsync.. Failing script")


def test_file_size(sshport: int, output_dir: str, exclude_file_path: str = None):
    if exclude_file_path != None:
        command = f"ssh -p {sshport} -oStrictHostKeyChecking=no {constants.CDSW_ROOT_USER} \"du -sh -k --exclude-from='{constants.EXCLUDE_FILE_ROOT_PATH}'\""
    else:
        command = f'ssh -p {sshport} -oStrictHostKeyChecking=no {constants.CDSW_ROOT_USER} "du -sh -k ."'
    output = subprocess.check_output(command, shell=True).decode("utf-8").strip()
    # Extract the file size from the output
    file_size = output.split("\t")[0]
    s = os.statvfs(output_dir)
    localdir_size = (s.f_bavail * s.f_frsize) / 1024
    if float(file_size) > float(localdir_size):
        logging.error(
            "Insufficient disk storage to download project files for the project."
        )
        raise RuntimeError


class ProjectExporter(BaseWorkspaceInteractor):
    def __init__(
        self,
        host: str,
        username: str,
        project_name: str,
        api_key: str,
        top_level_dir: str,
        ca_path: str,
        project_slug: str,
        owner_type: str,
    ) -> None:
        self._ssh_subprocess = None
        self.top_level_dir = top_level_dir
        self.project_id = None
        self.owner_type = owner_type
        super().__init__(host, username, project_name, api_key, ca_path, project_slug)
        self.metrics_data = dict()

    # Get CDSW project info using API v1
    def get_project_infov1(self):
        endpoint = Template(ApiV1Endpoints.PROJECT.value).substitute(
            username=self.username, project_name=self.project_slug
        )
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get CDSW project env variables using API v1
    def get_project_env(self):
        endpoint = Template(ApiV1Endpoints.PROJECT_ENV.value).substitute(
            username=self.username, project_name=self.project_slug
        )
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def get_creator_username(self):
        next_page_exists = True
        offset = 0
        project_list = []

        # Handle Pagination if exists
        while next_page_exists:
            # Note - projectName param makes LIKE query not the exact match
            endpoint = Template(ApiV1Endpoints.PROJECTS_SUMMARY.value).substitute(
                username=self.username,
                projectName=self.project_name,
                limit=constants.MAX_API_PAGE_LENGTH,
                offset=offset * constants.MAX_API_PAGE_LENGTH,
            )
            response = call_api_v1(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                api_key=self.api_key,
                ca_path=self.ca_path,
            )

            """
            End loop            
            a. If response len is less than MAX_API_PAGE_LENGTH 
                => Possible if less number of records
                => Possible if response is [] => len 0             
            b. If length of response is greater than MAX_API_PAGE_LENGTH => If source is CDSW, as CDSW doesn't honor limit
            c. If CDSW non-paginated response length is exactly the MAX_API_PAGE_LENGTH
            """
            if len(response.json()) != constants.MAX_API_PAGE_LENGTH:
                next_page_exists = False
            else:
                # Handling if CDSW non-paginated response length is MAX_API_PAGE_LENGTH
                if project_list == response.json():
                    break

            project_list = project_list + response.json()
            offset = offset + 1

        if project_list:
            for project in project_list:
                # It is possible that project lists can contain other users' public projects, or team's projects
                # so there could be projects that has the same name but belong to other users. To ensure that
                # we identify the correct project, we need to compare the project owner's name too.
                if project["name"] == self.project_name and project["owner"]["username"] == self.username:
                    if project["owner"]["type"] == constants.ORGANIZATION_TYPE:
                        return (
                            project["owner"]["username"],
                            project["slug_raw"],
                            constants.ORGANIZATION_TYPE,
                        )
                    else:
                        return (
                            project["creator"]["username"],
                            project["slug_raw"],
                            constants.USER_TYPE,
                        )
        return None, None, None

    # Get all models list info using API v1
    def get_models_listv1(self, project_id: int):
        endpoint = ApiV1Endpoints.MODELS_LIST.value
        json_data = {
            "projectId": project_id,
            "latestModelDeployment": True,
            "latestModelBuild": True,
        }
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="POST",
            api_key=self.api_key,
            json_data=json_data,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get all jobs list info using API v1
    def get_jobs_listv1(self):
        endpoint = Template(ApiV1Endpoints.JOBS_LIST.value).substitute(
            username=self.username, project_name=self.project_slug
        )
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get all applications list info using API v1
    def get_app_listv1(self):
        endpoint = Template(ApiV1Endpoints.APPS_LIST.value).substitute(
            username=self.username, project_name=self.project_slug
        )
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get CDSW model info using API v1
    def get_model_infov1(self, model_id: str):
        endpoint = ApiV1Endpoints.MODEL_INFO.value
        json_data = {
            "id": model_id,
            "latestModelDeployment": True,
            "latestModelBuild": True,
        }
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="POST",
            api_key=self.api_key,
            json_data=json_data,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get Job info using API v1
    def get_job_infov1(self, job_id: int):
        endpoint = Template(ApiV1Endpoints.JOB_INFO.value).substitute(
            username=self.username, project_name=self.project_slug, job_id=job_id
        )
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get application info using API v1
    def get_app_infov1(self, app_id: int):
        endpoint = Template(ApiV1Endpoints.APP_INFO.value).substitute(
            username=self.username, project_name=self.project_name, app_id=app_id
        )
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get all runtimes using API v1
    def get_all_runtimes(self):
        endpoint = ApiV1Endpoints.RUNTIMES.value
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def terminate_ssh_session(self):
        logging.info("Terminating ssh connection.")
        if self._ssh_subprocess is not None:
            self._ssh_subprocess.send_signal(signal.SIGINT)
        self._ssh_subprocess = None

    def transfer_project_files(self, log_filedir: str):
        rsync_enabled_runtime_id = -1
        if is_project_configured_with_runtimes(
            host=self.host,
            username=self.username,
            project_name=self.project_name,
            api_key=self.api_key,
            ca_path=self.ca_path,
            project_slug=self.project_slug,
        ):
            rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
                host=self.host, api_key=self.api_key, ca_path=self.ca_path
            )
        cdswctl_path = obtain_cdswctl(host=self.host, ca_path=self.ca_path)
        login_response = cdswctl_login(
            cdswctl_path=cdswctl_path,
            host=self.host,
            username=self.username,
            api_key=self.api_key,
        )
        if login_response.returncode != 0:
            logging.error("Cdswctl login failed")
            raise RuntimeError
        project_data_dir, _ = ensure_project_data_and_metadata_directory_exists(
            self.top_level_dir, self.project_name
        )

        logging.info("Creating SSH connection")
        ssh_subprocess, port = open_ssh_endpoint(
            cdswctl_path=cdswctl_path,
            project_name=self.project_name,
            runtime_id=rsync_enabled_runtime_id,
            project_slug=self.project_slug,
        )
        self._ssh_subprocess = ssh_subprocess
        exclude_file_path = get_ignore_files(
            host=self.host,
            username=self.username,
            project_name=self.project_name,
            api_key=self.api_key,
            ca_path=self.ca_path,
            ssh_port=port,
            project_slug=self.project_slug,
            top_level_dir=self.top_level_dir,
        )
        test_file_size(
            sshport=port,
            output_dir=project_data_dir,
            exclude_file_path=exclude_file_path,
        )
        transfer_project_files(
            sshport=port,
            source=constants.CDSW_PROJECTS_ROOT_DIR,
            destination=project_data_dir,
            retry_limit=3,
            project_name=self.project_name,
            exclude_file_path=exclude_file_path,
            log_filedir=log_filedir,
        )
        self.remove_cdswctl_dir(cdswctl_path)
        self.terminate_ssh_session()

    def verify_project_files(self, log_filedir: str):
        rsync_enabled_runtime_id = -1
        if is_project_configured_with_runtimes(
            host=self.host,
            username=self.username,
            project_name=self.project_name,
            api_key=self.api_key,
            ca_path=self.ca_path,
            project_slug=self.project_slug,
        ):
            rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
                host=self.host, api_key=self.api_key, ca_path=self.ca_path
            )
        cdswctl_path = obtain_cdswctl(host=self.host, ca_path=self.ca_path)
        login_response = cdswctl_login(
            cdswctl_path=cdswctl_path,
            host=self.host,
            username=self.username,
            api_key=self.api_key,
        )
        if login_response.returncode != 0:
            logging.error("Cdswctl login failed")
            raise RuntimeError

        logging.info("Creating SSH connection")
        ssh_subprocess, port = open_ssh_endpoint(
            cdswctl_path=cdswctl_path,
            project_name=self.project_name,
            runtime_id=rsync_enabled_runtime_id,
            project_slug=self.project_slug,
        )
        self._ssh_subprocess = ssh_subprocess
        exclude_file_path = get_ignore_files(
            host=self.host,
            username=self.username,
            project_name=self.project_name,
            api_key=self.api_key,
            ca_path=self.ca_path,
            ssh_port=port,
            project_slug=self.project_slug,
            top_level_dir=self.top_level_dir,
        )
        result = verify_files(
            sshport=port,
            source=os.path.join(
                get_project_data_dir_path(
                    top_level_dir=self.top_level_dir, project_name=self.project_name
                ),
                "",
            ),
            destination=constants.CDSW_PROJECTS_ROOT_DIR,
            retry_limit=3,
            project_name=self.project_name,
            exclude_file_path=exclude_file_path,
            log_filedir=log_filedir,
        )
        self.remove_cdswctl_dir(cdswctl_path)
        self.terminate_ssh_session()
        return result

    def _export_project_metadata(self):
        filepath = get_project_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        logging.info("Exporting project metadata to path %s", filepath)
        project_info_resp = self.get_project_infov1()
        project_env = self.get_project_env()
        if "CDSW_APP_POLLING_ENDPOINT" not in project_env:
            project_env["CDSW_APP_POLLING_ENDPOINT"] = "."
        project_info_flatten = flatten_json_data(project_info_resp)
        project_metadata = extract_fields(project_info_flatten, constants.PROJECT_MAP)

        if project_info_flatten[
            "default_project_engine_type"
        ] == constants.LEGACY_ENGINE and not bool(
            legacy_engine_runtime_constants.engine_to_runtime_map()
        ):
            project_metadata["default_project_engine_type"] = constants.LEGACY_ENGINE

        project_metadata["template"] = "blank"
        project_metadata["environment"] = project_env

        # Create project in team context
        if self.owner_type == constants.ORGANIZATION_TYPE:
            project_metadata["team_name"] = self.username
            logging.warning(
                "Project %s belongs to team %s. Ensure that the team already exists in the target workspace prior to executing the import command.",
                self.project_name,
                self.username,
            )
        self.project_id = project_info_resp["id"]
        write_json_file(file_path=filepath, json_data=project_metadata)

    def _export_models_metadata(self):
        filepath = get_models_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        logging.info("Exporting models metadata to path %s", filepath)
        model_list = self.get_models_listv1(project_id=self.project_id)
        model_name_list = []
        if len(model_list) == 0:
            logging.info("Models are not present in the project %s.", self.project_name)
        runtime_list = self.get_all_runtimes()
        model_metadata_list = []
        for model in model_list:
            model_info_flatten = flatten_json_data(model)
            model_metadata = extract_fields(model_info_flatten, constants.MODEL_MAP)
            model_name_list.append(model_metadata["name"])
            if "authEnabled" in model:
                model_metadata["disable_authentication"] = not model["authEnabled"]
            if "latestModelBuild.runtimeId" in model_info_flatten:
                runtime_obj = find_runtime(
                    runtime_list=runtime_list["runtimes"],
                    runtime_id=model_info_flatten["latestModelBuild.runtimeId"],
                )
                if runtime_obj != None:
                    model_metadata.update(runtime_obj)
            else:
                if (
                    model_info_flatten["project.default_project_engine_type"]
                    == constants.LEGACY_ENGINE
                ):
                    # We are expecting LEGACY_ENGINE_MAP if the user want to migrate from an engine to runtime,
                    # and the mapping should be given in LEGACY_ENGINE_MAP
                    # If the mapping is not given/empty, the workloads will be created with the default engine images.
                    if bool(legacy_engine_runtime_constants.engine_to_runtime_map()):
                        if model_info_flatten["latestModelBuild.kernel"] != "":
                            runtime_identifier = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                model_info_flatten["latestModelBuild.kernel"],
                                legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                    "default"
                                ),
                            )
                            model_metadata["runtime_identifier"] = runtime_identifier
                        else:
                            model_metadata[
                                "runtime_identifier"
                            ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                "default"
                            )
                    else:
                        if model_info_flatten["latestModelBuild.kernel"] != "":
                            model_metadata["kernel"] = model_info_flatten[
                                "latestModelBuild.kernel"
                            ]
                        else:
                            model_metadata[
                                "runtime_identifier"
                            ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                "default"
                            )

            model_metadata_list.append(model_metadata)
        write_json_file(file_path=filepath, json_data=model_metadata_list)
        self.metrics_data["total_model"] = len(model_name_list)
        self.metrics_data["model_name_list"] = sorted(model_name_list)

    def _export_application_metadata(self):
        filepath = get_applications_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        logging.info("Exporting application metadata to path %s", filepath)
        app_list = self.get_app_listv1()
        app_name_list = []
        if len(app_list) == 0:
            logging.info(
                "Applications are not present in the project %s.", self.project_name
            )
        app_metadata_list = []
        for app in app_list:
            app_info_flatten = flatten_json_data(app)
            app_metadata = extract_fields(app_info_flatten, constants.APPLICATION_MAP)
            app_name_list.append(app_metadata["name"])
            app_metadata["environment"] = app["environment"]
            if (
                app_info_flatten["currentDashboard.kernel"] != None
                and app_info_flatten["currentDashboard.kernel"] != ""
            ):
                # We are expecting LEGACY_ENGINE_MAP if the user want to migrate from an engine to runtime,
                # and the mapping should be given in LEGACY_ENGINE_MAP
                # If the mapping is not given, the workloads will be created with the default engine images.
                if bool(legacy_engine_runtime_constants.engine_to_runtime_map()):
                    runtime_identifier = (
                        legacy_engine_runtime_constants.engine_to_runtime_map().get(
                            app_info_flatten["currentDashboard.kernel"],
                            legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                "default"
                            ),
                        )
                    )
                    app_metadata["runtime_identifier"] = runtime_identifier
                else:
                    app_metadata["kernel"] = app_info_flatten["currentDashboard.kernel"]
            app_metadata_list.append(app_metadata)

        write_json_file(file_path=filepath, json_data=app_metadata_list)
        self.metrics_data["total_application"] = len(app_metadata_list)
        self.metrics_data["application_name_list"] = sorted(app_name_list)

    def collect_export_job_list(self):
        job_list = self.get_jobs_listv1()
        job_name_list = []
        if len(job_list) == 0:
            logging.info("Jobs are not present in the project %s.", self.project_name)
        else:
            logging.info("Project {} has {} Jobs".format(self.project_name, len(job_list)))
        job_metadata_list = []
        for job in job_list:
            job_info_flatten = flatten_json_data(job)
            job_metadata = extract_fields(job_info_flatten, constants.JOB_MAP)
            job_name_list.append(job_metadata["name"])
            job_metadata_list.append(job_metadata)
        return job_metadata_list, sorted(job_name_list)

    def collect_export_model_list(self, proj_id):
        model_list = self.get_models_listv1(proj_id)
        model_name_list = []
        if len(model_list) == 0:
            logging.info("Models are not present in the project %s.", self.project_name)
        else:
            logging.info("Project {} has {} Models".format(self.project_name, len(model_list)))
        model_metadata_list = []
        for model in model_list:
            model_info_flatten = flatten_json_data(model)
            model_metadata = extract_fields(model_info_flatten, constants.MODEL_MAP)
            model_name_list.append(model_metadata["name"])
            model_metadata_list.append(model_metadata)
        return model_metadata_list, sorted(model_name_list)

    def collect_export_application_list(self):
        app_list = self.get_app_listv1()
        app_name_list = []
        if len(app_list) == 0:
            logging.info(
                "Applications are not present in the project %s.", self.project_name
            )
        else:
            logging.info("Project {} has {} Applications".format(self.project_name, len(app_list)))
        app_metadata_list = []
        for app in app_list:
            app_info_flatten = flatten_json_data(app)
            app_metadata = extract_fields(app_info_flatten, constants.APPLICATION_MAP)
            app_name_list.append(app_metadata["name"])
            project_env = self.get_project_env()
            if not app_metadata.get("environment"):
                app_metadata["environment"] = project_env
            app_metadata_list.append(app_metadata)
        return app_metadata_list, sorted(app_name_list)

    def _export_job_metadata(self):
        filepath = get_jobs_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        logging.info("Exporting job metadata to path %s ", filepath)
        job_list = self.get_jobs_listv1()
        if len(job_list) == 0:
            logging.info("Jobs are not present in the project %s.", self.project_name)
        runtime_list = self.get_all_runtimes()
        job_metadata_list = []
        job_name_list = []

        for job_item in job_list:
            job = self.get_job_infov1(job_item["id"])
            job_info_flatten = flatten_json_data(job)
            job_metadata = extract_fields(job_info_flatten, constants.JOB_MAP)
            job_name_list.append(job_metadata["name"])
            job_metadata["attachments"] = job.get("report", []).get("attachments", [])
            job_metadata["environment"] = job.get("environment", {})
            if "runtime.id" in job_info_flatten:
                runtime_obj = find_runtime(
                    runtime_list=runtime_list["runtimes"],
                    runtime_id=job_info_flatten["runtime.id"],
                )
                if runtime_obj != None:
                    job_metadata.update(runtime_obj)
                else:
                    job_metadata[
                        "runtime_identifier"
                    ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                        "default"
                    )
            else:
                if (
                    job_info_flatten["project.default_project_engine_type"]
                    == constants.LEGACY_ENGINE
                ):
                    # We are expecting LEGACY_ENGINE_MAP if the user want to migrate from an engine to runtime,
                    # and the mapping should be given in LEGACY_ENGINE_MAP
                    # If the mapping is not given, the workloads will be created with the default engine images.
                    if bool(legacy_engine_runtime_constants.engine_to_runtime_map()):
                        if job_info_flatten["kernel"] != "":
                            runtime_identifier = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                job_info_flatten["kernel"],
                                legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                    "default"
                                ),
                            )
                            job_metadata["runtime_identifier"] = runtime_identifier
                        else:
                            job_metadata[
                                "runtime_identifier"
                            ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                "default"
                            )
                    else:
                        if job_info_flatten["kernel"] != "":
                            job_metadata["kernel"] = job_info_flatten["kernel"]
                        else:
                            job_metadata[
                                "runtime_identifier"
                            ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                "default"
                            )
                else:
                    job_metadata[
                        "runtime_identifier"
                    ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                        "default"
                    )

            job_metadata_list.append(job_metadata)

        write_json_file(file_path=filepath, json_data=job_metadata_list)
        self.metrics_data["total_job"] = len(job_name_list)
        self.metrics_data["job_name_list"] = sorted(job_name_list)

    def dump_project_and_related_metadata(self):
        self._export_project_metadata()
        self._export_models_metadata()
        self._export_application_metadata()
        self._export_job_metadata()
        return self.metrics_data

    def collect_export_project_data(self):
        proj_data_raw = self.get_project_infov1()
        proj_info_flatten = flatten_json_data(proj_data_raw)
        proj_data = [extract_fields(proj_info_flatten, constants.PROJECT_MAP)]
        proj_list = [self.project_name.lower()]
        if not proj_data[0].get("shared_memory_limit"):
            proj_data[0]["shared_memory_limit"] = 0

        model_data, model_list = self.collect_export_model_list(
            int(proj_data_raw["id"])
        )
        app_data, app_list = self.collect_export_application_list()
        job_data, job_list = self.collect_export_job_list()
        return (
            proj_data,
            proj_list,
            model_data,
            model_list,
            app_data,
            app_list,
            job_data,
            job_list,
        )


class ProjectImporter(BaseWorkspaceInteractor):
    def __init__(
        self,
        host: str,
        username: str,
        project_name: str,
        api_key: str,
        top_level_dir: str,
        ca_path: str,
        project_slug: str,
    ) -> None:
        self._ssh_subprocess = None
        self.top_level_dir = top_level_dir
        super().__init__(host, username, project_name, api_key, ca_path, project_slug)
        self.metrics_data = dict()

    def get_creator_username(self):
        next_page_exists = True
        offset = 0
        project_list = []

        # Handle Pagination if exists
        while next_page_exists:
            # Note - projectName param makes LIKE query not the exact match
            endpoint = Template(ApiV1Endpoints.PROJECTS_SUMMARY.value).substitute(
                username=self.username,
                projectName=self.project_name,
                limit=constants.MAX_API_PAGE_LENGTH,
                offset=offset * constants.MAX_API_PAGE_LENGTH,
            )
            response = call_api_v1(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                api_key=self.api_key,
                ca_path=self.ca_path,
            )

            """
            End loop           
            a. If response len is less than MAX_API_PAGE_LENGTH 
                => Possible if less number of records
                => Possible if response is [] => len 0             
            b. If length of response is greater than MAX_API_PAGE_LENGTH => If source is CDSW, as CDSW doesn't honor limit
            c. If CDSW non-paginated response length is exactly the MAX_API_PAGE_LENGTH
            """
            if len(response.json()) != constants.MAX_API_PAGE_LENGTH:
                next_page_exists = False
            else:
                # Handling if CDSW non-paginated response length is MAX_API_PAGE_LENGTH
                if project_list == response.json():
                    break

            project_list = project_list + response.json()
            offset = offset + 1

        if project_list:
            for project in project_list:
                if project["name"] == self.project_name:
                    return project["creator"]["username"], project["slug_raw"]
        return None

    def transfer_project(self, log_filedir: str, verify=False):
        result = None
        rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
            host=self.host, api_key=self.apiv2_key, ca_path=self.ca_path
        )
        cdswctl_path = obtain_cdswctl(host=self.host, ca_path=self.ca_path)
        login_response = cdswctl_login(
            cdswctl_path=cdswctl_path,
            host=self.host,
            username=self.username,
            api_key=self.api_key,
        )
        if login_response.returncode != 0:
            logging.error("Cdswctl login failed")
            raise RuntimeError
        ssh_subprocess, port = open_ssh_endpoint(
            cdswctl_path=cdswctl_path,
            project_name=self.project_name,
            runtime_id=rsync_enabled_runtime_id,
            project_slug=self.project_slug,
        )
        self._ssh_subprocess = ssh_subprocess
        transfer_project_files(
            sshport=port,
            source=os.path.join(
                get_project_data_dir_path(
                    top_level_dir=self.top_level_dir, project_name=self.project_name
                ),
                "",
            ),
            destination=constants.CDSW_PROJECTS_ROOT_DIR,
            retry_limit=3,
            project_name=self.project_name,
            log_filedir=log_filedir,
        )
        if verify:
            result = verify_files(
                sshport=port,
                source=os.path.join(
                    get_project_data_dir_path(
                        top_level_dir=self.top_level_dir, project_name=self.project_name
                    ),
                    "",
                ),
                destination=constants.CDSW_PROJECTS_ROOT_DIR,
                retry_limit=3,
                project_name=self.project_name,
                log_filedir=log_filedir,
            )
        self.remove_cdswctl_dir(cdswctl_path)
        return result

    def verify_project(self, log_filedir: str):
        rsync_enabled_runtime_id = get_rsync_enabled_runtime_id(
            host=self.host, api_key=self.apiv2_key, ca_path=self.ca_path
        )
        cdswctl_path = obtain_cdswctl(host=self.host, ca_path=self.ca_path)
        login_response = cdswctl_login(
            cdswctl_path=cdswctl_path,
            host=self.host,
            username=self.username,
            api_key=self.api_key,
        )
        if login_response.returncode != 0:
            logging.error("Cdswctl login failed")
            raise RuntimeError
        ssh_subprocess, port = open_ssh_endpoint(
            cdswctl_path=cdswctl_path,
            project_name=self.project_name,
            runtime_id=rsync_enabled_runtime_id,
            project_slug=self.project_slug,
        )
        self._ssh_subprocess = ssh_subprocess
        result = verify_files(
            sshport=port,
            source=os.path.join(
                get_project_data_dir_path(
                    top_level_dir=self.top_level_dir, project_name=self.project_name
                ),
                "",
            ),
            destination=constants.CDSW_PROJECTS_ROOT_DIR,
            retry_limit=3,
            project_name=self.project_name,
            log_filedir=log_filedir,
        )
        self.remove_cdswctl_dir(cdswctl_path)
        return result

    def terminate_ssh_session(self):
        logging.info("Terminating ssh connection.")
        if self._ssh_subprocess is not None:
            self._ssh_subprocess.send_signal(signal.SIGINT)
        self._ssh_subprocess = None

    def create_project_v2(self, proj_metadata) -> str:
        try:
            endpoint = ApiV2Endpoints.PROJECTS.value
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="POST",
                user_token=self.apiv2_key,
                json_data=proj_metadata,
                ca_path=self.ca_path,
            )
            json_resp = response.json()
            return json_resp["id"]
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def convert_project_to_engine_based(self, proj_patch_metadata) -> bool:
        try:
            endpoint2 = Template(ApiV1Endpoints.PROJECT.value).substitute(
                username=self.username, project_name=self.project_name
            )
            response = call_api_v1(
                host=self.host,
                endpoint=endpoint2,
                method="PATCH",
                api_key=self.api_key,
                json_data=proj_patch_metadata,
                ca_path=self.ca_path,
            )
            return True
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def create_model_v2(self, proj_id: str, model_metadata) -> str:
        try:
            endpoint = Template(ApiV2Endpoints.CREATE_MODEL.value).substitute(
                project_id=proj_id
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="POST",
                user_token=self.apiv2_key,
                json_data=model_metadata,
                ca_path=self.ca_path,
            )
            json_resp = response.json()
            return json_resp["id"]
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def create_model_build_v2(
        self, proj_id: str, model_id: str, model_metadata
    ) -> None:
        endpoint = Template(ApiV2Endpoints.BUILD_MODEL.value).substitute(
            project_id=proj_id, model_id=model_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="POST",
            user_token=self.apiv2_key,
            json_data=model_metadata,
            ca_path=self.ca_path,
        )
        return

    def create_application_v2(self, proj_id: str, app_metadata) -> str:
        try:
            endpoint = Template(ApiV2Endpoints.CREATE_APP.value).substitute(
                project_id=proj_id
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="POST",
                user_token=self.apiv2_key,
                json_data=app_metadata,
                ca_path=self.ca_path,
            )
            json_resp = response.json()
            return json_resp["id"]
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def stop_application_v2(self, proj_id: str, app_id: str) -> None:
        endpoint = Template(ApiV2Endpoints.STOP_APP.value).substitute(
            project_id=proj_id, application_id=app_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="POST",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return

    def create_job_v2(self, proj_id: str, job_metadata) -> str:
        try:
            endpoint = Template(ApiV2Endpoints.CREATE_JOB.value).substitute(
                project_id=proj_id
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="POST",
                user_token=self.apiv2_key,
                json_data=job_metadata,
                ca_path=self.ca_path,
            )
            json_resp = response.json()
            return json_resp["id"]
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def update_job_v2(self, proj_id: str, job_id: str, job_metadata) -> None:
        endpoint = Template(ApiV2Endpoints.UPDATE_JOB.value).substitute(
            project_id=proj_id, job_id=job_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="PATCH",
            user_token=self.apiv2_key,
            json_data=job_metadata,
            ca_path=self.ca_path,
        )
        return

    # Get all runtimes using API v1
    def get_all_runtimes(self):
        endpoint = ApiV1Endpoints.RUNTIMES.value
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            api_key=self.api_key,
            ca_path=self.ca_path,
        )
        return response.json()

    # Get spark runtime addons using API v2
    def get_spark_runtimeaddons(self):
        search_option = {"identifier": constants.SPARK_ADDON, "status": "AVAILABLE"}
        encoded_option = urllib.parse.quote(json.dumps(search_option).replace('"', '"'))
        endpoint = Template(ApiV2Endpoints.RUNTIME_ADDONS.value).substitute(
            search_option=encoded_option
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        result_list = response.json()["runtime_addons"]
        if result_list:
            return result_list[0]["identifier"]
        return None

    def get_all_runtimes_v2(self, page_token=""):
        endpoint = Template(ApiV2Endpoints.RUNTIMES.value).substitute(
            page_size=constants.MAX_API_PAGE_LENGTH, page_token=page_token
        )

        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        result_list = response.json()
        if result_list:
            return result_list
        return None

    def check_project_exist(self, project_name: str, team_name: str = None) -> str:
        try:
            search_option = {"name": project_name}
            encoded_option = urllib.parse.quote(
                json.dumps(search_option).replace('"', '"')
            )
            endpoint = Template(ApiV2Endpoints.SEARCH_PROJECT.value).substitute(
                search_option=encoded_option
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            project_list = response.json()["projects"]

            # If the project is a team's project, then the owner of the project is the team
            if team_name:
                owner = team_name
            else:
                owner = self.username

            # It is possible that project lists can contain other users' public projects, or team's projects
            # so there could be projects that has the same name but belong to other users. To ensure that
            # we identify the correct project, we need to compare the project owner's name too.
            if project_list:
                for project in project_list:
                    if project["name"] == project_name and project["owner"]["username"] == owner:
                        return project["id"]
            return None
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def check_model_exist(self, model_name: str, proj_id: str) -> bool:
        try:
            search_option = {"name": model_name}
            encoded_option = urllib.parse.quote(
                json.dumps(search_option).replace('"', '"')
            )
            endpoint = Template(ApiV2Endpoints.SEARCH_MODEL.value).substitute(
                project_id=proj_id, search_option=encoded_option
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            model_list = response.json()["models"]
            if model_list:
                for model in model_list:
                    if model["name"] == model_name:
                        return True
            return False
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def check_job_exist(self, job_name: str, script: str, proj_id: str) -> str:
        try:
            search_option = {"name": job_name, "script": script}
            encoded_option = urllib.parse.quote(
                json.dumps(search_option).replace('"', '"')
            )
            endpoint = Template(ApiV2Endpoints.SEARCH_JOB.value).substitute(
                project_id=proj_id, search_option=encoded_option
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            job_list = response.json()["jobs"]
            if job_list:
                for job in job_list:
                    if job["name"] == job_name and job["script"] == script:
                        return job["id"]
            return None
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def check_app_exist(self, subdomain: str, proj_id: str) -> bool:
        try:
            search_option = {"subdomain": subdomain}
            encoded_option = urllib.parse.quote(
                json.dumps(search_option).replace('"', '"')
            )
            endpoint = Template(ApiV2Endpoints.SEARCH_APP.value).substitute(
                project_id=proj_id, search_option=encoded_option
            )
            response = call_api_v2(
                host=self.host,
                endpoint=endpoint,
                method="GET",
                user_token=self.apiv2_key,
                ca_path=self.ca_path,
            )
            app_list = response.json()["applications"]
            if app_list:
                for app in app_list:
                    if app["subdomain"] == subdomain:
                        return True
            return False
        except KeyError as e:
            logging.error(f"Error: {e}")
            raise

    def get_models_listv2(self, proj_id: str):
        endpoint = Template(ApiV2Endpoints.MODELS_LIST.value).substitute(
            project_id=proj_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def get_models_detailv2(self, proj_id: str, model_id: str):
        endpoint = Template(ApiV2Endpoints.BUILD_MODEL.value).substitute(
            project_id=proj_id, model_id=model_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def get_jobs_listv2(self, proj_id: str):
        endpoint = Template(ApiV2Endpoints.JOBS_LIST.value).substitute(
            project_id=proj_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def get_application_listv2(self, proj_id: str):
        endpoint = Template(ApiV2Endpoints.APPS_LIST.value).substitute(
            project_id=proj_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def import_metadata(self, project_id: str):
        models_metadata_filepath = get_models_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        self.create_models(
            project_id=project_id, models_metadata_filepath=models_metadata_filepath
        )

        app_metadata_filepath = get_applications_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        self.create_stoppped_applications(
            project_id=project_id, app_metadata_filepath=app_metadata_filepath
        )

        job_metadata_filepath = get_jobs_metadata_file_path(
            top_level_dir=self.top_level_dir, project_name=self.project_name
        )
        self.create_paused_jobs(
            project_id=project_id, job_metadata_filepath=job_metadata_filepath
        )
        self.get_project_infov2(proj_id=project_id)
        self.collect_import_model_list(project_id=project_id)
        self.collect_import_application_list(project_id=project_id)
        self.collect_import_job_list(project_id=project_id)
        return self.metrics_data

    def collect_imported_project_data(self, project_id: str):
        proj_data_raw = self.get_project_infov2(proj_id=project_id)
        proj_info_flatten = flatten_json_data(proj_data_raw)
        proj_data = [extract_fields(proj_info_flatten, constants.PROJECT_MAPV2)]
        proj_list = [
            self.project_name.lower()
            if self.check_project_exist(self.project_name)
            else None
        ]
        model_data, model_list = self.collect_import_model_list(project_id=project_id)
        app_data, app_list = self.collect_import_application_list(project_id=project_id)
        job_data, job_list = self.collect_import_job_list(project_id=project_id)
        return (
            proj_data,
            proj_list,
            model_data,
            model_list,
            app_data,
            app_list,
            job_data,
            job_list,
        )

    def create_models(self, project_id: str, models_metadata_filepath: str):
        try:
            runtime_list = self.get_all_runtimes()
            proj_with_runtime = is_project_configured_with_runtimes(
                host=self.host,
                username=self.username,
                project_name=self.project_name,
                api_key=self.api_key,
                ca_path=self.ca_path,
                project_slug=self.project_slug,
            )
            model_metadata_list = read_json_file(models_metadata_filepath)
            if model_metadata_list != None:
                for model_metadata in model_metadata_list:
                    if not self.check_model_exist(
                        model_name=model_metadata["name"], proj_id=project_id
                    ):
                        model_metadata["project_id"] = project_id
                        if (
                            not "runtime_identifier" in model_metadata
                            and proj_with_runtime
                        ):
                            runtime_identifier = get_best_runtime(
                                runtime_list["runtimes"],
                                model_metadata["runtime_edition"],
                                model_metadata["runtime_editor"],
                                model_metadata["runtime_kernel"],
                                model_metadata["runtime_shortversion"],
                                model_metadata["runtime_fullversion"],
                            )
                            if runtime_identifier != None:
                                model_metadata[
                                    "runtime_identifier"
                                ] = runtime_identifier
                            else:
                                logging.warning(
                                    "Couldn't locate runtime identifier for model %s",
                                    model_metadata["name"],
                                )
                                logging.info(
                                    "Applying default runtime %s",
                                    legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                        "default"
                                    ),
                                )
                                model_metadata[
                                    "runtime_identifier"
                                ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                    "default"
                                )
                        model_id = self.create_model_v2(
                            proj_id=project_id, model_metadata=model_metadata
                        )
                        self.create_model_build_v2(
                            proj_id=project_id,
                            model_id=model_id,
                            model_metadata=model_metadata,
                        )
                        logging.info(
                            "Model- %s has been migrated successfully",
                            model_metadata["name"],
                        )
                    else:
                        logging.info(
                            "Skipping the already existing model- %s",
                            model_metadata["name"],
                        )

            return
        except FileNotFoundError as e:
            logging.info("No model-metadata file found for migration")
            return
        except Exception as e:
            logging.error("Model migration failed")
            logging.error(f"Error: {e}")
            raise

    def create_stoppped_applications(self, project_id: str, app_metadata_filepath: str):
        try:
            runtime_list = self.get_all_runtimes()
            proj_with_runtime = is_project_configured_with_runtimes(
                host=self.host,
                username=self.username,
                project_name=self.project_name,
                api_key=self.api_key,
                ca_path=self.ca_path,
                project_slug=self.project_slug,
            )
            app_metadata_list = read_json_file(app_metadata_filepath)
            if app_metadata_list != None:
                for app_metadata in app_metadata_list:
                    if not self.check_app_exist(
                        subdomain=app_metadata["subdomain"], proj_id=project_id
                    ):
                        app_metadata["project_id"] = project_id
                        if (
                            not "runtime_identifier" in app_metadata
                            and proj_with_runtime
                        ):
                            runtime_identifier = get_best_runtime(
                                runtime_list["runtimes"],
                                app_metadata["runtime_edition"],
                                app_metadata["runtime_editor"],
                                app_metadata["runtime_kernel"],
                                app_metadata["runtime_shortversion"],
                                app_metadata["runtime_fullversion"],
                            )
                            if runtime_identifier != None:
                                app_metadata["runtime_identifier"] = runtime_identifier
                            else:
                                app_metadata[
                                    "runtime_identifier"
                                ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                    "default"
                                )
                        app_id = self.create_application_v2(
                            proj_id=project_id, app_metadata=app_metadata
                        )
                        self.stop_application_v2(proj_id=project_id, app_id=app_id)
                        logging.info(
                            "Application- %s has been migrated successfully",
                            app_metadata["name"],
                        )
                    else:
                        logging.info(
                            "Skipping the already existing application %s with same subdomain- %s",
                            app_metadata["name"],
                            app_metadata["subdomain"],
                        )

            return
        except FileNotFoundError as e:
            logging.info("No application-metadata file found for migration")
            return
        except Exception as e:
            logging.error("Application migration failed")
            logging.error(f"Error: {e}")
            raise

    def create_paused_jobs(self, project_id: str, job_metadata_filepath: str):
        try:
            runtime_list = self.get_all_runtimes()
            spark_runtime_id = self.get_spark_runtimeaddons()
            proj_with_runtime = is_project_configured_with_runtimes(
                host=self.host,
                username=self.username,
                project_name=self.project_name,
                api_key=self.api_key,
                ca_path=self.ca_path,
                project_slug=self.project_slug,
            )
            job_metadata_list = read_json_file(job_metadata_filepath)
            src_tgt_job_mapping = {}
            # Create job in target CML workspace.
            if job_metadata_list != None:
                for job_metadata in job_metadata_list:
                    target_job_id = self.check_job_exist(
                        job_name=job_metadata["name"],
                        script=job_metadata["script"],
                        proj_id=project_id,
                    )
                    if target_job_id == None:
                        job_metadata["project_id"] = project_id
                        job_metadata["paused"] = True
                        if spark_runtime_id != None:
                            job_metadata["runtime_addon_identifiers"] = [
                                spark_runtime_id
                            ]
                        if (
                            not "runtime_identifier" in job_metadata
                            and proj_with_runtime
                        ):
                            runtime_identifier = get_best_runtime(
                                runtime_list["runtimes"],
                                job_metadata["runtime_edition"],
                                job_metadata["runtime_editor"],
                                job_metadata["runtime_kernel"],
                                job_metadata["runtime_shortversion"],
                                job_metadata["runtime_fullversion"],
                            )
                            if runtime_identifier != None:
                                job_metadata["runtime_identifier"] = runtime_identifier
                            else:
                                job_metadata[
                                    "runtime_identifier"
                                ] = legacy_engine_runtime_constants.engine_to_runtime_map().get(
                                    "default"
                                )
                        target_job_id = self.create_job_v2(
                            proj_id=project_id, job_metadata=job_metadata
                        )
                        logging.info(
                            "Job- %s has been migrated successfully",
                            job_metadata["name"],
                        )
                    else:
                        logging.info(
                            "Skipping the already existing job- %s",
                            job_metadata["name"],
                        )

                    src_tgt_job_mapping[job_metadata["source_jobid"]] = target_job_id

                # Update job dependency
                for job_metadata in job_metadata_list:
                    if "parent_jobid" in job_metadata:
                        tgt_job_id = src_tgt_job_mapping[job_metadata["source_jobid"]]
                        tgt_parent_jobid = src_tgt_job_mapping[
                            job_metadata["parent_jobid"]
                        ]
                        json_post_req = {"parent_id": tgt_parent_jobid}
                        self.update_job_v2(
                            proj_id=project_id,
                            job_id=tgt_job_id,
                            job_metadata=json_post_req,
                        )
            logging.warning("Internal job report recipients may not get migrated")

            return
        except FileNotFoundError as e:
            logging.info("No job-metadata file found for migration")
            return
        except Exception as e:
            logging.error("Job migration failed")
            logging.error(f"Error: {e}")
            raise

    def get_project_infov2(self, proj_id: str):
        endpoint = Template(ApiV2Endpoints.GET_PROJECT.value).substitute(
            project_id=proj_id
        )
        response = call_api_v2(
            host=self.host,
            endpoint=endpoint,
            method="GET",
            user_token=self.apiv2_key,
            ca_path=self.ca_path,
        )
        return response.json()

    def collect_import_job_list(self, project_id):
        job_list = self.get_jobs_listv2(proj_id=project_id)["jobs"]
        job_name_list = []
        if len(job_list) == 0:
            logging.info("Jobs are not present in the project %s.", self.project_name)
        else:
            logging.info("Project {} has {} Jobs".format(self.project_name, len(job_list)))
        job_metadata_list = []
        for job in job_list:
            job_info_flatten = flatten_json_data(job)
            job_metadata = extract_fields(job_info_flatten, constants.JOB_MAP)
            job_name_list.append(job_metadata["name"])
            job_metadata_list.append(job_metadata)
        self.metrics_data["total_job"] = len(job_name_list)
        self.metrics_data["job_name_list"] = sorted(job_name_list)
        return job_metadata_list, sorted(job_name_list)

    def collect_import_model_list(self, project_id):
        model_list = self.get_models_listv2(proj_id=project_id)["models"]
        model_name_list = []
        if len(model_list) == 0:
            logging.info("Models are not present in the project %s.", self.project_name)
        else:
            logging.info("Project {} has {} Models".format(self.project_name, len(model_list)))
        model_metadata_list = []
        model_detail_data = {}
        for model in model_list:
            model_info_flatten = flatten_json_data(model)
            model_detail_data["name"] = model_info_flatten["name"]
            model_detail_data["description"] = model_info_flatten["description"]
            model_detail_data["disable_authentication"] = model_info_flatten["auth_enabled"] if isinstance(model_info_flatten["auth_enabled"], bool) else model_info_flatten["auth_enabled"]
            model_details = self.get_models_detailv2(
                proj_id=project_id, model_id=model_info_flatten["id"]
            )
            model_metadata = {}
            if len(model_details["model_builds"]) > 0:
                model_metadata = extract_fields(
                    model_details["model_builds"][0], constants.MODEL_MAPV2
                )
                model_detail_data.update(model_metadata)

            model_name_list.append(model_info_flatten["name"])
            model_metadata_list.append(model_detail_data)
        self.metrics_data["total_model"] = len(model_name_list)
        self.metrics_data["model_name_list"] = sorted(model_name_list)
        return model_metadata_list, sorted(model_name_list)

    def collect_import_application_list(self, project_id):
        app_list = self.get_application_listv2(proj_id=project_id)["applications"]
        app_name_list = []
        if len(app_list) == 0:
            logging.info(
                "Applications are not present in the project %s.", self.project_name
            )
        else:
            logging.info("Project {} has {} Application".format(self.project_name, len(app_list)))
        app_metadata_list = []
        for app in app_list:
            app_info_flatten = flatten_json_data(app)
            app_metadata = extract_fields(app_info_flatten, constants.APPLICATION_MAPV2)
            app_name_list.append(app_metadata["name"])
            app_metadata_list.append(app_metadata)
        self.metrics_data["total_application"] = len(app_name_list)
        self.metrics_data["application_name_list"] = sorted(app_name_list)
        return app_metadata_list, sorted(app_name_list)
