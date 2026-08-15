# 阈值校准

[English](CALIBRATION.md) | [简体中文](CALIBRATION.zh-CN.md)

`calibrate` 命令将人工审核候选样本转换成明确、分类别的 AUTO/REVIEW 策略。它解决固定置信度阈值无法回答的问题：自动写入标签的决策究竟有多少审核证据支持？

## 输入约定

默认 CSV 字段如下：

| 字段 | 含义 |
|---|---|
| `class_name` | 数据集类别名称 |
| `conf` | Teacher 在 `[0, 1]` 范围内的置信度 |
| `verdict` | 人工结论，例如 `accept` 或 `reject` |

字段名称可以通过命令行修改。接受结论支持 `accept`、`true`、`yes`、`tp`、`1`，拒绝结论支持 `reject`、`false`、`no`、`fp`、`0`。

审核样本应来自目标摄像头和实际业务域，不应再把同一份数据当成独立测试集来宣传模型效果。

## 阈值选择策略

每个类别只按置信度排序一次，再通过累计真阳性和假阳性，以 `O(N log N)` 时间复杂度生成全部阈值点。

对于阈值 `t`：

```text
precision(t) = 置信度 >= t 且审核通过的候选数 / 置信度 >= t 的全部候选数
recall(t)    = 置信度 >= t 且审核通过的候选数 / 全部审核通过候选数
```

AUTO 阈值选择同时满足以下条件的最低阈值：

- 经验精度不低于 `--target-auto-precision`；
- AUTO 区域至少包含 `--min-auto-samples` 条审核样本。

在满足精度约束的前提下选择最低阈值，可以最大化自动补标覆盖率。

REVIEW 阈值选择不高于 AUTO，且能够保留至少 `--target-review-recall` 正样本的最高阈值。在满足召回约束的前提下选择最高阈值，可以减少人工复核工作量。

如果样本无法支持目标，工具会返回 `auto_target_not_met`、`review_target_not_met` 或 `no_positive_samples`，而不会为了输出数字强行提供不安全的回退阈值。

## 运行示例

```powershell
python examples\create_calibration_fixture.py

yolo-label-recovery calibrate `
  examples\calibration\reviewed_candidates.csv `
  --output-dir examples\calibration\output `
  --target-auto-precision 0.95 `
  --target-review-recall 0.90 `
  --min-auto-samples 20 `
  --redact-paths
```

输出内容：

- `calibration.json`：策略、分类别结果和可直接使用的阈值覆盖参数；
- `threshold_curve.csv`：全部类别、阈值对应的精度召回数据；
- `calibration.html`：自包含可视化证据报告。

## 使用边界

- 置信度依赖 Teacher 和业务域；更换模型、摄像头、光照或标注规范后应重新校准。
- 经验精度不是统计学保证。高风险部署应增加审核样本，或使用置信区间下界策略。
- 审核样本应覆盖全部工况，不能只审核容易样本或高置信度样本。
- 校准数据应与最终模型测试数据分离。
- 高置信度 Teacher 预测仍然只是证据，不等于真实标签。

## 面试讲解

该设计将模型分数和业务风险分开。AUTO 采用精度约束，因为错误自动标签会静默污染训练数据；REVIEW 采用召回约束，因为它的主要成本是人工时间，而不是静默污染。必须按类别制定策略，因为吸烟、拖鞋等小目标与拖拉机等大目标的置信度校准特性并不相同。
