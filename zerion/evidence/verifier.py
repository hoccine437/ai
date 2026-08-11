"""
Evidence Verification and Epistemic Level Re-evaluation
"""

from typing import List, Tuple
from zerion.evidence.claim import Claim, EvidenceItem, EpistemicLevel


class ClaimVerifier:
    def __init__(self):
        pass

    def evaluate_claim(self, claim: Claim, evidence_items: List[EvidenceItem]) -> Tuple[EpistemicLevel, float]:
        """
        Recomputes epistemic level and confidence based on supporting vs contradicting evidence.
        """
        supporting = [e for e in evidence_items if e.id in claim.supporting_evidence_ids]
        contradicting = [e for e in evidence_items if e.id in claim.contradicting_evidence_ids]

        if not supporting and not contradicting:
            return EpistemicLevel.UNKNOWN, 0.0

        support_weight = sum(e.confidence_weight for e in supporting)
        contra_weight = sum(e.confidence_weight for e in contradicting)

        total_weight = support_weight + contra_weight
        if total_weight == 0:
            return EpistemicLevel.UNKNOWN, 0.0

        # Normalized net support (0.0 to 1.0)
        net_ratio = max(0.0, (support_weight - contra_weight) / total_weight)

        # Scale by sample size confidence factor: min(1.0, len(supporting) / 2.0)
        sample_factor = min(1.0, len(supporting) / 2.0) if supporting else 0.0
        final_conf = round(net_ratio * sample_factor, 4)

        if contradicting and contra_weight >= support_weight:
            level = EpistemicLevel.UNCERTAIN
            final_conf = 0.2
        elif final_conf >= 0.90 and len(supporting) >= 2:
            level = EpistemicLevel.KNOWN
        elif final_conf >= 0.70:
            level = EpistemicLevel.SUPPORTED
        elif final_conf >= 0.45:
            level = EpistemicLevel.PROBABLE
        elif final_conf >= 0.20:
            level = EpistemicLevel.UNCERTAIN
        else:
            level = EpistemicLevel.UNKNOWN

        return level, final_conf
