# 多对象尺寸作用域与摘要衔接

## 根因

- “矩形宽4米高2米”曾整体成为对象名，尺寸本身无法稳定绑定矩形；确认摘要追加的同值宽高又被当作整图包围盒要求。四角圆伸出矩形后，整图自然大于4×2，不代表矩形尺寸错误。
- 部件条款内的坐标逗号和尺寸逗号重置作用域。C16的“墙体左下角…，宽4米高2米”及“门左下角…，宽1米高1.5米”可能被归为整体尺寸。
- 补参索引回写遍历了全部有效尺寸，但未检查fact.subject；门的尺寸会覆盖项目全局width_m/height_m。解释器又将这些摘要数值追加到原始要求后，重复制造错误整体尺寸。
- explicit_dimensions直接取文本中最后的宽高，进一步把最后一个部件当作整体。

## 改动

1. requirement_contract从创建对象身份中分离已有标量尺寸，识别图元名称前后的内联尺寸；内联矩形宽高为explicit_subject，不自动解释为整个组合的包围盒。
2. 在明确部件名称+位置/坐标/冒号条款内保留部件作用域，直到分号、句号或换行等强边界；不跨强边界猜测下一个对象。
3. 数字索引只回写唯一根对象的尺寸；部件或未绑定数字不覆盖根对象字段。原文已有相同字段时不再追加摘要值（即使摘要值不同），但仍保留旧项目缺来源字段的已有兼容路径。
4. explicit_dimensions优先读取唯一根对象的有效尺寸；多对象只有原文明示共同尺寸且全部对象一致时返回共享值，不把最后一个部件尺寸当作共享尺寸。
5. 对明确矩形/圆/圆弧的来源目标，当前模型标签不一致时允许按实际唯一图元类型绑定；矩形还需实际矩形测量成立。多个候选不按尺寸挑一个，不猜测身份，继续unresolved。

原始来源与字符范围保持不变，没有增加生成器、固定生产坐标或降低尺寸门槛。完整覆盖仍需其他要求的证据，本轮没有把多对象部分检查改成complete。

## 验证

Conda test / Python3.11.18；新增test_component_dimension_scope_handoff.py和来源标记的历史计划夹具recorded_component_scope.json。

```powershell
python -m pytest tests/test_component_dimension_scope_handoff.py tests/test_single_primitive_source_handoff.py tests/test_control_point_source_handoff.py tests/test_ellipse_axis_handoff.py tests/test_cad_requirement_contract.py tests/test_cad_source_acceptance.py tests/test_cad_structure_contract.py tests/test_cad_construction_interpreter.py tests/test_cad_construction_commit.py tests/test_cad_template_plan.py -q
```

243 passed，18.92秒。包含部件原文字符证据、全局索引保护、过期摘要、逗号/分号边界、唯一目标/歧义、共享尺寸、多对象布局及旋转矩形原回归。

历史计划离线重放：C:\Users\29924\Codes\cad-eval-20261117\component_scope_replay.py；结果component-scope-replay.json。分别输入纯原文及故意带width=1/height=1.5的过期摘要：

- C7两种输入均能试算，矩形尺寸只测矩形引用，不因外侧圆扩大包围盒误报整体尺寸错误。但仍review_required，其他来源覆盖未闭合；不算交付成功。
- C16两种输入均在独立部件检查失败：原历史计划的门宽2米/高1.2米，不符合后续门宽1米/高1.5米。错误是structure_requirement_failed，不再是把整图要求成1×1.5。墙体无法唯一映射的情况仍保持待复核。
- C16有效根尺寸仍为4×3米；墙体4×2、门1×1.5各自保留，不相互覆盖。

没有调用真实模型或修改原70条结果，不据本轮离线诊断宣称全量通过率上升。

## 未完成

复合实体内部部件的可靠几何绑定、部件位置/数量/关系的完整覆盖仍需继续接通。当前修复首先消除错误约束、错误拒绝及摘要污染；不是让所有组合请求直接通过。

修改文件：cad_requirement_contract.py、cad_construction_interpreter.py、cad_source_acceptance.py、cad_structure_contract.py、agent_service.py。改前文件在C:\Users\29924\Codes\cad-eval-20261117\scope-before；不推送、不合并。
