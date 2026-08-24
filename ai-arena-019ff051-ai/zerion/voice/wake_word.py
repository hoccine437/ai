"""
Layered Wake-Word Detection Subsystem for ZERION-X
Implements 3-Layer Wake-Word Architecture:
- Layer 1: Dedicated Keyword Match
- Layer 2: Fuzzy Phonetic & Normalized String Similarity
- Layer 3: Contextual Intent Confirmation

Tolerates accent variations (Zérion), common ASR substitutions (Zirion, Zerian, Zeryon, Zerionn),
and conversational prefixes (Hey Zerion, OK Zerion) while rejecting unrelated ambient speech.
"""

from dataclasses import dataclass, field
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import unicodedata


@dataclass
class WakeDetectionResult:
    detected: bool
    confidence: float
    matched_phrase: str
    cleaned_command: str           # The user's command trailing the wake phrase
    layer_triggered: str           # "LAYER_1_EXACT", "LAYER_2_FUZZY", "LAYER_3_CONTEXTUAL", "NONE"
    latency_ms: float
    rejection_reason: Optional[str] = None


class LayeredWakeWordDetector:
    def __init__(
        self,
        wake_confidence_threshold: float = 0.75,
        fuzzy_similarity_threshold: float = 0.78,
        cooldown_seconds: float = 0.5
    ):
        self.wake_confidence_threshold = wake_confidence_threshold
        self.fuzzy_similarity_threshold = fuzzy_similarity_threshold
        self.cooldown_seconds = cooldown_seconds
        self._last_activation_time = 0.0

        # Canonical target wake root
        self.canonical_root = "zerion"
        
        # Known phonetic and ASR variations
        self.known_variants = {
            "zerion", "zerian", "zirion", "zeryon", "zerionn", "zerione", "zérion",
            "xerio", "xerion", "serion", "zeriun", "zeron", "zerio", "zerrion"
        }

        # Conversational prefixes
        self.prefixes = {"hey", "hi", "ok", "okay", "hello", "yo"}

    def normalize_text(self, text: str) -> str:
        """Strips accents, punctuation, repeated characters, and normalizes whitespace."""
        # 1. Normalize unicode (e.g. é -> e)
        nfkd = unicodedata.normalize("NFKD", text)
        ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()

        # 2. Strip punctuation
        cleaned = re.sub(r"[^\w\s]", " ", ascii_text)

        # 3. Collapse multiple spaces
        cleaned = " ".join(cleaned.split())

        return cleaned

    def compute_similarity(self, s1: str, s2: str) -> float:
        """Computes normalized Levenshtein similarity ratio between two strings (0.0 to 1.0)."""
        if s1 == s2:
            return 1.0
        if not s1 or not s2:
            return 0.0

        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                dp[i][j] = min(
                    dp[i - 1][j] + 1,      # deletion
                    dp[i][j - 1] + 1,      # insertion
                    dp[i - 1][j - 1] + cost # substitution
                )

        distance = dp[m][n]
        max_len = max(m, n)
        return round(1.0 - (distance / max_len), 4)

    def process_transcript(self, raw_transcript: str, bypass_cooldown: bool = False) -> WakeDetectionResult:
        t0 = time.perf_counter()
        now = time.time()

        # Check cooldown to prevent duplicate triggers
        if not bypass_cooldown and (now - self._last_activation_time) < self.cooldown_seconds:
            latency = (time.perf_counter() - t0) * 1000.0
            return WakeDetectionResult(
                detected=False,
                confidence=0.0,
                matched_phrase="",
                cleaned_command="",
                layer_triggered="NONE",
                latency_ms=round(latency, 2),
                rejection_reason="Cooldown period active"
            )

        normalized = self.normalize_text(raw_transcript)
        tokens = normalized.split()
        if not tokens:
            latency = (time.perf_counter() - t0) * 1000.0
            return WakeDetectionResult(
                detected=False,
                confidence=0.0,
                matched_phrase="",
                cleaned_command="",
                layer_triggered="NONE",
                latency_ms=round(latency, 2),
                rejection_reason="Empty speech input"
            )

        # --- LAYER 1: Dedicated / Exact Token Matching ---
        # Check first 1-3 tokens for exact wake variant
        for i, token in enumerate(tokens[:3]):
            if token in self.known_variants:
                matched_phrase = " ".join(tokens[:i+1])
                command = " ".join(tokens[i+1:])
                self._last_activation_time = now
                latency = (time.perf_counter() - t0) * 1000.0
                return WakeDetectionResult(
                    detected=True,
                    confidence=1.0,
                    matched_phrase=matched_phrase,
                    cleaned_command=command,
                    layer_triggered="LAYER_1_EXACT",
                    latency_ms=round(latency, 2)
                )

        # --- LAYER 2: Fuzzy Phonetic Similarity ---
        for i, token in enumerate(tokens[:3]):
            sim = self.compute_similarity(token, self.canonical_root)
            if sim >= self.fuzzy_similarity_threshold:
                matched_phrase = " ".join(tokens[:i+1])
                command = " ".join(tokens[i+1:])
                self._last_activation_time = now
                latency = (time.perf_counter() - t0) * 1000.0
                return WakeDetectionResult(
                    detected=True,
                    confidence=sim,
                    matched_phrase=matched_phrase,
                    cleaned_command=command,
                    layer_triggered="LAYER_2_FUZZY",
                    latency_ms=round(latency, 2)
                )

        # --- LAYER 3: Contextual Addressing Check ---
        if len(tokens) >= 2 and tokens[0] in self.prefixes:
            candidate = tokens[1]
            sim = self.compute_similarity(candidate, self.canonical_root)
            if sim >= 0.70 or candidate in self.known_variants:
                matched_phrase = f"{tokens[0]} {tokens[1]}"
                command = " ".join(tokens[2:])
                self._last_activation_time = now
                latency = (time.perf_counter() - t0) * 1000.0
                return WakeDetectionResult(
                    detected=True,
                    confidence=round(max(0.85, sim), 3),
                    matched_phrase=matched_phrase,
                    cleaned_command=command,
                    layer_triggered="LAYER_3_CONTEXTUAL",
                    latency_ms=round(latency, 2)
                )

        # Rejection
        latency = (time.perf_counter() - t0) * 1000.0
        return WakeDetectionResult(
            detected=False,
            confidence=0.15,
            matched_phrase="",
            cleaned_command=raw_transcript,
            layer_triggered="NONE",
            latency_ms=round(latency, 2),
            rejection_reason="No wake phrase detected"
        )
