from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AgentContext:
    task_id: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    agent_name: str
    success: bool
    output: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BaseAgent:
    name: str
    role: str

    def run(self, context: AgentContext) -> AgentResult:
        raise NotImplementedError("BaseAgent.run must be implemented by concrete agents.")
