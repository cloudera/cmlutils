import logging
import os
import sys
import time
from configparser import ConfigParser, NoOptionError
from json import dump
import json
from logging.handlers import RotatingFileHandler

import click

from cmlutils import constants
from cmlutils.constants import (
    API_V1_KEY,
    CA_PATH_KEY,
    OUTPUT_DIR_KEY,
    URL_KEY,
    USERNAME_KEY,
)
from cmlutils.directory_utils import get_project_metadata_file_path
from cmlutils.projects import ProjectExporter, ProjectImporter
from cmlutils.script_models import ValidationResponseStatus
from cmlutils.utils import (
    compare_metadata,
    get_absolute_path,
    parse_runtimes_v2,
    read_json_file,
    update_verification_status,
    write_json_file
)
from cmlutils.validator import (
    initialize_export_validators,
    initialize_import_validators,
)


def _configure_project_command_logging(log_filedir: str, project_name: str):
    os.makedirs(name=log_filedir, exist_ok=True)
    log_filename = log_filedir + constants.LOG_FILE
    logging.basicConfig(
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(
                filename=log_filename, maxBytes=10000000, backupCount=5
            ),
        ],
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(custom_attribute)s - %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
    )
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.custom_attribute = project_name
        return record

    logging.setLogRecordFactory(record_factory)


def _read_config_file(file_path: str, project_name: str):
    output_config = {}
    config = ConfigParser()
    if os.path.exists(file_path):
        config.read(file_path)
        keys = (USERNAME_KEY, URL_KEY, API_V1_KEY, OUTPUT_DIR_KEY)
        for key in keys:
            try:
                value = config.get(project_name, key)
                output_config.setdefault(key, value)
            except NoOptionError:
                print("Key %s is missing from config file." % (key))
                raise
        output_config[CA_PATH_KEY] = config.get(project_name, CA_PATH_KEY, fallback="")
        return output_config
    else:
        print("Validation error: cannot find config file:", file_path)
        raise RuntimeError("validation error", "Cannot find config file")


@click.group(name="project")
def project_cmd():
    """
    Sub-entrypoint for project command
    """


@project_cmd.command(name="export")
@click.option(
    "--project_name",
    "-p",
    help="Name of the project to be migrated. Make sure the name matches with the section name in export-config.ini file",
    required=True,
)
def project_export_cmd(project_name):
    pexport = None
    config = _read_config_file(
        os.path.expanduser("~") + "/.cmlutils/export-config.ini", project_name
    )

    username = config[USERNAME_KEY]
    url = config[URL_KEY]
    apiv1_key = config[API_V1_KEY]
    output_dir = config[OUTPUT_DIR_KEY]
    ca_path = config[CA_PATH_KEY]

    output_dir = get_absolute_path(output_dir)
    ca_path = get_absolute_path(ca_path)

    log_filedir = os.path.join(output_dir, project_name, "logs")
    _configure_project_command_logging(log_filedir, project_name)
    logging.info("Started exporting project: %s", project_name)
    try:
        # Get username of the creator of project - This is required so that admins can also migrate the project
        pobj = ProjectExporter(
            host=url,
            username=username,
            project_name=project_name,
            api_key=apiv1_key,
            top_level_dir=output_dir,
            ca_path=ca_path,
            project_slug=project_name,
            owner_type="",
        )
        creator_username, project_slug, owner_type = pobj.get_creator_username()
        if creator_username is None:
            logging.error(
                "Validation error: Cannot find project - %s under username %s",
                project_name,
                username,
            )
            raise RuntimeError("Validation error")
        logging.info("Begin validating for export.")
        validators = initialize_export_validators(
            host=url,
            username=creator_username,
            project_name=project_name,
            top_level_directory=output_dir,
            apiv1_key=apiv1_key,
            ca_path=ca_path,
            project_slug=project_slug,
        )
        for v in validators:
            validation_response = v.validate()
            if validation_response.validation_status == ValidationResponseStatus.FAILED:
                logging.error(
                    "Validation error: %s",
                    project_name,
                    validation_response.validation_msg,
                )
                raise RuntimeError(
                    "validation error", validation_response.validation_msg
                )
        logging.info(
            "Finished validating export validations for project %s.", project_name
        )
        logging.info("File transfer has started.")
        pexport = ProjectExporter(
            host=url,
            username=creator_username,
            project_name=project_name,
            api_key=apiv1_key,
            top_level_dir=output_dir,
            ca_path=ca_path,
            project_slug=project_slug,
            owner_type=owner_type,
        )
        start_time = time.time()
        pexport.transfer_project_files(log_filedir=log_filedir)
        exported_data = pexport.dump_project_and_related_metadata()
        print("\033[32m✔ Export of Project {} Successful \033[0m".format(project_name))
        print(
            "\033[34m\tExported {} Jobs {}\033[0m".format(
                exported_data.get("total_job"), exported_data.get("job_name_list")
            )
        )
        print(
            "\033[34m\tExported {} Models {}\033[0m".format(
                exported_data.get("total_model"), exported_data.get("model_name_list")
            )
        )
        print(
            "\033[34m\tExported {} Applications {}\033[0m".format(
                exported_data.get("total_application"),
                exported_data.get("application_name_list"),
            )
        )
        end_time = time.time()
        export_file = log_filedir + constants.EXPORT_METRIC_FILE
        write_json_file(file_path=export_file, json_data=exported_data)
        print(
            "{} Export took {:.2f} seconds".format(
                project_name, (end_time - start_time)
            )
        )
    except:
        logging.error("Exception:", exc_info=1)
        if pexport:
            pexport.terminate_ssh_session()
        exit()


@project_cmd.command(name="import")
@click.option(
    "--project_name",
    "-p",
    help="Name of the project to be migrated. Make sure the name matches with the section name in import-config.ini file",
    required=True,
)
@click.option(
    "--verify",
    "-v",
    is_flag=True,
    help="Flag to automatically trigger migration validation after import.",
)
def project_import_cmd(project_name, verify):
    pimport = None
    import_diff_file_list = None
    config = _read_config_file(
        os.path.expanduser("~") + "/.cmlutils/import-config.ini", project_name
    )

    username = config[USERNAME_KEY]
    url = config[URL_KEY]
    apiv1_key = config[API_V1_KEY]
    local_directory = config[OUTPUT_DIR_KEY]
    ca_path = config[CA_PATH_KEY]
    local_directory = get_absolute_path(local_directory)
    ca_path = get_absolute_path(ca_path)
    log_filedir = os.path.join(local_directory, project_name, "logs")

    _configure_project_command_logging(log_filedir, project_name)
    p = ProjectImporter(
        host=url,
        username=username,
        project_name=project_name,
        api_key=apiv1_key,
        top_level_dir=local_directory,
        ca_path=ca_path,
        project_slug=project_name,
    )
    logging.info("Started importing project: %s", project_name)
    try:
        validators = initialize_import_validators(
            host=url,
            username=username,
            project_name=project_name,
            top_level_directory=local_directory,
            apiv1_key=apiv1_key,
            ca_path=ca_path,
        )
        logging.info("Begin validating for import.")
        for v in validators:
            validation_response = v.validate()
            if validation_response.validation_status == ValidationResponseStatus.FAILED:
                logging.error(
                    "Validation error for project %s: %s",
                    project_name,
                    validation_response.validation_msg,
                )
                raise RuntimeError(
                    "validation error", validation_response.validation_msg
                )
        logging.info(
            "Finished validating import validations for project %s.", project_name
        )
        project_filepath = get_project_metadata_file_path(
            top_level_dir=local_directory, project_name=project_name
        )
        project_metadata = read_json_file(project_filepath)

        uses_engine = False
        if "default_project_engine_type" in project_metadata:
            uses_engine = True
            project_metadata.pop("default_project_engine_type", None)

        # check if the project to be imported is a team's project
        if "team_name" in project_metadata:
            project_id = p.check_project_exist(project_metadata["name"], project_metadata["team_name"])
        else:
            project_id = p.check_project_exist(project_metadata["name"])

        if project_id == None:
            logging.info(
                "Creating project %s to migrate files and metadata.", project_name
            )
            project_id = p.create_project_v2(proj_metadata=project_metadata)
        else:
            logging.warning(
                "Project %s already exist in the target workspace. Retrying the import won't update existing project settings or artifacts. Only missing artifacts will be migrated, However the project files will be synced via rsync.",
                project_metadata.get("name", ""),
            )
        if "team_name" in project_metadata:
            username = project_metadata["team_name"]
        creator_username, project_slug = p.get_creator_username()

        # reuse the ProjectImporter obj since it already generated the apiv2 key
        # this fixed the bug of team projects import where cmlutil was trying to
        # generate apiv2 key using the team's username
        pimport = p
        pimport.username = username
        pimport.project_slug = project_slug

        start_time = time.time()
        if verify:
            import_diff_file_list=pimport.transfer_project(log_filedir=log_filedir, verify=True)
        else:
            pimport.transfer_project(log_filedir=log_filedir)

        if uses_engine:
            proj_patch_metadata = {"default_project_engine_type": "legacy_engine"}
            pimport.convert_project_to_engine_based(
                proj_patch_metadata=proj_patch_metadata
            )
        import_data = dict()
        import_data["project_name"] = project_name
        import_data = pimport.import_metadata(project_id=project_id)
        print("\033[32m✔ Import of Project {} Successful \033[0m".format(project_name))
        print(
            "\033[34m\tImported {} Jobs {}\033[0m".format(
                import_data.get("total_job"), import_data.get("job_name_list")
            )
        )
        print(
            "\033[34m\tImported {} Models {}\033[0m".format(
                import_data.get("total_model"), import_data.get("model_name_list")
            )
        )
        print(
            "\033[34m\tImported {} Applications {}\033[0m".format(
                import_data.get("total_application"),
                import_data.get("application_name_list"),
            )
        )
        end_time = time.time()
        import_file = log_filedir + constants.IMPORT_METRIC_FILE
        write_json_file(file_path=import_file, json_data=import_data)
        print(
            "{} Import took {:.2f} seconds".format(
                project_name, (end_time - start_time)
            )
        )
        pimport.terminate_ssh_session()
        # If verification is also needed after import
        if verify:
            print("***************************************************** Started verifying migration for project: {} ***************************************************** ".format(project_name))
            (
                imported_project_data,
                imported_project_list,
                imported_model_data,
                imported_model_list,
                imported_app_data,
                imported_app_list,
                imported_job_data,
                imported_job_list,
            ) = pimport.collect_imported_project_data(project_id=project_id)
            # import_diff_file_list = pimport.verify_project(log_filedir=log_filedir)

            pexport = None
            validation_data = dict()
            config = _read_config_file(
                os.path.expanduser("~") + "/.cmlutils/export-config.ini", project_name
            )

            export_username = config[USERNAME_KEY]
            export_url = config[URL_KEY]
            export_apiv1_key = config[API_V1_KEY]
            output_dir = config[OUTPUT_DIR_KEY]
            ca_path = config[CA_PATH_KEY]

            export_output_dir = get_absolute_path(output_dir)
            export_ca_path = get_absolute_path(ca_path)

            log_filedir = os.path.join(output_dir, project_name, "logs")
            _configure_project_command_logging(log_filedir, project_name)

            import_file = log_filedir + constants.IMPORT_METRIC_FILE
            with open(import_file, 'r') as file:
                validation_data = json.load(file)
            try:
                # Get username of the creator of project - This is required so that admins can also migrate the project
                pobj = ProjectExporter(
                    host=export_url,
                    username=export_username,
                    project_name=project_name,
                    api_key=export_apiv1_key,
                    top_level_dir=export_output_dir,
                    ca_path=export_ca_path,
                    project_slug=project_name,
                    owner_type="",
                )
                (
                    export_creator_username,
                    export_project_slug,
                    export_owner_type,
                ) = pobj.get_creator_username()
                if export_creator_username is None:
                    logging.error(
                        "Validation error: Cannot find project - %s under username %s",
                        project_name,
                        export_username,
                    )
                    raise RuntimeError("Validation error")
                logging.info("Begin validating export project")
                validators = initialize_export_validators(
                    host=export_url,
                    username=export_creator_username,
                    project_name=project_name,
                    top_level_directory=export_output_dir,
                    apiv1_key=export_apiv1_key,
                    ca_path=export_ca_path,
                    project_slug=export_project_slug,
                )
                for v in validators:
                    validation_response = v.validate()
                    if validation_response.validation_status == ValidationResponseStatus.FAILED:
                        logging.error(
                            "Validation error: %s",
                            project_name,
                            validation_response.validation_msg,
                        )
                        raise RuntimeError(
                            "validation error", validation_response.validation_msg
                        )
                logging.info(
                    "Finished validating export verification validations for project %s.",
                    project_name,
                )
                pexport = ProjectExporter(
                    host=export_url,
                    username=export_creator_username,
                    project_name=project_name,
                    api_key=export_apiv1_key,
                    top_level_dir=export_output_dir,
                    ca_path=export_ca_path,
                    project_slug=export_project_slug,
                    owner_type=export_owner_type,
                )
                (
                    exported_proj_data,
                    exported_proj_list,
                    exported_model_data,
                    exported_model_list,
                    exported_app_data,
                    exported_app_list,
                    exported_job_data,
                    exported_job_list,
                ) = pexport.collect_export_project_data()

                # File verification
                export_diff_file_list = pexport.verify_project_files(
                    log_filedir=log_filedir
                )
                logging.info("Project Migration Verification Result")

                logging.info(
                    "No Difference Between Source And Local File Found"
                    if not export_diff_file_list
                    else "Difference between  Local File and Source are {}".format(
                        export_diff_file_list
                    )
                )
                logging.info(
                    "No Difference Between Local File And Destination Found"
                    if not import_diff_file_list
                    else "Difference between Local File and Destination are {}".format(
                        import_diff_file_list
                    )
                )
                update_verification_status(
                    (export_diff_file_list or import_diff_file_list),
                    message="Project File Verification",
                )

                # Project verification
                proj_diff, proj_config_diff = compare_metadata(
                    imported_project_data,
                    exported_proj_data,
                    imported_project_list,
                    exported_proj_list,
                )
                logging.info("Project {} Present at Source".format(exported_proj_list))
                logging.info(
                    "Project {} Present at Destination".format(imported_project_list)
                )
                logging.info(
                    "Project {} found in source and destination ".format(project_name)
                    if not proj_diff
                    else "Project {} Not Found in source or destination".format(
                        project_name
                    )
                )
                logging.info(
                    "No Project Config Difference Found"
                    if not proj_config_diff
                    else "Difference in project Config {}".format(proj_config_diff)
                )
                update_verification_status(
                    True if (proj_diff or proj_config_diff) else False,
                    message="Project Verification",
                )

                # Application verification
                app_diff, app_config_diff = compare_metadata(
                    imported_app_data,
                    exported_app_data,
                    imported_app_list,
                    exported_app_list,
                    skip_field=["environment"],
                )
                logging.info("Source Application list {}".format(exported_app_list))
                logging.info("Destination Application list {}".format(imported_app_list))
                logging.info(
                    "All Application in source project is present at destination project ".format(
                        app_diff
                    )
                    if not app_diff
                    else "Application {} Not Found in source or destination".format(
                        app_diff
                    )
                )
                logging.info(
                    "No Application Config Difference Found"
                    if not app_config_diff
                    else "Difference in application Config {}".format(app_config_diff)
                )
                update_verification_status(
                    True if (app_diff or app_config_diff) else False,
                    message="Application Verification",
                )

                # Model verification
                model_diff, model_config_diff = compare_metadata(
                    imported_model_data,
                    exported_model_data,
                    imported_model_list,
                    exported_model_list,
                )
                logging.info("Source Model list {}".format(exported_model_list))
                logging.info("Destination Model list {}".format(imported_model_list))
                logging.info(
                    "All Model in source project is present at destination project ".format(
                        model_diff
                    )
                    if not model_diff
                    else "Model {} Not Found in source or destination".format(model_diff)
                )
                logging.info(
                    "No Model Config Difference Found"
                    if not model_config_diff
                    else "Difference in Model Config {}".format(model_config_diff)
                )
                update_verification_status(
                    True if (model_diff or model_config_diff) else False,
                    message="Model Verification",
                )

                # Job verification
                job_diff, job_config_diff = compare_metadata(
                    imported_job_data,
                    exported_job_data,
                    imported_job_list,
                    exported_job_list,
                    skip_field=["source_jobid"],
                )
                logging.info("Source Job list {}".format(exported_job_list))
                logging.info("Destination Job list {}".format(imported_job_list))
                logging.info(
                    "All Job in source project is present at destination project ".format(
                        job_diff
                    )
                    if not job_diff
                    else "Job {} Not Found in source or destination".format(job_diff)
                )
                logging.info(
                    "No Job Config Difference Found"
                    if not job_config_diff
                    else "Difference in Job Config {}".format(job_config_diff)
                )
                update_verification_status(
                    True if (job_diff or job_config_diff) else False,
                    message="Job Verification",
                )
                result = [export_diff_file_list,import_diff_file_list,proj_diff,
                          proj_config_diff,app_diff,app_config_diff,model_diff,model_config_diff,job_diff, job_config_diff]
                migration_status = all(not sublist for sublist in result)
                validation_data["isMigrationSuccessful"] = migration_status
                update_verification_status(
                    not migration_status,
                    message="Migration Validation status for project : {} is".format(project_name),
                )
                write_json_file(file_path=import_file, json_data=validation_data)

            except:
                logging.error("Exception:", exc_info=1)
                validation_data["isMigrationSuccessful"] = False
                logging.info("Project Import was completed but Verification Failed")
                write_json_file(file_path=import_file, json_data=validation_data)
                if pexport:
                    pexport.terminate_ssh_session()
                if pimport:
                    pimport.terminate_ssh_session()
                exit()
    except:
        logging.error("Exception:", exc_info=1)
        if pimport:
            pimport.terminate_ssh_session()
        exit()


@project_cmd.command(name="validate-migration")
@click.option(
    "--project_name",
    "-p",
    help="Name of project migrated. Make sure the name matches with the section name in import-config.ini and export-config.ini file",
    required=True,
)
def project_verify_cmd(project_name):
    pexport = None
    validation_data = dict()
    config = _read_config_file(
        os.path.expanduser("~") + "/.cmlutils/export-config.ini", project_name
    )

    export_username = config[USERNAME_KEY]
    export_url = config[URL_KEY]
    export_apiv1_key = config[API_V1_KEY]
    output_dir = config[OUTPUT_DIR_KEY]
    ca_path = config[CA_PATH_KEY]

    export_output_dir = get_absolute_path(output_dir)
    export_ca_path = get_absolute_path(ca_path)

    log_filedir = os.path.join(output_dir, project_name, "logs")
    _configure_project_command_logging(log_filedir, project_name)
    logging.info("Started Verifying project: %s", project_name)
    import_file = log_filedir + constants.IMPORT_METRIC_FILE
    try:
        with open(import_file, 'r') as file:
            validation_data = json.load(file)
    except:
        logging.error("File not found Exception: ", exc_info=1)
    try:
        # Get username of the creator of project - This is required so that admins can also migrate the project
        pobj = ProjectExporter(
            host=export_url,
            username=export_username,
            project_name=project_name,
            api_key=export_apiv1_key,
            top_level_dir=export_output_dir,
            ca_path=export_ca_path,
            project_slug=project_name,
            owner_type="",
        )
        (
            export_creator_username,
            export_project_slug,
            export_owner_type,
        ) = pobj.get_creator_username()
        if export_creator_username is None:
            logging.error(
                "Validation error: Cannot find project - %s under username %s",
                project_name,
                export_username,
            )
            raise RuntimeError("Validation error")
        logging.info("Begin validating export project")
        validators = initialize_export_validators(
            host=export_url,
            username=export_creator_username,
            project_name=project_name,
            top_level_directory=export_output_dir,
            apiv1_key=export_apiv1_key,
            ca_path=export_ca_path,
            project_slug=export_project_slug,
        )
        for v in validators:
            validation_response = v.validate()
            if validation_response.validation_status == ValidationResponseStatus.FAILED:
                logging.error(
                    "Validation error: %s",
                    project_name,
                    validation_response.validation_msg,
                )
                raise RuntimeError(
                    "validation error", validation_response.validation_msg
                )
        logging.info(
            "Finished validating export verification validations for project %s.",
            project_name,
        )
        pexport = ProjectExporter(
            host=export_url,
            username=export_creator_username,
            project_name=project_name,
            api_key=export_apiv1_key,
            top_level_dir=export_output_dir,
            ca_path=export_ca_path,
            project_slug=export_project_slug,
            owner_type=export_owner_type,
        )
        (
            exported_proj_data,
            exported_proj_list,
            exported_model_data,
            exported_model_list,
            exported_app_data,
            exported_app_list,
            exported_job_data,
            exported_job_list,
        ) = pexport.collect_export_project_data()
        pexport.terminate_ssh_session()
        pimport = None
        import_config = _read_config_file(
            os.path.expanduser("~") + "/.cmlutils/import-config.ini", project_name
        )

        import_username = import_config[USERNAME_KEY]
        import_url = import_config[URL_KEY]
        import_apiv1_key = import_config[API_V1_KEY]
        local_directory = import_config[OUTPUT_DIR_KEY]
        ca_path = import_config[CA_PATH_KEY]
        import_local_directory = get_absolute_path(local_directory)
        import_ca_path = get_absolute_path(ca_path)
        p = ProjectImporter(
            host=import_url,
            username=import_username,
            project_name=project_name,
            api_key=import_apiv1_key,
            top_level_dir=import_local_directory,
            ca_path=import_ca_path,
            project_slug=project_name,
        )
        logging.info("Started Verifying imported project: %s", project_name)
        try:
            validators = initialize_import_validators(
                host=import_url,
                username=import_username,
                project_name=project_name,
                top_level_directory=import_local_directory,
                apiv1_key=import_apiv1_key,
                ca_path=import_ca_path,
            )
            logging.info("Begin validating for import.")
            for v in validators:
                validation_response = v.validate()
                if (
                    validation_response.validation_status
                    == ValidationResponseStatus.FAILED
                ):
                    logging.error(
                        "Validation error for project %s: %s",
                        project_name,
                        validation_response.validation_msg,
                    )
                    raise RuntimeError(
                        "validation error", validation_response.validation_msg
                    )
            logging.info(
                "Finished validating import verification validations for project %s.",
                project_name,
            )
            project_id = p.check_project_exist(project_name)

            project_filepath = get_project_metadata_file_path(
                top_level_dir=local_directory, project_name=project_name
            )
            project_metadata = read_json_file(project_filepath)

            if "team_name" in project_metadata:
                import_username = project_metadata["team_name"]
            import_creator_username, import_project_slug = p.get_creator_username()
            pimport = ProjectImporter(
                host=import_url,
                username=import_username,
                project_name=project_name,
                api_key=import_apiv1_key,
                top_level_dir=import_local_directory,
                ca_path=import_ca_path,
                project_slug=import_project_slug,
            )

            (
                imported_project_data,
                imported_project_list,
                imported_model_data,
                imported_model_list,
                imported_app_data,
                imported_app_list,
                imported_job_data,
                imported_job_list,
            ) = pimport.collect_imported_project_data(project_id=project_id)

            # File verification
            logging.info("Project export Verification")
            export_diff_file_list = pexport.verify_project_files(
                log_filedir=log_filedir
            )
            logging.info("Project import Verification")
            import_diff_file_list = pimport.verify_project(log_filedir=log_filedir)
            pimport.terminate_ssh_session()
            logging.info(
                "No Difference Between Source And Local File Found"
                if not export_diff_file_list
                else "Difference between  Local File and Source are {}".format(
                    export_diff_file_list
                )
            )
            logging.info(
                "No Difference Between Local File And Destination Found"
                if not import_diff_file_list
                else "Difference between Local File and Destination are {}".format(
                    import_diff_file_list
                )
            )
            update_verification_status(
                (export_diff_file_list or import_diff_file_list),
                message="Project File Verification",
            )

            # Project verification
            proj_diff, proj_config_diff = compare_metadata(
                imported_project_data,
                exported_proj_data,
                imported_project_list,
                exported_proj_list,
            )
            logging.info("Project {} Present at Source".format(exported_proj_list))
            logging.info(
                "Project {} Present at Destination".format(imported_project_list)
            )
            logging.info(
                "Project {} found in source and destination ".format(project_name)
                if not proj_diff
                else "Project {} Not Found in source or destination".format(
                    project_name
                )
            )
            logging.info(
                "No Project Config Difference Found"
                if not proj_config_diff
                else "Difference in project Config {}".format(proj_config_diff)
            )
            update_verification_status(
                True if (proj_diff or proj_config_diff) else False,
                message="Project Verification",
            )

            # Application verification
            app_diff, app_config_diff = compare_metadata(
                imported_app_data,
                exported_app_data,
                imported_app_list,
                exported_app_list,
                skip_field=["environment"],
            )
            logging.info("Source Application list {}".format(exported_app_list))
            logging.info("Destination Application list {}".format(imported_app_list))
            logging.info(
                "All Application in source project is present at destination project ".format(
                    app_diff
                )
                if not app_diff
                else "Application {} Not Found in source or destination".format(
                    app_diff
                )
            )
            logging.info(
                "No Application Config Difference Found"
                if not app_config_diff
                else "Difference in application Config {}".format(app_config_diff)
            )
            update_verification_status(
                True if (app_diff or app_config_diff) else False,
                message="Application Verification",
            )

            # Model verification
            model_diff, model_config_diff = compare_metadata(
                imported_model_data,
                exported_model_data,
                imported_model_list,
                exported_model_list,
            )
            logging.info("Source Model list {}".format(exported_model_list))
            logging.info("Destination Model list {}".format(imported_model_list))
            logging.info(
                "All Model in source project is present at destination project ".format(
                    model_diff
                )
                if not model_diff
                else "Model {} Not Found in source or destination".format(model_diff)
            )
            logging.info(
                "No Model Config Difference Found"
                if not model_config_diff
                else "Difference in Model Config {}".format(model_config_diff)
            )
            update_verification_status(
                True if (model_diff or model_config_diff) else False,
                message="Model Verification",
            )

            # Job verification
            job_diff, job_config_diff = compare_metadata(
                imported_job_data,
                exported_job_data,
                imported_job_list,
                exported_job_list,
                skip_field=["source_jobid"],
            )
            logging.info("Source Job list {}".format(exported_job_list))
            logging.info("Destination Job list {}".format(imported_job_list))
            logging.info(
                "All Job in source project is present at destination project ".format(
                    job_diff
                )
                if not job_diff
                else "Job {} Not Found in source or destination".format(job_diff)
            )
            logging.info(
                "No Job Config Difference Found"
                if not job_config_diff
                else "Difference in Job Config {}".format(job_config_diff)
            )
            update_verification_status(
                True if (job_diff or job_config_diff) else False,
                message="Job Verification",
            )
            result = [export_diff_file_list,import_diff_file_list,proj_diff,
                      proj_config_diff,app_diff,app_config_diff,model_diff,model_config_diff,job_diff, job_config_diff]
            migration_status = all(not sublist for sublist in result)
            update_verification_status(
                not migration_status,
                message="Migration Validation status for project : {} is".format(project_name),
            )
            validation_data["isMigrationSuccessful"] = migration_status
            write_json_file(file_path=import_file, json_data=validation_data)

        except:
            logging.error("Exception:", exc_info=1)
            validation_data["isMigrationSuccessful"] = False
            write_json_file(file_path=import_file, json_data=validation_data)
            if pimport:
                pimport.terminate_ssh_session()
            if pexport:
                pexport.terminate_ssh_session()
            exit()
    except:
        logging.error("Exception:", exc_info=1)
        validation_data["isMigrationSuccessful"] = False
        write_json_file(file_path=import_file, json_data=validation_data)
        if pexport:
            pexport.terminate_ssh_session()
        if pimport:
            pimport.terminate_ssh_session()
        exit()


@click.group(name="helpers")
def project_helpers_cmd():
    """
    Sub-entrypoint for helpers command
    """


@project_helpers_cmd.command("populate_engine_runtimes_mapping")
def populate_engine_runtimes_mapping():
    project_name = "DEFAULT"
    config = _read_config_file(
        os.path.expanduser("~") + "/.cmlutils/import-config.ini", project_name
    )

    username = config[USERNAME_KEY]
    url = config[URL_KEY]
    apiv1_key = config[API_V1_KEY]
    local_directory = config[OUTPUT_DIR_KEY]
    ca_path = config[CA_PATH_KEY]

    local_directory = get_absolute_path(local_directory)
    ca_path = get_absolute_path(ca_path)

    log_filedir = os.path.join(local_directory, project_name, "logs")
    _configure_project_command_logging(log_filedir, project_name)

    p = ProjectImporter(
        host=url,
        username=username,
        project_name=project_name,
        api_key=apiv1_key,
        top_level_dir=local_directory,
        ca_path=ca_path,
        project_slug=project_name,
    )

    page_token = ""

    response = p.get_all_runtimes_v2(page_token)
    if not response:
        logging.info(
            "populate_engine_runtimes_mapping: Get Runtimes API returned empty response"
        )
        return
    runtimes = response.get("runtimes", [])
    page_token = response.get("next_page_token", "")

    while len(page_token) > 0:
        response = p.get_all_runtimes_v2(page_token)
        if not response:
            break
        runtimes = runtimes + response.get("runtimes", [])
        page_token = response.get("next_page_token", "")

    if len(runtimes) > 0:
        legacy_runtime_image_map = parse_runtimes_v2(runtimes)
    else:
        logging.error(
            "populate_engine_runtimes_mapping: No runtimes present in the get_runtimes API response"
        )
        return

    # Tries to create/overwrite the data present in <home-dir>/.cmlutils/legacy_engine_runtime_constants.json
    # Please make sure utility is having necessary permissions to write/overwrite data
    try:
        with open(
            os.path.expanduser("~")
            + "/.cmlutils/"
            + "legacy_engine_runtime_constants.json",
            "w",
        ) as legacy_engine_runtime_constants:
            dump(legacy_runtime_image_map, legacy_engine_runtime_constants)
    except:
        logging.error(
            "populate_engine_runtimes_mapping: Please make sure Write Perms are set write/overwrite data."
            "Encountered Error during write/overwrite data in ",
            os.path.expanduser("~")
            + "/.cmlutils/"
            + "legacy_engine_runtime_constants.json",
        )
