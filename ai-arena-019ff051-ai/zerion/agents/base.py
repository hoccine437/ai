"""Base Agent class — all 21 specialized agents inherit from this."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class AgentResult:
    """Structured output from an agent execution."""
    agent_id: str
    success: bool
    output: str
    confidence: float = 0.5
    tools_used: List[str] = field(default_factory=list)
    reasoning: str = ""
    evidence: List[str] = field(default_factory=list)
    uncertainty: str = ""
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class Agent:
    """Base class for a specialized ZERION agent.

    Each agent is a focused intelligence with:
    - A clear domain of expertise
    - Specific tools it can use
    - Reasoning logic for its domain
    - Self-verification capability
    - Ability to report uncertainty
    """

    def __init__(self, agent_id: str, name: str, domain: str,
                 description: str, specializations: List[str],
                 tools_allowed: List[str]):
        self.agent_id = agent_id
        self.name = name
        self.domain = domain
        self.description = description
        self.specializations = specializations
        self.tools_allowed = tools_allowed
        self._execution_count = 0
        self._success_count = 0
        self._failure_count = 0

    def can_handle(self, task_description: str) -> float:
        """Return confidence [0.0, 1.0] that this agent can handle the task.
        Override in subclasses for domain-specific matching."""
        task_lower = (task_description or "").lower()
        score = 0.0
        for spec in self.specializations:
            if spec.lower() in task_lower:
                score = max(score, 0.8)
        # Domain keyword matching
        domain_words = set(self.domain.lower().split() + self.name.lower().split())
        task_words = set(task_lower.split())
        overlap = domain_words & task_words
        if overlap:
            score = max(score, min(0.6, 0.3 * len(overlap)))
        return score

    async def execute(self, task: str, context: Dict[str, Any],
                      tool_executor: Any = None) -> AgentResult:
        """Execute a task. Override in subclasses.
        Args:
            task: The task description
            context: Additional context (conversation history, memory, etc.)
            tool_executor: Callable to execute tools: async (name, arg) -> result
        Returns:
            AgentResult with the agent's output
        """
        t0 = time.perf_counter()
        result = self._execute_impl(task, context, tool_executor)
        latency = (time.perf_counter() - t0) * 1000.0

        self._execution_count += 1
        if result.success:
            self._success_count += 1
        else:
            self._failure_count += 1
        result.latency_ms = latency
        return result

    def _execute_impl(self, task: str, context: Dict[str, Any],
                      tool_executor: Any = None) -> AgentResult:
        """Override in subclasses with the actual agent logic."""
        return AgentResult(
            agent_id=self.agent_id, success=False,
            output=f"Agent {self.name} not implemented",
            reasoning="Base class — override _execute_impl")

    def success_rate(self) -> float:
        if self._execution_count == 0:
            return 0.0
        return self._success_count / self._execution_count

    def describe(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "domain": self.domain,
            "description": self.description,
            "specializations": self.specializations,
            "tools_allowed": self.tools_allowed,
            "executions": self._execution_count,
            "success_rate": self.success_rate(),
        }
