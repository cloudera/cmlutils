from dataclasses import dataclass
from enum import Enum


class ValidationResponseStatus(Enum):
    PASSED = 1
    FAILED = 2
    SKIPPED = 3


@dataclass
class ValidationResponse:
    validation_name: str
    validation_msg: str
    validation_status: ValidationResponseStatus
