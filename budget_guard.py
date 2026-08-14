from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ledger import Ledger


class BudgetDenied(RuntimeError):
    pass


def _day_start_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _month_start_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


@dataclass
class BudgetGuard:
    ledger: Ledger
    daily_limit_usd: float
    monthly_limit_usd: float

    def reserve(
        self,
        *,
        task_id: str,
        step_id: str,
        amount_usd: float,
        task_limit_usd: float,
        idempotency_key: str | None = None,
    ) -> str:
        if amount_usd < 0:
            raise ValueError("reservation must be non-negative")

        reservation_id = (
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"ai-loop-budget:{idempotency_key}"))
            if idempotency_key is not None
            else str(uuid.uuid4())
        )
        existing = self.ledger.get_budget_reservation(reservation_id)
        if existing is not None:
            if (
                existing["task_id"] != task_id
                or existing["step_id"] != step_id
                or abs(float(existing["reserved_usd"]) - amount_usd) > 1e-12
            ):
                raise RuntimeError("budget reservation key belongs to another request")
            return reservation_id

        day_spend = self.ledger.spend(since_iso=_day_start_iso())
        month_spend = self.ledger.spend(since_iso=_month_start_iso())
        task_spend = self.ledger.spend(task_id=task_id)

        day_reserved = self.ledger.active_reservations(since_iso=_day_start_iso())
        month_reserved = self.ledger.active_reservations(since_iso=_month_start_iso())
        task_reserved = self.ledger.active_reservations(task_id=task_id)

        checks = [
            ("daily", day_spend + day_reserved + amount_usd, self.daily_limit_usd),
            ("monthly", month_spend + month_reserved + amount_usd, self.monthly_limit_usd),
            ("task", task_spend + task_reserved + amount_usd, task_limit_usd),
        ]
        for name, projected, limit in checks:
            if projected > limit + 1e-12:
                self.ledger.event(
                    "budget_denied",
                    {
                        "scope": name,
                        "projected_usd": projected,
                        "limit_usd": limit,
                        "requested_reservation_usd": amount_usd,
                    },
                    task_id,
                )
                raise BudgetDenied(
                    f"{name} budget would be exceeded: "
                    f"${projected:.4f} > ${limit:.4f}"
                )

        self.ledger.reserve(reservation_id, task_id, step_id, amount_usd)
        return reservation_id

    def settle(self, reservation_id: str, actual_usd: float) -> None:
        self.ledger.settle(reservation_id, actual_usd)
