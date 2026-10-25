# HackerRank Orchestrate — October 2026: Ghost Data Still Exists

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests Passing](https://img.shields.io/badge/tests-821%20passed-brightgreen.svg)]()
[![Contract Conformance](https://img.shields.io/badge/output.csv-100%25%20valid-success.svg)]()
[![Deterministic](https://img.shields.io/badge/pipeline-100%25%20deterministic-blue.svg)]()
[![License: Proprietary](https://img.shields.io/badge/challenge-HackerRank%20Orchestrate-orange.svg)](https://wwww.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists)

An enterprise-grade, deterministic, AI-powered deletion-audit agent and remediation planner built for the **HackerRank Orchestrate (October 2026)** technical challenge: **“Ghost Data Still Exists.”**

---

## 1. Executive Summary and Challenge Overview

Commercial platforms frequently report privacy deletion requests as **Complete** while personal data remains active across primary databases, regional replicas, support ticketing systems, export archives, search indexes, analytics warehouses, or unblocked backup snapshots. Furthermore, background data synchronization pipelines and disaster-recovery restore procedures frequently reintroduce and recreate deleted records.

This solution implements a forensic deletion-audit agent that independently establishes the true ground-truth state of every deletion subject at their exact `audit_at` cutoff timestamp without trusting workflow claims. For every request, the engine:

1. **Determines Request Applicability**: Distinguishes valid deletion authorizations from non-deletion requests (subject access, rectification, data portability, marketing opt-outs), classifying non-deletion requests as `NOT_APPLICABLE` with `steps_json = []`.
2. **Reconstructs Current & Historical Identities**: Correlates stable internal references (`user_id`), historical emails, phone numbers, and cryptographic email hashes across temporal snapshots.
3. **Statically Inspects Multimodal Evidence**: Extracts records across SQLite SQL snapshot dumps, PDF documents, PNG screenshots (OCR), JSON records, plain-text files, and application logs without executing untrusted SQL or dynamic code.
4. **Enforces Strict Temporal Admissibility**: Excludes future evidence captured or occurring after the case cutoff ($T_{\text{event}} \le T_{\text{audit}}$ and $T_{\text{captured}} \le T_{\text{audit}}$).
5. **Applies Enterprise Deletion Policies**: Enforces data retention obligations, anonymization rules, and account tombstone specifications (preserving internal user references while redacting prohibited direct PII).
6. **Synthesizes Safe Lifecycle Remediation Plans**: Produces dependency-ordered remediation plans that disable active data flows and block restore risks *before* mutating dependent database records.
7. **Emits Evidence-Backed Verification**: Validates completed deletions using admissible participant-visible evidence citations.

The production pipeline processes all **518 evaluation requests** in `dataset/deletion_requests.csv`, emitting a structurally valid, fully compliant root-level `output.csv`.

---

## 2. Architecture and Forensic Data Flow

The solution is architected as a modular, pipeline-driven forensic audit engine composed of 7 core packages:

```
                                  [ dataset/deletion_requests.csv ]
                                                  │
                                                  ▼
                                      ┌───────────────────────┐
                                      │ Request Applicability │ ── Non-Deletion ──► NOT_APPLICABLE (steps_json = [])
                                      └───────────────────────┘
                                                  │ Valid Deletion
                                                  ▼
┌─────────────────────────┐           ┌───────────────────────┐           ┌─────────────────────────┐
│  user_identities.csv    │ ────────► │  Identity Resolution  │ ◄──────── │   user_audit_log.csv    │
└─────────────────────────┘           └───────────────────────┘           └─────────────────────────┘
                                                  │ Canonical & Historical Identifiers
                                                  ▼
┌─────────────────────────┐           ┌───────────────────────┐           ┌─────────────────────────┐
│   evidence_files.csv    │ ────────► │  Evidence Integration │ ◄──────── │ dataset/evidence/*      │
│   system_activity.csv   │           │   & Static Parsing    │           │ (SQL, PDF, PNG, Logs)   │
└─────────────────────────┘           └───────────────────────┘           └─────────────────────────┘
                                                  │ Grounded Evidence Records
                                                  ▼
                                      ┌───────────────────────┐
                                      │ Timeline Reconstruct  │ (Filters T_event <= T_audit,
                                      │ & Cutoff Enforcement  │  Filters T_captured <= T_audit)
                                      └───────────────────────┘
                                                  │ Temporal Event Graph
                                                  ▼
┌─────────────────────────┐           ┌───────────────────────┐
│   deletion_rules.csv    │ ────────► │     Policy Engine     │ (Tombstones, Mandatory Retention,
└─────────────────────────┘           └───────────────────────┘  PII Redaction, Anonymization)
                                                  │ Resource Treatment Decisions
                                                  ▼
                                      ┌───────────────────────┐
                                      │ Case Status Resolver  │ ── All Compliant ──► COMPLETE (Verification Only)
                                      └───────────────────────┘
                                                  │ Violations / Risks Detected
                                                  ▼
                                      ┌───────────────────────┐
                                      │ Step Planner & Order  │ (DISABLE_FLOW -> BLOCK_RESTORE ->
                                      │ Lifecycle Orchestrator│  DELETE/REDACT -> VERIFY)
                                      └───────────────────────┘
                                                  │
                                                  ▼
                                           [ root output.csv ]
                                    (518 rows, sorted by case_id)
```

---

## 3. Repository Structure

```text
hackerrank-orchestrate-october26/
├── README.md                           # Authoritative project documentation & execution guide
├── AGENTS.md                           # AI coding agent contract, session rules, & log specifications
├── problem_statement.md                # Official challenge problem statement and specification
├── requirements.txt                    # Production & test Python dependencies
├── output.csv                          # Final 518-case submission output file
├── log.txt                             # Unbroken development transcript & audit log
├── code.zip                            # Packaged submission archive (267 KB)
├── dataset/                            # Authoritative participant-facing datasets
│   ├── deletion_requests.csv           # 518 evaluation requests (case_33 .. case_550)
│   ├── sample_deletion_requests.csv    # 32 public benchmark requests (case_01 .. case_32)
│   ├── sample_output.csv               # Public benchmark reference answers
│   ├── user_identities.csv             # 850 current user identity snapshots
│   ├── user_audit_log.csv              # 306 historical identity change records
│   ├── system_activity.csv             # 4,011 global platform event log entries
│   ├── deletion_rules.csv              # 15 enterprise data category policy rules
│   ├── evidence_files.csv              # 94 manifest entries mapping evidence paths
│   └── evidence/                       # Raw multimodal evidence corpus
│       ├── databases/                  # SQLite SQL snapshot dumps (primary & replicas)
│       ├── documents/                  # Customer handover & support PDFs
│       ├── images/                     # System screenshots (PNG with OCR data)
│       ├── logs/                       # Application & sync server log streams
│       └── records/                    # Plain text & JSON data exports
├── code/                               # Core Python source packages
│   ├── main.py                         # Production entry point generating output.csv
│   ├── identity/                       # Canonical & historical identity resolution
│   │   ├── resolver.py                 # IdentityResolver: email normalization, hash recovery
│   │   └── integration.py              # EvidenceIntegrator: cross-corpus identifier search
│   ├── evidence/                       # Multimodal static parsing & ingestion
│   │   ├── reader.py                   # Static reader for PDF, JSON, TXT, LOG, and PNG
│   │   ├── sql_parser.py               # Static AST SQL parser (zero dynamic execution)
│   │   └── collector.py                # EvidenceCatalog loader and manifest indexer
│   ├── timeline/                       # Temporal reconstruction and state modeling
│   │   └── reconstructor.py            # TimelineReconstructor: cutoff enforcement & causality
│   ├── policy/                         # Enterprise deletion policy evaluation
│   │   ├── loader.py                   # PolicyLoader: rules parsing and validation
│   │   ├── engine.py                   # TreatmentEngine: tombstone & retention rules
│   │   ├── mapper.py                   # Operation mapping & combination matrix
│   │   ├── temporal.py                 # Timestamp normalization and ISO validation
│   │   └── service.py                  # PolicyEvaluationService: case-level evaluation
│   ├── status/                         # Forensic status resolution & risk assessment
│   │   ├── pipeline.py                 # CaseStatusPipeline: end-to-end status determination
│   │   ├── resolver.py                 # StatusResolver: COMPLETE vs INCOMPLETE vs NOT_APPLICABLE
│   │   ├── applicability.py            # Natural language request intent classifier
│   │   ├── remaining_data.py           # Prohibited residual PII assessor
│   │   ├── risk_assessment.py          # Data recreation & restore risk assessor
│   │   ├── aggregator.py               # Multi-resource state aggregator
│   │   └── explanation.py              # Grounded natural-language audit reasoning
│   ├── planner/                        # Remediation planning & lifecycle sequencing
│   │   ├── orchestrator.py             # StepPlannerOrchestrator: 3-phase plan synthesis
│   │   ├── findings.py                 # Phase 1: FINDING step generation with evidence IDs
│   │   ├── remediation.py              # Phase 2: REMEDIATION dependency ordering
│   │   ├── verification.py             # Phase 3: VERIFICATION step generation
│   │   ├── sequencer.py                # Step numbering (1..N) and canonical tie-breaking
│   │   ├── validator.py                # Output contract enforcement & schema validator
│   │   └── models.py                   # StepPlan dataclasses and serialization
│   └── evaluation/                     # Evaluation, benchmarking, and telemetry
│       ├── main.py                     # Evaluation entry point (benchmarks & custom cases)
│       ├── validate_output.py          # Standalone output.csv contract validator
│       ├── evaluate_output.py          # Benchmark comparison & mismatch diagnostic engine
│       ├── telemetry.py                # Runtime model usage & cost accounting framework
│       ├── usage_ledger.json           # Machine-readable telemetry ledger for run
│       ├── evaluation_report.md        # Comprehensive evaluation & custom case report
│       └── usage_report.md             # Truthful model usage & cost accounting report
└── reports/                            # Comprehensive Phase 0–15 audit & release reports
    ├── master_project_audit.md         # Read-only repository audit
    ├── phase_12_full_run_verification_report.md # Phase 12 release gate report
    ├── phase_13_final_verification_report.md   # Phase 13 packaging & build report
    └── phase_15_readme_audit_report.md         # Final documentation audit report
```

---

## 4. Input Datasets and Evidence Corpus

| Dataset | Row Count | Primary Role | Description & Integrity Rules |
| :--- | :---: | :--- | :--- |
| `dataset/deletion_requests.csv` | 518 | **Evaluation Target** | Requests `case_33` through `case_550`. Fields: `case_id, email, requested_at, reported_status, reported_at, audit_at, request_text`. |
| `dataset/sample_deletion_requests.csv` | 32 | Benchmark Input | Reference requests `case_01` through `case_32` for public benchmark calibration. |
| `dataset/sample_output.csv` | 32 | Reference Answers | Format and decision benchmark for public sample requests. |
| `dataset/user_identities.csv` | 850 | Identity Snapshot | Current user identity records (`user_id, name, email, phone, email_hash, updated_at`). |
| `dataset/user_audit_log.csv` | 306 | Identity Audit Trail | Historical modifications to email, phone, or name across 196 users. |
| `dataset/system_activity.csv` | 4,011 | Global Event Stream | Global deletion, backup, restore, sync, and index events across platforms. |
| `dataset/deletion_rules.csv` | 15 | Policy Matrix | Data category rules defining mandatory `DELETE`, `REDACT`, `ANONYMIZE`, `RETAIN`, or `ACCOUNT_TOMBSTONE` actions. |
| `dataset/evidence_files.csv` | 94 | Evidence Manifest | Maps 94 evidence files to source systems and capture timestamps (`captured_at`). |
| `dataset/evidence/` | 94 files | Multimodal Evidence | Raw files across databases (SQL snapshots), documents (PDF), images (PNG), logs, and exports. |

### Multimodal Static Evidence Handling
* **SQL Snapshots**: Parsed using a custom static AST tokenizer (`code/evidence/sql_parser.py`) without dynamic execution. Differentiates primary tables from regional, reporting, and failover replicas to detect replication drift.
* **PDF Documents**: Ingested via `pypdf` extraction of text and metadata locators.
* **PNG Screenshots**: Structured text and field extraction from application screens.
* **Logs & JSON Records**: Parsed line-by-line with provenance tracking (`file_id`, line number, byte offset).

---

## 5. Output CSV Contract Specification

The solution generates `output.csv` at the repository root with the exact header:

```text
case_id,deletion_status,steps_json
```

### 5.1 Output Requirements
1. **Row Count**: Exactly **518 data rows** (+ 1 header row) sorted consecutively by `case_id` (`case_33` through `case_550`).
2. **Allowed Statuses**: Exactly one of `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`.
3. **Step Structure (`steps_json`)**: Valid JSON array containing consecutive 1-indexed objects:
   ```json
   {
     "step_no": 1,
     "phase": "FINDING",
     "system_id": "account_service",
     "resource_id": "account_005",
     "operation": "REPORT_REMAINING_RECORD",
     "state": "PRESENT",
     "evidence_id": "evidence_01"
   }
   ```
4. **Permitted Operation & State Combinations**:
   * **FINDING**:
     * `REPORT_REMAINING_RECORD` $\to$ `PRESENT` (Evidence ID required)
     * `REPORT_EXPOSED_PII` $\to$ `PRESENT` (Evidence ID required)
     * `REPORT_ACTIVE_DATA_FLOW` $\to$ `ACTIVE` (Evidence ID required)
     * `REPORT_RESTORE_RISK` $\to$ `ACTIVE` (Evidence ID required)
   * **REMEDIATION**:
     * `DISABLE_DATA_FLOW` $\to$ `DISABLED` (`evidence_id = ""`)
     * `BLOCK_RESTORE` $\to$ `BLOCKED` (`evidence_id = ""`)
     * `DELETE_RECORD` $\to$ `ABSENT` (`evidence_id = ""`)
     * `REDACT_RECORD` $\to$ `REDACTED` (`evidence_id = ""`)
     * `ANONYMIZE_RECORD` $\to$ `ANONYMIZED` (`evidence_id = ""`)
   * **VERIFICATION**:
     * `VERIFY_RECORD_ABSENT` $\to$ `ABSENT`
     * `VERIFY_RECORD_PRESENT` $\to$ `PRESENT` (Policy retention)
     * `VERIFY_RECORD_REDACTED` $\to$ `REDACTED`
     * `VERIFY_RECORD_ANONYMIZED` $\to$ `ANONYMIZED`
     * `VERIFY_DATA_FLOW_DISABLED` $\to$ `DISABLED`
     * `VERIFY_RESTORE_BLOCKED` $\to$ `BLOCKED`
5. **Lifecycle Sequencing Rules**:
   * `NOT_APPLICABLE`: Strictly 0 steps (`steps_json = []`).
   * `COMPLETE`: Contains only admissible evidence-backed `VERIFICATION` steps proving the compliant state at $T \le T_{\text{audit}}$.
   * `INCOMPLETE`: Enforces linear ordering `FINDING` $\to$ `REMEDIATION` $\to$ `VERIFICATION`. Remediation actions disable active sync flows and block backup restore vectors *before* mutating dependent records.

---

## 6. Installation, Setup, and Prerequisites

### Prerequisites
* **Python**: Version 3.10, 3.11, 3.12, 3.13, or 3.14.
* **Operating System**: macOS, Linux, or Windows.
* **Disk Space**: ~300 MB for repository and virtual environment.

### Setup Instructions

1. **Clone the repository and enter directory**:
   ```bash
   git clone https://github.com/interviewstreet/hackerrank-orchestrate-october26.git
   cd hackerrank-orchestrate-october26
   ```

2. **Create and activate a virtual environment**:
   * On **macOS / Linux**:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
   * On **Windows**:
     ```powershell
     python -m venv .venv
     .venv\Scripts\Activate.ps1
     ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

Dependencies in `requirements.txt`:
```text
pandas>=2.0.0
pypdf>=4.0.0
pillow>=10.0.0
python-dateutil>=2.8.0
pytest>=8.0.0
```

---

## 7. How to Run the Pipeline and Verify Results

### 7.1 Production Execution (Generate `output.csv`)
Run the production pipeline to process all 518 evaluation requests and write the final predictions to root `output.csv`:

```bash
python3 code/main.py
```

* **Expected Output**: Processes 518/518 requests in ~31 seconds (throughput: ~22 cases/sec). Emits root [output.csv](file:///Users/harsh/hackerrank-orchestrate-october26/output.csv) with 518 data rows. Exit code `0`.

### 7.2 Independent Output Contract Validation
Validate that the generated `output.csv` conforms to all schema, lifecycle, numbering, ordering, and evidence citation rules:

```bash
python3 code/evaluation/validate_output.py output.csv
```

* **Validation Summary**:
  ```text
  Overall Valid:          True
  Total Rows:             518
  Status Distribution:    {'COMPLETE': 153, 'INCOMPLETE': 355, 'NOT_APPLICABLE': 10}
  Total Steps Generated:  2448
  Lifecycle Violations:   0
  Numbering Violations:   0
  Ordering Violations:    0
  Total Error Count:      0
  ```

### 7.3 Evaluation Benchmark & Custom Test Suite
Execute the benchmark comparison against `sample_output.csv` and verify all custom edge-case scenarios:

```bash
python3 code/evaluation/main.py
```
*(Or run `python3 code/evaluation/evaluate_output.py` for comprehensive row, field, and sequence diagnostics).*

* **Benchmark Results**:
  * **87.50% (28/32)** case-level status accuracy on public reference samples.
  * **4/4 (100%)** pass rate on custom edge-case evaluation scenarios.

### 7.4 Running the Test Suite
Run the comprehensive regression test suite covering all subsystems:

```bash
pytest code/ -q
```

* **Expected Result**: **`821 passed, 24 subtests passed in ~160 seconds`** (Exit code `0`).

---

## 8. Evaluation Methodology and Benchmark Results

The solution's evaluation strategy is detailed in [code/evaluation/evaluation_report.md](file:///Users/harsh/hackerrank-orchestrate-october26/code/evaluation/evaluation_report.md) and summarized below:

### 8.1 Public Sample Comparison (`sample_output.csv`)
* **Total Evaluated Cases**: 32 public benchmark requests (`case_01` through `case_32`).
* **Status Match Rate**: **87.50% (28/32)**.
* **Forensic Discrepancy Analysis**: 4 sample cases (`case_01`, `case_02`, `case_03`, `case_04`) diverged between reference `COMPLETE` and forensic `INCOMPLETE`.
  * *Root Cause*: The synthetic public reference answers accepted workflow claim `reported_status="COMPLETE"` as proof of deletion. Our forensic agent discovered residual personal data in secondary attachment logs, correctly classifying them as `INCOMPLETE` pursuant to the core challenge rule: *"Treat activity logs, workflow statuses, and system messages as claims unless the available evidence establishes the resulting state."*

### 8.2 Custom Evaluation Scenarios
Four rigorous custom scenarios were designed, implemented, and verified:
1. `custom_replica_leak_01`: Detects residual data in support attachment platforms and enforces mandatory 3-phase remediation lifecycle (`PASS`).
2. `custom_backup_risk_02`: Identifies unblocked backup snapshot restore risks (`REPORT_RESTORE_RISK`), mitigating via `BLOCK_RESTORE` (`PASS`).
3. `custom_access_request_03`: Subject Access Request classification (GDPR Art. 15): non-deletion request yields `NOT_APPLICABLE` with `steps_json = []` (`PASS`).
4. `custom_retention_complete_04`: Compliant policy retention and tombstone verification citing admissible evidence $\le T_{\text{audit}}$ (`PASS`).

---

## 9. Model Usage Accounting and Cost Telemetry

A complete accounting of runtime computation and model telemetry is recorded in [code/evaluation/usage_report.md](file:///Users/harsh/hackerrank-orchestrate-october26/code/evaluation/usage_report.md) and [code/evaluation/usage_ledger.json](file:///Users/harsh/hackerrank-orchestrate-october26/code/evaluation/usage_ledger.json):

| Metric | Measured Fact / Value | Source / Semantic |
| :--- | :--- | :--- |
| **Execution Scope** | 518 Evaluation Requests (`prod-run-518-20261025`) | `dataset/deletion_requests.csv` |
| **Model Invocations** | **0 External API Calls** | Local deterministic Python pipeline |
| **Input Tokens** | **0** | Exact measured quantity |
| **Output Tokens** | **0** | Exact measured quantity |
| **Total Tokens** | **0** | Exact measured quantity |
| **Total Billable Cost** | **$0.000000 USD** | Actual verified commercial charge |
| **Wall-Clock Duration** | **31.26 seconds** | Measured via monotonic clock |
| **Planning Throughput** | **22.14 cases / second** | High-efficiency local compute |

*Adherence to Prompt & Challenge Rules*: The pipeline is an offline, deterministic forensic engine. No external LLM, model API, or commercial inference endpoint was queried during production execution. Per challenge rules, no token counts, pricing, or API calls were fabricated.

---

## 10. Packaging and Submission Deliverables

Per challenge specifications, the submission consists of four primary artifacts:

| Item | File Path | Description | Verification Status |
| :--- | :--- | :--- | :---: |
| **Code Package** | [code.zip](file:///Users/harsh/hackerrank-orchestrate-october26/code.zip) | Standalone package containing source modules, documentation, and evaluation reports. | **VERIFIED** (267 KB, SHA-256: `8de76597...`) |
| **Prediction File** | [output.csv](file:///Users/harsh/hackerrank-orchestrate-october26/output.csv) | Final predictions for all 518 evaluation requests sorted by `case_id`. | **VERIFIED** (518 rows, 0 contract violations) |
| **Chat Transcript** | [log.txt](file:///Users/harsh/hackerrank-orchestrate-october26/log.txt) | Complete development audit trail following `AGENTS.md` §5.1 / §5.2 specifications. | **VERIFIED** (0 secret leaks, exact metadata) |
| **AI Interview** | Live Session | Technical defense of architecture, timeline cutoffs, and policy engine. | **READY** (Documented in reports) |

### 10.1 Packaging Verification (`code.zip`)
To package `code.zip` from the repository root without bundling datasets or virtual environments:

* **macOS / Linux**:
  ```bash
  zip -r code.zip README.md requirements.txt code evaluation -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/.git/*" "*/.DS_Store" "*/*.bak"
  ```
* **Windows (PowerShell)**:
  ```powershell
  Compress-Archive -Path README.md, requirements.txt, code, evaluation -DestinationPath code.zip -Force
  ```

### 10.2 Clean-Environment Package Verification
As documented in [reports/phase_13_final_verification_report.md](file:///Users/harsh/hackerrank-orchestrate-october26/reports/phase_13_final_verification_report.md), `code.zip` was extracted to an external temporary directory outside the workspace and tested under clean conditions:
1. **Clean Test Suite**: All 821 tests passed in 160.82s.
2. **Clean Production Run**: Executed `code/main.py` against external dataset, generating 518 valid rows with 0 errors.
3. **Bit-for-Bit Output Reconciliation**: Output generated by the extracted package was verified **100% bit-for-bit identical** (493,049 bytes) to the repository root `output.csv`.

---

## 11. Phase 0–15 Implementation Inventory Table

| Phase | Phase Title & Responsibility | Implementation Evidence | Test / Validation Evidence | Current Status |
| :---: | :--- | :--- | :--- | :---: |
| **0** | Project Setup & Baseline Inspection | Inspected `AGENTS.md`, README, and challenge requirements | Verified starter execution & test baselines | **VERIFIED COMPLETE** |
| **1** | Dataset Schema & Inventory Audit | Inspected all 8 CSVs and 94 evidence files | Checked headers, types, and manifest files | **VERIFIED COMPLETE** |
| **2** | Structural Data Validation | Referential integrity check across users and activity | Created `reports/data_validation_report.md` | **VERIFIED COMPLETE** |
| **3A** | Identity Resolution Engine | `code/identity/resolver.py`: Email normalization, hash recovery | `code/identity/test_resolver.py` (7 passed) | **VERIFIED COMPLETE** |
| **3B** | Evidence Integration Layer | `code/identity/integration.py`: Multimodal identifier search | `code/identity/test_integration.py` (22 passed) | **VERIFIED COMPLETE** |
| **4** | Multimodal Evidence Extraction | `code/evidence/`: Static SQLite AST parser, PDF/PNG readers | `code/evidence/test_reader.py` (21 passed) | **VERIFIED COMPLETE** |
| **5** | Timeline Reconstruction & Cutoffs | `code/timeline/reconstructor.py`: Cutoff enforcement ($T \le T_{\text{audit}}$) | `code/timeline/test_reconstructor.py` (28 passed) | **VERIFIED COMPLETE** |
| **6** | Deletion Policy Engine | `code/policy/`: Tombstone retention vs. PII redaction rules | `code/policy/test_engine.py` (19 passed) | **VERIFIED COMPLETE** |
| **7** | Forensic Status Resolver | `code/status/`: COMPLETE vs INCOMPLETE vs NOT_APPLICABLE | `code/status/test_resolver.py` (67 passed) | **VERIFIED COMPLETE** |
| **8** | Step Planner & Lifecycle Remediation | `code/planner/`: Ordered remediation plans & consecutive numbering | `code/planner/test_lifecycle_remediation.py` (538 passed) | **VERIFIED COMPLETE** |
| **9** | Output Generation & Packaging | `code/main.py`: Generates root `output.csv` (518 rows) | `code/evaluation/validate_output.py` (100% valid) | **VERIFIED COMPLETE** |
| **10** | Benchmark Evaluation & Custom Cases | `code/evaluation/evaluate_output.py`: Benchmark runner | 87.50% sample status match; 4/4 custom cases | **VERIFIED COMPLETE** |
| **11** | Model Usage Accounting & Telemetry | `code/evaluation/telemetry.py`: Usage accounting ledger | `code/evaluation/test_usage_telemetry.py` (15 passed) | **VERIFIED COMPLETE** |
| **12** | Full Production Run & Edge-Case Audit | Executed 518 cases; audited 26 edge-case categories | Multi-run determinism verified (0 diffs) | **VERIFIED COMPLETE** |
| **13** | Packaging & Clean-Environment Audit | Rebuilt `code.zip` (267 KB); clean directory testing | Clean extraction passed all 821 tests & prod run | **VERIFIED COMPLETE** |
| **14** | Transcript & Logging Verification | `log.txt`: Strict compliance with `AGENTS.md` §5.1 / §5.2 | Verified 0 secret leaks; exact metadata | **VERIFIED COMPLETE** |
| **15** | Final Documentation & README Audit | `README.md` & `reports/phase_15_readme_audit_report.md` | Comprehensive documentation audit & check | **VERIFIED COMPLETE** |

---

## 12. Troubleshooting and Known Limitations

* **Offline Determinism**: The system intentionally does not invoke remote LLM APIs at runtime. It executes as a deterministic, reproducible Python engine.
* **External Dataset Requirement**: `code.zip` deliberately excludes `dataset/` per competition guidelines. When evaluating from `code.zip`, ensure `dataset/` is mounted or placed in the working directory next to `code/`.
* **Public Sample Divergence (4 cases)**: As demonstrated in Section 8, the 4 divergent public sample cases reflect forensic rigor where our agent refuses to accept unverified workflow completion claims in the presence of residual attachment logs.

---

## 13. Official Challenge & Submission Link

The official October challenge and submission URL is:

👉 **[HackerRank Orchestrate October 2026: Ghost Data Still Exists](https://wwww.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists)**

Upload the following verified deliverables:
1. `code.zip` (Code package with documentation and reports)
2. `output.csv` (Final 518-case prediction file)
3. `log.txt` (Complete agent conversation transcript)
