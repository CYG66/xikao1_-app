# T1 真实生产 HTTP 验证

本轮只执行冻结计划 T1，未执行 T2～T6，未修改 CAD 生产代码，未调用机器人链路。

## 结果

- 自然语言第一轮：`把这个圆复制到右侧3米处。`
- 自然语言第二轮：`把刚才复制的圆半径改为0.5米。`
- T1：`passed`
- 端到端分类：`end_to_end_pass / model_not_invoked`
- DeepSeek 实际调用：0 次
- 本轮新增 Token：0
- 本轮新增费用：$0
- 累计账本：2 次兼容探测、320 输入 Token、38 输出 Token、峰值费率估算 $0.0001416

## 实际几何与版本

第一轮生成新版本，父版本正确，几何为：

- 原圆：geometry_id=1，中心 `(0,0)` mm，半径 `1000` mm
- 副本：geometry_id=2，中心 `(3000,0)` mm，半径 `1000` mm
- 来源映射：`source_geometry_id=1 → geometry_id=2`

第二轮生成其子版本：

- 原圆 geometry_id=1 保持中心和半径不变
- 副本 geometry_id=2 半径变为 `500` mm
- 父版本为第一轮复制版本
- 来源映射在新版本中保留

## 模型参与判断

两轮响应的 `provider_calls` 均为 0，响应 usage 也为 0；运行账本 `new_model_calls=0`。因此本次成功证明的是现有确定性自然语言编辑路由、身份映射、版本保存和目标解析闭环，不能计为 DeepSeek 理解成功。

## 原始证据

完整请求、响应、项目快照和逐轮结果：

`D:\xikao\.local-ai-test\c2-flash-t1-live-20261106`

其中 `summary.json` 的 T1 状态为 `passed`，`result.json` 记录两轮 `provider_calls=0` 及前后几何。

## 决策

T1 的确定性端到端路径已通过，未发现新的生产缺陷。按测试计划可以继续 T2～T5；应继续把模型未参与和模型参与结果分开统计。T6 仍保持原有 `blocked` 状态。
