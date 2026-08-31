# Agent Backend Evaluation Matrix

Use this matrix for Pi, Claude Agent SDK, Craft Agents, or another candidate.

| Area | Questions | Required evidence |
|---|---|---|
| Layer | Model, client SDK, Agent Backend, or application? | official architecture/docs and imports |
| Models | Multiple Provider/Model support? Runtime switching? | model registry code/example |
| Session | Create, resume, fork, cancel, dispose? | runnable session example |
| Events | Stable typed stream? Ordering and terminal events? | event types and trace |
| Tools | Schema, permission hook, timeout, cancellation, errors? | tool example and failure run |
| Context | Compaction, truncation, cache, long-context behavior? | docs/code and measured run |
| State | Where is state authoritative? Can LawAgent own it? | persistence interface/code |
| Replay | Deterministic replay or transcript import? | runnable proof |
| Security | PII, sandbox, credentials, prompt injection seams? | config and threat notes |
| Observability | token, cost, latency, tool and model events? | emitted metadata |
| Failure | retries, 429/5xx, invalid output, partial result? | injected failure evidence |
| Deployment | local/hosted, process model, network needs? | official deployment docs |
| License | redistribution and modification constraints? | canonical license |
| Exit | Can Adapter be replaced without changing ScenarioPack/UI? | contract test or prototype |

Use `ADOPT | ADAPT | BORROW | DEFER | REJECT` for each row and explain the smallest proof needed before implementation.

