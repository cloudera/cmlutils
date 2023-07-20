import os
import shutil
from datetime import datetime, timedelta
from string import Template

from cmlutils.constants import ApiV1Endpoints
from cmlutils.utils import call_api_v1

_apiv2_key = None


class BaseWorkspaceInteractor(object):
    def __init__(
        self,
        host: str,
        username: str,
        project_name: str,
        api_key: str,
        ca_path: str,
        project_slug: str,
    ) -> None:
        self.host = host
        self.username = username
        self.project_name = project_name
        self.api_key = api_key
        self.ca_path = ca_path
        self.project_slug = project_slug

    @property
    def apiv2_key(self) -> str:
        global _apiv2_key
        if _apiv2_key is not None:
            return _apiv2_key
        endpoint = Template(ApiV1Endpoints.API_KEY.value).substitute(
            username=self.username
        )
        json_data = {
            "expiryDate": (datetime.now() + timedelta(weeks=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        }
        response = call_api_v1(
            host=self.host,
            endpoint=endpoint,
            method="POST",
            api_key=self.api_key,
            json_data=json_data,
            ca_path=self.ca_path,
        )
        response_dict = response.json()
        _apiv2_key = response_dict["apiKey"]
        return _apiv2_key

    def remove_cdswctl_dir(self, file_path: str):
        if os.path.exists(file_path):
            dirname = os.path.dirname(file_path)
            shutil.rmtree(dirname, ignore_errors=True)
