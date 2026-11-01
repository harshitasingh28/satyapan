# AI usage disclosure (draft for the team to complete and confirm)

The Forge guidelines do not say whether AI coding assistants are allowed or how to disclose them. The team asked the organisers on 1 Nov 2026. This file records the facts so they can be disclosed accurately, whatever the answer.

## AI coding assistance

| Period | Tool | What it did | What the team did |
|---|---|---|---|
| 30 to 31 Oct 2026 | Claude (Anthropic), through claude.ai | Wrote most of the feasibility prototype (backend pipeline, evidence gate, media checks, tests, audits, documents) | Chose the problem and constraints, created API keys, ran the code and the live API tests on a team MacBook, reported failures, imported real PIB data |
| 1 Nov 2026 onward | Claude (Anthropic), through claude.ai | Wrote most of the 2.0 changes: Hugging Face integration, then Cloudflare Workers AI as the free default, MongoDB storage, semantic retrieval, AI comparison with code checks, streaming API, media match tiers, Next.js frontend, deployment files, tests | Set the stack and the verification rules, reviewed and approved each stage, ran live tests |

Team members: add your own contributions here, with dates.

## AI inside the product

Satyapan calls hosted models at run time: by default Cloudflare Workers AI (`@cf/qwen/qwen3-30b-a3b-fp8` for chat, `@cf/baai/bge-m3` for embeddings), or another hosted provider if configured. The chat model extracts claims, compares evidence and writes the explanation. The embedding model finds multilingual matches. These models never set a verdict. Code checks their quotes and citations. See `docs/ARCHITECTURE.md`.

## Commit history

The repository was published on 1 Nov 2026 as a single commit. Nothing is backdated. The code builds on a feasibility prototype written on 30 and 31 Oct 2026 (see `docs/FEASIBILITY_README.md`), and the commit message says so.
