# 主动审核优先级队列

[English](ACTIVE_REVIEW.md) | [简体中文](ACTIVE_REVIEW.zh-CN.md)

`prioritize` 命令将大量候选 CSV 转换为确定性的图片级人工审核队列。它不是简单按置信度排序，而是联合三个信号：

- **不确定性：** 检测置信度的归一化伯努利熵，在 `0.5` 附近最高。
- **类别稀缺度：** 类别频率的平方根倒数，并随着该类别已经获得审核席位而动态衰减。
- **视觉多样性：** 当前图片到已选集合的最小 dHash/aHash 感知距离。

该命令仅使用 CPU 且严格只读，不会修改源候选、图片或标签。

## 使用方法

```powershell
yolo-label-recovery prioritize D:\runs\candidates_review.csv D:\data\mining-safety `
  --output-dir D:\runs\priority-review `
  --budget 500 `
  --workers 4 `
  --uncertainty-weight 0.45 `
  --rarity-weight 0.20 `
  --diversity-weight 0.35 `
  --redact-paths
```

三个权重必须非负且总和为 `1`。默认只处理 REVIEW；只有明确需要在同一队列抽查 AUTO 时，才使用 `--modes review auto`。

## 图片级获取策略

人工通常打开整张图片审核，而不是孤立查看一行预测。因此工具会按 `split + image` 聚合同一图片的所有候选，保留关联类别和框，并计算图片级不确定性与稀缺度。候选路径可以是绝对路径、数据集相对路径或划分内相对路径，但解析结果必须位于数据集根目录内。

每个队列位置使用以下获取函数：

```text
优先级 = 0.45 * 不确定性
       + 0.20 * 动态类别稀缺度
       + 0.35 * 到已选集合的最小视觉距离
```

每选中一张图片，就更新类别覆盖数量和所有剩余图片的最小视觉距离。该贪心过程完全确定；对于 `N` 张审核图片和预算 `B`，大约需要 `O(N * B)` 次紧凑哈希比较，不会在内存中保留全分辨率像素。

## 输出文件

| 文件 | 用途 |
|---|---|
| `review_queue.csv` | 每张选中图片一行，包含排名和各评分分量 |
| `review_queue_candidates.csv` | 选中图片对应的原始候选行及优先级 |
| `review_pool.csv` | 全部可读审核图片及是否入选 |
| `image_failures.csv` | 缺失、越界或损坏图片证据 |
| `prioritization_summary.json` | 策略、总量、分布与队列数据 |
| `prioritization_report.html` | 可交付、可用于作品集的自包含报告 |

## 统计边界

该队列有意偏向不确定、稀缺和多样的样本，可提高每小时发现问题的效率，但**不能**用于估计无偏精度、召回率或缺陷比例。模型指标必须使用单独的随机或分层随机审核样本；主动队列用于发现与修复问题。

检测置信度默认也不是经过校准的概率。这里的熵只是获取启发式，不代表预测一定错误。阈值校准和人工结论仍是独立阶段。

## 公开样例

```powershell
python examples\create_prioritization_fixture.py --output-dir .priority-fixture
yolo-label-recovery prioritize .priority-fixture\candidates_review.csv .priority-fixture\dataset `
  --output-dir .priority-output `
  --budget 12 `
  --redact-paths
```

公开样例包含 `36` 张类别不均衡的审核图片，最终选择 `12` 张并覆盖全部 `6` 类；前六个位置每类各获得一个席位，之后才继续分配额外审核预算。
