from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.schema import ResearchPlan, SearchResult
from tools.search_tool import MockSearchTool


class SearcherAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="SearcherAgent", role="searcher")

    def run(self, context: AgentContext) -> AgentResult:
        plan = context.inputs["plan"]
        if not isinstance(plan, ResearchPlan):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="SearcherAgent expected a ResearchPlan in context.inputs['plan'].",
                metadata={"role": self.role, "handoff": "plan -> search_results"},
            )

        metadata = self._base_metadata(context)
        results = self._search_with_tool_or_fallback(plan, context, metadata)
        metadata["result_count"] = len(results)
        self._write_memory(context, results, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=results,
            metadata=metadata,
        )

    def _search_with_tool_or_fallback(
        self,
        plan: ResearchPlan,
        context: AgentContext,
        metadata: dict,
    ) -> List[SearchResult]:
        search_provider_registry = context.search_provider_registry or context.inputs.get(
            "search_provider_registry"
        )
        if search_provider_registry is not None:
            return self._search_with_provider_registry(
                plan,
                context,
                metadata,
                search_provider_registry,
            )

        search_tool = context.inputs.get("search_tool")
        max_results = int(context.inputs.get("max_results", 5))
        if search_tool is None:
            return self._deterministic_results(plan)

        provider = getattr(search_tool, "provider", search_tool.__class__.__name__)
        metadata["search_provider"] = provider
        try:
            results: List[SearchResult] = []
            for query in plan.search_queries:
                results.extend(search_tool.search(query, max_results=max_results))
            if not results:
                raise ValueError("search tool returned no results")
            metadata["used_real_search"] = provider != "mock"
            return results[:max_results]
        except Exception as exc:
            metadata["used_real_search"] = False
            metadata["fallback_used"] = True
            metadata["search_error"] = str(exc)
            fallback_tool = MockSearchTool()
            fallback_results: List[SearchResult] = []
            for query in plan.search_queries:
                fallback_results.extend(fallback_tool.search(query, max_results=1))
            return fallback_results or self._deterministic_results(plan)

    def _search_with_provider_registry(
        self,
        plan: ResearchPlan,
        context: AgentContext,
        metadata: dict,
        search_provider_registry,
    ) -> List[SearchResult]:
        max_results = int(context.inputs.get("max_results", 5))
        provider_order = context.inputs.get("search_provider_order") or ["mock"]
        real_search_enabled = bool(context.inputs.get("real_search_enabled", False))
        metadata["real_search_enabled"] = real_search_enabled
        metadata["search_provider_order"] = list(provider_order)

        results: List[SearchResult] = []
        attempted_providers: List[str] = []
        provider_errors: dict = {}
        selected_provider = None
        fallback_used = False

        for query in plan.search_queries:
            response = search_provider_registry.search_with_fallback(
                query=query,
                provider_order=provider_order,
                max_results=max_results,
            )
            response_metadata = response.metadata or {}
            for provider_name in response_metadata.get("attempted_providers", []):
                if provider_name not in attempted_providers:
                    attempted_providers.append(provider_name)
            provider_errors.update(response_metadata.get("provider_errors", {}))
            fallback_used = fallback_used or bool(response_metadata.get("fallback_used"))
            selected_provider = selected_provider or response_metadata.get("selected_provider")

            if response.success:
                for item in response.results:
                    results.append(
                        SearchResult(
                            title=item.title,
                            url=item.url,
                            snippet=item.snippet,
                            source=item.provider,
                        )
                    )
            else:
                provider_errors[query] = response.error or "search failed"

        if not results:
            metadata["fallback_used"] = True
            metadata["search_error"] = "provider registry returned no usable results"
            fallback_tool = MockSearchTool()
            for query in plan.search_queries:
                results.extend(fallback_tool.search(query, max_results=1))
            selected_provider = "mock"
            fallback_used = True

        selected_provider = selected_provider or (results[0].source if results else "mock")
        metadata["search_provider"] = selected_provider
        metadata["attempted_providers"] = attempted_providers or list(provider_order)
        metadata["provider_errors"] = provider_errors
        metadata["fallback_used"] = fallback_used or metadata.get("fallback_used", False)
        metadata["used_real_search"] = selected_provider != "mock"
        if provider_errors and metadata["search_error"] is None:
            metadata["search_error"] = "; ".join(
                f"{provider}: {error}" for provider, error in provider_errors.items()
            )
        return results[:max_results]

    def _deterministic_results(self, plan: ResearchPlan) -> List[SearchResult]:
        dimensions = [
            ("成本与基础设施", "企业需要同时评估模型许可、推理算力、部署维护和规模扩张带来的总拥有成本。"),
            ("治理与合规", "数据边界、许可证义务、模型责任和审计能力会影响开源大语言模型能否进入正式业务流程。"),
            ("系统集成", "与现有数据平台、身份权限、业务应用和运维体系的集成工作量会直接影响落地周期。"),
            ("能力与可控性", "模型在目标任务上的效果、可定制程度、版本稳定性和输出可控性需要结合具体场景验证。"),
            ("人才与运营", "企业是否具备模型评测、微调、部署、安全响应和持续监控能力会影响长期运营可行性。"),
            ("业务价值", "采用决策需要把技术指标转化为效率、质量、风险或收入等可衡量的业务结果。"),
        ]
        selected_dimensions = dimensions[:1] if len(plan.search_queries) == 1 else dimensions
        results: List[SearchResult] = []
        for index, (dimension, snippet) in enumerate(selected_dimensions, start=1):
            results.append(
                SearchResult(
                    title=f"{dimension}分析线索（本地演示）",
                    url=f"mock://source/{index}",
                    snippet=snippet,
                    source="mock",
                )
            )
        return results

    def _base_metadata(self, context: AgentContext) -> dict:
        metadata = {
            "role": self.role,
            "handoff": "plan -> search_results",
            "task_id": context.task_id,
            "result_count": 0,
            "used_real_search": False,
            "search_provider": "deterministic_mock",
            "fallback_used": False,
            "search_error": None,
            "attempted_providers": [],
            "provider_errors": {},
            "real_search_enabled": False,
        }
        return metadata

    def _write_memory(self, context: AgentContext, results: List[SearchResult], metadata: dict) -> None:
        if context.memory is None:
            return
        try:
            context.memory.add_record(
                item_type="search_results",
                content=results,
                source_agent=self.name,
                task_id=context.task_id,
                metadata=metadata,
            )
        except Exception as exc:
            metadata["memory_error"] = str(exc)
