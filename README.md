
# SlopGate

[![tests](https://github.com/Khwahish29/Slopgate/actions/workflows/tests.yml/badge.svg)](https://github.com/Khwahish29/Slopgate/actions/workflows/tests.yml)

**Evidence-first verification and triage of AI-generated vulnerability reports.**

SlopGate is an agentic AI research system designed to evaluate the credibility of AI-generated software vulnerability reports using verifiable repository evidence.

AI-assisted security tools can generate convincing vulnerability reports that contain fabricated functions, incorrect code references, unsupported claims, or misleading conclusions. SlopGate addresses this problem by extracting technical claims, checking them against actual source code, and producing evidence-backed triage decisions.

The system combines deterministic verification, LLM-assisted analysis, repository-aware tools, and an autonomous verification agent to investigate how reliably AI-generated security reports can be grounded in real code.

## Project Overview

SlopGate implements an end-to-end vulnerability report verification workflow, from report ingestion to final evidence-backed classification.

The system includes:

- Report sanitization and prompt-injection detection.
- Structured technical claim extraction.
- Repository and version-aware source-code analysis.
- Evidence collection and traceable verification.
- Agentic reasoning with tool-assisted investigation.
- Skeptic-based verification and citation checking.
- Automated verdict generation.
- Benchmarking, statistical evaluation, and robustness analysis.

SlopGate was developed as part of the CSE 598 Agentic AI Capstone project.

**Project status:** End-to-end research prototype with implemented verification pipelines, evaluation tools, benchmark datasets, and automated testing.

## Key Features

### 1. Vulnerability Report Processing

SlopGate accepts vulnerability reports containing technical descriptions, code references, and alleged security issues.

The processing pipeline:

- Sanitizes potentially malicious or irrelevant instructions.
- Extracts primary vulnerability claims.
- Identifies referenced functions, files, and versions.
- Structures claims for repository verification.

### 2. Repository-Aware Evidence Grounding

SlopGate verifies technical claims against a specified repository checkout and revision.

Supported checks include:

- File and path existence.
- Function and symbol identification.
- Version and commit resolution.
- Source-code reference validation.
- Line-range checks.
- Reachability-related evidence checks.

The system uses repository-aware tools rather than relying exclusively on model-generated explanations.

### 3. Agentic Verification Workflow

The agent-based system coordinates evidence gathering and verification through an iterative tool-assisted workflow.

The agent can:

- Select verification tools based on report claims.
- Investigate repository evidence.
- Track intermediate verification results.
- Use evidence to support or challenge report claims.
- Produce structured verification outcomes.

The agent workflow is designed to keep repository evidence separate from untrusted report text.

### 4. Evidence Ledger and Verification

SlopGate records evidence generated during verification.

This supports:

- Traceable tool outputs.
- Evidence-backed conclusions.
- Citation and reference checking.
- Inspection of verification decisions.
- Analysis of unsupported or contradictory claims.

### 5. Skeptic and Robustness Checks

The system includes verification mechanisms intended to reduce unsupported conclusions.

These include:

- Skeptic-based review.
- Citation verification.
- Prompt-injection sanitization.
- Version-aware grounding.
- Robustness tests against misleading supporting details.

### 6. Automated Evaluation Framework

SlopGate includes an evaluation infrastructure for comparing verification systems.

Capabilities include:

- Resumable benchmark execution.
- Per-report prediction tracking.
- Cross-system result aggregation.
- Accuracy and classification metrics.
- Bootstrap confidence intervals.
- McNemar statistical testing.
- Tool and model usage accounting.
- Ablation experiments.
- D3/D4 robustness review.
- Automated reproduction workflows.

## System Architecture

SlopGate follows an evidence-first verification pipeline.

```text
                  Vulnerability Report
                          |
                          v
                 Report Sanitization
                          |
                          v
                   Claim Extraction
                          |
                          v
              Repository / Ref Resolution
                          |
                          v
                 Verification Engine
                          |
            +-------------+-------------+
            |                           |
            v                           v
    Deterministic Checks          Agentic Analysis
            |                           |
            |                    Tool Selection
            |                           |
            |                    Evidence Gathering
            |                           |
            +-------------+-------------+
                          |
                          v
                    Evidence Ledger
                          |
                          v
              Citation / Skeptic Checks
                          |
                          v
                  Verdict Generation
                          |
                          v
              Final Evidence-Backed Report
```

The architecture separates untrusted vulnerability-report content from repository evidence and verification decisions.

## Installation

### Requirements

- Python 3.9 or later
- Git
- Dependencies from `requirements.txt`
- API credentials for LLM-based systems

Clone the repository:

```bash
git clone https://github.com/Khwahish29/Slopgate.git
cd Slopgate
```

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Verify installation:

```bash
python -m slopgate.cli --help
```

## Quick Start

Run SlopGate against a local repository.

```bash
python -m slopgate.cli \
  --report "The function parse_url in src/http.c at line 120 is vulnerable." \
  --repo-root /path/to/repo \
  --ref HEAD
```

Replace `/path/to/repo` with the target repository directory.

The example claim is illustrative and does not represent a confirmed vulnerability.

## Verification Systems

SlopGate supports multiple verification approaches for comparing deterministic and agentic methods.

| System | Description |
|---|---|
| `b0` | Grep-based baseline |
| `b1` | Deterministic rule-based verification |
| `b2` | Single-model verification |
| `b2_alt` | Alternative single-model configuration |
| `b3_rules` | Fixed rule-based verification pipeline |
| `b3_llm` | LLM-assisted fixed verification pipeline |
| `agent` | Tool-using agentic verification system |

### Agent Ablations

The framework includes the following ablation configurations:

- `agent_no_skeptic` — Removes the skeptic verification stage.
- `agent_same_model_skeptic` — Uses the same model for the skeptic stage.
- `agent_no_citation` — Disables citation-related verification.
- `agent_no_history` — Disables repository-history-related functionality.

These configurations help evaluate the contribution of individual verification components.

## LLM Configuration

Deterministic baselines can run without external model credentials.

LLM-based verification requires API configuration.

Planner model:

```bash
export XAI_API_KEY="your_api_key"
export XAI_BASE_URL="your_api_base_url"
export XAI_MODEL="your_model"
```

Optional cross-model skeptic:

```bash
export SKEPTIC_API_KEY="your_api_key"
export SKEPTIC_BASE_URL="your_api_base_url"
export SKEPTIC_MODEL="your_model"
```

Do not commit API keys or other credentials to the repository.

## Benchmark Datasets

SlopGate evaluates verification behavior using multiple benchmark datasets.

| Dataset | Description |
|---|---|
| D0 | Initial sanity and verification cases |
| D1 | Generated vulnerability reports across fixture repositories |
| D2 | Public curl vulnerability reports |
| D3 | Suppression robustness cases |
| D4 | Prompt-injection robustness cases |

### D1: Generated Reports

D1 contains 164 generated vulnerability reports across four fixture repositories.

The dataset includes fabricated and grounded claims for evaluating repository-aware verification.

### D2: Real-World Reports

D2 contains a pilot collection of 18 public curl vulnerability reports.

The dataset is used to examine verification behavior on reports involving real repository structures and source-code references.

### D3: Suppression Robustness

D3 contains 32 reports derived from D1.

It evaluates whether misleading supporting details can cause verification systems to incorrectly dismiss legitimate vulnerability claims.

### D4: Prompt-Injection Robustness

D4 contains 32 reports derived from D1.

It evaluates whether instructions embedded in vulnerability reports can influence verification decisions.

## Running the Evaluation

### Run Unit Tests

```bash
python -m pytest -q
```

Or use:

```bash
make test
```

### Generate Datasets

```bash
python -m slopgate.datasets.d1
python -m slopgate.datasets.d3_d4
```

### Reproduce Offline Results

```bash
make reproduce
```

The offline reproduction workflow:

1. Runs automated tests.
2. Generates D1, D3, and D4 datasets.
3. Executes deterministic B0 and B1 baselines.
4. Aggregates evaluation results.
5. Generates cost summaries.
6. Produces D3/D4 review outputs.

The default offline workflow does not require LLM API credentials.

### Run the Resumable Evaluation Harness

```bash
python -m slopgate.evaluation.resume \
  --data corpus/d1/d1.jsonl \
  --systems b0 b1 \
  --out results/d1
```

The resumable runner saves progress so completed report evaluations can be reused when continuing an interrupted run.

### Run Multiple Verification Systems

```bash
python -m slopgate.evaluation.harness \
  --data corpus/d1/d1.jsonl \
  --systems b0 b1 b3_rules b2 b3_llm agent \
  --out results/d1
```

Model-based systems require valid API configuration.

## Evaluation Metrics

SlopGate measures verification performance using:

- Accuracy.
- Precision, recall, and F1 score.
- Confusion matrices.
- False dismissal rates.
- Hallucination detection performance.
- Model and tool usage.
- Token consumption.
- Execution latency.
- API cost when available.
- Bootstrap confidence intervals.
- Paired McNemar statistical tests.

The evaluation emphasizes evidence grounding and avoiding incorrect dismissal of legitimate vulnerability reports.

## Offline Benchmark Results

The following results were obtained from the local deterministic reproduction workflow.

| Dataset | Reports | B0 Accuracy | B1 Accuracy |
|---|---:|---:|---:|
| D1 | 164 | 63.41% | 100.00% |
| D3 | 32 | 100.00% | 87.50% |
| D4 | 32 | 81.25% | 100.00% |

The offline evaluation processed 228 reports across two deterministic systems, resulting in 456 report-system evaluations.

These results are specific to the generated datasets and local evaluation configuration. They do not represent measured performance of every LLM-based or agentic configuration.

## Statistical Analysis and Cost Tracking

The evaluation framework includes statistical tools for comparing systems.

### Bootstrap Confidence Intervals

Bootstrap resampling is used to estimate uncertainty around evaluation metrics.

### McNemar Significance Testing

Paired McNemar testing supports comparisons between systems evaluated on the same reports.

### Cost Accounting

The cost analysis tracks available resource-usage information, including:

- Model calls.
- Tool calls.
- Token counts.
- Execution time.
- API cost when pricing information is available.

## Robustness Review

The D3/D4 review functionality supports inspection of individual benchmark cases.

It can display:

- Report identifiers.
- Expected and predicted classifications.
- Transformation categories.
- Injection metadata.
- Evaluation errors.
- Available verification evidence.

Example:

```bash
python -m slopgate.evaluation.review \
  --data corpus/d4/d4.jsonl \
  --predictions results/d4/b1_predictions.jsonl \
  --errors-only
```

## Repository Structure

```text
Slopgate/
├── slopgate/
│   ├── agent_layer/       # Agentic verification and baselines
│   ├── datasets/          # Dataset generation
│   └── evaluation/        # Evaluation and statistical analysis
├── corpus/                # Datasets and fixture repositories
├── docs/                  # Research and project documentation
├── tests/                 # Unit and regression tests
├── .github/
│   └── workflows/         # GitHub Actions CI
├── Makefile               # Automated project workflows
├── requirements.txt       # Python dependencies
└── README.md
```

## Continuous Integration

SlopGate uses GitHub Actions for automated testing and reproducibility checks.

The CI workflow includes:

- Python environment setup.
- Dependency installation.
- Unit and regression tests.
- Regex and tree-sitter parser configurations.
- Offline benchmark reproduction.
- Evaluation artifact verification.

Workflow status is available through the badge at the top of this README.

## Research Limitations

SlopGate is an experimental research prototype.

Important limitations include:

- Source-code grounding alone cannot establish exploitability.
- Some vulnerabilities require runtime or environment-specific analysis.
- Real vulnerability reports may contain incomplete or ambiguous references.
- LLM-based verification introduces variability and external API dependencies.
- Generated benchmark performance may not generalize to other repositories.
- Prompt-injection defenses cannot guarantee protection against every attack.
- Human review remains important for security-critical decisions.

SlopGate is designed to improve evidence-based analysis, not replace comprehensive security auditing.

## Contributors

Developed collaboratively by a five-member team for the CSE 598 Agentic AI Project.

- Prakruti Dangi
- Kaushha Trivedi
- Khwahish Patel
- Meet Patel
- Krish Shah

## License

Refer to the repository's license file, if one is provided, for applicable terms.
