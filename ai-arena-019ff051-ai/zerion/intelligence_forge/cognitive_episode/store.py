"""
Durable Cognitive Episode Store with SQLite WAL Persistence & Resume
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
from zerion.intelligence_forge.cognitive_episode.episode import CognitiveEpisode, EpisodeLifecycleState


class CognitiveEpisodeStore:
    def __init__(self, db_path: Optional[str] = "data/cognitive_episodes.db"):
        self.db_path = db_path
        self._episodes: Dict[str, CognitiveEpisode] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cognitive_episodes (
                    episode_id TEXT PRIMARY KEY,
                    objective TEXT,
                    status TEXT,
                    data_json TEXT,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def save_episode(self, episode: CognitiveEpisode):
        self._episodes[episode.episode_id] = episode
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO cognitive_episodes VALUES (?, ?, ?, ?, ?)",
                (episode.episode_id, episode.objective, episode.status.value, json.dumps(episode.to_dict()), episode.updated_at)
            )
            conn.commit()
            conn.close()

    def get_episode(self, episode_id: str) -> Optional[CognitiveEpisode]:
        return self._episodes.get(episode_id)

    def list_episodes(self, limit: int = 20) -> List[CognitiveEpisode]:
        return sorted(self._episodes.values(), key=lambda e: e.updated_at, reverse=True)[:limit]

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute("SELECT data_json FROM cognitive_episodes").fetchall():
                ep = CognitiveEpisode.from_dict(json.loads(row[0]))
                self._episodes[ep.episode_id] = ep
            conn.close()
        except Exception:
            pass
