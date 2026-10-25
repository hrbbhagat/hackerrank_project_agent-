# Phase 3 — Identity Resolution Audit Report

## 1. Objective

Resolve deletion requests to the correct user using current identity snapshots and verified historical identifiers, respecting each case's `audit_at` cutoff.

## 2. Implementation

- Resolver: `code/identity/resolver.py`
- Persistent tests: `code/identity/test_resolver.py`
- Identity snapshot: `dataset/user_identities.csv`
- Identity history: `dataset/user_audit_log.csv`

The resolver supports email, email hash, and phone identifiers. Historical audit events are considered only when their timestamps are at or before the relevant cutoff for historical identifier collection.

## 3. Validation Results

| Check | Result |
|---|---:|
| Current identities loaded | 850 |
| Users with identity audit events | 196 |
| Audit-log events examined | 306 |
| Email values examined across current and historical data | 957 |
| Cross-user email collisions found | 0 |
| Deletion requests examined | 518 |
| Requests resolved uniquely | 518 |
| Ambiguous requests | 0 |
| Unresolved requests | 0 |
| Events later than their user's snapshot `updated_at` | 0 |
| Persistent unit tests passed | 7 of 7 |

## 4. Test Coverage

The persistent test suite verifies:

1. Dataset loading.
2. Historical email resolution.
3. Unknown email handling.
4. Empty email handling.
5. Ambiguous email handling.
6. UTC cutoff timestamp parsing.
7. Reconstructed state comparison against the `user_35` identity snapshot.

Additional manual checks verified the tested historical timestamp boundaries for `user_35`.

## 5. Findings

- Every deletion request email resolved to exactly one user under the implemented resolver logic and that case's `audit_at` cutoff.
- No cross-user email collisions were found in the examined current and historical email values.
- The tested reconstructed state for `user_35` matched the current snapshot for email, email hash, and phone.
- All seven persistent tests passed when run directly using `python3 code/identity/test_resolver.py -v`.

## 6. Limitations and Remaining Work

- Unique resolution coverage does not independently prove that every resolved identity is semantically correct.
- The automated suite currently tests a limited set of historical boundary examples rather than every identity transition.
- Identity resolution alone does not prove deletion. Evidence collection, policy interpretation, remediation requirements, and verification must still be implemented and audited separately.
- The final end-to-end deletion audit must ensure that evidence used for each case is valid and available by its `audit_at` cutoff.

## 7. Current Status

**Identity resolution implementation and initial validation: PASS.**

Phase 3 should receive final sign-off after the identity-history boundary tests and integration with the deletion evidence pipeline have been reviewed.

## 8. Extended Historical Boundary Validation

An additional historical reconstruction test was executed against all recorded
email, email-hash, and phone audit transitions.

| Check | Result |
|---|---:|
| Historical boundary checks | 918 |
| Failures | 0 |
| Result | PASS |

For each recorded identifier change, the resolver was checked one second before,
at, and one second after the event timestamp. The reconstructed identifier
values matched the independently derived expected values in all tested cases.

### Interpretation

This supports the correctness of historical reconstruction for the recorded
transitions and tested boundary timestamps. It does not independently prove
that all deletion evidence is valid or that the overall deletion audit is
correct.

### Remaining Phase 3 Work

- Integrate identity resolution with evidence collection and the main audit pipeline.
- Verify that evidence searches use the resolved user and applicable historical identifiers.
- Run end-to-end tests to confirm cutoff enforcement across identity resolution and evidence processing.
