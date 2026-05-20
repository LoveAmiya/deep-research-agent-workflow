"""Agent interfaces for DeepResearchAgent."""

from .base_agent import AgentContext, AgentResult, BaseAgent
from .blue_agent import BlueAgent
from .critic_agent import CriticAgent
from .planner_agent import PlannerAgent
from .reader_agent import ReaderAgent
from .red_agent import RedAgent
from .red_blue_loop import RedBlueLoopConfig, RedBlueLoopResult, RedBlueLoopRunner, RedBlueRoundResult
from .searcher_agent import SearcherAgent
from .writer_agent import WriterAgent

__all__ = [
    "AgentContext",
    "AgentResult",
    "BaseAgent",
    "BlueAgent",
    "CriticAgent",
    "PlannerAgent",
    "RedAgent",
    "RedBlueLoopConfig",
    "RedBlueLoopResult",
    "RedBlueLoopRunner",
    "RedBlueRoundResult",
    "ReaderAgent",
    "SearcherAgent",
    "WriterAgent",
]
