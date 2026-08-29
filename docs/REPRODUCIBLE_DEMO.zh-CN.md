# 公开演示与验收指南

本指南用于没有私有数据、没有模型权重、甚至没有 GPU 的环境。目标不是展示模型精度，而是证明数据审计、阈值校准、候选治理、人工审核和安全写回这些工程机制能够被第三方复现。

## 1. 环境准备

```powershell
git clone https://github.com/jiapengLi11/yolo-label-recovery.git
cd yolo-label-recovery
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

验证入口：

```powershell
yolo-label-recovery --version
yolo-label-recovery --help
python tests\run_smoke_tests.py
pytest
```

## 2. 五分钟：数据审计

```powershell
python examples\create_synthetic_dataset.py --output .demo-dataset
yolo-label-recovery audit .demo-dataset `
  --output-dir .demo-audit `
  --hash-images `
  --check-images
```

打开 `.demo-audit\dataset_audit.html`。演示数据故意包含非法类别 ID、孤立标签和跨 train/val 的精确重复，预期审计状态为 `FAIL`。这里的成功不是“没有问题”，而是工具准确发现了预先注入的问题。

验收点：

- `dataset_audit.json` 中 `critical_issues == 2`。
- `cross_split_duplicate_groups == 1`。
- 报告能够定位具体 split、文件和问题类型。

## 3. 十分钟：完整 GT/AUTO 审核包

```powershell
python examples\create_review_fixture.py --output-dir .demo-review-fixture
yolo-label-recovery review-build `
  .demo-review-fixture\dataset `
  .demo-review-fixture\candidates.csv `
  --output-dir .demo-review-result `
  --render `
  --redact-paths
```

打开 `.demo-review-result\review_summary.html`，再启动 `.demo-review-result\START_REVIEW.bat`。公开样例枚举 `GT0_AUTO0`、`GT1_AUTO0`、`GT0_AUTO1` 和 `GT1_AUTO1`，用于观察同目标歧义、包含关系、模型内部重复和跨类别冲突。

完成少量决策后执行：

```powershell
yolo-label-recovery review-apply `
  .demo-review-fixture\dataset `
  .demo-review-result\company_decisions.csv `
  --output-root .demo-reviewed-dataset
```

验收点：

- 源数据集标签未发生修改。
- 输出目录是一个独立的标准 YOLO 数据集。
- 未完成决策会阻止写回。
- `REPLACE_GT` 会校验被替换 GT 是否仍与审核时一致。

## 4. 十五分钟：阈值、共识、近重复和主动审核

仓库已经提交了公开 fixture 和预生成报告；也可以重新执行：

```powershell
python examples\create_calibration_fixture.py --output .demo-reviewed.csv
yolo-label-recovery calibrate .demo-reviewed.csv `
  --output-dir .demo-calibration `
  --target-auto-precision 0.95 `
  --auto-confidence-level 0.95 `
  --target-review-recall 0.90 `
  --min-auto-samples 20 `
  --redact-paths

python examples\create_consensus_fixture.py --output-dir .demo-consensus-fixture
yolo-label-recovery consensus `
  .demo-consensus-fixture\primary_candidates.csv `
  .demo-consensus-fixture\verifier_candidates.csv `
  --output-dir .demo-consensus `
  --redact-paths

python examples\create_near_duplicate_fixture.py --output .demo-near-duplicates
yolo-label-recovery cluster .demo-near-duplicates `
  --output-dir .demo-near-duplicate-output `
  --redact-paths

python examples\create_prioritization_fixture.py --output-dir .demo-priority-fixture
yolo-label-recovery prioritize `
  .demo-priority-fixture\candidates_review.csv `
  .demo-priority-fixture\dataset `
  --output-dir .demo-priority-output `
  --budget 12 `
  --redact-paths
```

每个命令同时产生机器可读 JSON/CSV 和人可读 HTML。演示时先讲决策问题，再展示报告：为什么一个全局阈值不安全、为什么一个验证 Teacher 不能批准多个主候选、为什么近重复不能只靠文件哈希、为什么主动审核通过率不能直接当模型精度。

## 5. GPU 演示的边界

只有在具备目标数据和单类别权重时才执行 `run`。先安装与显卡匹配的 PyTorch，再安装推理依赖：

```powershell
python -m pip install -e ".[inference]"
yolo-label-recovery doctor --output environment.json --redact-paths
```

首次运行必须使用 `--dry-run`。它生成候选证据和复核图，不授权修改标签。稳定后才移除 `--dry-run`，并在明确需要可训练目录时增加 `--materialize-dataset`。

## 6. 演示讲解顺序

1. 问题：漏标会把真实目标当背景，形成错误监督。
2. 证据：单类别 Teacher 发现疑似漏标，但不直接成为真值。
3. 决策：分类别阈值、几何关系和人工审核共同授权。
4. 安全：源标签只读，写回生成派生数据集，可回滚、可比较。
5. 协作：多人平台用行锁、租约、版本号和审计避免并发错误。
6. 验证：公开 fixture 证明机制，私有固定测试集才证明模型收益。

## 7. 常见失败

| 症状 | 先检查 | 正确处理 |
|---|---|---|
| `run` 缺少 `ultralytics` | 是否只安装了轻量依赖 | 安装兼容 CUDA 的 PyTorch 后再装 `.[inference]` |
| 报告里路径不能公开 | 是否保留了真实绝对路径 | 使用 `--redact-paths` 重新生成 |
| 审核 UI 找不到 CSV | 是否在错误工作目录启动 | 从审核包根目录启动或传入绝对路径 |
| 续跑被拒绝 | 数据、模型或参数是否变化 | 保持原签名，或新建输出目录重新运行 |
| 写回被拒绝 | 是否有未决项或源 GT 漂移 | 完成审核，核对源数据版本后再应用 |
