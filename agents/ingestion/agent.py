"""ingestion agent — see docs/architecture.md"""
from dataclasses import dataclass
from typing import Any


@dataclass
class IngestionInput:
    docket_id: str


@dataclass
class IngestionOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any]


class IngestionAgent:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def run(self, inputs: IngestionInput) -> IngestionOutput:
        raise NotImplementedError
