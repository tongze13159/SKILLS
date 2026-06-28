---
name: viral-shot-remake-production
description: Build or run a protocol-driven, dry-run-first pipeline for remaking no-face ecommerce product demonstration videos. Use when Codex needs to analyze a reference viral product video, understand a new product, transfer physically valid actions, create an original shot plan and storyboards, compile Seedance image-to-video tasks, or compose localized voiceover, subtitles, BGM/SFX, and a final video. Do not use for face videos, celebrity imitation, one-to-one copying, or unauthorized brand or music reuse.
---

# Viral Shot Remake Production

## Purpose

Create and operate a resumable, budget-controlled pipeline for no-face ecommerce product videos
with hand-only operation, multi-shot visual rhythm, localized copy, and conversion-oriented
structure.

This Skill is the right fit when the user wants to:

- 仿拍产品展示视频
- 复刻爆款分镜
- 重构无人物产品视频
- 从参考视频生成原创但同节奏的电商短视频
- 做 TikTok / Douyin 风格的产品演示短片

## Hard boundaries

- Refuse face replacement, celebrity imitation, realistic impersonation, or one-to-one copying.
- Do not reuse exact subtitles, music, watermarks, brand elements, or background layouts.
- Preserve only transferable shot functions, pacing logic, product demonstration paths, and
  commercial structure; rebuild the execution as original material.
- Do not call paid APIs unless the user explicitly requests a real run and required keys exist.
- Default to `--dry-run` when API keys are missing.
- Read `project_config.json` as the source of truth for market, language, format, cost, and
  generation constraints.

## Start every run

1. Read `AGENTS.md`.
2. Read the selected project config.
3. Confirm the input video is a no-face product demonstration and the intended use respects the
   hard boundaries.
4. Run the dry pipeline first unless the user explicitly requests and authorizes real API calls.
5. Inspect `output/manifests/pipeline_state.json`,
   `output/manifests/cost_ledger.json`, and `output/manifests/seedance_tasks.json`.

## Run

From this Skill directory:

```bash
python3 scripts/run_pipeline.py --dry-run
```

This command reads fixed fixtures from `tests/mock_input/`, routes all provider-backed nodes
through `adapters/mock_adapter.py`, and writes validated outputs to `tests/mock_run/`. It does not
read API keys or call Gemini, OpenAI, FLUX, Seedance, or ElevenLabs.

Resume:

```bash
python3 scripts/run_pipeline.py --dry-run --resume
```

Run one step:

```bash
python3 scripts/run_step.py \
  --project-dir ./tests/mock_run \
  --step 16_compile_seedance_tasks \
  --dry-run
```

## Required pipeline

Execute these steps in order:

1. Normalize inputs.
2. Preprocess the reference video.
3. Extract subtitles.
4. Transcribe speech.
5. Extract reference visual facts.
6. Analyze commercial shot strategy.
7. Build a strict product profile.
8. Build a product action matrix with fallbacks.
9. Transfer reference actions to physically valid product actions.
10. Create the single master `new_video_plan.json`.
11. Localize subtitles and voiceover.
12. Compile the audio asset manifest.
13. Compile storyboard prompts.
14. Generate storyboard first frames.
15. Precheck storyboards.
16. Compile and validate `seedance_tasks.json` locally.
17. Generate independent video clips per shot.
18. Generate voiceover.
19. Render the final video or dry-run final manifest.

## Protocol rules

- Use stable IDs: `ref_###`, `new_###`, `act_###`, `act_###_fallback`, and `prod_001`.
- Use milliseconds for all timeline fields.
- Include `schema_version`, `project_id`, `artifact_id`, `created_at`,
  `source_artifacts`, `model_info`, and `cost_rmb` in generated artifacts.
- Validate every artifact before downstream use.
- Repair invalid model JSON at most `max_json_repair_retries`; stop and preserve state when repair
  fails.
- Require every high-risk action to have a fallback.
- Require storyboards to show the action start state, not the completed action.
- Compile final Seedance prompts with `scripts/compile_seedance_tasks.py`; do not let an LLM freely
  create the launch manifest.
- Estimate cost before every paid call and stop before the call when the configured budget would
  be exceeded.
- Persist every completed step in `pipeline_state.json` so reruns resume at the first incomplete
  step.

## Implementation map

- `config/`: project defaults, API key names, and config schema.
- `schemas/`: Pydantic models and JSON Schemas for every artifact.
- `scripts/`: orchestration, validation, repair, normalization, cost, and compiler tools.
- `adapters/`: the only allowed boundary for external services.
- `prompts/`: structured-output instructions for model-backed nodes.
- `assets/`: approved local audio, subtitle style, and render templates.
- `examples/`: key-free dry-run fixtures and expected outputs.

## Real-service status

Treat local FFmpeg probing as implemented when FFmpeg is available. Treat OCR, STT, Gemini,
OpenAI, FLUX, Seedance, ElevenLabs, and Remotion network operations as explicit adapter stubs
until their adapter reports a real implementation. Never report mock output as a real generation.

## Final outputs

- Real run: `output/final/final_video.mp4`
- Dry run: `output/final/final_video_manifest.json`
- Launch manifest: `output/manifests/seedance_tasks.json`
- Cost ledger: `output/manifests/cost_ledger.json`
- Resume state: `output/manifests/pipeline_state.json`
- Intermediate JSON artifacts under `output/artifacts/`
