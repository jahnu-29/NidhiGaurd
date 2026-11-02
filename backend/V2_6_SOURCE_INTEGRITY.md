# V2.6 source integrity

**V2.6 is an intentional evolution of the application code, made after the frozen
V2.3–V2.5 evaluation runs.** It adds and modifies files under `backend/app/**` and
`src/**` (the investigator workflow and audit trail). It does **not** touch the V1
intelligence engine, risk formulas, thresholds or scores, authentication/authorization
behaviour, or any V2.1–V2.5 evaluation data, labels, predictions, results or manifests.

## Two separate questions

| Question | Verified by | Source of truth |
|---|---|---|
| **Historical freeze** — are the V2.3/V2.4/V2.5 experiments' recorded manifests and artifacts intact? | `evaluation/tests/*` (the five "frozen" tests) | the manifests recorded inside `baseline_predictions_meta.json`, `ablation/ablation_predictions_meta.json`, `calibration/calibration_metadata.json` — **immutable, never regenerated** |
| **Current V2.6 source** — does the application source on disk match what V2.6 shipped? | `backend/tests/test_v2_6_source_integrity.py` | `backend/v2_6_source_manifest.json` |

```
V1 source ──> V2.3 / V2.4 / V2.5 experiments ──> historical manifests (immutable evidence)

V2.6 intentionally changes backend/app + src ──> V2.6 manifest ──> current tree verified against it
```

## How the historical tests treat V2.6

The recorded `v1_backend_and_frontend_source` group is a *snapshot of the V1 code the
experiments ran on*. The five historical freeze tests still compare every group exactly
as before (V1 intelligence, V2.1 dataset/spec, V2.2, V2.3, V2.4). In the V1 backend/frontend
group they tolerate **only** the files listed under `v2_6_changes_from_v1_snapshot` in the
V2.6 manifest. Any other difference there — for example an unplanned edit to
`src/pages/DashboardPage.tsx` — still fails.

`test_v2_6_source_integrity.py` also proves the declared list is *exactly* the real
difference between the recorded V1 snapshot and the tree on disk, so the allowance can't
drift, and pins the SHA-256 of the three historical manifest files so they cannot be edited
silently.

## The V2.6 manifest

* SHA-256; sorted, repo-relative POSIX paths; UTF-8; LF newlines; no timestamps or machine paths.
* Text files are hashed with CRLF normalised to LF, so a Windows checkout does not change a hash.
* Stored in `backend/` (outside `backend/app/**`) so it never hashes itself.

```
python -m backend.v2_6_integrity --check   # verify; exit 1 on any mismatch
python -m backend.v2_6_integrity --write   # regenerate — only when an application source change is intended
```

Never regenerate to make an unexpected difference disappear, and never regenerate the
historical V2.3–V2.5 manifests or results.
