# CiteVerify Custom Verification Evaluation Dataset

## 1. Executive Summary & Purpose

Automated verification of scientific assertions requires benchmarking against nuanced failure modes that frequently arise in scientific communication: cherry-picked statistics, extrapolation of in vitro findings to clinical human cures, subtle numerical transcriptions errors, outdated paradigms, and citation swaps.

The **CiteVerify Custom Verification Evaluation Dataset** comprises **32 manually reviewed and curated scientific claim–evidence test cases** designed to validate the Natural Language Inference (NLI) and verification engine (**Stage 6 — Claim Verification**).

---

## 2. Dataset Design & Taxonomy

The dataset evaluates performance across the 6 standard CiteVerify verdicts defined in `app.models.schemas.VerdictEnum`:
1. `supported`: The evidence directly and comprehensively backs up the claim.
2. `partially_supported`: The evidence supports the core premise, but omits an essential qualification, condition, or boundary condition.
3. `unsupported`: The evidence discusses the general scientific domain or method, but does not substantiate the specific assertion made.
4. `contradictory`: The evidence directly refutes or contradicts the claim.
5. `potentially_outdated`: The claim reflects historical literature that was superseded by later scientific consensus.
6. `insufficient_evidence`: The evidence is truncated, paywalled, or too ambiguous for a reliable automated judgment, triggering explicit model abstention.

### Error Category Taxonomy

In addition to the primary verdict, each case is labeled with a specific error or discrepancy category:
- `none`: Clean, valid factual citation.
- `scope_overgeneralization`: Laboratory, in vitro, or animal findings uncritically generalized to human clinical applications or universal contexts.
- `unsubstantiated_omnibus_claim`: Overreaching claims of universal dominance across all benchmarks when empirical gains are mixed.
- `magnitude_inflation`: The claimed effect size significantly exceeds the measured empirical metric.
- `absolute_assertion_inflation`: Claims of 100% elimination or zero error when residual errors remain.
- `unsupported_inference`: Extrapolations or assertions not stated in the source text.
- `unsupported_assertion`: Biological or mechanistic assertions contradicted by known developmental pathways.
- `contradiction`: Inversion of measured trends, rates, or knockout effects.
- `outdated_consensus`: Claims relying on historical literature superseded by modern high-throughput or standard consensus.
- `numerical_mismatch`: Numeric discrepancies between the claim and the source tables or text.
- `citation_mismatch`: Citations citing the wrong paper (e.g. citing an architecture paper for a mathematical approximation theorem).
- `insufficient_data`: Truncated, paywalled, or ongoing clinical trial text requiring abstention.
- `ambiguous_findings`: Mixed or topology-dependent findings preventing definitive verification.

---

## 3. Benchmark Cases Catalog

Below is the complete inventory of all 32 curated evaluation test cases:

| Case ID | Domain | Error Category | Expected Verdict | Expected Abstention |
|---|---|---|---|---|
| **EVAL-001** | Artificial Intelligence | `none` | `supported` | No |
| **EVAL-002** | Artificial Intelligence | `none` | `supported` | No |
| **EVAL-003** | Biomedicine | `none` | `supported` | No |
| **EVAL-004** | Genetics & Molecular Biology | `none` | `supported` | No |
| **EVAL-005** | Materials Science | `none` | `supported` | No |
| **EVAL-006** | Biomedicine | `scope_overgeneralization` | `partially_supported` | No |
| **EVAL-007** | Artificial Intelligence | `unsubstantiated_omnibus_claim` | `partially_supported` | No |
| **EVAL-008** | Cardiovascular Medicine | `magnitude_inflation` | `partially_supported` | No |
| **EVAL-009** | Artificial Intelligence | `absolute_assertion_inflation` | `partially_supported` | No |
| **EVAL-010** | Artificial Intelligence | `unsupported_inference` | `unsupported` | No |
| **EVAL-011** | Climate Science | `unsupported_inference` | `unsupported` | No |
| **EVAL-012** | Neuroscience | `unsupported_assertion` | `unsupported` | No |
| **EVAL-013** | Materials Science | `unsupported_inference` | `unsupported` | No |
| **EVAL-014** | Biomedicine | `contradiction` | `contradictory` | No |
| **EVAL-015** | Artificial Intelligence | `contradiction` | `contradictory` | No |
| **EVAL-016** | Climate Science | `contradiction` | `contradictory` | No |
| **EVAL-017** | Neuroscience | `contradiction` | `contradictory` | No |
| **EVAL-018** | Genetics & Genomics | `outdated_consensus` | `potentially_outdated` | No |
| **EVAL-019** | Neuroscience | `outdated_consensus` | `potentially_outdated` | No |
| **EVAL-020** | Astrophysics & Planetary Science | `outdated_consensus` | `potentially_outdated` | No |
| **EVAL-021** | Oncology | `scope_overgeneralization` | `partially_supported` | No |
| **EVAL-022** | Artificial Intelligence | `scope_overgeneralization` | `unsupported` | No |
| **EVAL-023** | Biogerontology | `scope_overgeneralization` | `partially_supported` | No |
| **EVAL-024** | Artificial Intelligence | `numerical_mismatch` | `unsupported` | No |
| **EVAL-025** | Genetics & Biotechnology | `numerical_mismatch` | `unsupported` | No |
| **EVAL-026** | Astrophysics | `numerical_mismatch` | `unsupported` | No |
| **EVAL-027** | Computer Science & ML | `citation_mismatch` | `unsupported` | No |
| **EVAL-028** | Microbiology & Pharmacology | `citation_mismatch` | `unsupported` | No |
| **EVAL-029** | Structural Biology | `citation_mismatch` | `contradictory` | No |
| **EVAL-030** | Pediatric Medicine | `insufficient_data` | `insufficient_evidence` | **Yes** |
| **EVAL-031** | Environmental Epidemiology | `insufficient_data` | `insufficient_evidence` | **Yes** |
| **EVAL-032** | Quantum Computing | `ambiguous_findings` | `insufficient_evidence` | **Yes** |

---

## 4. In-Depth Case Review Samples

### 4.1 Supported Claim (`EVAL-001`)
- **Claim:** FlashAttention reduces wall-clock execution time by 2-4x and memory footprint by tiling attention computation in SRAM.
- **Source Evidence:** *"FlashAttention computes exact attention with fewer memory accesses by tiling the input into SRAM blocks... achieving 2-4x wallclock speedup on GPT-2 and reducing memory footprint from quadratic to linear in sequence length."*
- **Verdict:** `supported` (Strength: 0.90–1.00)
- **Reasoning:** Direct correspondence between claim metrics, mechanism (SRAM tiling), and empirical benchmarks.

### 4.2 Scope Overgeneralization (`EVAL-006`)
- **Claim:** Metformin universally extends median lifespan across all adult mammalian species by activating AMPK.
- **Source Evidence:** *"Metformin extended median lifespan by 5.8% in male C57BL/6 mice via AMPK activation, but failed to show significant lifespan extension in genetically heterogeneous male mice or female cohorts."*
- **Verdict:** `partially_supported` (Strength: 0.75–0.90)
- **Reasoning:** AMPK pathway and rodent lifespan extension are substantiated, but the claim overgeneralizes to all mammalian species, ignoring the null findings in female and heterogeneous mouse cohorts.
- **Warning:** `OVERGENERALIZATION_WARNING: Claim asserts universal mammalian lifespan extension, but source observed effect only in specific male mouse cohorts.`

### 4.3 Direct Contradiction (`EVAL-014`)
- **Claim:** Hydroxychloroquine significantly reduced 28-day mortality in hospitalized patients with severe COVID-19 infection.
- **Source Evidence:** *"In the RECOVERY randomized trial, 25.7% of patients in the hydroxychloroquine group died within 28 days compared to 23.5% in the usual care group (rate ratio, 1.09; 95% CI, 0.97 to 1.23; p=0.15). The trial concluded that hydroxychloroquine did not reduce mortality."*
- **Verdict:** `contradictory` (Strength: 0.92–1.00)
- **Reasoning:** The clinical trial directly refutes the claim; mortality was higher in the intervention arm and the trial found no evidence of survival benefit.

### 4.4 Outdated Consensus (`EVAL-018`)
- **Claim:** The human genome contains approximately 100,000 protein-coding genes according to comprehensive transcript mapping.
- **Source Evidence:** *"Early hybridization and EST analyses (Fields et al., 1994) estimated between 80,000 and 100,000 protein-coding genes in the human genome. Modern consensus from the Human Genome Project, GENCODE, and CHM13 refines this to approximately 19,900-20,400 protein-coding genes."*
- **Verdict:** `potentially_outdated` (Strength: 0.85–0.98)
- **Reasoning:** The claim accurately cites pre-genomic 1990s estimations, but this consensus has been replaced by modern high-quality whole-genome sequencing establishing ~20,000 protein-coding genes.

### 4.5 Numerical Mismatch (`EVAL-024`)
- **Claim:** BERT-Large achieved a fine-tuned F1 score of 93.2 on the SQuAD v1.1 question answering development set.
- **Source Evidence:** *"Table 2: BERT-Large achieves 90.9 F1 on SQuAD v1.1 dev (84.1 EM), while BERT-Base achieves 88.5 F1."*
- **Verdict:** `unsupported` (Strength: 0.88–0.98)
- **Reasoning:** Direct numerical discrepancy: the claim states 93.2 F1, whereas the published table records 90.9 F1.
- **Warning:** `NUMERICAL_MISMATCH: Claim asserts 93.2 F1, source Table 2 reports 90.9 F1.`

### 4.6 Citation Swap / Mismatch (`EVAL-027`)
- **Claim:** Convolutional neural networks were proven to be Universal Approximators for continuous functions by Krizhevsky et al. (2012).
- **Source Evidence:** *"Krizhevsky, A., Sutskever, I., & Hinton, G. E. (2012). ImageNet classification with deep convolutional neural networks. Advances in Neural Information Processing Systems. (Paper introduces AlexNet for visual object classification, not universal approximation theory)."*
- **Verdict:** `unsupported` (Strength: 0.90–0.99)
- **Reasoning:** The cited paper is AlexNet; the actual mathematical theorem was established by Hornik (1989) and Cybenko (1989). The citation is misplaced.

### 4.7 Model Abstention on Incomplete Evidence (`EVAL-030`)
- **Claim:** ClinicalMed-9B achieves 98.4% diagnostic accuracy across rare pediatric inborn errors of metabolism in active clinical deployment.
- **Source Evidence:** *"[Abstract preview only: 'We present ClinicalMed-9B for pediatric evaluations. Preliminary hospital trials are ongoing. Comprehensive diagnostic yield metrics and validation datasets will be published upon study closure.']"*
- **Verdict:** `insufficient_evidence` (Strength: 0.85–0.95)
- **Abstention Required:** `true`
- **Warning:** `ABSTENTION_REQUIRED: Source text is an ongoing trial announcement without published performance data.`

---

## 5. Evaluation Harness & Verification Metrics

CiteVerify includes an offline evaluation harness located at `tests/fixtures/evaluation_harness.py`.

### Computed Metrics
1. **Overall Accuracy:** $\frac{\sum \text{Correct}}{\text{Total Cases}}$
2. **Per-Class Precision, Recall, and F1:** Evaluated independently across each of the 6 verdict classes.
3. **Macro-F1:** Unweighted mean of F1 scores across all 6 classes:
   $$\text{Macro-F1} = \frac{1}{6} \sum_{i=1}^6 \text{F1}_i$$
4. **Abstention Accuracy:** Accuracy of predicting when to abstain on paywalled, truncated, or ambiguous snippets.
5. **Confusion Matrix:** Full $6 \times 6$ contingency matrix detailing class confusion patterns (e.g. `supported` vs `partially_supported`).

### Running the Harness Programmatically

```python
from tests.fixtures import VerificationBenchmarkHarness

harness = VerificationBenchmarkHarness()

# Pass model predictions
report = harness.evaluate(my_predictions)
print(f"Accuracy: {report.accuracy:.2%}")
print(f"Macro-F1: {report.macro_f1:.4f}")
print(f"Abstention Accuracy: {report.abstention_accuracy:.2%}")
```

### Running the Automated Tests

```powershell
pytest -v tests/test_evaluation_dataset.py
```
