# AGENTS.md - viral-shot-remake-production

## Engineering rules

- Prefer deterministic Python over free-form model decisions.
- Pass structured JSON artifacts between steps.
- Declare exact inputs and outputs for every step.
- Validate every output before downstream use.
- Call external services only through `adapters/`.
- Never store API keys in files, logs, JSON artifacts, or exceptions.
- Implement dry-run first and keep it working.
- Use milliseconds for all times.
- Use stable IDs: `ref_###`, `new_###`, `act_###`, and `prod_001`.
- Record estimated and actual cost for every paid API call.
- Resume partial runs from `pipeline_state.json`.
- Write files atomically and preserve the last valid artifact after failure.
- Do not claim a real provider call succeeded when an adapter returned mock output.

## Testing rules

- Validate Schema syntax and fixtures.
- Test timeline normalization and cross-artifact IDs.
- Test budget stops before a paid call.
- Run the full dry pipeline without API keys.
- Verify every generated artifact is accepted by its declared Schema.
- Verify resume skips completed steps and begins at the first incomplete step.
