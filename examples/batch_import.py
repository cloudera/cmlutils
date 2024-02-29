# Copyright (c) 2023 Cloudera, Inc. All rights reserved.
# Author: Cloudera
# Description: An example script to perform batch import of projects.

import os
import shlex
import json
import subprocess
from configparser import ConfigParser
from multiprocessing.pool import ThreadPool

OUTPUT_DIR_KEY = "output_dir"
IMPORT_METRIC_FILE = "logs/import_metrics.json"
# This variable controls the number of threads that can run simultaneously.
BATCH_SIZE = 10

# This variable controls if user want to trigger migration validation automatically after import
# NOTE: Migration validation is resource intensive task keep the BATCH_SIZE to optimal size
VERIFY = False


# import a single project using cmlutility.
def import_project(project_name: str):
    if VERIFY:
        import_command = "yes | cmlutil project import -p  {} --verify".format(
            shlex.quote(project_name)
        )
    else:
        import_command = "yes | cmlutil project import -p  {}".format(
            shlex.quote(project_name)
        )
    subprocess.run(import_command, shell=True)


def get_absolute_path(path: str) -> str:
    if path.startswith("~"):
        return path.replace("~", os.path.expanduser("~"), 1)
    return os.path.abspath(path=path)


def import_validate(project_name: str):
    output_dir = _read_config_file((os.path.expanduser("~") + "/.cmlutils/import-config.ini"),
                            project_name)
    import_metrics_file_path = os.path.join(get_absolute_path(output_dir[OUTPUT_DIR_KEY]), project_name, IMPORT_METRIC_FILE)

    try:
        with open(import_metrics_file_path, "r") as file:
            data = json.load(file)
    except FileNotFoundError:
        is_migration_successful = False
    else:
        # Access the value of the isMigrationSuccessful key
        is_migration_successful = data.get("isMigrationSuccessful", False)
    return is_migration_successful


def _read_config_file(file_path: str, project_name: str):
    output_config = {}
    config = ConfigParser()
    if os.path.exists(file_path):
        config.read(file_path)
        key = OUTPUT_DIR_KEY
        try:
            value = config.get(project_name, key)
            output_config.setdefault(key, value)
        except NoOptionError:
            print("Key %s is missing from config file." % (key))
            raise
        return output_config
    else:
        print("Validation error: cannot find config file:", file_path)
        raise RuntimeError("validation error", "Cannot find config file")


# Read list of section/project names from import-config.ini
def _get_project_list(file_path: str):
    config = ConfigParser()
    if os.path.exists(file_path):
        config.read(file_path)
        project_names = config.sections()
        return project_names
    else:
        print("Validation error: cannot find config file:", file_path)
        raise RuntimeError("validation error", "Cannot find config file")


def main():
    failed_validation_list = list()
    project_names = _get_project_list(
        os.path.expanduser("~") + "/.cmlutils/import-config.ini"
    )
    project_iter = []

    for project in project_names:
        element = [project]
        project_iter.append(element)

    # create a thread pool
    with ThreadPool(BATCH_SIZE) as pool:
        # call a function on each item in a list
        pool.starmap(import_project, project_iter)

    # validation summary if VERIFY=True
    if VERIFY:
        for project in project_names:
            result = import_validate(project)
            if not result:
                failed_validation_list.append(project)

        print("\033[34m\tValidation of {} out of {} project are successful\033[0m".format(len(project_iter)-len(failed_validation_list), len(project_iter)))
        if failed_validation_list:
            print("\033[31m\tValidation Failed for {} \n\tPlease check the logs of individual projects for more info\033[0m".format(failed_validation_list))
        else:
            print("\033[32m\tValidation Passed for all the projects\033[0m")


if __name__ == "__main__":
    main()





