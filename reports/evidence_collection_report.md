# Phase 4 — Evidence Collection Report

## 1. Objective

Collect and parse the evidence files listed in the evidence manifest. Preserve source context and extract identifiers, timestamps, resource references, and record content without treating extraction as proof of deletion.

## 2. Evidence inventory

| Format | Files processed |
|---|---:|
| LOG | 26 |
| JSON | 28 |
| TXT | 1 |
| PNG | 11 |
| SQL | 24 |
| PDF | 4 |
| **Total** | **94** |

## 3. Integrated reader validation

Latest observed validation results:

- Manifest files processed: 94
- Extracted records: 3,973
- Records with identifier-like fields: 1,435
- Files with reported extraction errors: 0
- Reader regression tests: 6 passed
- SQL parser tests: 9 passed
- Python syntax compilation: passed

Result: PASS for the current dataset's integrated extraction check.

## 4. SQL parsing

The static SQL parser was tested against 24 SQL files.

- INSERT statements examined: 969
- Successfully parsed INSERT statements: 969
- Failed INSERT statements: 0
- Schema parse errors: 0
- CREATE TABLE statements recognized: 127
- CREATE INDEX statements recognized: 55
- BEGIN TRANSACTION statements recognized: 24
- COMMIT statements recognized: 24

SQL evidence is parsed statically and is not executed. Parsed statements must still be evaluated in context, including source system, snapshot time, resource identity, and audit cutoff.

## 5. Supported extraction methods

- JSON: records, snapshots, collection and data-store context, flattened fields, and raw records.
- LOG: line-level timestamps, key-value fields, service/event context, trace IDs, resource IDs, and raw text.
- SQL: table schemas and supported INSERT values, with parse errors surfaced through the reader.
- TXT: line-level text and timestamp candidates.
- PDF: page-level extracted text and timestamp candidates.
- PNG: OCR text, word-level confidence, and timestamp candidates.

## 6. Limitations and evidence-handling safeguards

1. Extraction success does not establish that a record belongs to the target user.
2. Identifier-like fields are candidates for matching, not proof of identity.
3. Identity resolution and audit-cutoff enforcement must be applied before using evidence in a case decision.
4. SQL statements must not be treated as proof of current live state without examining source type and timestamp.
5. OCR may contain recognition errors. Low-confidence OCR matches require corroboration; OCR alone must not establish deletion completion.
6. Text handovers and status assertions are claims that require corroborating evidence.
7. Evidence collected after the case's audit cutoff must not be used to justify the historical decision.

## 7. Outstanding integration checks

- Integrate evidence search with the identity resolver.
- Apply per-case audit cutoffs to evidence matching and timeline reconstruction.
- Correlate evidence by user, identifier, resource, system, timestamp, and operation.
- Distinguish primary databases, replicas, backups, exports, caches, and downstream systems.
- Ensure ambiguous or weak evidence cannot independently produce a COMPLETE decision.
- Add end-to-end case tests and verify the final output against the required output schema.

## 8. Phase status

**Status: Extraction implementation and current-dataset validation passed; phase-wide sign-off remains pending.**

The reader processes all 94 manifest files without reported extraction errors, and the current reader and SQL parser test suites pass. Evidence relevance, identity matching, temporal validity, and deletion completeness remain downstream audit responsibilities.

