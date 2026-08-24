"""
Reality Experiment Engine - Scientific Hypothesis Testing Loop
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, Optional
from zerion.experiments.design import ExperimentDesign
from zerion.experiments.sandbox import ExecutionSandbox, SandboxResult
from zerion.evidence.engine import EvidenceEngine
from zerion.evidence.claim import EvidenceItem, VerificationMethod
from zerion.world.graph import WorldModel


@dataclass
class ExperimentOutcome:
    experiment_id: str
    hypothesis_statement: str
    supported: bool
    observed_value: Any
    expected_value: Any
    sandbox_result: SandboxResult
    evidence_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class ExperimentEngine:
    def __init__(self, sandbox: Optional[ExecutionSandbox] = None, evidence_engine: Optional[EvidenceEngine] = None):
        self.sandbox = sandbox or ExecutionSandbox()
        self.evidence_engine = evidence_engine or EvidenceEngine()

    async def run_experiment(
        self,
        design: ExperimentDesign,
        world_model: Optional[WorldModel] = None
    ) -> ExperimentOutcome:
        """
        Full scientific loop:
        1. Run designed experiment in sandbox
        2. Sample reality observation
        3. Compare expected vs observed
        4. Generate verified EvidenceItem
        5. Update World Model and Evidence ledger
        """
        # Execute code in sandbox
        sandbox_res = await self.sandbox.run_python_code(
            code=design.execution_code,
            timeout_seconds=design.timeout_seconds
        )

        observed_val = sandbox_res.stdout if sandbox_res.success else sandbox_res.stderr

        # Check hypothesis confirmation
        supported = False
        if sandbox_res.success:
            if design.expected_outcome is not None:
                supported = str(design.expected_outcome).strip() in observed_val
            else:
                supported = True

        # Generate Evidence Item
        evidence_item = EvidenceItem(
            source=f"sandbox_experiment:{design.id}",
            verification_method=VerificationMethod.SANDBOX_EXPERIMENT,
            data={
                "stdout": sandbox_res.stdout,
                "stderr": sandbox_res.stderr,
                "return_code": sandbox_res.return_code,
                "duration_ms": sandbox_res.duration_ms
            },
            confidence_weight=0.95 if supported else 0.85
        )
        evi_id = self.evidence_engine.add_evidence(evidence_item)

        # Update World Model causal hypothesis if linked
        if world_model and design.hypothesis_id:
            causal_hyp = world_model.get_causal_hypothesis(design.hypothesis_id)
            if causal_hyp:
                causal_hyp.record_falsification_result(falsified=(not supported), evidence_id=evi_id)
                world_model._persist_causal(causal_hyp)

        return ExperimentOutcome(
            experiment_id=design.id,
            hypothesis_statement=design.hypothesis_statement,
            supported=supported,
            observed_value=observed_val,
            expected_value=design.expected_outcome,
            sandbox_result=sandbox_res,
            evidence_id=evi_id
        )
