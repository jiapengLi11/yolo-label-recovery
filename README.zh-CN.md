# YOLO Label Recovery

[English](README.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/jiapengLi11/yolo-label-recovery/actions/workflows/ci.yml/badge.svg)](https://github.com/jiapengLi11/yolo-label-recovery/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/jiapengLi11/yolo-label-recovery)](https://github.com/jiapengLi11/yolo-label-recovery/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a085.svg)](LICENSE)

一个安全、可审计、内存友好的多 Teacher YOLO 数据集漏标恢复流水线。

本项目源自工业安全视觉任务。它使用每个类别各自的单类别检测器扫描多类别数据集，发现未被现有标签覆盖的高置信度预测，并将新增标注写入派生标签目录，始终不修改源数据集。

## 预生成展示结果

查看以下结果不需要 GPU、私有数据集或现场执行命令。两张截图均由仓库内的合成测试数据生成，用于展示工具行为和报告结构，不代表生产数据精度。

### 无模型数据集审计

![预生成 YOLO 数据集审计结果](docs/assets/audit-preview.png)

合成数据主动注入了一个非法类别 ID、一个孤立标签，以及一组跨 train/val 的精确重复图片。审计结果正确返回 `FAIL`、`2` 个严重问题、`1` 个警告和 `1` 组跨划分重复。

### 多 Teacher 漏标恢复报告

![预生成多 Teacher 质量报告](docs/assets/report-preview.png)

| 展示证据 | 预生成结果 |
|---|---:|
| 图片-模型扫描次数 | 3,600 |
| 单类别 Teacher 数量 | 3 |
| AUTO / REVIEW 示例 | 3 / 3 |
| 初始 batch | 32 |
| 各模型稳定 batch | 32 / 16 / 8 |
| 模拟 OOM 重试次数 | 3 |
| 是否修改源标签 | 否 |

## 为什么需要这个项目

多类别数据集经常包含 `person + helmet + smoking`、`person + slipper` 等联合场景。如果原始标注工作每次只关注一个目标，图中其他类别的有效目标就可能漏标。使用不完整标签训练多类别模型时，这些目标会被当作背景，从而向模型传递错误监督信号。

本工作流采用保守策略：

```mermaid
flowchart TD
    A["现有 YOLO 数据集"] --> Q["无模型数据审计"]
    Q -->|"结构与数据划分检查通过"| B["只读源标签"]
    B --> C["加载一个单类别 Teacher"]
    C --> D["批量 FP16 流式推理"]
    D --> E["预测框与同类别原标签进行 IoU 匹配"]
    E -->|"IoU >= 已标注阈值"| F["已有标签：忽略"]
    E -->|"疑似漏标"| G["按置信度分流"]
    G --> H["IGNORE"]
    G --> I["REVIEW + 审计 CSV"]
    G --> J["AUTO + 派生标签目录"]
    J --> K["可训练 YOLO 数据集"]
    I --> L["HTML 报告与分类抽样图"]
    J --> L
```

## 核心特性

- 工具将原始 `labels/` 视为只读数据。
- 显存中同一时间只保留一个检测模型。
- 使用 `stream=True` 增量消费推理结果。
- 候选记录持续写入 CSV，不在内存中累计全部预测。
- 单类别模型的类别 ID 会映射到 `data.yaml` 中的多类别 ID。
- 已有标签匹配 IoU 与候选框去重 IoU 分开控制。
- `--materialize-dataset` 可生成标准 YOLO 数据集，并在条件允许时使用硬链接。
- 复核图按原图聚合，同一张图中的多个候选目标会一起展示。
- GPU 推理前先进行无模型审计，检查错误标签、损坏图片和 train/val/test 精确重复。
- 每次扫描生成 manifest，记录参数、图片清单、依赖版本、CUDA 和 GPU 信息。

## 一分钟公开演示

演示脚本会故意生成非法类别 ID、孤立标签，以及跨数据划分重复图片。它不需要模型权重或私有数据。

```powershell
python examples\create_synthetic_dataset.py --output .demo-dataset
yolo-label-recovery audit .demo-dataset `
  --output-dir .demo-audit `
  --hash-images `
  --check-images
```

打开 `.demo-audit\dataset_audit.html`。预期结果为 `FAIL`，说明审计工具成功捕获了演示数据中主动注入的问题。

在昂贵的全量扫描前检查陌生训练机环境：

```powershell
yolo-label-recovery doctor --output environment.json --redact-paths
```

## 快速开始

只安装轻量数据审计与报告功能，不下载 PyTorch 或 Ultralytics：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .

yolo-label-recovery audit D:\data\mining-safety --output-dir D:\data\audit-001 --hash-images --check-images
```

如需使用 GPU 自动补标，请先安装与目标 GPU/CUDA 兼容的 PyTorch，再安装推理依赖：

```powershell
python -m pip install -e ".[inference]"

yolo-label-recovery run `
  --dataset-root D:\data\mining-safety `
  --out-root D:\data\autolabel_run_001 `
  --models-json configs\models.example.json `
  --classes person helmet vest tractor slipper smoking `
  --splits train val test `
  --imgsz 832 `
  --batch 32 `
  --device 0 `
  --workers 0 `
  --draw-review `
  --draw-auto-samples 80 `
  --adaptive-batch `
  --dry-run `
  --force
```

建议始终先使用 `--dry-run`。它会生成统计信息、候选 CSV 和复核图，但不会写入自动新增标签。检查结果后，移除 `--dry-run`；如需生成可直接训练的数据集，再增加 `--materialize-dataset`。

运行完成后生成可视化质量报告：

```powershell
yolo-label-recovery report D:\data\autolabel_run_001
```

向 GitHub 或面试作品集发布报告时应增加 `--redact-paths`。真实运行的 manifest 为了复现会保留本地数据集和模型路径，未经检查不应直接公开。

长时间扫描意外中断后，可以使用完全相同的原始参数，将 `--force` 替换为 `--resume`：

```powershell
yolo-label-recovery run <相同参数> --resume
```

每个批次成功后，检查点会保存已提交的图片游标和统计信息。候选 CSV 与标签写入均具有幂等性，因此中断批次可以安全重试，不会产生重复记录或标签。

## 数据集格式

```text
dataset-root/
  data.yaml
  images/
    train/
    val/
    test/
  labels/
    train/
    val/
    test/
```

`data.yaml` 必须按照标签类别 ID 的顺序定义 `names`。扫描前工具会校验类别名称。

## 输出格式

```text
out-root/
  labels_autofill_v1/       # 原标签加 AUTO 新增标签
  candidates_auto.csv       # 高置信度候选
  candidates_review.csv     # 中等置信度候选
  candidates_all.csv        # 完整候选审计流
  auto_samples/<class>/     # AUTO 分类抽样图
  review_images/<class>/    # REVIEW 分类抽样图
  summary.json
  summary.txt
  state.json                # 原子化断点续跑状态
  manifest.json             # 参数、数据清单、依赖、CUDA 与 GPU
  report.html               # 可视化质量报告
  trainable_dataset/        # 可选，由 --materialize-dataset 生成
    data.yaml
    images/
    labels/
```

源标签目录绝不会被用作输出目录。如需撤销一次实验，只需删除输出目录，然后从未被修改的源数据重新运行。

## 默认阈值

| 类别 | AUTO | REVIEW |
|---|---:|---:|
| person | 0.75 | 0.55 |
| helmet | 0.75 | 0.55 |
| vest | 0.75 | 0.55 |
| tractor | 0.70 | 0.50 |
| slipper | 0.65 | 0.45 |
| smoking | 0.65 | 0.40 |

使用 `--threshold smoking:0.70:0.45` 覆盖单个类别，格式为 `类别:AUTO阈值:REVIEW阈值`。

## 资源模型

对于 `N` 张图片和 `K` 个单类别模型，计算量约为 `K x N` 次图片-模型推理。实现不会一次加载所有图片或所有模型：

- GPU 显存：当前模型、当前批次激活值、当前预测张量。
- CPU 内存：图片路径、当前批次解码对象、当前类别标签缓存、有限数量的复核样本。
- 磁盘：流式 CSV 记录和派生标签副本。

启用 `--adaptive-batch` 后，工具会记录发生 OOM 的类别、数据划分和批大小，丢弃尚未提交的当前批次，然后将批大小减半重试。只有成功生成候选后，当前批次才会提交到 CSV 和标签目录。汇总文件与 HTML 报告会显示初始/稳定批大小以及 OOM 重试次数。

## 项目状态

该仓库是经过清理的工程作品，不是公开基准测试。真实项目图片、标注、模型权重、日志和机器路径均被有意排除。可复现实验需要用户自行提供 YOLO 数据集和单类别模型权重。

延伸阅读：

- [架构与工作流](docs/ARCHITECTURE.md)
- [内存与显存设计](docs/MEMORY_AND_GPU.md)
- [数据治理](docs/DATA_GOVERNANCE.md)
- [面试项目讲解](docs/INTERVIEW_STORY.md)
- [作品集与面试指南（中文）](docs/PORTFOLIO_GUIDE.zh-CN.md)
- [作品集与面试指南（英文）](docs/PORTFOLIO_GUIDE.md)
- [检测模型卡模板](docs/MODEL_CARD_TEMPLATE.md)
- [架构决策记录](docs/adr/0001-immutable-derived-labels.md)
- [路线图](docs/ROADMAP.md)
- [贡献指南](CONTRIBUTING.md)

## 验证

仓库包含不依赖 pytest 的轻量冒烟测试：

```powershell
python -m py_compile autolabel_with_single_class_models.py
python tests\run_smoke_tests.py
pytest
```

完整开发环境可使用 `python -m pip install -e ".[inference,dev]"` 安装。
