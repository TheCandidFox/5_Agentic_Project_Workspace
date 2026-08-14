from __future__ import annotations

import pytest

from budget_guard import BudgetGuard
from ledger import Ledger


def test_budget_reservation_key_replays_without_double_reserving(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    guard = BudgetGuard(ledger, daily_limit_usd=1, monthly_limit_usd=1)

    first = guard.reserve(
        task_id="task-budget",
        step_id="attempt-1",
        amount_usd=0.25,
        task_limit_usd=1,
        idempotency_key="repair:attempt:1",
    )
    second = guard.reserve(
        task_id="task-budget",
        step_id="attempt-1",
        amount_usd=0.25,
        task_limit_usd=1,
        idempotency_key="repair:attempt:1",
    )

    assert second == first
    assert ledger.active_reservations(task_id="task-budget") == pytest.approx(0.25)

