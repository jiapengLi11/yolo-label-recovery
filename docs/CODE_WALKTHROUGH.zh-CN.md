# 核心代码导读

这份导读按一次候选从“图片”走到“派生标签”的生命线阅读，而不是按目录逐个介绍文件。每个阶段都给出入口、必须理解的不变量和建议动手验证的失败路径。

## 1. 命令如何进入业务代码

入口位于 `yolo_label_recovery/cli.py`。它只负责解析一级子命令并延迟导入对应模块。`run` 会延迟导入 Ultralytics 推理依赖，因此只使用审计、报告和审核功能时不必安装 PyTorch。

阅读顺序：

1. `cli.main()`：命令分发与可选依赖边界。
2. `configuration.py`：分类别阈值和模型路径解析。
3. `dataset.py`：`data.yaml` 与类别顺序契约。
4. `domain.py`：`Box`、`Candidate`、`ModelSpec` 等跨模块数据结构。

关键问题：为什么 CLI 不在模块顶层直接导入 `torch` 和 `ultralytics`？答案是把轻量数据治理与昂贵 GPU 运行时解耦，既缩短安装路径，也使 CI 能在无 GPU 环境验证大部分逻辑。

## 2. 多 Teacher 扫描主循环

主流程位于 `autolabel_with_single_class_models.py::main()`。阅读时按下面五个边界定位：

```text
参数与输出路径校验
  -> 构建图片索引和只读标签缓存
  -> 每次只加载一个单类别 Teacher
  -> 当前 split 按 batch 流式推理
  -> 当前 batch 成功后提交 CSV、派生标签和 state.json
```

重要实现：

- `validate_output_path()` 阻止输出落到源数据、模型目录或危险父目录。
- `preload_labels()` 只缓存当前类别的 GT，而不是把全部图片解码进内存。
- `CandidateWriter` 流式写入候选并使用稳定键去重。
- `append_batch_labels()` 只写派生标签树。
- `materialize_dataset()` 最后才组装标准 YOLO 数据集，图片优先硬链接、条件不满足时复制。
- OOM 时仅回滚未提交 batch，减小 batch 后重试；成功提交后才推进断点。

建议实验：把 batch 设得足够大触发 OOM，确认候选 CSV 没有半批记录、断点没有越过失败批次，恢复后候选数量不重复。

## 3. 候选为什么不是标签

`geometry.py` 处理向量化 IoU；`review_decision.py` 负责更完整的人工审核关系判断。

一个候选至少经历三次不同问题：

1. 与同类别已有 GT 的 IoU 是否足够大，判断“可能已经标过”。
2. 与其他候选是否近乎重复，判断“模型是否给同一目标多个框”。
3. 与同类和跨类 GT 的 IoU、IoS、中心距离、面积比组合是否支持某种审核动作。

这些阈值不能共用。已有标签匹配阈值过高会把框尺度变化误判成漏标；候选去重阈值过低会吞掉相邻真实目标；跨类别重叠则可能是 `person + helmet` 的合理嵌套。

## 4. 断点、幂等与运行证据

`state.py` 使用规范化输入构建 run signature。数据集、模型、类别、阈值或匹配参数发生变化时，旧断点不能继续使用，以免两个实验被静默拼接。

`runtime.py` 生成 `manifest.json`，记录参数、图片/模型清单、依赖版本、CUDA 和 GPU。`state.json` 回答“从哪里继续”，`manifest.json` 回答“这次运行到底是什么”。两者职责不同。

原子写文件采用“临时文件写完后替换正式文件”。这只能保证单文件不会出现半截内容，跨 CSV、标签和断点的一致性仍由批次提交顺序与幂等键共同保证。

## 5. 从候选证据到审核包

`review.py::build_review_package()` 读取候选和源 GT，枚举四种图片/类别状态，对每个候选调用 `review_decision.classify_candidate()`，生成：

- 完整候选与关系字段；
- 可执行动作集合；
- 按图片聚合的可视化；
- 决策模板、摘要和启动器。

桌面审核器 `review_gui.py` 把同图候选聚合显示。每次决定先追加 JSONL 日志，再原子替换 CSV 快照；崩溃后重放日志恢复最近决定。这里的 JSONL 是写前日志，CSV 是便于交接的当前快照。

## 6. 安全写回

`review_apply.py::apply_review_decisions()` 是离线链路唯一允许创建审核后数据集的阶段。它会：

1. 拒绝未完成或非法决策。
2. 检查候选框是否合法。
3. 对 `REPLACE_GT` 核对源 GT 行和坐标是否漂移。
4. 再次执行重复检查，防止审核期间数据变化。
5. 默认隔离 val/test 改动，避免静默移动评测目标。
6. 物化到新的输出目录，保留源数据不变。

面试时应强调：人工点击不是直接 append，一次决定仍需通过写回阶段的并发与数据完整性校验。

## 7. Web 平台的请求生命线

多人平台的高频路径是：

```text
Vue claimNext()
  -> POST /api/tasks/claim-next
  -> TaskService.claimNext()
  -> TaskRepository.findClaimable() + PESSIMISTIC_WRITE
  -> ReviewTask.claim() 写 claimed_by 和 lease_until
  -> Vue 定时 heartbeat()
  -> submitDecision() 携带 expectedVersion
  -> MySQL 保存决定、状态和审计事件
  -> advanceAfterDecision() 优先领取本图下一框
```

`TaskService` 是最值得精读的后端文件。它把认证后的用户、项目访问权、事务、行锁、租约、版本冲突、决策策略和审计串起来。Controller 只做 HTTP 输入输出，Repository 只表达查询，真正的业务不变量在 Service。

## 8. MySQL 约束如何保护业务

Flyway `V1` 创建用户、项目、成员、任务、决定和审计表；`V2` 根据真实界面查询增加同图候选和最近审核复合索引。

| 约束/索引 | 保护的问题 |
|---|---|
| `UNIQUE(project_id, candidate_id)` | 重复导入同一候选不会生成两条任务 |
| `UNIQUE(task_id)` on decisions | 一个任务只有一个当前最终决定 |
| `(project_id, state, lease_until, id)` | 高效寻找待领取或已过期任务 |
| `(project_id, split, image_name, id)` | 左侧列表快速加载本图全部候选 |
| `@Version` | 旧页面不能覆盖更新后的任务 |

行锁只保护领取事务的瞬间竞争；租约保护跨请求的临时所有权；乐观版本保护提交时的陈旧状态。把三者混为“数据库锁”会失去设计重点。

## 9. Vue 审核工作台

`platform/frontend/src/App.vue` 是一个图像优先的专用工作台。重点阅读：

- `claimNext()` 和 `activateTask()`：领取并切换任务。
- `loadImageCandidates()`：按原图加载全部候选。
- `submitDecision()` 与 `advanceAfterDecision()`：一键保存并自动前进。
- `startHeartbeat()`：租约续期和失败可见化。
- `openRecentDecision()`：回到历史决定并基于版本纠错。
- `handleShortcut()`：高频审核快捷键。
- `loadVisual()` 与 `revokeVisual()`：带 JWT 读取图片并释放 Blob URL。

前端隐藏按钮不是权限控制。所有项目访问、角色限制、任务所有权和版本检查必须由后端再次执行。

## 10. 建议的调试顺序

1. 先运行纯函数和 fixture 测试，确认几何与状态逻辑。
2. 再运行 Python CLI 的公开演示，确认产物契约。
3. 启动后端 H2 集成测试，观察事务和授权。
4. 启动前端，使用两个账号制造领取竞争、过期和修订。
5. 最后才接入真实 MySQL、真实审核包和局域网。

每次调试保留一种证据：失败日志、API 响应、数据库行、审计事件、截图或测试报告。没有证据的“应该没问题”不能算完成。
