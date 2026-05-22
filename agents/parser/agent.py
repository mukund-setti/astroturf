"""parser agent — see docs/architecture.md"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ParserInput:
    docket_id: str


@dataclass
class ParserOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any]


class ParserAgent:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def run(self, inputs: ParserInput) -> ParserOutput:
        raise NotImplementedError
