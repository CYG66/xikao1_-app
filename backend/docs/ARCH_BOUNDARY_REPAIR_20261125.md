# 拱门错误边界诊断与有限修复衔接

已确定上一轮V6-r2首回合草稿是实际几何错误，而非正确几何被测量器误判。原独立oracle报告边界最大距离270.0977毫米，缺边与额外边均存在。

原计划将半圆中心横坐标设为0米；根据底边左端-1.36米和宽3.26米，应为0.27米。底边从-1.36到1.63，实际长2.99米；左墙从(-1.63,2.26)斜接到(-1.36,-0.72)。外包框仍为3.26×4.61米，因此模型自带宽高断言通过，不能证明墙弧结构正确。

前次报告将表示/测量适配列为待排查原因，本次已通过原计划、实际边、独立oracle排除此猜测。旧结果及恢复记录未改写。

## 修复

`cad_curve_fit_acceptance.verify_semicircular_arch`沿用原阈值与判定，只在已证实某边不属于两侧竖直墙、水平底边或上半圆时，补充`non_semicircular_boundary_edge`、实际边端点及推定圆心/半径。

`cad_semantic_source_coverage.verify_semicircular_outline_source`仅在原文已完整解析且得到该明确反例时，抛出带原始尺寸、几何ID和实测证据的`StructureContractError`。既有解释器将其包装为`construction_error.code=structure_requirement_failed`，进入既有有限修复；外层通用错误码仍为`trial_execution_failed`。

未知/其他未证明边界仍走原partial处理；没有一律把partial当错误，没有替换几何、增加生成器或放宽精度。原宽高、起点及其他来源验收保持不变。

## 验证

新增`tests/test_arch_boundary_repair_handoff.py`两项及`tests/fixtures/arch_failed_boundary.json`，直接保留原草稿和后续正确版本的计划及来源。原错误现在返回invalid和可供有限修复消费的结构证据，原计划不变；正确版本通过，附加未知旋转仍partial。

定向首次运行29通过、1失败：测试错误地期望外层错误码就是结构码，核对既有包装契约后改为检查`construction_error`，未改生产错误协议。完整CAD结果见下方补录。

完整CAD首跑为1196通过、3失败，耗时428.91秒，目录`.local-dev/test-hoh5ldvn`。三项为`test_outline_delivery_source`的bottom/curve/sparse错误几何反例，旧测试只接受返回未通过；新行为为抛出结构错误，拒绝语义未变。随后仅更新这三项为明确检查异常、原因码及实测失败，未改变生产代码、评测规则或原错误几何。

最终复测上述失败所属文件及全部相关拱门文件：**71 passed in 121.52s**，目录`.local-dev/arch-boundary-final-proof-cvzvxirz`。其余1196项已在同一生产源码下通过。没有再跑一次完整全量，不将组合验证写成单次1199全通过。

真实DeepSeek回归目录`.local-dev/selected-transfer-live-98lqdbou/run`：原V6两次重复，**2/2正式交付且首聊天回合通过**，每条1次模型调用，没有触发恢复。本批不证明该错误在真实模型中重现后已自动恢复；该入口主要由原始错误计划离线回放证明，文件`recorded-rejection-evidence.json`明确标记offline。

源清单摘要`4a0016364a7b6d4cf926fd473f6529f7d160d80febc22782507fdc50d7ac4c77`，150个app文件，源/冻结/执行副本哈希一致。固定原文、预览/确认语、两回合12请求上限及独立0.45毫米oracle保持不变。

2次请求/响应ID唯一，预留/结算2/2，无pending/stopped；输入38,084、输出1,206 token，估算$0.0128724，非供应商账单；产物密钥明文0处。原始API、step、项目、manifest及`holdout-integrity-audit.json`保留。未修改旧项目或上传GitHub。

原整组曝光回归12/12、首回合11/12，以及原第三批新留出4/12，均保持各自原口径。本轮只有V6曝光回归，没有新的泛化或70条成绩。接下来应以未参与修复的新数据检查，并继续单列首回合与有限恢复，避免把重试后的成功解释为稳定的一次规划能力。
