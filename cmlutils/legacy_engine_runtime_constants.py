import os
from json import load

#  If the mapping is Empty, the workloads will be created with the default engine images. Hence,
#  make this map empty in cases of default engine images scenario
_LEGACY_ENGINE_RUNTIME_CONSTANTS = {
    "python3": "docker.repository.cloudera.com/cloudera/cdsw/ml-runtime-workbench-python3.9-standard:2022.11.2-b2",
    "python2": "docker.repository.cloudera.com/cloudera/cdsw/ml-runtime-workbench-python3.9-standard:2022.11.2-b2",
    "r": "docker.repository.cloudera.com/cloudera/cdsw/ml-runtime-workbench-r4.1-standard:2022.11.2-b2",
    "scala": "docker.repository.cloudera.com/cloudera/cdsw/ml-runtime-workbench-scala2.11-standard:2022.11.2-b2",
    "default": "docker.repository.cloudera.com/cloudera/cdsw/ml-runtime-workbench-python3.9-standard:2023.05.2-b7",
}


def engine_to_runtime_map():
    # make sure this file is generated only via `cmlutil helpers populate_runtimes`
    file_path = (
        os.path.expanduser("~") + "/.cmlutils/legacy_engine_runtime_constants.json"
    )
    if os.path.exists(file_path):
        data = open(file_path)
        engine_map = load(data)
        return engine_map
    else:
        return _LEGACY_ENGINE_RUNTIME_CONSTANTS
