# Satyapan dataset validation report

Final run `run_20261030T222654Z` (UTC). Raw output: `results/audit/run_20261030T222654Z/dataset.log` and `dataset_validation.json`. Analysis: section J of `docs/FINAL_TEST_AUDIT.md`.

## Verdict

**The dataset has NOT been collected.** Claim manifest: 0 of 100 rows filled. Detector manifest: 0 of 120 rows filled. No accuracy figure exists for Satyapan and none may be quoted. Nothing was generated to fill the gap.

## Checks

* Plan totals: dev 30, test 70, declared {'dev': 30, 'test': 70, 'all': 100}. Consistent.
* Test-split ground truth from the plan: {'TRUE': 21, 'FALSE': 46, 'UNRESOLVED': 3}.
* FALSE categories whose expected verdict is UNVERIFIED by design (safe abstention, report separately): ['M'].
* Detector plan by split and label: {'dev/ai': 20, 'dev/real': 20, 'test/ai': 40, 'test/real': 40}.
* Validator on the manifest: exit 0, `WARNING 100 of 100 rows are still empty templates | 100 rows, 0 filled, 0 errors`.
* Near-duplicate leakage probe (a resized, recompressed copy of a dev image placed in test): DETECTED. Before the audit fix the validator only compared SHA-256 hashes and missed this (`audit_logs/13_dataset_audit_baseline.log`).

## Raw output

```
### 2026-10-30T22:33:48Z dataset: python audit/dataset_audit.py --out results/audit/run_20261030T222654Z/dataset_validation.json
claim manifest eval/manifest_template.csv: 0/100 rows filled
detector manifest eval/detector_manifest_template.csv: 0/120 rows filled, {'dev/ai': 20, 'dev/real': 20, 'test/ai': 40, 'test/real': 40}
plan dev 30 test 70 (declared {'dev': 30, 'test': 70, 'all': 100}), test truth {'TRUE': 21, 'FALSE': 46, 'UNRESOLVED': 3}
FALSE claims expected to abstain (UNVERIFIED) by design: ['M']
validator: WARNING 100 of 100 rows are still empty templates | 100 rows, 0 filled, 0 errors
PASS  near-duplicate leak detected: ['LEAKAGE (possible near-duplicate image, review): test T matches dev D (phash+orb)']
DATASET NOT COLLECTED: no accuracy figure can be reported
```
