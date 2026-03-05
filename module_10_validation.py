"""
Module 10: Validation and Consistency Checks (v2 — Fully Automated)

In full automation mode there is NO interactive review.
If critical fields are missing, the system raises a CriticalValidationError
and rejects the file, logging the reason.
Non-critical issues are logged as warnings.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


class CriticalValidationError(Exception):
    """Raised when the output cannot be trusted and the file must be rejected."""
    pass


SEVERITY_ERROR   = "ERROR"
SEVERITY_WARNING = "WARNING"

# Fields that MUST be present for every row
CRITICAL_FIELDS = ["hotel_name", "room_name", "start_date", "end_date", "currency"]


@dataclass
class ValidationIssue:
    row_index: int
    severity: str
    field: str
    message: str
    current_value: str = ""

    def __str__(self):
        return (
            f"[{self.severity}] Row {self.row_index} | {self.field}: "
            f"{self.message} (value: '{self.current_value}')"
        )


@dataclass
class ValidationReport:
    total_rows: int
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def add(self, issue: ValidationIssue):
        if issue.severity == SEVERITY_ERROR:
            self.errors.append(issue)
        else:
            self.warnings.append(issue)

    def summary(self) -> str:
        lines = [
            f"\nValidation Report: {self.total_rows} rows checked",
            f"  Errors   : {len(self.errors)}",
            f"  Warnings : {len(self.warnings)}",
            f"  Status   : {'PASS ✓' if self.passed else 'FAIL ✗'}",
        ]
        if self.errors:
            lines.append("\nErrors (first 20):")
            for e in self.errors[:20]:
                lines.append(f"  {e}")
        if self.warnings:
            lines.append("\nWarnings (first 10):")
            for w in self.warnings[:10]:
                lines.append(f"  {w}")
        return "\n".join(lines)


def validate_rows(rows: list, auto_reject: bool = True) -> ValidationReport:
    """
    Validate all CSV rows.
    If auto_reject=True and any errors are found, raises CriticalValidationError.
    """
    report = ValidationReport(total_rows=len(rows))

    if not rows:
        report.add(ValidationIssue(
            row_index=-1, severity=SEVERITY_ERROR,
            field="rows", message="No rows were generated — nothing to export.",
            current_value="0",
        ))
        if auto_reject:
            raise CriticalValidationError("No rows generated. File rejected.")
        return report

    for i, row in enumerate(rows):
        d = row.to_dict()
        _check_critical_fields(report, i, d)
        _check_cost(report, i, d)
        _check_capacity(report, i, d)
        _check_dates(report, i, d)
        _check_age_bands(report, i, d)
        _check_supplements(report, i, d)

    if auto_reject and report.errors:
        reasons = "\n".join(str(e) for e in report.errors[:5])
        raise CriticalValidationError(
            f"Validation failed with {len(report.errors)} error(s):\n{reasons}"
        )

    return report


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_critical_fields(report, idx, row):
    for f in CRITICAL_FIELDS:
        val = str(row.get(f, "")).strip()
        if not val:
            report.add(ValidationIssue(
                row_index=idx, severity=SEVERITY_ERROR,
                field=f, message="Critical field is empty", current_value=val,
            ))


def _check_cost(report, idx, row):
    try:
        cost = float(row.get("cost", 0))
        if cost < 0:
            report.add(ValidationIssue(
                row_index=idx, severity=SEVERITY_ERROR,
                field="cost", message="Cost cannot be negative", current_value=str(cost),
            ))
        if cost == 0 and str(row.get("min_age", "0")) != "0":
            # Zero cost for non-infant rows is a warning, not error
            report.add(ValidationIssue(
                row_index=idx, severity=SEVERITY_WARNING,
                field="cost", message="Cost is zero for a non-infant row", current_value="0",
            ))
    except (TypeError, ValueError):
        report.add(ValidationIssue(
            row_index=idx, severity=SEVERITY_ERROR,
            field="cost", message="Cost is not a valid number",
            current_value=str(row.get("cost")),
        ))


def _check_capacity(report, idx, row):
    try:
        max_cap = int(row.get("max_cap", 0))
        min_pax = int(row.get("min_pax", 1))
        max_pax = int(row.get("max_pax", 1))
        if max_cap < 1:
            report.add(ValidationIssue(
                row_index=idx, severity=SEVERITY_ERROR,
                field="max_cap", message="max_cap must be at least 1", current_value=str(max_cap),
            ))
        if min_pax > max_pax:
            report.add(ValidationIssue(
                row_index=idx, severity=SEVERITY_ERROR,
                field="min_pax", message="min_pax exceeds max_pax",
                current_value=f"{min_pax}>{max_pax}",
            ))
    except (TypeError, ValueError):
        pass


def _check_dates(report, idx, row):
    s = str(row.get("start_date", "")).strip()
    e = str(row.get("end_date",   "")).strip()

    sd = _parse_date(s)
    ed = _parse_date(e)

    if s and not sd:
        report.add(ValidationIssue(
            row_index=idx, severity=SEVERITY_ERROR,
            field="start_date", message="Invalid date (expected YYYY-MM-DD)", current_value=s,
        ))
    if e and not ed:
        report.add(ValidationIssue(
            row_index=idx, severity=SEVERITY_ERROR,
            field="end_date", message="Invalid date (expected YYYY-MM-DD)", current_value=e,
        ))
    if sd and ed and ed < sd:
        report.add(ValidationIssue(
            row_index=idx, severity=SEVERITY_ERROR,
            field="end_date", message="end_date is before start_date",
            current_value=f"{s} → {e}",
        ))


def _check_age_bands(report, idx, row):
    try:
        af = int(row.get("min_age", 0))
        at = int(row.get("max_age", 99))
        if af > at:
            report.add(ValidationIssue(
                row_index=idx, severity=SEVERITY_ERROR,
                field="min_age", message="min_age > max_age",
                current_value=f"{af}-{at}",
            ))
    except (TypeError, ValueError):
        pass


def _check_supplements(report, idx, row):
    for sf in ("single_supplement", "hb_supplement", "fb_supplement"):
        try:
            v = float(row.get(sf, 0))
            if v < 0:
                report.add(ValidationIssue(
                    row_index=idx, severity=SEVERITY_WARNING,
                    field=sf, message="Supplement value is negative", current_value=str(v),
                ))
        except (TypeError, ValueError):
            pass


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
