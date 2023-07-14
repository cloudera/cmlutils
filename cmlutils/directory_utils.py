import logging
import os


def get_project_data_dir_path(top_level_dir: str, project_name: str) -> str:
    return os.path.join(top_level_dir, project_name, "project-data")


def get_project_metadata_dir_path(top_level_dir: str, project_name: str) -> str:
    return os.path.join(top_level_dir, project_name, "project-metadata")


def get_project_metadata_file_path(top_level_dir: str, project_name: str) -> str:
    return os.path.join(
        get_project_metadata_dir_path(top_level_dir, project_name),
        "project-metadata.json",
    )


def get_models_metadata_file_path(top_level_dir: str, project_name: str) -> str:
    return os.path.join(
        get_project_metadata_dir_path(top_level_dir, project_name),
        "models-metadata.json",
    )


def get_applications_metadata_file_path(top_level_dir: str, project_name: str) -> str:
    return os.path.join(
        get_project_metadata_dir_path(top_level_dir, project_name),
        "applications-metadata.json",
    )


def get_jobs_metadata_file_path(top_level_dir: str, project_name: str) -> str:
    return os.path.join(
        get_project_metadata_dir_path(top_level_dir, project_name), "jobs-metadata.json"
    )


def does_directory_exist(dirname: str) -> bool:
    return os.path.exists(dirname) and os.path.isdir(dirname)


def ensure_project_data_and_metadata_directory_exists(
    top_level_dir: str, project_name: str
) -> tuple[str, str]:
    data_dir = get_project_data_dir_path(
        top_level_dir=top_level_dir, project_name=project_name
    )
    metadata_dir = get_project_metadata_dir_path(
        top_level_dir=top_level_dir, project_name=project_name
    )
    logging.info(
        "Project data and metadata directory path: %s , %s", data_dir, metadata_dir
    )
    os.makedirs(name=data_dir, exist_ok=True)
    os.makedirs(name=metadata_dir, exist_ok=True)
    return data_dir, metadata_dir
