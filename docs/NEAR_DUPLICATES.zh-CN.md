# 感知近重复图片聚类

[English](NEAR_DUPLICATES.md) | [简体中文](NEAR_DUPLICATES.zh-CN.md)

`cluster` 命令用于减少重复人工审核，并发现跨 YOLO 数据划分出现的视觉重复图片。它不依赖模型和 GPU，且严格只读：不会删除、移动或改写任何图片与标签。

## 使用方法

```powershell
yolo-label-recovery cluster D:\data\mining-safety `
  --output-dir D:\data\near-duplicate-audit `
  --splits train val test `
  --workers 4 `
  --max-distance 6 `
  --redact-paths
```

如果数据发布流程要求近重复图片绝不能跨划分，可在 CI 中增加 `--fail-on-cross-split`。

## 算法流程

1. 每个工作线程逐张解码图片，并应用 EXIF 方向修正。
2. 生成 64 位差值哈希 dHash、64 位均值哈希 aHash、尺寸及亮度统计。
3. 使用 BK-tree 查询 dHash 半径近邻，避免所有图片两两暴力比较。
4. 使用 aHash 距离和宽高比变化过滤错误候选。
5. 两张图片都属于低纹理图时，额外要求平均亮度接近，避免纯黑帧和纯白帧被错误合并。
6. 将通过检查的近邻关系转换为确定性的连通分量。
7. 每组选择分辨率最高的图片，作为人工首轮审核代表图。

对 `N` 张图片，指纹存储为 `O(N)`。BK-tree 在常见哈希分布下远少于暴力 `O(N²)` 比较，但极端哈希分布仍可能退化。像素内存受工作线程数限制，不会将全量数据集图片同时解码到内存。

## 输出文件

| 文件 | 用途 |
|---|---|
| `near_duplicate_members.csv` | 每张聚类成员图片、哈希及其到代表图的距离 |
| `review_representatives.csv` | 每组一张最高分辨率首轮审核代表图 |
| `fingerprint_failures.csv` | 损坏或无法读取的图片证据 |
| `near_duplicate_summary.json` | 策略、统计、分组成员和跨划分数量 |
| `near_duplicate_report.html` | 可直接交付的自包含可视化报告 |

## 安全边界与局限

- 分到同一组只代表视觉相似，不代表可以自动删除。
- 连通分量允许传递链：A 接近 B、B 接近 C 时，即使 A 与 C 距离较远也可能同组。报告会显示成员到代表图的最大 dHash 距离，便于检查松散组。
- dHash 适合发现缩放、JPEG 重压缩和轻微亮度变化，不擅长大幅裁剪、旋转或纯语义相似。
- 跨划分组是数据泄漏候选，移动图片前仍需确认来源，因为连续视频帧也可能被有意用于时序评测。
- 阈值属于数据策略。批量清理前应使用目标领域的人工样本验证。

## 可复现公开样例

```powershell
python examples\create_near_duplicate_fixture.py --output .near-duplicate-fixture
yolo-label-recovery cluster .near-duplicate-fixture `
  --output-dir .near-duplicate-output `
  --redact-paths
```

预期结果为：发现 `11` 个文件，其中 `1` 个故意损坏；形成 `3` 组、共 `7` 张聚类图片，其中 `2` 组跨数据划分。低纹理纯黑帧与纯白帧保持分离。

## 面试表达

该功能展示的是数据中心型 ML 工程能力，而不是简单封装训练命令。重点包括：有限内存解码、非暴力近邻搜索、保守防误合并、确定性审核分组、显式泄漏证据以及源数据不可变。
