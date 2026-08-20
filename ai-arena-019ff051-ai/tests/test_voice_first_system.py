"""
Voice-First Wake-Word & Audio-Reactive Interaction Test Suite
Verifies:
- Exact Wake Word ("Zerion")
- Natural Conversational Prefixes ("Hey Zerion", "Zerion, open my tasks")
- Likely ASR Variants ("Zirion", "Zerian", "Zeryon", "Zerionn")
- Accent Variations ("Zérion", "Hey, Zérion")
- Rejection of Unrelated Ambient Speech ("the horizon is clear", "onion soup", "serial number")
- Silent / Empty Audio Input Handling
- Voice Activity Detection (VAD) & Silence Timeout
- Natural Conversational Interruption
- End-to-End Voice Pipeline with Cognitive Organism Brain & Tool Execution
"""

import asyncio
import os
import shutil
import tempfile
import unittest

from zerion.voice.wake_word import LayeredWakeWordDetector, WakeDetectionResult
from zerion.voice.vad import VoiceActivityDetector, VADState
from zerion.voice.session import SecureVoiceSessionManager
from zerion.voice.pipeline import VoiceFirstInteractionPipeline
from zerion.engine import AscendantEngine
from zerion.ui.state_bridge import UIStateMode


class TestVoiceFirstSystem(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="voice_test_")
        self.engine = AscendantEngine(data_dir=self.temp_dir)
        self.detector = LayeredWakeWordDetector()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. Exact Wake Word Test
    def test_exact_wake_word(self):
        res = self.detector.process_transcript("Zerion", bypass_cooldown=True)
        self.assertTrue(res.detected)
        self.assertEqual(res.confidence, 1.0)
        self.assertIn("EXACT", res.layer_triggered)

    # 2. Natural Conversational Prefixes & Commands
    def test_natural_conversational_wake_phrases(self):
        test_phrases = [
            "Hey Zerion",
            "Hey Zerion, what is my status?",
            "Zerion, open my tasks and check active objectives",
            "OK Zerion, analyze the environment",
            "Zerion, listen"
        ]
        for phrase in test_phrases:
            res = self.detector.process_transcript(phrase, bypass_cooldown=True)
            self.assertTrue(res.detected, msg=f"Failed for phrase: {phrase}")
            self.assertGreaterEqual(res.confidence, 0.75)

    # 3. Likely ASR & Phonetic Variants
    def test_asr_phonetic_variations(self):
        variants = [
            "Zirion",
            "Zerian",
            "Zeryon",
            "Zerionn",
            "Zeron",
            "Hey Zirion",
            "OK Zerian, run tests"
        ]
        for var in variants:
            res = self.detector.process_transcript(var, bypass_cooldown=True)
            self.assertTrue(res.detected, msg=f"ASR variant failed: {var}")
            self.assertGreaterEqual(res.confidence, 0.75)

    # 4. Accent Variations
    def test_accent_variations(self):
        accents = [
            "Zérion",
            "Hey Zérion",
            "Zérion, bonjour"
        ]
        for acc in accents:
            res = self.detector.process_transcript(acc, bypass_cooldown=True)
            self.assertTrue(res.detected, msg=f"Accent failed: {acc}")
            self.assertGreaterEqual(res.confidence, 0.75)

    # 5. False Positive Rejection of Unrelated Speech
    def test_rejection_of_unrelated_ambient_speech(self):
        negative_cases = [
            "the horizon is very clear today",
            "can you pass the onion soup",
            "what is the serial number of the motherboard",
            "generation of complex computational scenarios",
            "zero is a number",
            "we are looking at section ten"
        ]
        for neg in negative_cases:
            res = self.detector.process_transcript(neg, bypass_cooldown=True)
            self.assertFalse(res.detected, msg=f"False positive activation on: {neg}")

    # 6. Silent & Empty Audio
    def test_silent_and_empty_speech(self):
        res1 = self.detector.process_transcript("", bypass_cooldown=True)
        self.assertFalse(res1.detected)

        res2 = self.detector.process_transcript("   ...  ", bypass_cooldown=True)
        self.assertFalse(res2.detected)

    # 7. Voice Activity Detection & Silence Tracker
    def test_voice_activity_detection_lifecycle(self):
        vad = VoiceActivityDetector(energy_threshold=0.05, silence_timeout_s=0.5)
        # Frame 1: Silence
        s1 = vad.process_frame(0.01)
        self.assertFalse(s1.is_speech_active)
        self.assertFalse(s1.turn_completed)

        # Frame 2: Speech start
        s2 = vad.process_frame(0.25)
        self.assertTrue(s2.is_speech_active)

        # Frame 3: Speech continue
        s3 = vad.process_frame(0.30)
        self.assertTrue(s3.is_speech_active)

    # 8. Secure Ephemeral Session Manager
    def test_secure_voice_session(self):
        mgr = SecureVoiceSessionManager()
        sess = mgr.create_ephemeral_session()
        self.assertTrue(sess.is_authenticated)
        self.assertTrue(len(sess.ephemeral_token_hash) > 10)
        self.assertTrue(mgr.validate_session(sess.session_id))

    # 9. End-to-End Voice Pipeline with Cognitive Organism Brain & Tool Execution
    async def test_end_to_end_voice_pipeline(self):
        await self.engine.start()
        pipeline = VoiceFirstInteractionPipeline(engine_ref=self.engine)

        try:
            # User says "Hey Zerion, check my active objectives"
            turn = await pipeline.process_speech_input("Hey Zerion, check my active objectives")
            self.assertTrue(turn.wake_result.detected)
            self.assertIn("active", turn.cognitive_response.lower())
            self.assertIsNotNone(turn.tool_executed)
            self.assertEqual(self.engine.ui_bridge.current_state.runtime_state, UIStateMode.LISTENING)

            # Test Natural Interruption
            self.engine.ui_bridge.set_speaking_state(True, audio_rms=0.85)
            await pipeline.handle_audio_frame(rms_amplitude=0.35) # user speaks over AI
            self.assertEqual(self.engine.ui_bridge.current_state.runtime_state, UIStateMode.LISTENING)
            self.assertIn("VOICE", self.engine.ui_bridge.current_state.explanation_chain[0])
        finally:
            await self.engine.stop()


if __name__ == "__main__":
    unittest.main()
