"""
Unit tests for Evidence Engine and Claims
"""

import os
import shutil
import tempfile
import unittest
from zerion.evidence.claim import Claim, EvidenceItem, EpistemicLevel, VerificationMethod
from zerion.evidence.verifier import ClaimVerifier
from zerion.evidence.engine import EvidenceEngine


class TestEvidence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "evidence.db")
        self.engine = EvidenceEngine(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_epistemic_evidence_support_and_contradiction(self):
        evi1 = EvidenceItem(
            source="benchmark_run_1",
            verification_method=VerificationMethod.EMPIRICAL_TEST,
            confidence_weight=0.9
        )
        evi2 = EvidenceItem(
            source="benchmark_run_2",
            verification_method=VerificationMethod.EMPIRICAL_TEST,
            confidence_weight=0.95
        )

        claim = self.engine.record_claim(
            statement="Sorting algorithm runs in O(N log N)",
            supporting_evidence=[evi1, evi2]
        )
        self.assertEqual(claim.epistemic_level, EpistemicLevel.KNOWN)
        self.assertGreaterEqual(claim.confidence, 0.9)

        # Introduce contradiction
        contra_evi = EvidenceItem(
            source="fuzz_test_worst_case",
            verification_method=VerificationMethod.EMPIRICAL_TEST,
            confidence_weight=0.95
        )
        self.engine.attach_evidence_to_claim(claim.id, contra_evi, contradicts=True)

        updated_claim = self.engine._claims[claim.id]
        self.assertEqual(updated_claim.epistemic_level, EpistemicLevel.UNCERTAIN)

    def test_i_do_not_know_response(self):
        query_res = self.engine.query_belief("Unknown quantum gravity constant")
        self.assertEqual(query_res["status"], "UNKNOWN")
        self.assertIn("I don't know", query_res["answer"])


if __name__ == "__main__":
    unittest.main()
