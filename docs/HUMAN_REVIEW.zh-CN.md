# GT/AUTO 全情况人工审核门控

[English](HUMAN_REVIEW.md) | [简体中文](HUMAN_REVIEW.zh-CN.md)

## 为什么需要人工门控

Teacher 预测只是证据，不是天然正确的标签。仅看置信度无法区分以下情况：真正漏标、已有标签的重复框、同一目标但框尺度不一致、两个相邻真实目标，以及合理的跨类别嵌套。因此，在生成任何派生训练数据前，工作流先把这些情况显式分类并交给人工决策。

## 完整图片/类别状态空间

每张图片和每个类别必然属于以下四种状态之一：

| 状态 | 原 GT | Teacher 证据 | 默认处理 |
|---|---:|---:|---|
| `GT0_AUTO0` | 无 | 无 | 不处理，但保留覆盖统计 |
| `GT1_AUTO0` | 有 | 无 | 保留原 GT |
| `GT0_AUTO1` | 无 | 有 | 进入置信度、几何关系和数据划分判断 |
| `GT1_AUTO1` | 有 | 有 | 区分已标注、同目标尺度冲突和不同目标 |

矩阵会枚举全部图片和类别组合，而不是只统计有候选框的图片，因此不会把“没有发生预测”的情况悄悄忽略。

## 联合几何关系

候选框 $A$ 与目标框 $B$ 的交并比为：

$$
\operatorname{IoU}(A,B)=\frac{|A\cap B|}{|A\cup B|}
$$

当小框被大框包含时，IoU 可能很低，因此增加交集占较小框面积的比例：

$$
\operatorname{IoS}(A,B)=\frac{|A\cap B|}{\min(|A|,|B|)}
$$

归一化中心距离为：

$$
d_c(A,B)=\frac{\sqrt{(c_x^A-c_x^B)^2+(c_y^A-c_y^B)^2}}{\sqrt{\min(|A|,|B|)}}
$$

面积倍率为：

$$
r_a(A,B)=\frac{\max(|A|,|B|)}{\min(|A|,|B|)}
$$

默认策略：

- 已标注：`IoU >= 0.60`，或 `IoS >= 0.90` 且归一化中心距离 `<= 0.35`。
- 同目标但尺度存疑：`IoU >= 0.20`，或 `IoS >= 0.55` 且归一化中心距离 `<= 0.80`。
- Teacher 同类候选近重复：候选间 `IoU >= 0.90`，只保留置信度更高者。
- 跨类别冲突：跨类 `IoU >= 0.65` 且面积倍率 `<= 2.0`，进入人工审核，避免误删合理嵌套的小目标。

## 候选终态

每个 Teacher 候选只能进入一个终态：

| 终态 | 是否审核 | 允许的结果 |
|---|---:|---|
| `INVALID` | 否 | 拒绝 |
| `MODEL_DUPLICATE` | 否 | 拒绝低置信重复框 |
| `GT_ALREADY_LABELED` | 否 | 保留 GT，不新增重复框 |
| `GT_SAME_AMBIGUOUS` | 是 | 明确替换匹配 GT 或拒绝 |
| `GT_CROSS_CLASS_CONFLICT` | 是 | 作为不同类别新增或拒绝 |
| `TRAIN_MISSING_HIGH/MEDIUM` | 是 | 新增或拒绝 |
| `EVAL_MISSING_HIGH/MEDIUM` | 是 | 接受为评测 gold 候选或拒绝 |
| `BELOW_REVIEW_THRESHOLD` | 默认否 | 保留在审计表，可选择扩展审核 |
| `SPLIT_DISABLED` | 否 | 拒绝 |

高置信度也不会绕过人工审核。置信度只代表证据强度，不代表修改标签的权限。

## 生成离线审核包

```powershell
yolo-label-recovery review-build D:\data\dataset D:\runs\candidates_all.csv `
  --policy configs\review_policy.example.yaml `
  --output-dir D:\runs\company-review `
  --render `
  --redact-paths
```

输出包括全量审计表、待审核队列、决策模板、全部可视化候选、矩阵覆盖统计、HTML 汇总和离线 Tk 审核器。审核器会自动保存 `company_decisions.csv`，关闭后从首个未完成任务继续。

审核快捷键：

- `A`：确认新增不同目标框。
- `P`：用 AUTO 替换高亮的同类 GT。
- `E`：接受为 val/test 的 gold 标签候选。
- `D`：拒绝。
- `U`：暂不确定，写回前必须重新处理。

## 安全写回

```powershell
yolo-label-recovery review-apply D:\data\dataset D:\runs\company-review\company_decisions.csv `
  --policy configs\review_policy.example.yaml `
  --output-root D:\data\dataset-reviewed
```

写回阶段强制保证：

- 存在空白或 `uncertain` 决策时，整体拒绝执行。
- 输出目录不能等于、包含或成为源数据集的父目录。
- 永不修改源图片和源标签。
- 只有 `GT_SAME_AMBIGUOUS` 才允许替换，而且审核时引用的 GT 必须仍未变化。
- 新增前会对最新派生标签再次查重。
- val/test 审核结果默认只保留证据，不自动改变评测口径。
- 新增、替换、暂存和拒绝均生成可追溯 CSV。

## 无 GPU 公开演示

```powershell
python examples\create_review_fixture.py --output-dir .demo-review-fixture
yolo-label-recovery review-build .demo-review-fixture\dataset .demo-review-fixture\candidates.csv `
  --output-dir .demo-review-result --render --redact-paths
```

合成样例覆盖全部四种图片/类别状态以及主要候选终态，不需要 GPU、私有图片或模型权重。
