# Reconstruction baseline

| Field | Value |
|---|---|
| Source repository | `PeterJFrancoIII/swipe-dating` |
| Source branch | `main` |
| Source commit | `5c6b35e8b133f4b34224785eb4fc1e7ab61423a4` |
| Baseline date | 2026-07-22 |
| Target repository | `PeterJFrancoIII/swipe-dating-python` |
| Target runtime | Python 3.12+ |

The source behavior was inspected directly at the pinned commit. The supplied DOCX rebuild specification was rendered and reviewed page-by-page before implementation. Broad product-research ideas are hypotheses only; the pinned implementation and explicit safety boundaries control behavior.

The target repository initially contained an incomplete single-part bootstrap archive. It could not be reconstructed because the script expected `source_*` parts while only `part_00` existed, and the decoded gzip stream ended early. This branch replaces that non-runnable shell with the recreated source.
