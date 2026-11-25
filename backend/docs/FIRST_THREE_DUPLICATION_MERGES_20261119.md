# 第一批三项重复功能归并

已按合并可行性报告实施。生产修改仅位于 `C:\Users\29924\Codes\codex-cad-agent\backend`，旧目录未修改。没有合并S形/矩形/布局的不同来源规则，没有增加生成器或改变验收门槛。

## 1. 单次构造复用完整验收证据

新增 `app/cad_validation_evidence.py` 的 `ConstructionEvidence`。每次实际构造试算拥有自己的实例，来源事实绑定和主验收使用同一实例，复用以下四个检查器的相同完整输入报告：

- 对称圆形分割验收。
- 圆周放射连接验收。
- 分支重复结构验收。
- 投影结构验收。

主入口为 `cad_construction_interpreter.py`，`verify_final_source_contract` 增加可选证据上下文；独立调用该函数时仍有独立上下文，不依赖全局请求状态。

复用以验证函数和完整输入摘要为键，输入变化重新测量；报告保存与返回均隔离可变对象；异常原样抛出且不缓存。JSON无法编码但检查器自身能够处理的元数据，回退为直接验证，避免因复用机制增加新的输入限制。没有跨请求缓存，修复后的新试算也建立新实例。

合并后的实际追踪确认：C22有效记录计划、C24、C31对应的完整检查均从2次计算降为1次。来源证据和最终验收报告继续保留，不以减少检查项目实现去重。

## 2. 同协议JSON/SHA256编码归并

新增 `app/cad_canonical_json.py`，以下5个接口保留原名称、参数和用途，内部调用同一编码实现：

- `cad_assertions._fingerprint`
- `cad_edit_preview._fingerprint`
- `cad_edit_gate.geometry_fingerprint`
- `cad_edit_gate.geometry_entity_fingerprint`
- `cad_local_repair.fingerprint`

保留排序键、紧凑分隔符、UTF-8、Unicode输出以及原有NaN/Infinity和整数/浮点表示。未修改其他指纹协议：版本证据的NaN策略、候选去重忽略ID、差分舍入和语义数值归一均保持原入口。

没有重写或迁移历史版本摘要。

## 3. 基础长度换算归并

新增 `app/cad_length_units.py`。原41处独立表改为调用公共因子表，基础倍率只维护米、毫米两种明确输出单位。

保留各调用处原有数值类型，必要时显式使用浮点因子；“公分”别名仅在原本支持的调用处启用。工厂每次返回独立字典，模块之间不会因修改换算表互相影响。

没有改动单位省略、混合单位、同轮冲突、后续参数覆盖或剩余文本判定策略。41处表的倍率、数字类型及别名范围均已从合并前快照冻结并逐项验证。查重后原41处换算表已归并为公共模块中的2张目标单位表。

## 验证

| 检查 | 结果 |
| --- | --- |
| 基础回归 | **639 passed**，`.local-dev/test-uh4y_wjo/result.json` |
| 编辑预览、断言、局部修复、解释器等相关套件 | **135 passed，16 subtests passed**，`.local-dev/merge-edit-regression-v4_q4mwo/result.json` |
| 合并前后完整验收返回比较 | 15/15逐项一致，包含正常、未知附加条款和错误尺寸计划 |
| 同协议指纹对照 | 113组输入输出一致，另有冻结历史摘要回归 |
| 单位表兼容 | 原41处倍率、数值类型和别名范围逐项一致 |
| 证据隔离 | 修改输入重新测量、报告不可变污染隔离、异常不缓存、并行构造隔离、新实例重新计算均通过 |
| 实际重复调用 | C22/C24/C31对应完整验收从2次降至1次 |

两组pytest套件存在重叠，不相加作为独立测试总数。本轮没有真实模型请求，没有重测70项，也不更新语料通过率；本次目标是保持业务结果的代码归并。

## 可审查材料

- 合并前生产快照及SHA256：`.local-dev/merge-first-three-before-gfyis2fi/manifest.json`。
- 生产差异：`.local-dev/merge-first-three-review.patch`；修改31个现有app文件，新增3个共享基础模块。大部分修改为换算表替换和导入。
- 41处换算表与原哈希编码的回归输入：`tests/fixtures/merge_first_three_golden.json`。
- 新回归：`tests/test_merge_first_three.py`，纳入默认基础套件。
- 最终15组完整结果比较：`.local-dev/merge-first-three-before-after.json`。
- 最终等价与隔离检查：`.local-dev/merge-feasibility-ci669cut`。
- 合并后调用追踪：`.local-dev/current-duplication-audit-xu7_6qnj/runtime-validation-traces.json`。

后续S形、矩形、布局的公共测量整合仍属于第二批，本轮没有直接删除或替换这些业务验收器。
