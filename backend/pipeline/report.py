"""Per-run diagnostics report, persisted whether or not the run produces
recommendations — the answer to "the run gave nothing, what happened?"."""

from __future__ import annotations

from datetime import date
from typing import Any

from time_utils import utc_now


class RunReportBuilder:
    """Accumulates stage-by-stage diagnostics during a pipeline run. The
    report survives mid-run failures: whatever was recorded before the crash
    is saved alongside the error."""

    def __init__(self, run_date: date) -> None:
        self.run_date = run_date
        self.started_at = utc_now()
        self.stages: list[dict[str, Any]] = []
        self.extra: dict[str, Any] = {}

    def stage(self, name: str, **data: Any) -> None:
        self.stages.append({"stage": name, "at": utc_now().isoformat(), **data})

    def set(self, key: str, value: Any) -> None:
        self.extra[key] = value

    @property
    def last_stage(self) -> str:
        return self.stages[-1]["stage"] if self.stages else "startup"

    def build(self) -> dict[str, Any]:
        return {"stages": self.stages, **self.extra}

    def headline_for(self, status: str, narrative_count: int, error: str | None = None) -> str:
        if status == "failed":
            return f"Run failed during '{self.last_stage}': {error or 'unknown error'}"

        verdicts = self.extra.get("dossier_verdicts") or []
        dossier_count = len(verdicts)
        multi_source = sum(1 for v in verdicts if v.get("meets_multi_source_bar"))
        dropped = self.extra.get("narratives_dropped") or []

        sports_setups = self.extra.get("sports_top_setups") or []

        if narrative_count > 0:
            tickers = sorted(
                {t for v in verdicts if v.get("meets_multi_source_bar") for t in [v.get("ticker")] if t}
            )
            ticker_note = f" ({', '.join(tickers[:6])})" if tickers else ""
            low_conf = self.extra.get("low_confidence_narratives") or 0
            low_conf_note = f", {low_conf} low-confidence" if low_conf else ""
            sports_note = f" · {len(sports_setups)} sports setup(s)" if sports_setups else ""
            return (
                f"{narrative_count} narrative{'s' if narrative_count != 1 else ''} from "
                f"{multi_source}/{dossier_count} multi-source dossiers{ticker_note}"
                f"{low_conf_note}{sports_note}"
            )

        # Empty day — explain why in one line
        parts: list[str] = ["0 narratives"]
        if self.run_date.weekday() >= 5:
            parts.append("markets closed (weekend)")
        if dossier_count:
            parts.append(f"{multi_source}/{dossier_count} dossiers met the multi-source bar")
        else:
            parts.append("no ticker dossiers built")
        if dropped:
            parts.append(f"{len(dropped)} model theses dropped in validation")
        raw = self.extra.get("raw_narrative_count")
        if raw == 0:
            parts.append("model proposed no theses")
        if sports_setups:
            best_ev = sports_setups[0].get("ev_pct")
            ev_note = f" (best {best_ev:+.1f}% EV)" if isinstance(best_ev, (int, float)) else ""
            parts.append(f"sports still surfaced {len(sports_setups)} setup(s){ev_note}")
        parts.append("full research review saved with this report")
        return ": ".join([parts[0], "; ".join(parts[1:])]) if len(parts) > 1 else parts[0]
