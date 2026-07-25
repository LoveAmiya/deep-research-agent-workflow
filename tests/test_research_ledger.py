import unittest

from memory.research_ledger import ResearchLedger


class TestResearchLedger(unittest.TestCase):
    def test_publishing_same_artifact_type_appends_a_new_version(self) -> None:
        ledger = ResearchLedger(run_id="run-1")

        first = ledger.publish(
            artifact_type="research_brief",
            producer_agent="PlannerAgent",
            task_id="planner_task",
            content={"question": "What affects adoption?"},
            summary="研究简报已生成。",
        )
        second = ledger.publish(
            artifact_type="research_brief",
            producer_agent="PlannerAgent",
            task_id="planner_task",
            content={"question": "What affects adoption?", "revision": 2},
            summary="研究简报已修订。",
        )

        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)
        self.assertNotEqual(first.artifact_id, second.artifact_id)
        self.assertEqual(ledger.latest("research_brief").artifact_id, second.artifact_id)
        self.assertEqual(len(ledger.list_artifacts("research_brief")), 2)

    def test_handoff_records_consumption_and_revision_request(self) -> None:
        ledger = ResearchLedger(run_id="run-2")
        brief = ledger.publish(
            artifact_type="research_brief",
            producer_agent="PlannerAgent",
            task_id="planner_task",
            content={"question": "Q"},
            summary="研究简报。",
        )

        consumed = ledger.acknowledge(
            sender_agent="PlannerAgent",
            recipient_agent="SearcherAgent",
            artifact_ids=[brief.artifact_id],
            reason="按研究简报发现候选资料。",
        )
        revision = ledger.request_revision(
            sender_agent="CriticAgent",
            recipient_agent="WriterAgent",
            artifact_ids=[brief.artifact_id],
            reason="研究范围需要收窄。",
        )

        self.assertEqual(consumed.status, "ACKNOWLEDGED")
        self.assertEqual(revision.status, "REVISION_REQUESTED")
        self.assertEqual(len(ledger.list_handoffs()), 2)

    def test_round_trip_preserves_artifacts_and_handoffs(self) -> None:
        ledger = ResearchLedger(run_id="run-3")
        finding = ledger.publish(
            artifact_type="approved_findings",
            producer_agent="ReaderAgent",
            task_id="reader_task",
            content=[{"text": "Evidence-backed finding"}],
            summary="已提取 1 条可用发现。",
            dependencies=["artifact-brief"],
            status="APPROVED",
        )
        ledger.acknowledge(
            sender_agent="ReaderAgent",
            recipient_agent="WriterAgent",
            artifact_ids=[finding.artifact_id],
            action="consume",
            reason="仅使用已批准发现撰写初稿。",
        )

        restored = ResearchLedger.from_dict(ledger.to_dict())

        self.assertEqual(restored.run_id, "run-3")
        self.assertEqual(restored.latest("approved_findings").dependencies, ["artifact-brief"])
        self.assertEqual(restored.list_handoffs()[0].recipient_agent, "WriterAgent")


if __name__ == "__main__":
    unittest.main()
