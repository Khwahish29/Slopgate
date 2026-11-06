# Milestone 2 Report: SlopGate Claim Extraction Work

## 1. Objective

This milestone focuses on the claim extraction and evidence-grounding component of the SlopGate triage pipeline. The central task is to turn prose-based vulnerability reports into structured claims that can be checked against a repository checkout and a claimed version or ref.

## 2. Work completed

The implementation includes a lightweight extraction layer that:

- sanitizes injected or instruction-like content from the report text,
- finds claim-bearing sentences or metadata-like lines,
- creates structured claim objects with identifiers, role, source, and span,
- preserves a clean evidence path so each extracted claim can later be validated against the repository.

## 3. Key contribution

The main implementation is in `slopgate/claim_extractor.py`. It converts free-form report text into structured claims, which is essential because the stakeholder requirement says that real reports are often written in prose rather than fixed Markdown header formats.

This is the first step in the broader SlopGate agent loop:

1. sanitize the report,
2. extract claims,
3. ground those claims against the repository,
4. verify the evidence before any verdict is accepted.

## 4. Why this matters

A triage system cannot rely only on raw report text. The claim extraction layer ensures that vague prose is converted into concrete, checkable assertions. This improves the reliability of downstream verification and reduces the chance that fabricated or injected content influences the final verdict.

## 5. Validation

The current code is validated through the repository test suite, which confirms that the basic extraction and sanitization flow remains stable.
