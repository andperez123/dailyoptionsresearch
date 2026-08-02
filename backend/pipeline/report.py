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

        if narrative_count > 0:
            tickers = sorted(
                {t for v in verdicts if v.get("meets_multi_source_bar") for t in [v.get("ticker")] if t}
            )
            ticker_note = f" ({', '.join(tickers[:6])})" if tickers else ""
            return (
                f"{narrative_count} narrative{'s' if narrative_count != 1 else ''} from "
                f"{multi_source}/{dossier_count} multi-source dossiers{ticker_note}"
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
        return ": ".join([parts[0], "; ".join(parts[1:])]) if len(parts) > 1 else parts[0]
