"""SQLite incident store (SQLAlchemy)."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.agent import Triage


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # naive UTC: SQLite drops tzinfo anyway


class Base(DeclarativeBase):
    pass


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    alertname: Mapped[str] = mapped_column(String(128))
    service: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|acknowledged|resolved
    triage_json: Mapped[str] = mapped_column(Text, default="")
    slack_ts: Mapped[str] = mapped_column(String(64), default="")
    slack_channel: Mapped[str] = mapped_column(String(64), default="")
    alert_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acked_by: Mapped[str] = mapped_column(String(64), default="")
    resolved_by: Mapped[str] = mapped_column(String(64), default="")

    @property
    def triage(self) -> Triage | None:
        return Triage(**json.loads(self.triage_json)) if self.triage_json else None


class Store:
    def __init__(self, url: str) -> None:
        if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url)
        Base.metadata.create_all(self.engine)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        return self._sessions()

    def open_or_dedupe(
        self, fingerprint: str, alertname: str, service: str, severity: str
    ) -> tuple[Incident, bool]:
        """Return (incident, created). A repeat alert for an open incident only bumps its count."""
        with self.session() as s:
            inc = s.scalars(
                select(Incident).where(
                    Incident.alertname == alertname,
                    Incident.service == service,
                    Incident.status != "resolved",
                )
            ).first()
            if inc:
                inc.alert_count += 1
                s.commit()
                return inc, False
            inc = Incident(
                fingerprint=fingerprint, alertname=alertname, service=service, severity=severity
            )
            s.add(inc)
            s.commit()
            return inc, True

    def save_triage(self, incident_id: int, triage: Triage) -> None:
        with self.session() as s:
            s.get(Incident, incident_id).triage_json = json.dumps(asdict(triage))
            s.commit()

    def set_slack(self, incident_id: int, channel: str, ts: str) -> None:
        with self.session() as s:
            inc = s.get(Incident, incident_id)
            inc.slack_channel, inc.slack_ts = channel, ts
            s.commit()

    def get(self, incident_id: int) -> Incident | None:
        with self.session() as s:
            return s.get(Incident, incident_id)

    def ack(self, incident_id: int, user: str) -> Incident | None:
        with self.session() as s:
            inc = s.get(Incident, incident_id)
            if inc and inc.status == "open":
                inc.status, inc.acknowledged_at, inc.acked_by = "acknowledged", utcnow(), user
                s.commit()
                return inc
            return None  # unknown id, or no state change (e.g. double click)

    def resolve(self, incident_id: int, user: str) -> Incident | None:
        with self.session() as s:
            inc = s.get(Incident, incident_id)
            if inc and inc.status != "resolved":
                inc.status, inc.resolved_at, inc.resolved_by = "resolved", utcnow(), user
                s.commit()
                return inc
            return None

    def list_open(self) -> list[Incident]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(Incident)
                    .where(Incident.status != "resolved")
                    .order_by(Incident.id.desc())
                )
            )

    def list_all(self, limit: int = 50) -> list[Incident]:
        with self.session() as s:
            return list(s.scalars(select(Incident).order_by(Incident.id.desc()).limit(limit)))

    def stats(self) -> dict:
        """Aggregates for /metrics. MTTA/MTTR are means in seconds (0 when no data yet)."""
        incs = self.list_all(limit=100_000)
        open_by_sev: dict[str, int] = {}
        for i in incs:
            if i.status != "resolved":
                open_by_sev[i.severity] = open_by_sev.get(i.severity, 0) + 1

        def mean(deltas: list[float]) -> float:
            return sum(deltas) / len(deltas) if deltas else 0.0

        return {
            "total": len(incs),
            "open_by_severity": open_by_sev,
            "mtta": mean(
                [
                    (i.acknowledged_at - i.created_at).total_seconds()
                    for i in incs
                    if i.acknowledged_at
                ]
            ),
            "mttr": mean(
                [(i.resolved_at - i.created_at).total_seconds() for i in incs if i.resolved_at]
            ),
        }
