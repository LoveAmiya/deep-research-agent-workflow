from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
from core.schema import ResearchPlan, ResearchQuestion


class PlannerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="PlannerAgent", role="planner")

    def run(self, context: AgentContext) -> AgentResult:
        question = context.inputs["question"]
        if not isinstance(question, ResearchQuestion):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="PlannerAgent expected a ResearchQuestion in context.inputs['question'].",
                metadata={"role": self.role, "handoff": "question -> plan"},
            )

        base_question = question.question.strip()
        sub_questions = [
            f"What is the current enterprise context for {base_question}?",
            f"What benefits and constraints shape decisions about {base_question}?",
            f"What practical adoption considerations matter most for {base_question}?",
        ]
        search_queries = [
            base_question,
            f"{base_question} enterprise benefits and risks",
            f"{base_question} enterprise adoption challenges",
        ]
        expected_sections = ["Background", "Key Findings", "Conclusion"]
        plan = ResearchPlan(
            question=base_question,
            sub_questions=sub_questions,
            search_queries=search_queries,
            expected_sections=expected_sections,
            question_id=question.question_id,
        )
        metadata = {
            "role": self.role,
            "handoff": "question -> plan",
            "task_id": context.task_id,
            "used_llm": False,
            "llm_error": None,
            "fallback_used": False,
        }
        if context.llm_client is not None:
            try:
                prompt = load_prompt("planner")
                context.llm_client.generate(
                    [
                        LLMMessage(role="system", content=prompt),
                        LLMMessage(role="user", content=f"Research question: {base_question}"),
                    ]
                )
                metadata["used_llm"] = True
                metadata["fallback_used"] = True
            except Exception as exc:
                metadata["llm_error"] = str(exc)
                metadata["fallback_used"] = True
        self._write_memory(context, plan, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=plan,
            metadata=metadata,
        )

    def _write_memory(self, context: AgentContext, plan: ResearchPlan, metadata: dict) -> None:
        if context.memory is None:
            return
        try:
            context.memory.add_record(
                item_type="plan",
                content=plan,
                source_agent=self.name,
                task_id=context.task_id,
                metadata=metadata,
            )
        except Exception as exc:
            metadata["memory_error"] = str(exc)
