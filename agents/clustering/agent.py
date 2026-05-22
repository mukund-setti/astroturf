"""clustering agent — see docs/architecture.md"""
from dataclasses import dataclass
from typing import Any


@dataclass
class ClusteringInput:
    docket_id: str


@dataclass
class ClusteringOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any]


class ClusteringAgent:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def run(self, inputs: ClusteringInput) -> ClusteringOutput:
        raise NotImplementedError
