"""
Meta-Prediction Engine - Pre-Execution Forecasting & Post-Execution Calibration
Forecasts strategy success, required compute, and expected failure modes prior to task solving;
calibrates strategy selection heuristics upon post-execution feedback.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class MetaPrediction:
    task_id: str
    prediction_id: str = field(default_factory=lambda: f"pred_{uuid.uuid4().hex[:8]}")
    predicted_strategy: str = ""
    predicted_compute_tier: str = "NORMAL"
    predicted_success_probability: float = 0.85
    predicted_latency_ms: float = 50.0
    likely_failure_modes: List[str] = field(default_factory=list)
    recommend_experimentation: bool = False
    recommend_external_model: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "task_id": self.task_id,
            "predicted_strategy": self.predicted_strategy,
            "predicted_compute_tier": self.predicted_compute_tier,
            "predicted_success_probability": round(self.predicted_success_probability, 3),
            "predicted_latency_ms": round(self.predicted_latency_ms, 2),
            "likely_failure_modes": self.likely_failure_modes,
            "recommend_experimentation": self.recommend_experimentation,
            "recommend_external_model": self.recommend_external_model,
            "timestamp": self.timestamp
        }


@dataclass
class MetaCalibrationRecord:
    prediction_id: str
    task_id: str
    actual_strategy_used: str
    actual_success: bool
    actual_latency_ms: float
    probability_error: float          # |P_pred - Actual|
    latency_error_ms: float           # |T_pred - T_act|
    calibration_penalty: float        # Brier single-item penalty
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "task_id": self.task_id,
            "actual_strategy_used": self.actual_strategy_used,
            "actual_success": self.actual_success,
            "actual_latency_ms": round(self.actual_latency_ms, 2),
            "probability_error": round(self.probability_error, 4),
            "latency_error_ms": round(self.latency_error_ms, 2),
            "calibration_penalty": round(self.calibration_penalty, 4),
            "timestamp": self.timestamp
        }


class MetaPredictionEngine:
    def __init__(self, db_path: Optional[str] = "data/meta_prediction.db"):
        self.db_path = db_path
        self._predictions: Dict[str, MetaPrediction] = {}
        self._calibrations: List[MetaCalibrationRecord] = []
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meta_predictions (
                    prediction_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    data_json TEXT,
                    timestamp REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meta_calibrations (
                    prediction_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    data_json TEXT,
                    timestamp REAL
                )
            """)
            conn.commit()
            conn.close()

    def generate_pre_prediction(
        self,
        task_id: str,
        task_domain: str,
        uncertainty: float,
        difficulty: float
    ) -> MetaPrediction:
        """Forecasts strategy, compute tier, and failure modes before task execution."""
        prob_success = max(0.2, min(0.98, 1.0 - (difficulty * 0.4) - (uncertainty * 0.3)))
        compute_tier = "DEEP" if difficulty > 0.7 else ("FAST" if difficulty < 0.3 else "NORMAL")
        recommend_exp = uncertainty > 0.65

        pred = MetaPrediction(
            task_id=task_id,
            predicted_strategy=f"strategy_{task_domain}",
            predicted_compute_tier=compute_tier,
            predicted_success_probability=prob_success,
            predicted_latency_ms=10.0 if compute_tier == "FAST" else (50.0 if compute_tier == "NORMAL" else 200.0),
            likely_failure_modes=["incomplete_context", "sandbox_timeout"] if difficulty > 0.6 else [],
            recommend_experimentation=recommend_exp,
            recommend_external_model=difficulty > 0.85
        )
        self._predictions[pred.prediction_id] = pred
        self._persist_prediction(pred)
        return pred

    def record_post_execution_feedback(
        self,
        prediction_id: str,
        actual_strategy: str,
        actual_success: bool,
        actual_latency_ms: float
    ) -> Optional[MetaCalibrationRecord]:
        """Calculates prediction error and updates calibration parameters."""
        pred = self._predictions.get(prediction_id)
        if not pred:
            return None

        actual_binary = 1.0 if actual_success else 0.0
        prob_error = abs(pred.predicted_success_probability - actual_binary)
        lat_error = abs(pred.predicted_latency_ms - actual_latency_ms)
        penalty = (pred.predicted_success_probability - actual_binary) ** 2

        cal_record = MetaCalibrationRecord(
            prediction_id=prediction_id,
            task_id=pred.task_id,
            actual_strategy_used=actual_strategy,
            actual_success=actual_success,
            actual_latency_ms=actual_latency_ms,
            probability_error=prob_error,
            latency_error_ms=lat_error,
            calibration_penalty=penalty
        )
        self._calibrations.append(cal_record)
        self._persist_calibration(cal_record)
        return cal_record

    def get_mean_calibration_error(self) -> float:
        if not self._calibrations:
            return 0.0
        return round(sum(c.calibration_penalty for c in self._calibrations) / len(self._calibrations), 4)

    def _persist_prediction(self, pred: MetaPrediction):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT OR REPLACE INTO meta_predictions VALUES (?, ?, ?, ?)", (pred.prediction_id, pred.task_id, json.dumps(pred.to_dict()), pred.timestamp))
        conn.commit()
        conn.close()

    def _persist_calibration(self, cal: MetaCalibrationRecord):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT OR REPLACE INTO meta_calibrations VALUES (?, ?, ?, ?)", (cal.prediction_id, cal.task_id, json.dumps(cal.to_dict()), cal.timestamp))
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute("SELECT data_json FROM meta_predictions").fetchall():
                p_dict = json.loads(row[0])
                pred = MetaPrediction(
                    task_id=p_dict["task_id"],
                    prediction_id=p_dict["prediction_id"],
                    predicted_strategy=p_dict.get("predicted_strategy", ""),
                    predicted_compute_tier=p_dict.get("predicted_compute_tier", "NORMAL"),
                    predicted_success_probability=p_dict.get("predicted_success_probability", 0.8),
                    predicted_latency_ms=p_dict.get("predicted_latency_ms", 50.0),
                    likely_failure_modes=p_dict.get("likely_failure_modes", []),
                    recommend_experimentation=p_dict.get("recommend_experimentation", False),
                    recommend_external_model=p_dict.get("recommend_external_model", False),
                    timestamp=p_dict.get("timestamp", time.time())
                )
                self._predictions[pred.prediction_id] = pred
            conn.close()
        except Exception:
            pass
