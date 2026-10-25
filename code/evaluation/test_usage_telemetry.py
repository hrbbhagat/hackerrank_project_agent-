"""
Comprehensive Unit Tests for Model Usage Accounting, Telemetry, and Cost Calculation.

Validates all 15 mandatory Phase 11 scenarios:
1. Zero model calls: Truthful zero-usage report for deterministic Python executions.
2. Single model call: Correct provider-reported input/output capture.
3. Multiple calls: Accurate aggregation across multiple invocations.
4. Multiple models: Complete separation of usage and costs per model and provider.
5. Retry handling: Retries tracked as distinct invocations without double-counting base calls.
6. Missing token fields: Unknown/None usage is not incorrectly converted to zero.
7. Failed or interrupted calls: Unknown billing is marked unknown rather than free ($0.00).
8. Cached token accounting: Cached tokens accounted cleanly without double-counting total tokens.
9. Pricing unavailable: Cost marked unknown (None) rather than fabricated.
10. Pricing calculation: Verified formula: (tokens / pricing_unit) * rate.
11. Duplicate ledger entries: Duplicate invocation_id raises ValueError.
12. Sensitive information: Secrets and API keys redacted from ledger output.
13. Runtime accounting: Nonnegative elapsed duration and correct run scope.
14. No denominator: Zero requests or zero calls guard against ZeroDivisionError.
15. Partial telemetry: Incomplete usage records correctly flagged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest

CODE_DIR = Path(__file__).resolve().parent.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from evaluation.telemetry import (
    ModelInvocationRecord,
    UsageLedger,
    redact_secrets,
)


class TestUsageAccountingScenarios:

    # 1. Zero model calls
    def test_01_zero_model_calls(self):
        ledger = UsageLedger(run_id="run-zero")
        ledger.finalize(requests_processed=518, elapsed_seconds=25.0)
        summary = ledger.aggregate()

        assert summary.total_model_calls == 0
        assert summary.total_input_tokens == 0
        assert summary.total_output_tokens == 0
        assert summary.total_tokens == 0
        assert summary.total_cost == 0.0
        assert summary.is_deterministic_local_pipeline is True
        assert summary.avg_tokens_per_request == 0.0
        assert summary.avg_cost_per_request == 0.0

    # 2. Single model call
    def test_02_single_model_call(self):
        ledger = UsageLedger(run_id="run-single")
        rec = ModelInvocationRecord(
            invocation_id="call-01",
            run_id="run-single",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="openai",
            model_name="gpt-4o",
            operation_type="chat_completion",
            input_tokens=150,
            output_tokens=50,
            pricing_unit=1_000_000,
            input_rate=5.0,
            output_rate=15.0,
        )
        ledger.record_invocation(rec)
        ledger.finalize(requests_processed=1, elapsed_seconds=1.2)
        summary = ledger.aggregate()

        assert summary.total_model_calls == 1
        assert summary.total_input_tokens == 150
        assert summary.total_output_tokens == 50
        assert summary.total_tokens == 200
        # Cost: (150/1M * 5) + (50/1M * 15) = 0.00075 + 0.00075 = 0.0015
        assert summary.total_cost == 0.0015
        assert summary.is_deterministic_local_pipeline is False

    # 3. Multiple calls
    def test_03_multiple_calls_aggregation(self):
        ledger = UsageLedger(run_id="run-multi")
        for i in range(3):
            ledger.record_invocation(ModelInvocationRecord(
                invocation_id=f"call-0{i}",
                run_id="run-multi",
                timestamp_iso="2026-10-25T10:00:00Z",
                provider="anthropic",
                model_name="claude-3-5-sonnet",
                operation_type="chat_completion",
                input_tokens=100,
                output_tokens=50,
                pricing_unit=1_000_000,
                input_rate=3.0,
                output_rate=15.0,
            ))
        ledger.finalize(requests_processed=3, elapsed_seconds=3.0)
        summary = ledger.aggregate()

        assert summary.total_model_calls == 3
        assert summary.total_input_tokens == 300
        assert summary.total_output_tokens == 150
        assert summary.total_tokens == 450
        assert summary.avg_tokens_per_request == 150.0

    # 4. Multiple models separated
    def test_04_multiple_models_separation(self):
        ledger = UsageLedger(run_id="run-multi-model")
        ledger.record_invocation(ModelInvocationRecord(
            invocation_id="call-m1",
            run_id="run-multi-model",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="openai",
            model_name="gpt-4o",
            operation_type="chat_completion",
            input_tokens=200,
            output_tokens=100,
            billed_cost=0.002,
        ))
        ledger.record_invocation(ModelInvocationRecord(
            invocation_id="call-m2",
            run_id="run-multi-model",
            timestamp_iso="2026-10-25T10:00:01Z",
            provider="google",
            model_name="gemini-1.5-pro",
            operation_type="chat_completion",
            input_tokens=500,
            output_tokens=250,
            billed_cost=0.004,
        ))
        ledger.finalize(requests_processed=2)
        summary = ledger.aggregate()

        assert len(summary.per_model_aggregates) == 2
        assert "openai::gpt-4o" in summary.per_model_aggregates
        assert "google::gemini-1.5-pro" in summary.per_model_aggregates
        assert summary.per_model_aggregates["openai::gpt-4o"].total_tokens == 300
        assert summary.per_model_aggregates["google::gemini-1.5-pro"].total_tokens == 750
        assert summary.total_cost == 0.006

    # 5. Retry handling
    def test_05_retry_accounting(self):
        ledger = UsageLedger(run_id="run-retry")
        ledger.record_invocation(ModelInvocationRecord(
            invocation_id="call-retry-1",
            run_id="run-retry",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="openai",
            model_name="gpt-4o",
            operation_type="chat_completion",
            success=False,
            retry_count=1,
            input_tokens=100,
            output_tokens=0,
            billed_cost=0.0005,
        ))
        ledger.record_invocation(ModelInvocationRecord(
            invocation_id="call-retry-2",
            run_id="run-retry",
            timestamp_iso="2026-10-25T10:00:02Z",
            provider="openai",
            model_name="gpt-4o",
            operation_type="chat_completion",
            success=True,
            retry_count=2,
            input_tokens=100,
            output_tokens=80,
            billed_cost=0.0017,
        ))
        ledger.finalize(requests_processed=1)
        summary = ledger.aggregate()

        assert summary.total_model_calls == 2
        assert summary.successful_model_calls == 1
        assert summary.failed_model_calls == 1
        assert summary.total_retries == 3
        assert summary.total_tokens == 280

    # 6. Missing token fields (unknown not converted to 0)
    def test_06_missing_tokens_not_zeroed(self):
        ledger = UsageLedger(run_id="run-missing-tokens")
        ledger.record_invocation(ModelInvocationRecord(
            invocation_id="call-none-tok",
            run_id="run-missing-tokens",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="custom_api",
            model_name="unmetered_model",
            operation_type="completion",
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            billed_cost=0.01,
        ))
        ledger.finalize(requests_processed=1)
        summary = ledger.aggregate()

        assert summary.has_unknown_tokens is True
        assert summary.total_tokens is None  # Must NOT be 0
        assert summary.avg_tokens_per_request is None

    # 7. Failed or interrupted calls (unknown billing not marked free)
    def test_07_failed_calls_unknown_billing(self):
        ledger = UsageLedger(run_id="run-failed")
        ledger.record_invocation(ModelInvocationRecord(
            invocation_id="call-timeout",
            run_id="run-failed",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="openai",
            model_name="gpt-4o",
            operation_type="chat_completion",
            success=False,
            input_tokens=100,
            output_tokens=None,
            billed_cost=None,  # Unknown billing
        ))
        ledger.finalize(requests_processed=1)
        summary = ledger.aggregate()

        assert summary.is_cost_known is False
        assert summary.total_cost is None  # Must NOT be marked $0.00
        assert summary.avg_cost_per_request is None

    # 8. Cached token accounting
    def test_08_cached_tokens_separate(self):
        rec = ModelInvocationRecord(
            invocation_id="call-cached",
            run_id="run-cached",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="anthropic",
            model_name="claude-3-5-sonnet",
            operation_type="chat_completion",
            input_tokens=1000,
            cached_tokens=800,
            output_tokens=200,
            pricing_unit=1_000_000,
            input_rate=3.0,
            cached_rate=0.30,
            output_rate=15.0,
        )
        assert rec.total_tokens == 1200
        # Cost: (1000/1M * 3) + (800/1M * 0.3) + (200/1M * 15) = 0.003 + 0.00024 + 0.003 = 0.00624
        assert rec.billed_cost == 0.00624

    # 9. Pricing unavailable
    def test_09_pricing_unavailable_marks_unknown(self):
        rec = ModelInvocationRecord(
            invocation_id="call-no-pricing",
            run_id="run-no-pricing",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="internal_cluster",
            model_name="llama-3-8b",
            operation_type="chat_completion",
            input_tokens=500,
            output_tokens=100,
            # No rates or billed_cost provided
        )
        assert rec.billed_cost is None

        ledger = UsageLedger(run_id="run-no-pricing")
        ledger.record_invocation(rec)
        ledger.finalize(requests_processed=1)
        summary = ledger.aggregate()

        assert summary.is_cost_known is False
        assert summary.total_cost is None

    # 10. Pricing calculation formula verified
    def test_10_pricing_calculation_formula(self):
        rec = ModelInvocationRecord(
            invocation_id="call-pricing-calc",
            run_id="run-calc",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="openai",
            model_name="gpt-4o-mini",
            operation_type="chat_completion",
            input_tokens=100_000,
            output_tokens=20_000,
            pricing_unit=1_000_000,
            input_rate=0.15,
            output_rate=0.60,
        )
        # Expected: (100k/1M * 0.15) + (20k/1M * 0.60) = 0.015 + 0.012 = 0.027
        assert rec.billed_cost == 0.027

    # 11. Duplicate ledger entries rejected
    def test_11_duplicate_invocation_rejected(self):
        ledger = UsageLedger(run_id="run-dup")
        rec = ModelInvocationRecord(
            invocation_id="dup-id-123",
            run_id="run-dup",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="openai",
            model_name="gpt-4o",
            operation_type="chat",
        )
        ledger.record_invocation(rec)
        with pytest.raises(ValueError, match="Duplicate invocation_id detected"):
            ledger.record_invocation(rec)

    # 12. Sensitive information redacted
    def test_12_sensitive_information_redacted(self):
        secret_str = "Bearer sk-proj-1234567890abcdef1234567890"
        redacted = redact_secrets(secret_str)
        assert "sk-proj-1234567890abcdef1234567890" not in redacted
        assert "[REDACTED]" in redacted

        rec = ModelInvocationRecord(
            invocation_id="call-secret",
            run_id="run-secret",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="openai",
            model_name="gpt-4o",
            operation_type="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        )
        d = rec.to_dict()
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in d["operation_type"]

    # 13. Runtime accounting nonnegative
    def test_13_runtime_nonnegative(self):
        ledger = UsageLedger(run_id="run-time")
        ledger.finalize(requests_processed=10, elapsed_seconds=-5.0)
        assert ledger.wall_clock_seconds == 0.0

        ledger2 = UsageLedger(run_id="run-time-pos")
        ledger2.finalize(requests_processed=10, elapsed_seconds=12.5)
        assert ledger2.wall_clock_seconds == 12.5

    # 14. No denominator (division by zero prevention)
    def test_14_zero_denominator_guards(self):
        ledger = UsageLedger(run_id="run-empty")
        ledger.finalize(requests_processed=0, elapsed_seconds=0.0)
        summary = ledger.aggregate()

        assert summary.requests_processed == 0
        assert summary.avg_tokens_per_request is None
        assert summary.avg_cost_per_request is None
        assert summary.avg_tokens_per_call is None

    # 15. Partial telemetry clearly identified
    def test_15_partial_telemetry_identified(self):
        ledger = UsageLedger(run_id="run-partial")
        # Call 1 has tokens
        ledger.record_invocation(ModelInvocationRecord(
            invocation_id="c1",
            run_id="run-partial",
            timestamp_iso="2026-10-25T10:00:00Z",
            provider="openai",
            model_name="gpt-4o",
            operation_type="chat",
            input_tokens=100,
            output_tokens=50,
            billed_cost=0.001,
        ))
        # Call 2 missing tokens
        ledger.record_invocation(ModelInvocationRecord(
            invocation_id="c2",
            run_id="run-partial",
            timestamp_iso="2026-10-25T10:00:01Z",
            provider="openai",
            model_name="gpt-4o",
            operation_type="chat",
            input_tokens=None,
            output_tokens=None,
            billed_cost=0.001,
        ))
        ledger.finalize(requests_processed=2)
        summary = ledger.aggregate()

        assert summary.total_model_calls == 2
        assert summary.has_unknown_tokens is True
        assert summary.total_tokens is None  # Refuses to present partial total as complete total
        assert summary.total_cost == 0.002
