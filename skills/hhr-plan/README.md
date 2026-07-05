# hhr-plan: Mingdao APaaS Design Engine

A Claude Code skill that applies design axioms, dependency graph analysis, and dual-agent verification to low-code platform (Mingdao) application design and troubleshooting.

**4 modes, 1 engine**: Greenfield design, brownfield modification, root-cause diagnosis, health audit — all driven by 5 design axioms distilled from a production system with 136 worksheets and 338 workflows.

## Quick Start

```bash
# Clone into your Claude Code skills directory
git clone https://github.com/YOUR_USER/hhr-plan.git ~/.claude/skills/hhr-plan

# Run the environment health check
bash ~/.claude/skills/hhr-plan/scripts/doctor.sh
```

Then invoke in Claude Code:
```
/hhr-plan 帮我设计一个采购审批流程
/hhr-plan 为什么付款金额不对
/hhr-plan 检查这个项目的健康度
```

## What It Does

| Mode | What you say | What it does |
|------|-------------|--------------|
| **A: Greenfield** | "新建一个..." "从零设计..." | Entity identification → Hub table design → workflow chain → field config → dual-gate verification |
| **B: Brownfield** | "改这个工作流" "加个字段" | Impact analysis → lifecycle check → incremental change → verification |
| **C: Diagnose** | "为什么..." "排查..." "不工作" | Term mapping → workflow location → data flow tracing → root cause hypothesis |
| **D: Audit** | "检查这个项目" "审计" | Full axiom compliance scan → scorecard → issues ranked by severity |

## Architecture

```
hhr-plan/
├── SKILL.md                    # Entry point + metadata
├── system-prompt.md            # Core methodology (2 meta-axioms + 5 design axioms → 8 theorems)
├── agents/
│   ├── logic-verify.md         # Agent 1: Design logic verification (5 sections)
│   ├── platform-verify.md      # Agent 2: Platform capability verification (8 sections)
│   ├── verification-orchestrator.md  # Parallel agent orchestration + merge protocol
│   ├── audit-scanner.md        # Agent 3: Audit scan completeness check
│   └── descriptors/            # Mode interface descriptors (YAML, machine-readable)
├── built-in-skills/            # Mode-specific instruction pipelines (A/B/C/D + utilities)
├── scripts/
│   ├── doctor.sh               # Environment health check (5 layers)
│   ├── search.py               # FTS5 full-text search across projects
│   ├── rebuild_graph.py        # Dependency graph + entity lifecycle
│   ├── verify-platform.py      # Deterministic platform gate (bash control flow)
│   ├── validate-agent-output.py # Post-hoc output integrity gate
│   ├── summarize-output.py     # Token-budgeted output summarizer
│   ├── verify-ledger.py        # Axiom coverage ledger validator
│   └── ...                     # Extraction, indexing, sync, diagnosis tools
├── references/
│   ├── axioms/                 # Evidence matrix + coverage ledger (44 constraints)
│   ├── patterns/               # Reusable workflow design patterns
│   └── templates/              # Output format templates
└── implementation-notes/       # Internal development notes (gitignored)
```

## Dependencies

### Required
- **Python 3.10+** — all scripts use stdlib only (except `auth.py`)
- **Claude Code** — this is a Claude Code skill, not a standalone app

### Optional
- **hap-bridge CLI** (`~/.claude/mcp-servers/hap-bridge/cli.py`) — for live workflow data queries and MCP integration
- **browser_cookie3** (`pip install browser_cookie3`) — for `auth.py` Chrome cookie extraction
- **Workflow Nodes Guide** — set `WORKFLOW_NODES_GUIDE_PATH` for Agent 2 platform verification

## Verification Gates

The verification pipeline uses **3 deterministic gates** (bash/Python control flow) + **2 LLM agents** (semantic reasoning):

```
Design → verify-platform.py (mechanical checks) → Agent 1 + Agent 2 (parallel)
                                                          ↓
User ← stop-gate-check.py ← validate-agent-output.py (integrity) ←
```

- **verify-platform.py**: typeId validity, actionId sub-modes, batch limits, topology — ~60% of Agent 2's checks run deterministically with zero LLM cost
- **validate-agent-output.py**: post-hoc check that all sections were completed, no skipped checks
- **summarize-output.py**: token-budgeted summary when full output exceeds context window

## Design Axioms

The engine is built on 5 axioms distilled from reverse-engineering a 136-worksheet, 338-workflow production system:

1. **Data lineage must not be lost** — every record must trace back to its origin
2. **Human in the loop** — automation moves data; humans make decisions
3. **Self-documenting system** — naming, numbering, and colors carry semantics
4. **Unidirectional dependency** — DAG topology; no bidirectional references
5. **Graceful degradation** — "continue execution" is the default, "abort" is the exception

Each axiom has MUST/MUST NOT constraint tables with evidence counts, falsification conditions, and known failure modes tracked in the [coverage ledger](references/axioms/coverage-ledger.tsv).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on adding patterns, improving verification agents, or validating axioms against new projects.

## License

[Apache 2.0](LICENSE)

## Acknowledgments

- Architecture patterns inspired by [RepoPrompt CE](https://github.com/repoprompt/repoprompt-ce) (health checks, guardrails, contract ledger)
- Built on real production data from the Mingdao low-code platform
