---
name: research-agent-backends
description: Research and compare agent SDKs, runtimes, model-provider layers, and full-stack agent repositories for LawAgent. Use when evaluating Pi, Claude Agent SDK, Craft Agents, another agent backend, or deciding whether to adopt, wrap, borrow, or reject a third-party capability.
---

# Research Agent Backends

Produce an evidence-backed adoption decision without surrendering LawAgent's domain workflow, policy, evidence, or delivery control.

## Workflow

1. Read `docs/design/SYSTEM_DESIGN.md`, `docs/interfaces/API_CONTRACTS.md`, and the relevant ADRs.
2. Use primary sources only: official documentation, canonical source repository, tagged release/commit, license, and runnable examples.
3. Record the exact version or commit. Do not treat moving `main` documentation as a stable contract.
4. Classify the subject before comparing it:
   - Model or Model Provider;
   - API client SDK;
   - Agent Backend/Runtime;
   - full-stack Agent application/reference architecture.
5. Run the smallest official example when source and environment are available. Record commands, output, network/credential needs, and failures.
6. Compare the candidate against the matrix in `references/evaluation-matrix.md`.
7. For every capability choose exactly one disposition:
   - `ADOPT` directly;
   - `ADAPT` behind a LawAgent interface;
   - `BORROW` the design and implement locally;
   - `DEFER` outside the MVP;
   - `REJECT` with reason.
8. Verify that the choice cannot bypass `PolicyOrchestrator`, `ToolExecutor`, Trace, Evidence Gate, Delivery Gate, TTL, or PII rules.
9. Write or update an ADR with evidence, alternatives, consequences, migration/exit path, and validation plan.
10. Add only stable, project-specific findings to references; link to upstream material rather than copying it.

## Required output

- Candidate identity, version/commit, license and primary links;
- layer classification;
- capability matrix and missing capabilities;
- SDK leakage and lock-in analysis;
- cost, latency, hosting, credential and data-boundary implications;
- adoption disposition per capability;
- minimum Adapter interface;
- runnable proof or explicit blocked evidence;
- ADR and next validation task.

## Guardrails

- Do not call Pi or Claude Agent SDK a Model Provider.
- Do not let third-party sessions become the source of truth for MatterState.
- Do not expose third-party event or message objects through application contracts.
- Do not accept an abstraction supported by only one hypothetical Adapter unless it removes verified SDK leakage.
- Do not copy third-party source or documentation into this repository without license review and a concrete need.
- Do not claim adoption success from documentation review alone.
