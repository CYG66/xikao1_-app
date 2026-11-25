# 当前代码查重清单

范围为当前 `C:\Users\29924\Codes\codex-cad-agent\backend\app`，不是与旧目录作差异对比。本轮只新增审计脚本和报告；生产源码哈希前后一致，没有删除、合并或重写任何生产功能，模型调用0次。

## 方法和结果

- 扫描140个Python文件，按AST比较去除文档字符串后的函数体，并扫描连续4条语句的重复块。
- 发现**8组跨文件相同函数体**候选；另有1组重复语句块，它属于已发现的旋转函数，不能再作为独立一组累加。
- 找到**27个文件中的41处单位换算表**。这不是41份完整功能，也不能由此计算项目重复率。
- 对10个历史计划输入进行隔离调用追踪，按函数、完整实参摘要和调用来源识别同一请求内的重复调用。这是离线记录计划测试，不是新的自然语言模型测试，不产生通过率。
- 以下“确认重复”“职责重叠”“不能直接合并”分别列出。AST相同不代表所有生命周期和调用契约都相同。

完整机器证据：`.local-dev/current-duplication-audit-3v8q7ivu/static-evidence.json`、`runtime-validation-traces.json`、`summary.json`。

## 优先处理的业务重复

### D01：S形分割与小圆关系由两套测量器重复检查——确认重叠，高优先级

- `app/cad_path_relation_acceptance.py:48`，`verify_path_relations`。
- `app/cad_symmetric_divider_acceptance.py:8`，`verify_symmetric_divider_source`。
- 主链路分别调用于 `app/cad_construction_interpreter.py:882`、`:891`。

两者都检查分割路径连接、两瓣反向弯曲、与外圆的关系、两个小圆的尺寸及位置关系。它们在同一次构造中都会运行，确有测量职责重叠。

区别不能忽略：旧路径检查通过采样后的通用开放路径判定连接、自交和弯曲，可适应多种路径表达；新模块只接受3个圆与2个圆弧，并额外要求半圆尺度、小圆位于两瓣圆心等更严格条件。新模块还负责完整来源消费。因此不能直接删除其中一个并宣称等价；应把通用测量与特殊来源约束分开，复用已有路径测量，避免两个入口分别定义“正确”。

### D02：完整几何验收为绑定来源事实先算一次，主流程再算一次——运行时已确认，高优先级

| 验收函数 | 首次入口 | 再次入口 | 相同输入调用次数 |
| --- | --- | --- | --- |
| verify_symmetric_divider_source | cad_source_acceptance.py:145 | cad_construction_interpreter.py:891 | C31：2 |
| verify_radial_attachment_source | cad_source_acceptance.py:154 | cad_construction_interpreter.py:896 | C24：2 |
| verify_repetition_requirements | cad_source_acceptance.py:204 | cad_construction_interpreter.py:932 | C22有效历史计划：2 |

这里不只是函数类似，而是追踪证明同一函数在完整实参摘要相同的情况下重复执行。来源标量绑定阶段为了找外圆/外环/分支半径，会触发整个结构验收；随后主验收链又从头执行。

同样的静态调用模式还见于投影检查：`cad_source_acceptance.py:196` 与 `cad_construction_interpreter.py:923`。本轮没有追踪到足以确认该项相同输入重复的有效C27计划，因此将其列为**静态候选**，不冒充已证实的运行时结果。

整合方向：每次构造先形成可复用的结构测量证据，再让来源绑定消费同一证据。不要让来源绑定反向触发完整验收，也不要设置跨请求全局缓存，避免修改几何后复用旧证据。

### D03：单矩形身份、尺寸在多个入口重复测量——确认重叠，中高优先级

- `cad_structure_contract.py:498` 的 `_frame` 已检查闭合直边矩形、有效多边形、四角及轴对齐边界。
- `cad_rectangle_acceptance.py:9` 的 `verify_single_rectangle` 又先自行检查Polygon有效性、直边和闭合，然后调用 `_frame`，再检查宽高。
- `cad_source_acceptance.py:119` 的 `verify_final_source_contract` 同时按来源事实检查宽高。
- `cad_source_acceptance.py:339` 的 `verify_scoped_primitives` 对显式部件也执行矩形与尺寸匹配。

运行时A2中，`_frame` 对同一几何调用3次。部分原因是不同来源入口重查，部分是矩形模块在共同辅助函数外再次做相同形状检查。

不同点：单矩形模块承担完整原文消费，并增加有限值保护；来源事实模块负责事实ID、主体绑定和逐轮修改。不能将完整来源证明或有限值检查一起删除。应保留这些职责，把矩形身份和测量值收敛为一份证据。

### D04：图元布局与分主体验收重复检查半径、中心、矩形尺寸——确认重叠，中高优先级

- `cad_primitive_layout_acceptance.py:13` 的 `verify_primitive_layout`。
- `cad_source_acceptance.py:119`、`:339` 的标量/主体测量。
- 布局模块已经复用 `cad_relation_acceptance.verify_named_relations`，这一部分是正确的复用，不属于第二份关系算法。

布局模块重新解析并测量圆半径、中心、矩形起点、宽高，以及圆环包含和同心关系。完整来源语法与无标签图元绑定有增量，基础测量则与已有主体验收重叠。

运行时A11中，同一矩形的 `_frame` 调用5次，另一图元的 `_frame` 调用3次。布局模块自己的 `[(g,_frame(g)) for g in gs if _frame(g) is not None]` 还会对被识别的矩形在同一列表表达式内调用两次。

### D05：圆组验收与现有圆/关系测量交叉——部分重复，中优先级

`cad_circle_group_acceptance.py:13` 独立计算半径、中心距、水平对齐和相交。现有来源标量、圆图元检查以及关系层已有部分基础测量。

新增的匿名双圆绑定、精确数量与严格相交条件是增量，不能当作全部冗余。应先提取公共测量值与绑定结果，再由具体来源规则提出约束；不要维护多份圆心、半径和单位解释。

## 通用辅助代码重复

### D06：单位换算表与文本消费框架——确认基础数据重复，中优先级

41处表分布在27个文件，包含来源契约、坐标、矩形、圆组、布局、分支、波形、投影和编辑等模块。具体位置和表内容见 `static-evidence.json/unit_tables`。

必须区分输出单位：例如 `cad_axis_requirements.py:8`、`cad_composition_coverage.py:21` 以米为目标；`cad_rectangle_acceptance.py:16`、`cad_repetition_acceptance.py:15` 等以毫米为目标。不能把不同倍率直接替换为同一张表。

多个模块还各自实现“消费匹配文本→记录证据→检查剩余文本”的框架。其重复模式明确，但同轮冲突、后续覆盖、未知条款及单位缺失策略并不一致，不能直接合并整套解析器。优先统一单位转换、证据区间和公共原语，保留来源策略差异。

### D07：指纹函数重复——部分可合并，部分必须保留语义

确认函数体相同：

- `cad_assertions.py:16` `_fingerprint`。
- `cad_edit_preview.py:14` `_fingerprint`。

`cad_edit_gate.py:13`、`:20` 的两个函数，以及 `cad_local_repair.py:8` 也使用同类JSON排序序列化与SHA256，可评估共用基础编码工具。

以下不能因同叫指纹而直接合并：

- `cad_edit_gate._semantic_geometry_fingerprint` 把等价整数和浮点数归一。
- `cad_candidate_state.geometry_evidence_hash` 使用不同的Unicode/NaN策略，参与版本证据绑定。
- `cad_sketch_graph._geometry_fingerprint` 删除几何ID，用于候选去重。
- `geometry_diff._fingerprint` 先将浮点数舍入到3位，返回规范JSON字符串，而非相同SHA256协议。

不兼容地改变序列化会使已有版本指纹失效。应区分用途后共享基础实现，不能统一替换成一个“万能哈希”。

### D08：提取坐标点、中心、边界和旋转代码重写——部分重复，需先划分精度合同

`cad_target_resolver.py:426` 与 `incremental_cad.py:1233` 的 `_points` 遍历相同的点字段，写法近似；两者 `_bounds` 也都采用包围圆等方式估计范围。错误输入的容错行为不同，不能直接用异常策略较弱的一份替代另一份。

`construction_geometry_bounds` 是已有精确边界入口；`agent_skills.calculate_geometry_bounds` 则从预览采样点推导、换算并舍入。选择器的近似范围、执行验收的精确范围、预览采样范围不是相同合同。应共享安全的基础坐标工具，不把近似范围冒称精确范围。

## 8组相同函数体的完整清单

下列为静态AST证据，函数体相同，但接口和运行边界仍需人工判断。

| 组 | 位置 | 判断 |
| --- | --- | --- |
| 1 | agent_skills.py:330 `as_id`；cad_edit_gate.py:147 `_positive_id`；drawing_commands.py:35 `_entity_id`；geometry_catalog.py:44 `_geometry_id` | 相同正整数ID解析，可作为公共小工具整合候选 |
| 2 | agent_plan_sqlite_store.py:24 `_connect`；database.py:42 `_connect` | 相同SQLite连接初始化，业务数据库与计划存储职责不同；只评估共享连接基础设置 |
| 3 | agent_plan_sqlite_store.py:33 `_connection`；database.py:51 `_session` | 相同事务上下文与关闭逻辑，低优先级基础设施重复 |
| 4 | cad_assertions.py:16 `_fingerprint`；cad_edit_preview.py:14 `_fingerprint` | 确认一致，可优先提取共同编码工具并保持历史输出 |
| 5 | cad_constraint_solver.py:411 `_points`；native_constraint_worker.py:17 `_points` | 确认代码重复，但跨本机原生求解子进程，不能破坏隔离部署边界 |
| 6 | cad_constraint_solver.py:434 `_size`；native_constraint_worker.py:53 `_size` | 同上 |
| 7 | cad_constraint_solver.py:465 `_rotate`；native_constraint_worker.py:69 `_rotate` | 同上；唯一重复语句块也位于这里，不额外累加 |
| 8 | geometry_catalog.py:36 `_number`；ros_adapter.py:1414 `finite` | 相同有限数值转换，可评估共用轻量数值工具，不能给ROS侧引入整个CAD依赖链 |

原生worker用于隔离原生崩溃和ABI风险，父进程还要独立核验残差。存在相同辅助代码不等于应该合并进程或删除独立验证。

## 不应误判为重复的部分

- `verify_*_source_coverage` 消费来源文本、形成完整覆盖证明，与几何测量是不同职责。部分实现可共享框架，但不能直接删除覆盖层。
- 计划断言、来源独立验收、版本/父版本校验是不同的可信边界。它们都检查几何，不意味着后两者可以省略。
- 模板、规则和模型策略有不同输入与适用范围；仅因能输出同类图元，不能判定整条链路可以删除。
- 共享点记法与SketchGraph、六类约束求解不是完全相同能力。是否值得保留是必要性问题，本次未认定为代码克隆。
- 140个文件的AST扫描不能证明不存在其他语义重复；本报告是已确认部分与静态候选，不是全项目“重复率”。

## 建议整合次序

1. 先消除D02同一次请求中相同完整验收的重复执行，保留完整来源绑定与全部失败检查。
2. 再整合D01/D03/D04：复用一份结构/图元测量证据，分别应用来源规则，防止两套检查互相矛盾。
3. 再处理单位和确实相同的指纹/数值小工具；保留不同单位、舍入、NaN和版本协议。
4. 原生worker、数据库连接等跨部署或跨生命周期重复放后处理。

本轮只是查重和定位，尚未执行上述整合，当前业务行为保持不变。

## 复查入口

- 审计脚本：`evaluations/audit_current_duplication.py`。
- 静态证据：`.local-dev/current-duplication-audit-3v8q7ivu/static-evidence.json`，含全部源文件哈希、克隆组、单位表和验证调用位置。
- 实参摘要、次数及调用栈：同目录 `runtime-validation-traces.json`。
- 退出码和生产源码完整性：同目录 `summary.json`，`app_source_unchanged=true`。
