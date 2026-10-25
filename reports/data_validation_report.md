# Phase 2 — Data Validation Report

## 1. Purpose

Document the initial validation of the HackerRank Orchestrate
October 2026 "Ghost Data Still Exists" challenge dataset.

This report records structural and data-quality checks. Passing these
checks does not prove that deletion requests were correctly audited or
that personal data was actually deleted.

## 2. Dataset Inventory

All nine CSV files were found and loaded successfully.

| File | Rows loaded | Result |
|---|---:|---|
| deletion_requests.csv | 518 | PASS |
| deletion_rules.csv | 15 | PASS |
| evidence_files.csv | 94 | PASS |
| output.csv | 0 | PASS — empty submission template |
| sample_deletion_requests.csv | 32 | PASS |
| sample_output.csv | 32 | PASS |
| system_activity.csv | 4011 | PASS |
| user_audit_log.csv | 306 | PASS |
| user_identities.csv | 850 | PASS |

The `dataset/evidence/` directory is present.

## 3. Schema Validation

All nine CSV files matched their expected column names and column order.

- Schema mismatches: 0
- Result: PASS

The required submission header is:

`case_id,deletion_status,steps_json`

The final output must contain exactly 518 cases, sorted by `case_id`.

## 4. Identifier Validation

Primary identifiers were checked for missing values and duplicate rows.

| File | Primary identifier | Missing | Duplicate rows |
|---|---|---:|---:|
| deletion_requests.csv | case_id | 0 | 0 |
| deletion_rules.csv | rule_id | 0 | 0 |
| evidence_files.csv | file_id | 0 | 0 |
| output.csv | case_id | 0 | 0 |
| sample_deletion_requests.csv | case_id | 0 | 0 |
| sample_output.csv | case_id | 0 | 0 |
| system_activity.csv | activity_id | 0 | 0 |
| user_audit_log.csv | audit_id | 0 | 0 |
| user_identities.csv | user_id | 0 | 0 |

Result: PASS for the identifiers checked.

Note: `output.csv` currently has zero data rows. Its identifier check
does not validate a generated submission.

## 5. Relationship Validation

### Checks completed

- All 94 evidence manifest entries refer to existing files.
- No duplicate evidence file IDs were found.
- No duplicate rule IDs were found.
- No empty activity resource IDs were found.
- All 306 audit-log user IDs were found in the current identity table.
- 100 request emails did not match current identity emails.
- All 100 unmatched request emails were found in email audit history.
- No request email remained unmatched against both current identity
  emails and the inspected email audit history.

### Outstanding work

The 100 historical email matches still require proper identity
resolution. Finding an email in audit history alone does not establish
the correct user identity or prove which identifiers applied at a
specific request's `audit_at`.

Additional checks are needed to establish relevant relationships
between requests, identities, activity records, evidence, and deletion
rules. Activity resource IDs not found by literal text search in
evidence files are diagnostic findings, not automatically errors.

Result: PARTIAL — complete identity resolution and case-level
relationship validation in Phase 3.

## 6. Timestamp Validation

The following timestamp fields were parsed:

| File | Timestamp field | Values checked | Invalid or empty |
|---|---|---:|---:|
| deletion_requests.csv | requested_at | 518 | 0 |
| deletion_requests.csv | reported_at | 518 | 0 |
| deletion_requests.csv | audit_at | 518 | 0 |
| evidence_files.csv | captured_at | 94 | 0 |
| system_activity.csv | event_time | 4011 | 0 |
| user_audit_log.csv | event_time | 306 | 0 |
| user_identities.csv | updated_at | 850 | 0 |

Total timestamp values checked: 8,277.

Chronology checks found:
- reported_at earlier than requested_at: 0
- audit_at earlier than requested_at: 0

The latest activity timestamp was 2026-10-01T10:18:34Z.
The latest evidence capture timestamp was 2026-10-01T12:00:00Z.
The audit cutoff range was 2026-01-29T12:00:00Z through
2026-10-01T12:00:00Z.

Result: PASS for parsing and request chronology.

Limitation: Each case must still be evaluated using its own `audit_at`.
Evidence captured after that cutoff must not be used to prove the
state at the cutoff.

## 7. Evidence Path Validation

The evidence manifest contains 94 entries.

- Existing files: 94
- Missing files: 0
- Unsafe paths outside `dataset/evidence/`: 0

Evidence formats:
- JSON: 28
- LOG: 26
- SQL: 24
- PNG: 11
- PDF: 4
- TXT: 1

Result: PASS for manifest path existence and path containment.

The presence of a file does not establish that it proves deletion.
Evidence contents, timestamps, identity linkage, and relevance must
be checked for each case.

## 8. Validator Tests

A temporary in-memory structural validator was run against
`dataset/sample_output.csv`. No project source file was changed by
that test.

Results:
- Sample header check: PASS
- Sample rows tested: 32
- Structural validation errors: 0
- Unmodified sample row accepted: PASS
- Malformed JSON rejected: PASS
- Invalid deletion status rejected: PASS
- Invalid step number and operation/state pair rejected: PASS
- Non-empty NOT_APPLICABLE steps rejected: PASS

Limitation: These tests checked structural rules and selected invalid
inputs. The temporary validator was not saved as a reusable project
validator and did not establish semantic deletion correctness.

Further tests are required for evidence ID validity, evidence cutoff
enforcement, step ordering, rule compliance, identity resolution,
request authorization, and case-level evidence sufficiency.

## 9. Outstanding Issues and Next Actions

1. Complete identity resolution using current and verified historical
   identifiers as of each case's `audit_at`.
2. Validate request-to-activity and request-to-evidence relationships
   using resolved identities and relevant resource identifiers.
3. Inspect evidence contents and reject evidence that is post-cutoff,
   irrelevant, or merely a workflow claim.
4. Implement a reusable validator in the project.
5. Test the validator against valid, malformed, and boundary cases.
6. Implement the audit agent and produce exactly 518 output rows.
7. Validate every output case against the challenge's status, step,
   evidence, operation/state, and ordering requirements.
8. Complete the required evaluation and usage reports and submission
   packaging.

## 10. Overall Assessment

- Dataset inventory and CSV loading: PASS
- Schema validation: PASS
- Primary identifier checks: PASS
- Timestamp parsing and request chronology: PASS
- Evidence path validation: PASS
- Basic structural validator tests: PASS
- Relationship validation: PARTIAL
- Case-level evidence and deletion correctness: NOT YET ESTABLISHED

Phase 2 has completed the initial structural checks. Relationship
validation remains partial, and the dataset must not be considered
fully audit-ready until identity resolution and case-level evidence
validation are completed.
