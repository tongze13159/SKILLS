# viral-shot-remake-production 外部审查需求文档

## 1. 目标

把 `viral-shot-remake-production` 整理成一个可以交给第三方模型审查、也可以直接交给后续维护者接手的 Skill 版本。

这个版本需要满足：

- 能解释它是做什么的
- 能看懂每个脚本的输入、输出、依赖、环境变量
- 能在不泄露真实密钥的前提下安装和运行
- 能先 dry-run，再考虑 real-run
- 能通过最小测试验证基础链路
- 能清楚列出当前风险和边界

## 2. 范围

这个 Skill 只覆盖无露脸电商产品视频的流程化重构，包括：

- 参考视频分析
- 产品理解
- 动作转移
- 主视频计划生成
- 字幕与口播脚本
- 分镜 prompt
- Storyboard 首帧
- Seedance 任务编排

不覆盖：

- 人脸替换
- 明星模仿
- 1:1 照搬
- 未授权品牌、音乐、水印复用

## 3. 仓库结构

下面是当前项目的主要结构。`runs/` 是本地运行历史，建议在 git 中忽略。

```text
viral-shot-remake-production/
├── .env.example
├── AGENTS.md
├── README.md
├── SKILL.md
├── SOP.md
├── adapters/
├── agents/
├── assets/
├── config/
├── docs/
├── examples/
├── prompts/
├── schemas/
├── scripts/
├── tests/
└── runs/
```

## 4. 脚本参考

| 脚本 | 输入 | 输出 | 依赖 | 环境变量 |
| --- | --- | --- | --- | --- |
| `scripts/run_pipeline.py` | `--project-dir`、`--config`、`--reference-video`、`--product-images`、`--dry-run` / `--real`、`--resume`、`--step`、`--until-step` | 运行目录下的 `output/artifacts/*`、`output/manifests/*`、`output/storyboards/*`、`output/clips/*`、`output/audio/*`、`output/final/*` | `common.py`、`adapters/*`、`validate_artifact.py`、`normalize_duration.py`、`dry_run_fixture.py`、`jsonschema`、`requests`、`opencv-python-headless`、`scenedetect` | `.env` 中的 OpenAI、Gemini、FLUX/BFL、Seedance/Ark、ElevenLabs、base URL、endpoint ID |
| `scripts/run_step.py` | `--project-dir`、`--step`、`--dry-run` | 单步执行的同类产物 | `run_pipeline.py` | 同上，由 pipeline 读取 |
| `scripts/validate_artifact.py` | `--input`、可选 `--schema`、`--config`、`--project-dir` | stdout 校验结果，返回码表示成功/失败 | `common.py`、`jsonschema` | 无 |
| `scripts/repair_json.py` | `--input`、`--output`、`--schema` | 修复后的 JSON 文件 | `common.py`、`validate_artifact.py` | 无 |
| `scripts/estimate_cost.py` | `--config`、`--duration-ms` 或 `--seedance-tasks` | stdout JSON 成本估算 | `common.py` | 无 |
| `scripts/compile_seedance_tasks.py` | `--config`、`--plan`、`--product-profile`、`--action-matrix`、`--storyboards`、`--project-dir`、`--output` | `seedance_tasks.json` | `common.py`、`estimate_cost.py`、`validate_artifact.py` | 无 |
| `scripts/compile_audio_assets.py` | `--config`、`--plan`、`--output` | `audio_asset_manifest.json` | `common.py`、`dry_run_fixture.py` | 无 |
| `scripts/local_analysis.py` | 参考视频、产品图、`--project-dir`、可选抽帧参数 | `raw_shots.json`、`reference_visual_analysis.json`、抽帧结果图 | `cv2`、`scenedetect`、可选 `paddleocr` | `PADDLEOCR_*`（如果部署了 OCR 模型） |
| `scripts/normalize_duration.py` | `--input`、`--target-ms`、`--output` | 规范化后的主计划 JSON | `common.py` | 无 |
| `scripts/select_storyboards.py` | `--manifest`、`--precheck`、`--output` | 标注选中的 storyboard 清单 | `common.py` | 无 |

补充说明：

- `scripts/select_storyboards.py` 只是把预检结果映射回 storyboard 清单，不会调用外部 API。
- `scripts/run_step.py` 是 `run_pipeline.py` 的单步入口，适合定位单个步骤。
- `scripts/run_pipeline.py` 是唯一的总编排入口。

## 5. 环境变量

必须不要把真实值写进仓库。`.env.example` 里只能放空值或占位符。

必需变量：

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `FLUX_API_KEY` 或 `BFL_API_KEY`
- `SEEDANCE_API_KEY` 或 `ARK_API_KEY` / `BYTEPLUS_API_KEY` / `VOLCENGINE_API_KEY`
- `ELEVENLABS_API_KEY`

常见可选变量：

- `OPENAI_BASE_URL`
- `GEMINI_BASE_URL`
- `BFL_BASE_URL`
- `SEEDANCE_BASE_URL`
- `ELEVENLABS_BASE_URL`
- `FLUX_ENDPOINT_ID`
- `SEEDANCE_ENDPOINT_ID`
- `ELEVENLABS_VOICE_ID`
- `ELEVENLABS_TTS_MODEL`

## 6. 安装与运行

推荐运行环境：

- Python 3.11+
- `ffmpeg`
- `jsonschema`
- `requests`
- `opencv-python-headless`
- `scenedetect`
- `pydantic`
- `python-docx`（如果要生成或检查需求文档）

dry-run：

```bash
python3 scripts/run_pipeline.py --dry-run
```

dry-run 断点续跑：

```bash
python3 scripts/run_pipeline.py --dry-run --resume
```

真实前置链路，但只跑到 Seedance 编排：

```bash
python3 scripts/run_pipeline.py --real --resume --until-step 16_compile_seedance_tasks
```

单步：

```bash
python3 scripts/run_step.py --project-dir ./tests/mock_run --step 16_compile_seedance_tasks --dry-run
```

## 7. 测试方法

最小测试入口：

```bash
python3 -m unittest discover -s tests
```

建议至少覆盖：

- dry-run 全链路
- resume 行为
- schema 校验
- `.env` 别名加载
- Seedance 任务编译
- 预算熔断
- 审查包文件存在性

## 8. 当前风险

- 真实 provider 的返回结构可能和 prompt 预期有轻微漂移，需要兼容层兜底。
- Seedance 的分段约束会引发相邻合并，成本可能随分镜结构变化。
- 真实网络调用依赖本机 Python SSL/requests 环境，不能默认系统 Python 一定可用。
- `runs/` 里包含运行历史，不适合直接当作提交源。
- 如果外部密钥配置错误，真实链路会在早期步骤失败。

## 9. 验收标准

外部审查通过时，至少满足：

- `README.md` 能让人独立安装、运行、测试
- `.env.example` 不含任何真实密钥
- `SKILL.md` 能准确触发“产品展示视频仿拍、爆款分镜复刻、无人物产品视频重构”类任务
- 最小测试可运行
- 目录结构清晰，脚本职责清楚
- 风险和边界有明确说明
