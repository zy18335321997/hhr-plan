# Contributing to hhr-plan

## What to Contribute

- **New workflow design patterns** — add to `references/patterns/` with a README entry
- **Axiom validation against new projects** — run Mode D audit, update `coverage-ledger.tsv`
- **Script improvements** — any script under `scripts/` with `--help` and JSON output where applicable
- **Agent instruction refinements** — agents under `agents/` with clear "when to stop" conditions
- **Bug reports** — issues with reproduction steps (what you asked, what happened, what you expected)

## Before Submitting

1. Run the health check: `bash scripts/doctor.sh`
2. If adding a script, include `--help` and write output in JSON format for agent consumption
3. If modifying agent instructions, run at least one end-to-end test
4. Stage only your intended changes

## Code Patterns

### Scripts
- Output JSON to stdout, diagnostics to stderr
- Use `--quiet` flag for machine-only output
- Exit code 0 = pass, 1 = fail (for gate scripts)
- Accumulate all failures before exiting (no early-exit in validation scripts)

### Agent Instructions
- State explicit "complete all sections" discipline at the top
- Use concrete "Do not assume..." / "Prefer X over Y" patterns
- Output structured JSON with `verdict`, `summary`, `issues`, `fix_guide` fields

### Descriptors
- Each mode/utility in `agents/descriptors/` requires YAML with: `display_name`, `short_description`, `triggers`, `requires`, `tools`, `produces`, `verification`

## Adding a New Pattern

1. Create pattern file under `references/patterns/<category>/<name>.md`
2. Add entry to `references/patterns/README.md`
3. Update `agents/descriptors/pattern-select.yaml` triggers if applicable

## Validating Axioms Against a New Project

1. Run Mode D audit on the project
2. For each axiom constraint in `references/axioms/coverage-ledger.tsv`:
   - If the project validates the constraint, add project name to `validated_projects` column
   - Update `last_validated` date
3. Run `python3 scripts/verify-ledger.py` to validate the ledger
4. Submit PR with the updated TSV + audit report summary

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
