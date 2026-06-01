import logging
import signal
import socket
import subprocess
import time


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def open_ssh_endpoint(
    cdswctl_path: str, project_name: str, runtime_id: int, project_slug: str, skip_tls_verification: bool = False
) -> tuple[subprocess.Popen, int]:
    local_port = _find_free_port()
    command = [
        cdswctl_path,
        "ssh-endpoint",
        "-p",
        project_slug,
        "-c",
        "1.0",
        "-m",
        "0.5",
        "--port",
        str(local_port),
    ]
    if runtime_id != -1:
        command.append("-r")
        command.append(str(runtime_id))
    if skip_tls_verification:
        command.append("--insecure")
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
