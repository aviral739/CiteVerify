# CiteVerify Known Limitations & Roadmap

This document outlines boundaries of the current backend skeleton and areas slated for upcoming pipeline implementation.

## Current Skeleton Boundaries

1. **Verification Pipeline Inactive:**
   - The eight stages (`s1_parse` through `s8_persist`) have typed contracts and entrypoints, but their internal algorithms are mock implementations.
   - Verification results are not fabricated; reports indicate verification is pending.

2. **External Academic APIs:**
   - Rate limiters and cache schemas are established, but actual live HTTP queries to CrossRef, Semantic Scholar, Unpaywall, and OpenAlex will be integrated in subsequent milestones.

3. **In-Memory Job Registry:**
   - The current `JobRegistry` is in-memory for fast asynchronous background execution. Distributed task queues (e.g., Celery / Redis or ARQ) can be integrated if multi-worker horizontal scaling is needed.

4. **Paywalled Literature Access:**
   - For paywalled publications without open access mirrors, the pipeline will fallback to verifying against published abstracts (`abstract_only`) and label evidence completeness accordingly.

## Next Development Milestones

- **Milestone 2:** Implement PDF parsing and GROBID container integration for Stage 1 & 2.
- **Milestone 3:** CrossRef, OpenAlex, and Unpaywall integration for Stage 4 & 5.
- **Milestone 4:** Production Gemini API prompt engineering for natural language claim verification (Stage 6).
- **Milestone 5:** Document citation scoring and visualization export (Stage 7 & 8).

