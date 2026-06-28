# Viral Shot Remake Production SOP

这份 SOP 只做一件事：让你用同一套入口，稳定地跑起“参考视频拆解 → 产品理解 → 动作转移 → 分镜 → Seedance 任务”的流水线。

## 1. 适用范围

适合这些任务：

- 无露脸产品演示视频复刻
- 产品动作分析与重构
- 分镜脚本、字幕、配音、故事板、Seedance 任务编排

不适合这些任务：

- 真人脸部替换
- 明星模仿
- 一比一照搬参考视频
- 未授权品牌、音乐、水印复用

## 2. 默认原则

- 先 dry-run，再考虑 real-run。
- 先本地校验，再考虑外部服务。
- 任何一步失败，都先停，不继续往下写后续产物。
- 所有中间产物都必须通过 JSON Schema 校验。
- Seedance 任务只做本地编排，不在这一步直接发起生成。

## 3. 启动前检查

先确认这几件事：

- 当前目录在本 Skill 根目录内
- `tests/mock_input/` 已经有输入 fixture
- `.env` 已经配置好需要的 key
- 你这次要的是 `dry-run` 还是 `real-run`

如果只是验证流程，默认走 `dry-run`。

## 4. 最常用启动命令

### Dry-run

```bash
cd "/Users/tongze/Desktop/Codex Workspace/project-0001-爆款分镜复刻Skill/.agents/skills/viral-shot-remake-production"
python3 scripts/run_pipeline.py --dry-run
```

### Dry-run 断点续跑

```bash
python3 scripts/run_pipeline.py --dry-run --resume
```

### 单步运行

```bash
python3 scripts/run_step.py \
  --project-dir ./tests/mock_run \
  --step 16_compile_seedance_tasks \
  --dry-run
```

### 真实前置校验

```bash
python3 scripts/run_pipeline.py --real
```

当前版本里，`--real` 只会做前置检查，不会真的调用外部服务。

## 5. 业务逻辑顺序

流水线固定按下面顺序执行：

1. 读取输入并生成 `input_manifest.json`
2. 预处理参考视频，得到 `raw_shots.json`
3. 提取字幕，得到 `ocr_subtitles.json`
4. 转写语音，得到 `voice_transcript.json`
5. 分析参考画面，得到 `reference_visual_analysis.json`
6. 总结参考视频策略，得到 `reference_shot_strategy.json`
7. 生成产品画像，得到 `product_profile.json`
8. 生成产品动作矩阵，得到 `product_action_matrix.json`
9. 把参考动作转成可执行动作，得到 `action_transfer_plan.json`
10. 汇总成主计划，得到 `new_video_plan.json`
11. 生成字幕与配音脚本，得到 `subtitle_script.json` 和 `voiceover_script.json`
12. 生成音频资产清单，得到 `audio_asset_manifest.json`
13. 生成分镜 prompt，得到 `storyboard_prompts.json`
14. 生成分镜首帧，得到 `storyboard_manifest.json`
15. 做分镜预检，得到 `storyboard_precheck.json`
16. 编译 `seedance_tasks.json`
17. 生成视频切片清单，得到 `video_clips_manifest.json`
18. 生成配音资产清单，得到 `voiceover_asset_manifest.json`
19. 生成最终成片清单，得到 `final_video_manifest.json`

## 6. API 调用顺序

这套 Skill 的设计是“先本地编排，再按需接 provider”。当前版本里，真实 provider 还是 stub，但逻辑顺序是固定的：

1. 参考视频理解阶段
   - OCR
   - 语音转写
   - 参考画面分析
2. 策略和转移阶段
   - 参考 shot strategy
   - 产品画像
   - 产品动作矩阵
   - 动作转移
3. 脚本和分镜阶段
   - 新视频总计划
   - 字幕脚本
   - 配音脚本
   - 分镜 prompt
   - 分镜预检
4. Seedance 编排阶段
   - 本地编译 `seedance_tasks.json`
   - 估算成本
   - 预算熔断
5. 后处理阶段
   - 视频切片
   - 配音资产
   - 最终成片清单

## 7. 产物检查点

重点检查这几个文件：

- `output/manifests/pipeline_state.json`
- `output/manifests/cost_ledger.json`
- `output/manifests/seedance_tasks.json`
- `output/final/final_video_manifest.json`

如果是 dry-run，这些文件都应该能在 `tests/mock_run/` 下复现。

## 8. 出错处理

如果流程中断：

- 先看 `pipeline_state.json` 的 `current_step`
- 再看 `cost_ledger.json` 是否触发预算熔断
- 再看失败步骤的 artifact 是否通过 Schema
- 修完后用 `--resume` 继续

如果是接口或 key 问题：

- 先确认 `.env` 是否存在
- 再确认 `OPENAI_API_KEY`、`GEMINI_API_KEY`、`BFL_API_KEY`、`SEEDANCE_API_KEY`、`ELEVENLABS_API_KEY`
- 如果你习惯写 `FLUX_API_KEY`，这份 Skill 也会自动兼容到 `BFL_API_KEY`

## 9. 推荐日常节奏

1. 先跑 `--dry-run`
2. 看 `seedance_tasks.json` 和 `pipeline_state.json`
3. 如果结构对了，再考虑真实前置测试
4. 只在你明确授权后，再推进真实 provider

