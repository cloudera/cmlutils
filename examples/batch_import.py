# Copyright (c) 2023 Cloudera, Inc. All rights reserved.
# Author: Cloudera
# Description: An example script to perform batch import of projects.

import os
import shlex
import subprocess
from configparser import ConfigParser
from multiprocessing.pool import ThreadPool

# This variable controls the number of threads that can run simultaneously.
BATCH_SIZE = 10


# import a single project using cmlutility.
def import_project(project_name: str):
    import_command = "yes | cmlutil project import -p  {}".format(
        shlex.quote(project_name)
    )
    subprocess.run(import_command, shell=True)


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
    project_names = _get_project_list(
        os.path.expanduser("~") + "/.cmlutils/import-config.ini"
    )
    print(project_names)
    project_iter = []
    for project in project_names:
        element = [project]
        project_iter.append(element)

    # create a thread pool
    with ThreadPool(BATCH_SIZE) as pool:
        # call a function on each item in a list
        pool.starmap(import_project, project_iter)


if __name__ == "__main__":
    main()
