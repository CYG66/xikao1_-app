# 全库人工审读续篇（二）：会话、交付、存储与工具分发

日期：2026-11-25。仅审读 `C:/Users/29924/Codes/codex-cad-agent/backend`，没有修改生产功能或测试断言，没有真实模型请求，没有设备执行，没有 GitHub 操作。

## 1. 本轮覆盖

结合前轮已读且哈希未变的片段，补齐以下 6 个生产文件的全文人工审读，共 6,653 行：

| 文件 | 行数 | 重点核对 |
|---|---:|---|
| `app/agent_http_service.py` | 1824 | 同步/流式、候选可见性、导航、请求准备、检查点和恢复 |
| `app/conversation_memory.py` | 1308 | 对象焦点、活动 CAD 目标、需求摘要、待编辑状态和会话状态迁移 |
| `app/creative_projects.py` | 1239 | 项目状态、候选写入、迁移、选择、版本、分区和持久化回滚 |
| `app/creative_workflow.py` | 1214 | 规划提交、执行状态同步、恢复规划、导航回设计和验收报告 |
| `app/database.py` | 840 | 业务快照事务、版本与执行历史、案例记录、模板元数据、遥测和备份 |
| `app/task_store.py` | 228 | 待确认任务、状态迁移、到期和重启中断处理 |

另补读了 `agent_service.py` 的同步主流程、部分供应商工具循环、工具分发、确认与重试、路由以及安全/确认执行分支；并逐项追踪相关工具合同与参数解析。该文件尚未全文读完，未以本轮部分阅读替代其余分支审查。

精确覆盖记录和 SHA-256 见 `.local-dev/code-capability-audit-20261125/manual-reading-log.json`。这是阅读台账，不代表所有能力都完成了生产端到端测试。全库人工全文审读仍未完成。

## 2. 新确认：历史导航和新候选交付门槛冲突

调用链：`agent_chat` → `_prepare_agent_chat_context` → `_navigate_cad_candidate` → `_agent_chat` → `_finalize_run_result` → `_bind_and_filter_candidate_visibility`。

使用现有确定性解释器生成两个实际验收通过的圆形版本，建立父子关系；子版本的规划版本核验也通过。通过真实离线 `agent_chat` 入口请求“撤销刚才的修改”，结果是：

- 项目基准实际切回父版本，候选总数仍为 2，没有生成新版本。
- `rollback_verification.status=success`，历史几何哈希复核通过。
- 最终返回 `ok=false`、`variant=null`、`candidate_visibility.status=hidden`。
- 原因包含 `candidate_created_before_current_run`，运行记录被记为失败。

原因：最终交付门槛要求候选在当前运行创建；历史导航合法返回旧版本，与该条件冲突。已有“无变化操作保留来源”的专门交付分支，但没有同等覆盖历史导航。

**这是已有导航能力与交付能力之间的冲突，不是没有撤销实现。** 应区分新候选、历史导航和实测无变化结果的证据条件，保留来源版本与哈希核验，不应简单移除旧候选保护。

证据：`phase2_navigation_probe.py`、`phase2-navigation-probe.json`。复现使用真实业务入口、真实隔离存储与现有几何解释器；禁止模型路径被调用，没有真实网络或设备调用。它不是 DeepSeek 在线成绩。

## 3. 新确认：英文 mm 在多处解析为米

同一原文分别使用 `毫米` 与 `mm`：

| 来源 | `20毫米` | `20mm` |
|---|---:|---:|
| 会话需求摘要中的宽度 | 0.02 m | 20 m |
| `parameterize_design` 中的宽度 | 0.02 m | 20 m |
| 模板布局解析中的间距 | 0.02 m | 20 m |

高度 30 毫米同样会被解析为 30 米。`cm` 与中文厘米的对照一致。

相关路径：`ConversationMemoryStore._extract_requirements`、`agent_skills.parameterize_design`、`agent_skills._template_layout_requirements`。正则单位候选将 `m` 放在 `mm` 前，且没有足够的单位尾部约束，导致前缀匹配。

项目已经有 `cad_length_units`、坐标契约和带单位边界的来源解析；这些旧入口仍各自维护部分解析。**共享换算系数并不能保证单位词法解析也已经统一。**

复现范围是上述实际解析函数，没有将它扩大解释为所有 HTTP 路由都会错误交付。严格来源验收可能拦截错误，但错误摘要和间距仍可能干扰规划或补参。

证据：`phase2-probes.json` 的 `unit_equivalence`。

## 4. 新确认：空回复恢复函数引用未定义变量

`RobotAgentService._recover_candidate_after_empty_response` 引用了 `raw_followup`，但该函数没有参数、局部定义或模块全局提供这个名称。直接调用该现有函数即得到：

`NameError: name 'raw_followup' is not defined`

DeepSeek 和兼容供应商工具循环的部分进阶空回复分支会调用它。该异常发生在实际恢复构造前，因此现象可能是模型偶发空回复后，恢复本身再次失败。

另用 Python `symtable` 对生产文件的已绑定全局名称做交叉检查，唯一发现的这类未解析全局引用就是该处。符号检查只是辅助线索，运行时复现才证明本项错误；这项扫描不计为人工全文阅读。

证据：`phase2-probes.json` 的 `empty_response_recovery`、`unresolved-global-references.json`。没有真实供应商请求。

## 5. 新确认：确认失败后的重试任务丢失上下文

已读调用链：`_confirm_impl` → 可重试预检失败 → `_register_pending` → 新任务持久化 → 下次 `_confirm_impl`。

在隔离任务存储中，为第一次待确认任务提供合法冻结上下文；仅模拟“控制权未就绪”的预检失败，并禁止设备执行：

- 原任务含上下文。
- 首次确认返回 `retryable=true`，成功创建重试待确认任务。
- 新任务的 `execution_context` 缺失。
- 再次确认被拒绝：“待确认任务缺少原始请求上下文，已拒绝恢复，请重新发起请求。”
- 设备执行函数调用次数为 0。

原因：新任务只从请求 ContextVar 读取上下文；确认接口进入重试时，没有把原任务的冻结上下文传入该位置。恢复门槛正确拒绝缺失证据，缺口在重试创建端。

**该复现使用设备演示工具检查公共确认生命周期，不代表已验证所有高风险 CAD 编辑都走这个可重试分支。** CAD 的确认和普通请求共享相关基础设施，应保留这个边界说明。

证据：`phase2-probes.json` 的 `confirmation_retry_context`。

## 6. 新确认：独立图纸修改已有预演，却被分发为未实现工具

使用符合现行 Schema 的 `target + operations`，将隔离 JSON 图纸中一条线的终点从 1000 改为 2000 毫米：

- 工具参数验证通过。
- 直接调用现有 `_prepare_drawing_modification`，返回 `ok=true`，说明已有预演实现可处理它。
- 经正常 `_dispatch_tool_calls`，进入 `_execute_safe`，返回“安全工具尚未实现：modify_drawing”。
- 源文件字节保持不变。

相关合同：`TOOL_REGISTRY` 将 `modify_drawing` 配置为无需确认，`SAFE_TOOL_NAMES` 也包含它；实际修改和保存实现仍在 `_execute_confirmed` 中，安全分发没有对应分支。

这是**登记/分发与实际实现位置不一致**。不能因为错误消息写着“未实现”就另写一套修改引擎。应先明确现行独立文件编辑的确认与交付契约，再把已有实现接到正确的公共边界。候选项目编辑是另一个持久化域，不能直接互换两者。

范围：真实 Schema、预演与工具分发函数对照，没有真实模型调用，没有正式保存编辑后的图纸。不能据此声称所有 REST 图纸编辑接口均不可用。

证据：`phase2-probes.json` 的 `standalone_modify_dispatch`。

## 7. 本轮纠正或补充的能力认识

- 项目候选写入已经有幂等键、同锁回执、持久化失败回滚和旧草稿不阻止新验收结果的处理；这些能力应复用。
- 执行恢复已经能依据任务账本跳过已完成喷墨段，保留疑似部分执行段并要求检查；它与语言模型计划修复不是重复能力。
- 会话需求摘要是扁平索引，项目来源账本是原文与对象事实证据，二者不能不加区分地合成同一份权威需求。
- 数据库中的“案例晋升模板”目前主要是案例和参数/验收元数据管理；本轮检索到的调用方是管理接口，不能将它直接计为另一套已接入的 CAD 几何生成器。
- 工具列表、模式白名单、安全工具集合、分发函数和确认执行函数之间已经存在声明漂移。现有 `validate_tool_configuration` 检查部分声明一致性，但不能证明每个工具确有对应执行分支。整理时应扩展现有核对能力，避免新增另一份工具注册表。
- 多供应商调用有部分公共 `_dispatch_tool_calls`，但 OpenAI Responses、DeepSeek 的 `_streamed_tool_result` 等仍有并行的业务分发逻辑。它们对隐藏工具、错误返回和后续调用的处理并不完全相同，应先建立差异对照再提取公共分发。

## 8. 后续阅读队列

1. `agent_service.py` 尚未读完的模型规划回调、编辑目标绑定/落库、流式实现、配置、验证与设备分支。
2. `cad_construction_interpreter.py`、`cad_construction.py` 剩余构造归一化和执行分支。
3. `incremental_cad.py`、`agent_skills.py` 剩余解析与几何实现。
4. `logical_topology.py`、`spatial_partition.py`、`ros_adapter.py` 剩余路径，以及尚未全文审读的其他生产文件。
5. 未全文人工审读的测试、工具、脚本和评测入口。

本轮只增加审读台账、报告和隔离探针，不修复上述问题，不更新真实模型成绩。上一轮 2715 通过、63 失败、4 跳过是历史离线基线，本轮没有重跑全套测试，也没有据此宣称新的通过率。
