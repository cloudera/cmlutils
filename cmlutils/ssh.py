import logging
import signal
import subprocess
import time


def open_ssh_endpoint(
    cdswctl_path: str, project_name: str, runtime_id: int, project_slug: str
) -> tuple[subprocess.Popen, int]:
    command = [
        cdswctl_path,
        "ssh-endpoint",
        "-p",
        project_slug,
        "-c",
        "1.0",
        "-m",
        "0.5",
    ]
    if runtime_id != -1:
        command.append("-r")
        command.append(str(runtime_id))
    ssh_call = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    logging.info("Waiting for SSH connection")
    line = ssh_call.stdout.readline()
    if line == "" or line == None:
        error = ssh_call.stderr.readlines()
        logging.error(error)
        return None, -1
    else:
        arr = line.split(" ")
        if len(arr) <= 3 or (not arr[3].isdigit()):
            logging.error("SSH connection failed unexpectedly: " + line)
            logging.error(*ssh_call.stderr.readlines())
            raise Exception("SSH connection failed unexpectedly")
        logging.info("SSH connection successfull")
        return ssh_call, int(arr[3])
