"""Budget enforcement - prevents overspend at feature, daily, and weekly levels."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


class BudgetExceeded(Exception):
    """Raised when a budget limit would be exceeded."""
    pass


@dataclass
class BudgetLimits:
    per_feature_eur: float = 5.00
    per_day_eur: float = 20.00
    per_week_eur: float = 100.00


@dataclass
class BudgetCheckResult:
    allowed: bool
    current: float = 0.0
    limit: float = 0.0
    remaining: float = 0.0
    exceeded_by: float = 0.0
    reason: str = ""


@dataclass
class CanSpendResult:
    allowed: bool
    feature_remaining: float = 0.0
    daily_remaining: float = 0.0
    weekly_remaining: float = 0.0
    reason: str = ""


class BudgetEnforcer:
    """Enforces budget limits at feature, daily, and weekly levels."""

    def __init__(self, db, limits: Optional[BudgetLimits] = None):
        self.db = db
        self.limits = limits or BudgetLimits()

    def check_feature_budget(self, feature_id: str, current_cost: float) -> BudgetCheckResult:
        """Check if feature is within budget."""
        limit = self.limits.per_feature_eur
        remaining = limit - current_cost
        allowed = current_cost <= limit

        return BudgetCheckResult(
            allowed=allowed,
            current=current_cost,
            limit=limit,
            remaining=max(0, remaining),
            exceeded_by=max(0, current_cost - limit),
        )

    def check_daily_budget(self) -> BudgetCheckResult:
        """Check today's total spend against daily limit."""
        result = self.db.execute(
            """
            SELECT COALESCE(SUM(cost_eur), 0) as total
            FROM agency_tasks
            WHERE created_at >= CURRENT_DATE
            """
        ).fetchone()

        current = float(result["total"])
        limit = self.limits.per_day_eur
        remaining = limit - current
        allowed = current <= limit

        return BudgetCheckResult(
            allowed=allowed,
            current=current,
            limit=limit,
            remaining=max(0, remaining),
            exceeded_by=max(0, current - limit),
        )

    def check_weekly_budget(self) -> BudgetCheckResult:
        """Check this week's total spend against weekly limit."""
        result = self.db.execute(
            """
            SELECT COALESCE(SUM(cost_eur), 0) as total
            FROM agency_tasks
            WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            """
        ).fetchone()

        current = float(result["total"])
        limit = self.limits.per_week_eur
        remaining = limit - current
        allowed = current <= limit

        return BudgetCheckResult(
            allowed=allowed,
            current=current,
            limit=limit,
            remaining=max(0, remaining),
            exceeded_by=max(0, current - limit),
        )

    def can_spend(self, feature_id: str, amount: float) -> CanSpendResult:
        """Check if spending amount is allowed at all levels."""
        # Get current feature cost
        result = self.db.execute(
            "SELECT COALESCE(cost_eur, 0) as cost FROM agency_tasks WHERE feature_id = %s",
            (feature_id,)
        ).fetchone()

        feature_cost = float(result["cost"]) if result else 0.0
        feature_check = self.check_feature_budget(feature_id, feature_cost + amount)

        if not feature_check.allowed:
            return CanSpendResult(
                allowed=False,
                reason=f"Feature budget exceeded by €{feature_check.exceeded_by:.2f}",
            )

        daily_check = self.check_daily_budget()
        if not daily_check.allowed or daily_check.remaining < amount:
            return CanSpendResult(
                allowed=False,
                reason=f"Daily budget would be exceeded",
            )

        weekly_check = self.check_weekly_budget()
        if not weekly_check.allowed or weekly_check.remaining < amount:
            return CanSpendResult(
                allowed=False,
                reason=f"Weekly budget would be exceeded",
            )

        return CanSpendResult(
            allowed=True,
            feature_remaining=feature_check.remaining,
            daily_remaining=daily_check.remaining,
            weekly_remaining=weekly_check.remaining,
        )

    def record_spend(self, feature_id: str, amount: float) -> None:
        """Record spend atomically."""
        self.db.execute(
            """
            UPDATE agency_tasks
            SET cost_eur = cost_eur + %s, updated_at = NOW()
            WHERE feature_id = %s
            """,
            (amount, feature_id)
        )

    def get_summary(self) -> dict:
        """Get budget summary for all levels."""
        daily = self.check_daily_budget()
        weekly = self.check_weekly_budget()

        return {
            "daily": {
                "current": daily.current,
                "limit": daily.limit,
                "remaining": daily.remaining,
            },
            "weekly": {
                "current": weekly.current,
                "limit": weekly.limit,
                "remaining": weekly.remaining,
            },
        }
