"""embedding agent — see docs/architecture.md"""

from dataclasses import dataclass
from typing import Any


@dataclass
class EmbeddingInput:
    docket_id: str


@dataclass
class EmbeddingOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any]


class EmbeddingAgent:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def run(self, inputs: EmbeddingInput) -> EmbeddingOutput:
        raise NotImplementedError
