# CiteVerify Evaluation Methodology

CiteVerify is designed to verify factual and empirical assertions in scientific literature. To measure the system's accuracy, reliability, and robustness once pipeline stages are implemented, CiteVerify adopts an evidence-grounded benchmarking protocol.

## Core Evaluation Metrics

1. **Resolution Precision & Recall (Stage 4):**
   - Precision of matched DOIs against gold-standard CrossRef records.
   - Evaluated on benchmark corpora (e.g. PubMed Central open access subsets).

2. **Evidence Retrieval Effectiveness (Stage 5):**
   - **MRR (Mean Reciprocal Rank)** and **NDCG@5** of extracted evidence snippets containing the exact supporting or refuting data points.
   - Distinct scoring for abstract-only versus full-text PDF parsing.

3. **Verification Accuracy & NLI Metrics (Stage 6):**
   - **Macro-F1** across 6 verdict categories:
     - `supported`
     - `partially_supported`
     - `unsupported`
     - `contradictory`
     - `potentially_outdated`
     - `insufficient_evidence`
   - **Calibration Error:** Evaluating whether predicted `verdict_strength` aligns with empirical accuracy.

4. **Human Agreement & Discrepancy Rate:**
   - Cohen's Kappa ($\kappa$) between automated verdicts and expert reviewer decisions submitted via `/api/results/{id}/review`.

## Standard Datasets for Future Validation

- **SciFact:** Scientific claim verification dataset over biomedical abstracts.
- **PubMedQA:** Question answering and reasoning benchmark over research literature.
- **Evidence-Link Gold Benchmark (Internal):** Hand-annotated papers covering machine learning, biology, and medicine.

