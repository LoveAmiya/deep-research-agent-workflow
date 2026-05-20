from agents.base_agent import BaseAgent
from core.schema import ResearchPlan, ResearchQuestion


class PlannerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="PlannerAgent", role="planner")

    def run(self, question: ResearchQuestion) -> ResearchPlan:
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
        return ResearchPlan(
            question=base_question,
            sub_questions=sub_questions,
            search_queries=search_queries,
            expected_sections=expected_sections,
            question_id=question.question_id,
        )
