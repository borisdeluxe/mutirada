"""Tests for budget enforcement."""
import pytest
from decimal import Decimal

from orchestrator.budget import BudgetEnforcer, BudgetExceeded


class TestBudgetEnforcer:
    """Budget enforcer should prevent overspend at feature, daily, and weekly levels."""

    def test_check_feature_budget_passes_under_limit(self, budget: BudgetEnforcer):
        """Should allow spending when under feature limit."""
        result = budget.check_feature_budget("FAL-001", current_cost=3.00)

        assert result.allowed is True
        assert result.remaining == 2.00  # 5.00 limit - 3.00 spent

    def test_check_feature_budget_fails_at_limit(self, budget: BudgetEnforcer):
        """Should block spending when at or over feature limit."""
        result = budget.check_feature_budget("FAL-001", current_cost=5.50)

        assert result.allowed is False
        assert result.exceeded_by == 0.50

    def test_check_daily_budget_aggregates_all_features(self, budget: BudgetEnforcer):
        """Daily budget should sum all feature costs for today."""
        # FAL-001: 5.00, FAL-002: 8.00 = 13.00 total today
        result = budget.check_daily_budget()

        assert result.current == 13.00
        assert result.limit == 20.00
        assert result.allowed is True

    def test_check_daily_budget_fails_at_limit(self, budget_near_daily_limit: BudgetEnforcer):
        """Should block when daily limit exceeded."""
        result = budget_near_daily_limit.check_daily_budget()

        assert result.allowed is False

    def test_check_weekly_budget_aggregates_7_days(self, budget: BudgetEnforcer):
        """Weekly budget should sum costs from last 7 days."""
        result = budget.check_weekly_budget()

        assert result.limit == 100.00
        assert result.allowed is True

    def test_can_spend_checks_all_levels(self, budget: BudgetEnforcer):
        """can_spend should check feature, daily, and weekly budgets."""
        result = budget.can_spend("FAL-001", amount=1.00)

        assert result.allowed is True
        assert result.feature_remaining > 0
        assert result.daily_remaining > 0
        assert result.weekly_remaining > 0

    def test_can_spend_fails_if_any_level_exceeded(self, budget_near_daily_limit: BudgetEnforcer):
        """Should fail if any budget level would be exceeded."""
        result = budget_near_daily_limit.can_spend("FAL-NEW", amount=5.00)

        assert result.allowed is False
        assert "daily" in result.reason.lower()

    def test_record_spend_updates_atomically(self, budget: BudgetEnforcer, test_db):
        """Recording spend should use atomic UPDATE, not read-then-write."""
        budget.record_spend("FAL-001", amount=0.50)
        budget.record_spend("FAL-001", amount=0.30)

        # Verify in database
        result = test_db.execute(
            "SELECT cost_eur FROM agency_tasks WHERE feature_id = 'FAL-001'"
        ).fetchone()

        assert result[0] == Decimal("0.80")

    def test_get_budget_summary_returns_all_levels(self, budget: BudgetEnforcer):
        """Should return current spend and limits for all levels."""
        summary = budget.get_summary()

        assert "feature" not in summary  # No specific feature
        assert summary["daily"]["current"] == 13.00
        assert summary["daily"]["limit"] == 20.00
        assert summary["weekly"]["limit"] == 100.00


class TestBudgetLimits:
    """Budget limits should match TK14 specification."""

    def test_default_feature_limit(self, budget_limits_only: BudgetEnforcer):
        """Feature limit should be €5.00."""
        assert budget_limits_only.limits.per_feature_eur == 5.00

    def test_default_daily_limit(self, budget_limits_only: BudgetEnforcer):
        """Daily limit should be €20.00."""
        assert budget_limits_only.limits.per_day_eur == 20.00

    def test_default_weekly_limit(self, budget_limits_only: BudgetEnforcer):
        """Weekly limit should be €100.00."""
        assert budget_limits_only.limits.per_week_eur == 100.00


@pytest.fixture
def budget(test_db):
    """Budget enforcer with test data under limits."""
    # Insert test cost data
    test_db.execute("""
        INSERT INTO agency_tasks (feature_id, source, status, cost_eur, created_at)
        VALUES
            ('FAL-001', 'test', 'completed', 5.00, NOW()),
            ('FAL-002', 'test', 'completed', 8.00, NOW())
    """)
    return BudgetEnforcer(test_db)


@pytest.fixture
def budget_near_daily_limit(test_db):
    """Budget enforcer with daily limit nearly exceeded."""
    test_db.execute("""
        INSERT INTO agency_tasks (feature_id, source, status, cost_eur, created_at)
        VALUES
            ('FAL-001', 'test', 'completed', 10.00, NOW()),
            ('FAL-002', 'test', 'completed', 9.50, NOW())
    """)
    return BudgetEnforcer(test_db)


@pytest.fixture
def budget_limits_only(mock_db):
    """Budget enforcer for testing limits only (no DB operations)."""
    return BudgetEnforcer(mock_db)
