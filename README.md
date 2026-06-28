# viral-shot-remake-production

协议驱动、先 dry-run 后 real-run 的无露脸电商产品视频 Skill。

它适合做这些事：

- 产品展示视频仿拍
- 爆款分镜复刻
- 无人物产品视频重构
- 参考视频到原创电商短片的流程化改造

如果你要的是带有人脸、明星模仿、1:1 照搬、或者未授权品牌/音乐复用，这个 Skill 不适用。

## Quick Start

```bash
python3 scripts/run_pipeline.py --dry-run
```

默认会读取 `tests/mock_input/`，用 mock adapter 跑完整个前置链路，并把结果写到 `tests/mock_run/`。

## Installation

建议使用 Codex 提供的 bundled Python，或者至少准备这些运行依赖：

- `jsonschema`
- `requests`
- `opencv-python-headless`
- `scenedetect`
- `pydantic`
- `python-docx`，如果你要生成或检查需求文档的 `.docx`

本地还需要：

- `ffmpeg`，用于视频预处理和音频抽取
- 可选的 OCR 依赖，如果你要走更完整的本地识别链路

环境变量模板在 [`.env.example`](./.env.example)。

## Run

Dry-run：

```bash
python3 scripts/run_pipeline.py --dry-run
```

Dry-run 断点续跑：

```bash
python3 scripts/run_pipeline.py --dry-run --resume
```

真实前置链路，但只跑到 Seedance 任务编排为止：

```bash
python3 scripts/run_pipeline.py --real --resume --until-step 16_compile_seedance_tasks
```

单步运行：

```bash
python3 scripts/run_step.py \
  --project-dir ./tests/mock_run \
  --step 16_compile_seedance_tasks \
  --dry-run
```

## Testing

```bash
python3 -m unittest discover -s tests
```

重点测试覆盖：

- dry-run 全链路和 resume
- JSON Schema 校验
- 预算熔断
- `.env` 加载与别名兼容
- Seedance 任务编译

## 目录结构

主要源码目录如下：

```text
viral-shot-remake-production/
├── SKILL.md
├── SOP.md
├── README.md
├── .env.example
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
└── runs/   (local runtime history, ignored by git)
```

更完整的审查说明见 [docs/external_review_requirements.md](./docs/external_review_requirements.md)。

## 已知约束

- 默认先 dry-run，再 real-run
- 所有中间产物都要经过 JSON Schema 校验
- 真实 API 调用前会先打印预计成本
- FLUX 在实现里支持 `FLUX_API_KEY` 和 `BFL_API_KEY` 两种名字
- Seedance 的真实编排只应在明确授权后执行
