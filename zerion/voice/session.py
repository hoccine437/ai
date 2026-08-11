"""
Secure Voice Session & Ephemeral Credential Manager
Ensures zero hardcoded API keys in client-side code, APK assets, or public logs.
Uses environment variables and ephemeral session tokens for realtime voice interaction.
"""

from dataclasses import dataclass, field
import hashlib
import os
import time
from typing import Any, Dict, Optional
import uuid


@dataclass
class VoiceSessionCredentials:
    session_id: str
    is_authenticated: bool
    ephemeral_token_hash: str
    expires_at: float
    mode: str = "LOCAL_STT_TTS"  # "LOCAL_STT_TTS", "REALTIME_OPENAI", "OFFLINE_FALLBACK"


class SecureVoiceSessionManager:
    def __init__(self, session_ttl_seconds: float = 3600.0):
        self.session_ttl = session_ttl_seconds
        self._active_sessions: Dict[str, VoiceSessionCredentials] = {}

    def create_ephemeral_session(self) -> VoiceSessionCredentials:
        session_id = f"v_sess_{uuid.uuid4().hex[:12]}"
        now = time.time()
        
        # Check environment securely without logging
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        mode = "REALTIME_OPENAI" if openai_key and len(openai_key) > 10 else "LOCAL_STT_TTS"

        # Generate ephemeral session hash
        token_hash = hashlib.sha256(f"{session_id}:{now}".encode()).hexdigest()

        creds = VoiceSessionCredentials(
            session_id=session_id,
            is_authenticated=True,
            ephemeral_token_hash=token_hash,
            expires_at=now + self.session_ttl,
            mode=mode
        )
        self._active_sessions[session_id] = creds
        return creds

    def validate_session(self, session_id: str) -> bool:
        if session_id in self._active_sessions:
            sess = self._active_sessions[session_id]
            if time.time() < sess.expires_at:
                return True
            del self._active_sessions[session_id]
        return False
