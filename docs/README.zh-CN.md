# YOLO Label Recovery 文档导航

这不是一份按文件名排列的清单，而是一条按目标组织的阅读路线。第一次进入仓库时，建议先判断自己要完成的是“快速理解”“本地复现”“读懂代码”“部署协作平台”还是“准备面试”，再沿对应路径阅读。

## 30 秒理解项目

YOLO Label Recovery 解决多来源、多类别 YOLO 数据中的漏标问题。六个单类别 Teacher 只负责生成证据；几何规则、分类别阈值和人工审核决定候选如何流转；安全写回始终生成派生数据集，不覆盖源标签。多人协作平台将离线 CSV 队列转化为可登录、可租约领取、可版本校验、可审计纠错的 Web 工作流。

```mermaid
flowchart LR
    A[只读源数据] --> B[数据审计]
    B --> C[单类别 Teacher 串行扫描]
    C --> D[候选证据与几何关系]
    D --> E[人工审核任务]
    E --> F[安全写回派生数据集]
    F --> G[固定测试集评估]
    G --> H[部署与困难样本回流]
```

## 按目标阅读

| 目标 | 首先阅读 | 接着阅读 | 最终产出 |
|---|---|---|---|
| 快速理解价值 | [中文 README](../README.zh-CN.md) | [矿区项目复盘](MINING_SAFETY_AI_ENGINEERING_BLOG.zh-CN.md) | 能用 90 秒讲清问题、方案与边界 |
| 15 分钟复现 | [公开演示与验收](REPRODUCIBLE_DEMO.zh-CN.md) | [架构](ARCHITECTURE.md) | 本地报告、审计结果和审核包 |
| 读懂核心代码 | [核心代码导读](CODE_WALKTHROUGH.zh-CN.md) | [内存与显存](MEMORY_AND_GPU.md) | 能追踪候选从模型到派生标签的完整路径 |
| 部署多人平台 | [协作平台设计](COLLABORATION_PLATFORM.md) | [平台目录说明](../platform/README.md) | 局域网登录、领取、审核、纠错与审计 |
| 判断哪些结论可信 | [项目证据与边界](PROJECT_EVIDENCE.zh-CN.md) | [生产规模验证](PRODUCTION_VALIDATION.zh-CN.md) | 能区分实现、验证、设计和未来规划 |
| 理解完整矿区系统 | [矿区系统设计](MINING_SYSTEM_DESIGN.zh-CN.md) | [项目复盘博客](MINING_SAFETY_AI_ENGINEERING_BLOG.zh-CN.md) | 能解释在线监控闭环和离线模型闭环 |
| 准备面试 | [高频追问与回答](INTERVIEW_QA.zh-CN.md) | [作品集指南](PORTFOLIO_GUIDE.zh-CN.md) | 3 分钟项目介绍、30 分钟技术深挖 |

## 核心主题索引

### 数据与算法

- [数据治理](DATA_GOVERNANCE.md)：源数据不可变、派生数据集和审计证据。
- [阈值校准](CALIBRATION.zh-CN.md)：分类别 AUTO/REVIEW 阈值与 Wilson 下界。
- [跨 Teacher 一致性](CONSENSUS.zh-CN.md)：独立模型证据和保守降级。
- [近重复聚类](NEAR_DUPLICATES.zh-CN.md)：感知哈希、BK-tree 和跨划分泄漏。
- [主动审核队列](ACTIVE_REVIEW.zh-CN.md)：不确定性、类别稀缺度和视觉多样性。
- [GT/AUTO 全情况审核](HUMAN_REVIEW.zh-CN.md)：IoU、IoS、中心距离、面积比例和安全写回。

### 审核工具与平台

- [按图片聚合桌面审核器](GROUPED_REVIEW_APP.md)：离线交付、原子检查点和异常恢复。
- [多人 Web 审核平台](COLLABORATION_PLATFORM.md)：JWT、项目成员隔离、行锁、租约、乐观锁与审计。
- [架构决策记录](adr/0001-immutable-derived-labels.md)：为什么这些约束是主动设计，而不是偶然实现。

### 工程交付

- [公开演示与验收](REPRODUCIBLE_DEMO.zh-CN.md)：无 GPU 演示、预期结果和失败排查。
- [核心代码导读](CODE_WALKTHROUGH.zh-CN.md)：从 CLI 到 Python、Spring Boot、MySQL 和 Vue。
- [项目证据与边界](PROJECT_EVIDENCE.zh-CN.md)：可以确认、需要限定、仍待验证的内容。
- [路线图](ROADMAP.md)：已完成能力、计划项和非目标。

## 推荐学习顺序

1. 运行一次无 GPU 公开演示，先看到输入、输出和失败证据。
2. 沿 `run -> CandidateWriter -> review-build -> review-apply` 追踪离线数据链路。
3. 沿 `claim-next -> heartbeat -> decision -> recent decision` 追踪在线协作链路。
4. 主动构造一次重复导入、租约过期或旧版本提交，观察系统如何拒绝错误状态。
5. 最后阅读项目证据边界和面试问答，避免把设计方案描述成已落地事实。

## 文档维护规则

- 新功能必须同时更新 README 入口、CHANGELOG、至少一个可复现实例和自动化测试。
- 任何生产数字都要标明样本、口径和验证范围；截图不能替代模型精度评测。
- 本机路径、模型权重、私有数据和未脱敏日志不得进入仓库。
- 文档中的本地相对链接由 CI 自动检查，避免重构后入口失效。
