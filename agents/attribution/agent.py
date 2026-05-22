"""attribution agent — see docs/architecture.md"""
from dataclasses import dataclass
from typing import Any


@dataclass
class AttributionInput:
    docket_id: str


@dataclass
class AttributionOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any]


class AttributionAgent:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def run(self, inputs: AttributionInput) -> AttributionOutput:
        raise NotImplementedError
