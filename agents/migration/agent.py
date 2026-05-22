"""migration agent — see docs/architecture.md"""
from dataclasses import dataclass
from typing import Any


@dataclass
class MigrationInput:
    docket_id: str


@dataclass
class MigrationOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any]


class MigrationAgent:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def run(self, inputs: MigrationInput) -> MigrationOutput:
        raise NotImplementedError
