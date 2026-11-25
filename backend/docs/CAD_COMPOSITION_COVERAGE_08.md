# 组合图形的数量、位置与关系验收衔接

## 本轮修复

1. cad_composition_coverage.py复用现有explicit_composition和validate_explicit_composition，不生成坐标，不读取模型标签或断言作为通过依据。只连接现有能力：矩形四角放圆、矩形阵列、受支持的纯圆数量/两圆相交与圆心距离。
2. 要求原文所有支持字段与关系都被消费、数值与当前测量契约一致，才汇总完整覆盖证据。圈定范围外的附加对象、位置、线宽、面积、相同/等大关系、三圆关系、冲突或陈旧数量、缺少必要阵列间距等保持partial。没有把所有composition_validation.passed直接换为完整覆盖。
3. 保存可复核证据：实际数量/类型、矩形长宽、圆半径、矩形顶点和圆心一一对应、阵列行列及实际单元框/间距、已验证的两圆相交关系。
4. 修复construction_acceptance_summary中的重复汇总：preflight_structure的未知状态原本已经由post_structure_passed解析，却又在后一项any(review_required)中被无条件重新计入。现在保留前置不确定性的统一判定，不重复计入已被实际结构检查解析的同一个标记。完整来源缺失或实际结构没有通过时仍review_required；独立验收失败仍抛错。

修改cad_construction_interpreter.py；新增cad_composition_coverage.py及test_composition_coverage_handoff.py。未增加图形专用生成器、控制点、生产模板或模型输入字段，未改变原70条数据。

## 测试

Conda test / Python3.11.18、独立USERPROFILE，无真实模型调用。

```powershell
python -m pytest tests/test_composition_coverage_handoff.py tests/test_component_dimension_scope_handoff.py tests/test_control_point_source_handoff.py tests/test_single_primitive_source_handoff.py tests/test_ellipse_axis_handoff.py tests/test_cad_requirement_contract.py tests/test_cad_source_acceptance.py tests/test_cad_structure_contract.py tests/test_cad_construction_interpreter.py tests/test_cad_construction_commit.py tests/test_cad_template_plan.py tests/test_candidate_visibility_gate.py -q
```

273 passed，16.04秒。另独立覆盖acceptance_boundaries/construction_quality等相关范围时81 passed。

负例保留：少件/多件、错类型、错半径、错矩形尺寸、圆心偏离角点、两个圆重叠在同一个角点、阵列缺位/错间距、要求相交但实际分离、不支持的三圆关系、数量修订与旧契约不一致、没有测量的等大关系、未消费附加要求。

前置未知状态只有在执行后的相同组成验收通过且来源完整时才能解除；“只有后置成功但来源partial”和“来源complete但结构仍未验证”两个阴性对照均保留review_required。

## C7离线交付

脚本C:\Users\29924\Codes\cad-eval-20261117\composition_delivery_replay.py。

结果与项目：同目录composition-delivery-replay/summary.json、projects.json。

使用原历史保存计划和原始补参，没有更换几何计划或生成新模型响应。C7现在保存5个图元的验收通过候选，construction_record包含数量、矩形4×2m、四圆半径0.5m及四角一一对应证据。此前ready但review_required的原因是来源证据未汇总、前置未知标记被重复计入，而非缺少生成器。

模型调用0次。该结果是历史计划离线交付改善，不是实时模型首次成功率；未重算原70条通过率，也未验证完整App画布。

## 边界与下一步

未声明任意组合文本都已完整支持，C16的错误门尺寸等真实失败仍不可放行。下一步宜进行分链路整体验证，统计首次交付、补参后交付、合理澄清、待复核与前置阻塞，避免继续仅按单个案例的局部结果外推全量能力。

改前解释器备份在C:\Users\29924\Codes\cad-eval-20261117\composition-before；不推送、不合并。
