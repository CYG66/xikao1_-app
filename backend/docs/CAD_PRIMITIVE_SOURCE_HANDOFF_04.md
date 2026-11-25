# 普通图元来源验收与候选交付衔接

## 本轮范围

修改 cad_source_acceptance.py、cad_construction_interpreter.py；新增 test_single_primitive_source_handoff.py。没有新增生成器、固定形状控制点、模型协议或几何原语；本轮真实模型调用0次。曲线及其他未覆盖表达仍保持待复核，不能据本轮结果声称全部普通图形已解决。

## 修复

1. 对单个圆/圆弧的明确来源增加独立只读测量。解析要求的类型、数量、半径/直径、中心（若指定）、圆弧起止角及实际扫角，直接检查执行后的原生几何，不读取模型断言决定通过。解析后必须没有剩余要求文本；额外对象、方向、相对位置、上限、不支持语句、同轮矛盾参数等不能被忽略为完整覆盖。测量沿用已有位置/尺寸0.5mm和角度0.001度门槛。
2. 原文坐标使用显式坐标单位；没有单独坐标单位时仅在当前条款长度单位唯一时解释坐标。混合单位或未解析信息不推测完整覆盖。标量、中心及单图元要求分别测量，原来源文本保持不变。
3. 完整测量通过才接入现有来源验收与 coverage 汇总；partial 不直接改为 complete。其他独立检查的 unknown/review_required 仍有效。未通过测量抛出已有 StructureContractError，保留源证据和实际/期望值。
4. 最终标量验收读取执行器实际使用的 geometry_refs，同时兼容旧 geometry_ids；此前仅接受旧字段导致正确对象被判未绑定。圆弧的实际radius/diameter现在由同一半径测量入口支持，避免已测量半径仍被另一个检查记为不支持。

## 验证

Conda test / Python 3.11.18、独立USERPROFILE；命令在backend执行：

```powershell
python -m pytest tests/test_single_primitive_source_handoff.py tests/test_cad_source_acceptance.py tests/test_cad_requirement_contract.py tests/test_cad_construction_interpreter.py tests/test_cad_construction_commit.py tests/test_template_acceptance_handoff.py tests/test_cad_pipeline_handoff.py -q
```

158 passed，10.90秒。之后增强同一测试中的候选保存断言，并单独运行新增文件：21 passed，1.09秒，确认保存后仍为原生circle，acceptance为passed，construction_record保留独立来源测量证据。

覆盖正例：半径/直径、厘米换算、后续中心单位补充、圆弧角度；负例：半径错误、位置错误、重复图元、折线冒充圆、扫角多转一圈、同轮冲突、未消费需求、额外对象、未知方向/面积等。来源geometry_refs绑定还验证了错误尺寸继续被拒绝。

## 历史计划离线重放

使用原70条评测中A3/A5的第一份保存计划，不请求新模型，不为通过重写计划。离线解释结果均为ready + acceptance passed；此前这些计划因覆盖未接通或圆弧半径被记为不支持而成为review_required。

原始计划、当前解释结果及来源测量在：

`C:\Users\29924\Codes\cad-eval-20261117\primitive-source-replay.json`

复现脚本：同目录primitive_source_replay.py。原70条基线未覆盖、未重算；这是记录计划的离线执行与验收改善，不是当前真实模型生成成功率。

## 后续边界

单轮廓曲线控制点/单位、椭圆全轴与半轴表达、澄清后的计划重用仍需继续核对。本轮不宣称Bezier/Spline已经具备完整来源覆盖，不通过强制清空unknown或提升模型置信度放行。

改前文件在 C:\Users\29924\Codes\cad-eval-20261117\primitive-before；不推送、不合并。
