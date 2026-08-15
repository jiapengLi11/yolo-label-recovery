# 跨 Teacher 一致性门控

[English](CONSENSUS.md) | [简体中文](CONSENSUS.zh-CN.md)

`consensus` 命令在候选生成后增加独立验证门控。两个 Teacher 分别运行，因此显存中仍然只需要保留一个模型；随后工具按数据划分、规范化图片路径、类别和框 IoU 对两份候选 CSV 进行对齐。共识阶段本身不依赖模型推理。

## 为什么需要

单个 Teacher 的高置信预测仍可能是系统性误检。要求第二个 Teacher 提供空间位置支持，可以降低 AUTO 自动补标的风险。命令采用保守规则：

- 主 Teacher 原本的 REVIEW 保持 REVIEW；
- 获得验证支持的主 Teacher AUTO 保持 AUTO；
- 未获得支持的 AUTO 降级到 REVIEW，而不是静默删除。

这是一项风险门控策略，并不意味着两个模型意见一致就等于真实标签。

## 匹配算法

对于每个 `(split, image, class)` 分组，候选对需同时满足：

- 验证 Teacher 置信度不低于 `--verifier-min-confidence`；
- 归一化检测框 IoU 不低于 `--agreement-iou`。

全部可用边按 IoU、置信度排序后进行贪心一对一分配，避免一个验证框同时为多个重叠主框背书。共识分数采用两个置信度的几何平均值，同时保留原始置信度和一致性 IoU 供审计。

## 运行流程

使用两套独立模型配置分别以 `--dry-run` 扫描数据集。建议选择不同架构、训练随机种子或数据来源；两个高度相似的检查点可能共享相同错误。

验证 CSV 只包含其原扫描阶段保留下来的预测，因此有效验证下限是该扫描 REVIEW 阈值与 `--verifier-min-confidence` 中的较大值。验证扫描的 REVIEW 阈值应设置得足够低，才能保留共识阶段需要的全部证据。

```powershell
yolo-label-recovery consensus `
  outputs\primary\candidates_all.csv `
  outputs\verifier\candidates_all.csv `
  --output-dir outputs\consensus `
  --agreement-iou 0.50 `
  --verifier-min-confidence 0.50 `
  --label-additions-dir outputs\consensus-additions `
  --redact-paths
```

输出内容：

- `consensus_all.csv`：全部主 Teacher 候选、最终分流和验证证据；
- `consensus_auto.csv`：获得一致性支持的 AUTO；
- `consensus_review.csv`：原 REVIEW 和被降级的 AUTO；
- `consensus.json`：机器可读策略和分类统计；
- `consensus.html`：自包含可视化报告；
- 可选增量标签目录：仅包含 agreed AUTO 框，并按 YOLO 标签文件组织。

增量目录不包含原标签。应将其合并到独立的派生标签树，不能直接修改不可变的源数据集。

## 复杂度与资源

推理仍然是两次串行扫描。共识阶段只处理分组后的 CSV 记录和框几何，不加载 PyTorch、不解码图片、不申请显存。一般每张图片目标数量很少，因此匹配成本远低于推理，也不会进行全数据集两两比较。

## 使用边界

- 使用一致性作为 AUTO 门控前，应先在目标业务域分别审核两个 Teacher。
- 记录验证扫描阈值；扫描时被过滤掉的低置信候选无法在共识阶段恢复。
- 尽可能降低主模型与验证模型的错误相关性。
- IoU 需结合目标尺寸调整；小目标可能需要较低阈值，但误匹配风险也会增加。
- 对比门控前后的精度和覆盖率。一致性通常以 AUTO 覆盖率换取更低风险。
- 人工抽查应同时覆盖获得一致性支持和被降级的候选。

## 面试讲解

该阶段将计算调度与决策策略分离。模型继续串行运行以限制显存峰值，模型无关的 CSV 边界允许不同检测器参与验证；一对一匹配避免重复背书，“降级而非删除”则保护召回并保留完整审核队列。
