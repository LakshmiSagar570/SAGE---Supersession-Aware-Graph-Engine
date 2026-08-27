# SAGE — Suppression-Aware Graph Engine

> **SAGE (Suppression-Aware Graph Engine)** is a production-oriented NLP and knowledge-graph reasoning system designed to answer questions over structured, temporally evolving data while preserving **suppression semantics, provenance, temporal relationships, and deterministic graph reasoning**.

SAGE combines **Natural Language Processing (NLP)**, **knowledge graphs**, **graph query generation**, **schema contracts**, and **suppression-aware reasoning** into a controlled multi-stage pipeline.

The central design principle is:

> **Do not treat missing data as ordinary missing data when the source explicitly indicates that a value was suppressed, unavailable, confidential, below a reporting threshold, or otherwise non-observable.**

SAGE therefore distinguishes between:

* an actual numerical value,
* an explicit zero,
* a suppressed value,
* an unavailable value,
* a missing value,
* and an unknown/unresolved value.

This distinction is critical for trustworthy analytical question answering.

---

## Table of Contents

* [Overview](#overview)
* [Why SAGE Exists](#why-sage-exists)
* [Core Problem](#core-problem)
* [What Makes SAGE Different](#what-makes-sage-different)
* [Architecture](#architecture)
* [Pipeline](#pipeline)
* [Repository Structure](#repository-structure)
* [Core Contracts](#core-contracts)
* [NLP Layer](#nlp-layer)
* [Knowledge Graph Layer](#knowledge-graph-layer)
* [Suppression Awareness](#suppression-awareness)
* [Temporal Reasoning](#temporal-reasoning)
* [Query Generation](#query-generation)
* [Execution and Validation](#execution-and-validation)
* [Technology Stack](#technology-stack)
* [Getting Started](#getting-started)
* [Environment Setup](#environment-setup)
* [Running SAGE](#running-sage)
* [Development](#development)
* [Testing](#testing)
* [Production Design Principles](#production-design-principles)
* [Data Contracts](#data-contracts)
* [Observability and Debugging](#observability-and-debugging)
* [Security Considerations](#security-considerations)
* [Performance Considerations](#performance-considerations)
* [Design Trade-offs](#design-trade-offs)
* [Roadmap](#roadmap)
* [Project Status](#project-status)
* [Contributing](#contributing)
* [License](#license)

---

# Overview

Traditional question-answering systems generally follow a pattern similar to:

```text
User Question
      ↓
LLM
      ↓
Generated Answer
```

This is convenient, but it is insufficient for analytical questions where correctness depends on:

* exact graph relationships,
* temporal ordering,
* entity resolution,
* explicit data semantics,
* missing-vs-suppressed distinctions,
* reproducible query execution,
* and validation of the generated result.

SAGE instead uses a controlled pipeline:

```text
                         ┌──────────────────────┐
                         │      User Query      │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   Query / NLP Layer  │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Entity & Intent      │
                         │ Resolution           │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Semantic / Graph     │
                         │ Planning             │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Cypher Generation    │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Graph Execution      │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Result Validation    │
                         │ + Suppression Logic  │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Evidence / Answer    │
                         └──────────────────────┘
```

The pipeline is deliberately separated into stages so that every transformation can be inspected, tested, validated, and reproduced.

---

# Why SAGE Exists

Structured datasets frequently contain information that cannot safely be interpreted using ordinary SQL-style null semantics.

For example:

```text
value = 0
```

does not necessarily mean the same thing as:

```text
value = NULL
```

and neither necessarily means:

```text
value = suppressed
```

Consider an emissions dataset:

```text
January     10.4
February    11.2
March       S
April       13.1
```

where `S` means that the source suppressed the value.

A naïve analytical system might transform this into:

```text
January     10.4
February    11.2
March       NULL
April       13.1
```

and subsequently calculate statistics or changes incorrectly.

SAGE preserves the distinction between **observed**, **zero**, **suppressed**, **missing**, and **unknown** states throughout the reasoning pipeline.

---

# Core Problem

SAGE addresses analytical question answering over a knowledge graph where the answer depends on relationships rather than isolated records.

Typical questions include:

* "What was the emission for entity X in year Y?"
* "Which month had the highest value?"
* "What changed from one month to the next?"
* "Compare two entities."
* "What was January's change compared with December of the previous year?"
* "Which values were suppressed?"
* "What is the minimum observed value?"
* "Which records cannot be safely compared because the source suppressed a value?"

These questions require more than language understanding.

They require:

```text
Language Understanding
        +
Entity Resolution
        +
Schema Understanding
        +
Graph Traversal
        +
Temporal Reasoning
        +
Suppression Semantics
        +
Deterministic Execution
        +
Result Validation
```

SAGE is designed around that complete chain.

---

# What Makes SAGE Different

## 1. Suppression-aware reasoning

Suppressed observations are not silently converted into ordinary nulls or zeros.

## 2. Graph-native reasoning

Relationships are explicitly represented in the graph and traversed using Cypher.

## 3. Temporal awareness

Time relationships are modeled explicitly instead of relying only on string manipulation or application-side sorting.

## 4. Contract-driven architecture

Pipeline stages communicate through explicit schemas rather than undocumented Python dictionaries.

## 5. Deterministic execution

The LLM/NLP layer is separated from graph execution and validation.

## 6. Validation before answering

Generated queries and returned results are checked before being exposed as final answers.

## 7. Provenance

The system is designed to preserve where an answer came from and how it was derived.

## 8. Testability

Individual pipeline stages can be tested independently.

---

# Architecture

SAGE follows a layered architecture.

```text
┌──────────────────────────────────────────────────────────┐
│                         API Layer                         │
│                    FastAPI / HTTP                         │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│                     Pipeline Manager                     │
│              Orchestrates the SAGE stages                │
└───────────────────────────┬──────────────────────────────┘
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
       NLP / Parsing    Resolution     Graph Planning
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                    Query Generation
                            │
                            ▼
                    Graph Execution
                            │
                            ▼
                Validation / Semantics
                            │
                            ▼
                    Answer Generation
```

The repository keeps **contracts separate from agent/stage implementation**.

This prevents individual components from independently redefining the data exchanged between stages.

---

# Pipeline

SAGE is organized as a six-stage processing pipeline.

A conceptual representation is:

```text
Stage 1
Input / Understanding
        ↓
Stage 2
Entity / Semantic Resolution
        ↓
Stage 3
Graph Planning
        ↓
Stage 4
Query Generation
        ↓
Stage 5
Execution
        ↓
Stage 6
Validation / Answer
```

The exact implementation of each stage may evolve, but the **stage boundaries and contracts are treated as architectural interfaces**.

This makes it possible to replace an implementation without breaking the rest of the system.

---

# Repository Structure

The core repository is organized around contracts, pipeline stages, API boundaries, and infrastructure.

```text
SAGE---Suppression-Aware-Graph-Engine/
│
├── Dockerfile
├── Makefile
├── README.md
│
├── contracts/
│   ├── fact_schema.py
│   ├── stage_io.py
│   ├── CONTRACT_CHANGELOG.md
│   └── __pycache__/
│
├── src/
│   └── sage/
│       │
│       ├── api/
│       │   └── ...
│       │
│       ├── pipeline/
│       │   ├── manager.py
│       │   └── ...
│       │
│       ├── ...
│       │
│       └── ...
│
├── tests/
│   └── ...
│
└── ...
```

### Architectural rule

```text
contracts/
```

is intentionally separate from the implementation.

Contracts define what stages are allowed to exchange.

Implementation modules consume those contracts.

---

# Core Contracts

SAGE uses explicit contracts for stage-to-stage communication.

Important contract modules include:

```text
contracts/
├── fact_schema.py
├── stage_io.py
└── CONTRACT_CHANGELOG.md
```

## `fact_schema.py`

Defines the canonical representation of extracted or resolved facts.

A fact can conceptually contain information such as:

```text
entity
predicate
value
time
unit
status
provenance
confidence
```

The exact schema is defined by the implementation and should not be duplicated independently by downstream stages.

---

## `stage_io.py`

Defines the input/output boundaries between pipeline stages.

The objective is to prevent implicit coupling such as:

```python
stage_a_output["something"]["nested"]["value"]
```

without any contract guaranteeing that structure.

Instead, stage communication should be explicit and validated.

---

## `CONTRACT_CHANGELOG.md`

All intentional contract changes should be documented.

Contract changes are architectural changes because modifying a shared schema can affect multiple pipeline stages.

---

# NLP Layer

NLP is used where the system needs to convert natural-language intent into structured semantics.

For example:

```text
"What was Comoros' NMVOC emission in March 2006?"
```

must be transformed into something conceptually equivalent to:

```text
Entity:
    Comoros

Pollutant:
    NMVOC

Time:
    March 2006

Measure:
    Emission

Operation:
    Retrieve
```

NLP therefore acts as the **semantic interface between natural language and the graph**.

It is not responsible for blindly producing the final answer.

---

# Knowledge Graph Layer

SAGE uses a graph representation because the underlying problem is relationship-heavy.

A simplified graph may contain:

```text
(:ReportingEntity)
        │
        │ HAS_SERIES
        ▼
(:EmissionSeries)
        │
        │ FOR_POLLUTANT
        ▼
(:Pollutant)

(:EmissionSeries)
        │
        │ HAS_MONTHLY_EMISSION
        ▼
(:MonthlyEmission)
        │
        │ NEXT_MONTH
        ▼
(:MonthlyEmission)
```

This structure allows questions involving relationships to be represented naturally.

For example:

```text
January
   │
   │ NEXT_MONTH
   ▼
February
   │
   │ NEXT_MONTH
   ▼
March
```

This is materially different from merely storing:

```text
month = 1
month = 2
month = 3
```

because the graph explicitly encodes the relationship between observations.

---

# Suppression Awareness

Suppression is a first-class semantic concept in SAGE.

The system must distinguish states such as:

| State          | Meaning                                            |
| -------------- | -------------------------------------------------- |
| Observed value | A usable reported numerical observation            |
| Zero           | Explicitly reported zero                           |
| Suppressed     | Source intentionally hides or suppresses the value |
| Missing        | No observation exists                              |
| Unknown        | State cannot be established                        |
| Unavailable    | Source indicates the observation is unavailable    |

These states must not be collapsed prematurely.

For example:

```text
0
```

and:

```text
suppressed
```

are semantically different.

Similarly:

```text
missing
```

does not automatically mean:

```text
0
```

---

# Temporal Reasoning

Temporal reasoning is a core part of SAGE.

The system should preserve temporal relationships rather than treating dates as ordinary text fields.

For example:

```text
December 2005
      │
      │ NEXT_MONTH
      ▼
January 2006
      │
      │ NEXT_MONTH
      ▼
February 2006
```

Therefore, when a question asks:

> Show each month's change from the month before.

January 2006 must be compared against:

```text
December 2005
```

rather than:

```text
January 2006 → no previous value
```

This is especially important for monthly time-series queries crossing year boundaries.

---

# Query Generation

SAGE uses graph-query generation to translate resolved intent into executable Cypher.

A representative query may look like:

```cypher
MATCH (e:ReportingEntity {code: 'COM'})
      -[:HAS_SERIES]->(s:EmissionSeries)
      -[:FOR_POLLUTANT]->(:Pollutant {code: 'NMVOC'})
MATCH (s)-[:HAS_MONTHLY_EMISSION]->(m:MonthlyEmission)
RETURN m
```

For temporal comparison, graph relationships can be traversed directly:

```cypher
MATCH (current:MonthlyEmission)
      <-[:HAS_MONTHLY_EMISSION]-(s:EmissionSeries)
      -[:HAS_MONTHLY_EMISSION]->(previous:MonthlyEmission)
MATCH (previous)-[:NEXT_MONTH]->(current)
RETURN current, previous
```

The important principle is:

> **The generated query should express the user's semantic intent using the graph's canonical relationships.**

It should not reconstruct graph semantics unnecessarily in application code.

---

# Execution and Validation

Generated Cypher is not treated as the final authority.

The execution layer should:

1. Validate the query.
2. Execute it against the graph.
3. Inspect the returned records.
4. Preserve suppression state.
5. Validate temporal relationships.
6. Check expected cardinality.
7. Detect ambiguous or incomplete results.
8. Produce structured evidence.
9. Only then generate the final answer.

Conceptually:

```text
Natural Language
      ↓
Structured Intent
      ↓
Graph Plan
      ↓
Cypher
      ↓
Query Validation
      ↓
Neo4j
      ↓
Raw Results
      ↓
Semantic Validation
      ↓
Evidence
      ↓
Answer
```

---

# Technology Stack

SAGE is designed around a modern, production-oriented Python graph/NLP stack.

| Layer                   | Technology               |
| ----------------------- | ------------------------ |
| Language                | Python                   |
| API                     | FastAPI                  |
| Graph Database          | Neo4j                    |
| Graph Query Language    | Cypher                   |
| NLP / LLM Layer         | Pluggable                |
| Containerization        | Docker                   |
| Development Environment | Linux / WSL2 compatible  |
| Testing                 | Python testing ecosystem |
| Contracts               | Typed Python schemas     |
| Build / Tasks           | Make                     |

The architecture intentionally avoids coupling the core reasoning engine to one specific LLM provider.

---

# Getting Started

## Prerequisites

Install:

* Python 3.12+
* Docker
* Docker Compose, if using the containerized graph environment
* Git
* Neo4j

For Windows development, WSL2 with Ubuntu is supported and recommended for a Linux-compatible development environment.

---

# Clone the Repository

```bash
git clone <REPOSITORY_URL>
cd SAGE---Suppression-Aware-Graph-Engine
```

---

# Environment Setup

Create a virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Upgrade packaging tools:

```bash
python -m pip install --upgrade pip
```

Install project dependencies:

```bash
pip install -r requirements.txt
```

If the project uses an editable package installation:

```bash
pip install -e .
```

---

# Environment Variables

Runtime configuration should be supplied through environment variables rather than hard-coded credentials.

Typical configuration includes:

```text
NEO4J_URI=
NEO4J_USERNAME=
NEO4J_PASSWORD=

LLM_PROVIDER=
LLM_API_KEY=
LLM_MODEL=
```

Create a local environment file where appropriate:

```bash
cp .env.example .env
```

Never commit secrets to Git.

---

# Running Neo4j

If the repository provides a Docker configuration:

```bash
docker compose up -d
```

Check running containers:

```bash
docker ps
```

The graph database should then be available to the SAGE application according to the configured Neo4j connection settings.

---

# Running the API

A typical FastAPI development command is:

```bash
uvicorn sage.api.main:app --reload
```

The API will normally be available at:

```text
http://localhost:8000
```

Interactive API documentation:

```text
http://localhost:8000/docs
```

The exact entrypoint should follow the repository's current API module.

---

# Makefile

Where supported, common development operations can be exposed through the `Makefile`.

For example:

```bash
make help
```

and project-specific commands such as:

```bash
make test
make lint
make format
make run
```

The Makefile is the preferred place for standardized developer commands rather than requiring developers to memorize long command sequences.

---

# Development

A typical development workflow is:

```text
1. Create / switch to a feature branch
2. Modify implementation
3. Validate contracts
4. Run unit tests
5. Run integration tests
6. Run static checks
7. Run the complete pipeline
8. Inspect generated Cypher
9. Validate graph results
10. Commit
```

---

# Testing

Testing should exist at multiple levels.

## Unit tests

Test individual components in isolation.

Examples:

```text
Entity resolution
Date normalization
Suppression handling
Fact extraction
Query construction
Result normalization
```

---

## Contract tests

Verify that pipeline stages respect the shared schemas.

```text
Stage A output
       ↓
Contract validation
       ↓
Stage B input
```

This catches incompatible stage changes early.

---

## Integration tests

Verify interaction between:

```text
Pipeline
+
Neo4j
+
Cypher
```

---

## End-to-end tests

An end-to-end test should exercise:

```text
Natural-language question
        ↓
SAGE pipeline
        ↓
Graph query
        ↓
Graph execution
        ↓
Validation
        ↓
Final structured answer
```

---

# Production Design Principles

SAGE is intended to be **production-oriented**, not merely a research prototype.

## Determinism where possible

LLMs may be probabilistic, but critical graph operations should be deterministic.

For example:

```text
Entity code resolution
Date arithmetic
Suppression interpretation
Graph traversal
Result validation
```

should not depend on free-form LLM reasoning.

---

## Strong contracts

Shared data structures should be explicitly defined.

Bad:

```python
dict[str, object]
```

for every stage.

Preferred:

```text
Typed contract
    ↓
Validation
    ↓
Stage
    ↓
Typed output
```

---

## Separation of concerns

The following responsibilities should remain separate:

```text
NLP
Entity Resolution
Graph Planning
Query Generation
Graph Execution
Validation
Answer Formatting
```

This makes failures diagnosable.

---

## Fail closed

If the system cannot establish that a result is valid, it should not silently invent certainty.

For example:

```text
Suppressed
```

should not become:

```text
0
```

just because the downstream calculation expects a number.

---

## Provenance first

An analytical answer should ideally be traceable to:

```text
User question
      ↓
Resolved entities
      ↓
Generated query
      ↓
Graph records
      ↓
Derived calculation
      ↓
Final answer
```

---

# Data Contracts

Contracts are architectural boundaries.

A contract change can affect:

```text
Producer
   ↓
Contract
   ↓
Consumer
```

Therefore:

* Do not casually modify shared schemas.
* Document breaking changes.
* Update tests when contracts change.
* Keep compatibility considerations explicit.
* Record contract changes in `CONTRACT_CHANGELOG.md`.

---

# Observability and Debugging

A production-grade pipeline should make failures inspectable.

Important debugging information includes:

```text
Request ID
Pipeline stage
Resolved entities
Resolved temporal scope
Generated Cypher
Query parameters
Execution duration
Result cardinality
Suppression states
Validation failures
Final evidence
```

The goal is to make a failure answerable as:

> **Which stage produced the incorrect interpretation?**

rather than simply:

> **The model gave the wrong answer.**

---

# Security Considerations

SAGE should treat generated queries as untrusted output.

Recommended controls include:

* Parameterized Cypher where possible.
* Query validation before execution.
* Read-only graph credentials for analytical workloads.
* No secrets in source code.
* Environment-based configuration.
* Input validation at API boundaries.
* Request-level logging without leaking credentials.
* Restricted database permissions.
* Resource limits on expensive graph queries.

The LLM should never receive unrestricted authority to mutate the production graph.

---

# Performance Considerations

SAGE's performance depends on both graph design and pipeline architecture.

Important considerations include:

## Graph indexing

Frequently queried properties should have appropriate Neo4j indexes.

Typical candidates include:

```text
ReportingEntity.code
Pollutant.code
```

---

## Avoid unnecessary graph scans

Prefer:

```cypher
MATCH (e:ReportingEntity {code: $code})
```

over unrestricted label scans.

---

## Parameterized queries

Prefer:

```cypher
MATCH (e:ReportingEntity {code: $code})
```

with:

```text
$code
```

rather than constructing Cypher through string concatenation.

---

## Push computation into the graph when appropriate

For relationship-heavy operations, Cypher can often perform the required traversal more efficiently than retrieving large datasets into Python.

---

## Avoid unnecessary LLM calls

LLMs should be used for tasks that actually require language understanding.

Deterministic operations such as:

```text
date arithmetic
sorting
aggregation
relationship traversal
schema validation
```

should remain deterministic.

---

# Design Trade-offs

SAGE intentionally chooses architectural control over minimal implementation complexity.

| Decision                    | Benefit                           | Cost                           |
| --------------------------- | --------------------------------- | ------------------------------ |
| Multi-stage pipeline        | Debuggability and modularity      | More components                |
| Explicit contracts          | Safe interfaces                   | Schema maintenance             |
| Neo4j                       | Natural relationship modeling     | Operational complexity         |
| Cypher                      | Powerful graph traversal          | Requires graph-query expertise |
| Suppression-aware semantics | Correct analytical interpretation | More complex data model        |
| LLM-assisted NLP            | Natural-language interface        | Probabilistic behavior         |
| Deterministic validation    | Reliability                       | Additional implementation      |
| Provenance                  | Auditable answers                 | More metadata                  |

The objective is not to minimize lines of code.

The objective is to minimize **silent semantic errors**.

---

# Example Reasoning Flow

Consider:

> "For Comoros and NMVOC in 2006, show each month's change from the month before."

SAGE should conceptually resolve:

```text
Entity:
    Comoros

Entity code:
    COM

Pollutant:
    NMVOC

Year:
    2006

Operation:
    Month-over-month change

Temporal rule:
    January 2006 → December 2005
    February 2006 → January 2006
    ...
    December 2006 → November 2006
```

The important point is that January does **not** have a null predecessor merely because the requested year begins in January.

The graph's temporal relationship determines the correct predecessor.

---

# Example Graph Traversal

A conceptual structure:

```text
Comoros
   │
   │ HAS_SERIES
   ▼
EmissionSeries
   │
   │ FOR_POLLUTANT
   ▼
NMVOC
   │
   │ HAS_MONTHLY_EMISSION
   ▼
Dec 2005 ──NEXT_MONTH──> Jan 2006
                           │
                           └──NEXT_MONTH──> Feb 2006
```

This enables the system to calculate:

```text
change(Jan 2006)
    =
value(Jan 2006) - value(Dec 2005)
```

subject to suppression and observability rules.

---

# Failure Semantics

SAGE should distinguish between:

```text
No result
```

and:

```text
Result exists but is suppressed
```

and:

```text
Result exists but cannot be safely computed
```

and:

```text
Query was ambiguous
```

and:

```text
Query execution failed
```

These are different system states and should produce different responses.

---

# Project Philosophy

SAGE follows several principles:

### 1. Semantics before arithmetic

Do not calculate before establishing what the data means.

### 2. Graph relationships are first-class

Do not reconstruct relationships unnecessarily outside the graph.

### 3. Suppression is information

A suppressed observation is not equivalent to an absent observation.

### 4. LLMs assist reasoning; they do not replace validation

Natural-language interpretation can be probabilistic.

Critical data operations should not be.

### 5. Contracts protect the architecture

Pipeline stages should communicate through explicit interfaces.

### 6. Every important answer should be explainable

The system should be able to establish:

```text
What did the user ask?
What did we resolve?
What query did we execute?
What data did we retrieve?
How did we derive the result?
```

---

# Roadmap

Potential future improvements include:

* [ ] Expanded suppression taxonomy
* [ ] Stronger provenance graph
* [ ] Automatic query-plan validation
* [ ] Query cost estimation
* [ ] More comprehensive temporal reasoning
* [ ] Improved entity resolution
* [ ] Confidence calibration
* [ ] Structured evidence generation
* [ ] Expanded benchmark suite
* [ ] Automated regression testing
* [ ] Production telemetry
* [ ] Distributed execution for large workloads
* [ ] Additional graph datasets
* [ ] Model-provider abstraction
* [ ] Retrieval and reasoning evaluation framework

---

# Project Status

SAGE is an actively developed engineering project.

The architecture prioritizes:

```text
Correctness
    >
Semantic integrity
    >
Auditability
    >
Maintainability
    >
Performance
    >
Convenience
```

Performance optimization should not compromise semantic correctness, particularly around suppression and temporal reasoning.

---

# Contributing

Contributions should preserve the architectural boundaries of the system.

Before submitting changes:

1. Understand the relevant contract.
2. Identify affected pipeline stages.
3. Add or update tests.
4. Update contract documentation for schema changes.
5. Validate graph queries.
6. Check suppression semantics.
7. Check temporal edge cases.
8. Verify that existing behavior remains correct.

For significant architectural changes, document the rationale before implementation.

---

# License

This project is currently under active development.

Add the project's chosen license here before publishing a public release.

---

# Summary

SAGE is a **suppression-aware, graph-native NLP reasoning engine**.

Its purpose is not simply to convert:

```text
Natural Language → Answer
```

but to build a controlled chain:

```text
Natural Language
       ↓
Semantic Understanding
       ↓
Entity Resolution
       ↓
Graph Planning
       ↓
Cypher Generation
       ↓
Graph Execution
       ↓
Suppression-Aware Validation
       ↓
Temporal Reasoning
       ↓
Evidence
       ↓
Answer
```

The fundamental design goal is **trustworthy analytical reasoning over structured temporal graph data**.

> **SAGE — preserving the semantics that ordinary question-answering systems tend to lose.**
