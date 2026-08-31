# 审核完成后的安全回写、训练与评测手册

本文用于矿区六类联合场景补标审核完成后的正式交付。目标是保证审核决定、标签回写、5090训练和模型对比均可追溯，并且不修改原始数据集。

## 1. 完成判定

最终导出前必须同时满足：

- 平台任务进度为 100%。
- `PENDING=0`、`CLAIMED=0`。
- `UNCERTAIN=0`；升级复核项必须由管理员修改为明确决定。
- 所有审核人员停止操作，避免最终导出期间继续写入。

## 2. 冻结平台并生成交接包

先在仓库根目录定义路径，再停止 Spring Boot 平台；MySQL 保持运行：

```powershell
$RepoRoot = "D:\work\yolo-label-recovery"
$Workspace = "D:\review\company_review_6cls_v2"
Set-Location $RepoRoot
powershell -ExecutionPolicy Bypass -File ".\platform\campus-deploy\stop-platform.ps1"
```

执行最终导出：

```powershell
powershell -ExecutionPolicy Bypass -File ".\platform\campus-deploy\finalize-review.ps1" `
  -ProjectId 1 `
  -Workspace $Workspace
```

如果 `python.exe`、`mysql.exe` 和 `mysqldump.exe` 未加入 PATH，可显式追加 `-Python "D:\tools\python.exe" -MySqlBin "D:\tools\mysql\bin"`。

脚本会执行以下操作：

1. 拒绝在平台仍运行时导出，保证审核决定冻结。
2. 使用 `mysqldump --single-transaction` 备份平台数据库。
3. 以 `candidate_id` 将 MySQL 决定合并回完整候选模板。
4. 校验数据库任务数与模板行数完全一致。
5. 拒绝重复ID、未知ID、未审核项和 `UNCERTAIN`。
6. 生成最终CSV、审核策略、运行摘要和SHA-256清单。

最终交接目录位于：

```text
<审核工作区>\final_exports\review_final_YYYYMMDD_HHMMSS\
```

## 3. 交接包内容

| 文件 | 用途 |
|---|---|
| `company_decisions_final.csv` | 带完整框坐标、GT引用和人工决定的安全回写输入 |
| `company_decisions_final.csv.summary.json` | 数量、决定分布、缺失项和CSV哈希 |
| `label_review_database.sql` | 多人审核平台数据库快照 |
| `review_policy_used.yaml` | 本轮IoU、IoS、中心距离等判定策略 |
| `heq_smoking_exact_remap_manifest.csv` | 精确修复 HEQ 吸烟框由单类 `0` 误并入六类 `person(0)` 的清单 |
| `summary.json/summary.txt` | Teacher扫描与候选生成摘要 |
| `decision_matrix_coverage.csv` | GT/AUTO情况覆盖统计 |
| `SHA256SUMS.txt` | 文件完整性校验 |

## 4. 在5090生成派生数据集

原始数据集保持只读。把交接包放入5090工程，例如：

```text
<ULTRALYTICS_ROOT>\review_final\
```

把最终文件放到审核工作区，并将最终 CSV 命名为脚本约定的 `company_decisions.csv`：

```text
<ULTRALYTICS_ROOT>\review_workspaces\company_review_6cls_v2\
  company_decisions.csv
  heq_smoking_exact_remap_manifest.csv
```

确认 5090 工程中的 `tools\autolabel_review_v2` 已更新为本次交接版本，然后运行：

```cmd
cd /d <ULTRALYTICS_ROOT>
tools\autolabel_review_v2\04_apply_company_review_on_5090.bat
```

脚本先按框几何坐标精确执行 HEQ 吸烟类别修复，只将清单中的旧 `class 0` 框改为 `smoking(5)`，不会批量修改真正的 `person(0)`。随后应用人工决定：训练集用于补标训练，`val/test` 仅应用人工明确确认的 `ACCEPT_EVAL_LABEL`，仍与训练隔离。

派生数据集为 `datasets\mining-safety-expanded6-company-reviewed-v3`，原始 person-autofill-v1 数据集不被修改。评测时同时保留原始评测集和人工修正版评测集，两套指标都要报告，避免只展示修正后答案带来的表面提升。

## 5. 回写后质量门禁

必须检查派生数据集中的：

- `apply_summary.txt`：实际新增和替换数量。
- `applied_or_replaced.csv`：成功回写明细。
- `rejected_during_apply.csv`：重复框复检、GT漂移等被拦截项目。
- `held_reviewed_eval.csv`：未写入的val/test审核决定。
- 图片、标签一一对应，YOLO类别范围为 `0..5`，坐标均在 `(0, 1]`。
- 原始数据集文件数量和哈希保持不变。

先运行一次数据扫描，再训练；任何损坏图片、空标签异常、类别越界或重复框激增都应停止训练并排查。

## 6. 5090训练策略

使用官方预训练 `yolo26m.pt` 作为起点，而不是从上一版六类权重继续训练，从而公平衡量数据治理带来的收益。训练参数与上一版保持一致，核心参数为：

- `imgsz=832`
- `epochs=140`
- `optimizer=AdamW`
- `lr0=0.0005`
- `cos_lr=True`
- `close_mosaic=15`
- `device=1`（以5090实际空闲卡为准）

只改变训练数据，不同时改变模型结构、损失函数或分配策略，保证本轮属于严格的数据消融实验。

## 7. 固定测试集对比

新旧模型必须在同一份未修改测试集、同一 `imgsz`、同一置信度和IoU参数下比较：

- 总体 Precision、Recall、mAP50、mAP50-95。
- 六个类别分别的 mAP50 和 mAP50-95。
- 联合场景子集：安全帽+吸烟、安全帽+拖鞋、多人场景。
- 小目标专项：吸烟、拖鞋的召回率和漏检样例。
- 误检、漏检及同一目标重复框可视化。
- 推理速度和显存占用，避免精度提升以不可接受的部署成本为代价。

最终保留 `best.pt`、`last.pt`、`results.csv`、混淆矩阵、PR曲线、验证预测图、测试结果和训练配置，形成完整模型交付包。

## 8. 回滚原则

- 原始数据集永不原地修改。
- 数据集、决定CSV、策略文件和训练结果都使用独立版本目录。
- 任意阶段失败时，删除派生输出并从交接包重新执行，不手工修补中间结果。
- `SHA256SUMS.txt` 校验失败时禁止回写和训练。
