from dataclasses import dataclass


@dataclass
class BaseAgent:
    name: str
    role: str

    def run(self, *args, **kwargs):
        raise NotImplementedError("BaseAgent.run is a Phase 0 placeholder.")
