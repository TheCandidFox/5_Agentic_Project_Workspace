from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from project_paths import resolve_config_path

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")


@dataclass(frozen=True)
class Settings:
    project_root: Path = BASE

    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    openai_economy_model: str = os.getenv(
        "OPENAI_ECONOMY_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
    )
    openai_mid_model: str = os.getenv(
        "OPENAI_MID_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
    )
    anthropic_economy_model: str = os.getenv(
        "ANTHROPIC_ECONOMY_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    )
    anthropic_mid_model: str = os.getenv(
        "ANTHROPIC_MID_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    )

    openai_input_per_mtok: float = float(os.getenv("OPENAI_INPUT_PER_MTOK", "2.50"))
    openai_output_per_mtok: float = float(os.getenv("OPENAI_OUTPUT_PER_MTOK", "15.00"))
    anthropic_input_per_mtok: float = float(os.getenv("ANTHROPIC_INPUT_PER_MTOK", "2.00"))
    anthropic_output_per_mtok: float = float(os.getenv("ANTHROPIC_OUTPUT_PER_MTOK", "10.00"))

    daily_budget_usd: float = float(os.getenv("DAILY_BUDGET_USD", "5"))
    monthly_budget_usd: float = float(os.getenv("MONTHLY_BUDGET_USD", "150"))
    default_task_budget_usd: float = float(os.getenv("DEFAULT_TASK_BUDGET_USD", "10"))

    openai_max_output_tokens: int = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "5000"))
    anthropic_max_output_tokens: int = int(os.getenv("ANTHROPIC_MAX_OUTPUT_TOKENS", "5000"))

    ledger_path: Path = resolve_config_path(os.getenv("LEDGER_PATH", "ledger.db"), BASE)
    outputs_dir: Path = resolve_config_path(os.getenv("OUTPUTS_DIR", "outputs"), BASE)
    project_goal_path: Path = resolve_config_path(
        os.getenv("GOAL_PATH", "project/goal.md"), BASE
    )


SETTINGS = Settings()
