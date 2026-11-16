# DeepSeek Flash T1～T5 受控真实生产验证

本轮按冻结用例运行真实 HTTP 生产路由；没有修改 CAD 生产代码，没有执行 T6。

## 汇总

| 用例 | 结果 | DeepSeek 调用 | 说明 |
|---|---|---:|---|
| T1 | `passed` | 0 | 确定性路由完成复制、来源映射、连续修改 |
| T2 | `failed / clarified` | 0 | “刚才新增的那个圆”当前确定性选择器不支持，按规则澄清 |
| T3 | `failed / clarified` | 0 | “原来的圆”目标引用当前未被证明，按规则澄清 |
| T4 | `passed` | 0 | 重复半径设置返回 `no_change`，没有新增版本 |
| T5 | `passed` | 0 | 删除副本后再次引用被拒绝，未修改原圆 |

T1～T5 共产生 0 次新的模型请求。累计账本仍是此前 2 次兼容探测、320 输入 Token、38 输出 Token，峰值费率估算 `$0.0001416`。没有重置预算。

## 关键证据

T1：原圆 `geometry_id=1` 中心 `(0,0)`、半径 `1000mm`；复制圆 `geometry_id=2` 中心 `(3000,0)`、半径 `1000mm`；下一版本中副本半径 `500mm`，原圆几何完全不变，来源映射 `1 → 2` 和父子版本均保持。

T4：第二次相同修改版本数保持不变，结果为 `no_change`。

T5：删除副本后，后续引用返回 `target_resolution_failed`，版本数不增加。

T2、T3 的澄清不是模型失败：这几轮没有调用 DeepSeek，属于当前确定性目标解析能力边界，且与冻结计划中已知边界一致。

## 原始输出

- T1：`D:\xikao\.local-ai-test\c2-flash-t1-live-20261106`
- T2～T5：`D:\xikao\.local-ai-test\c2-flash-t2-t5-live-20261106`
- T1 详情：[DeepSeekFlash_T1真实生产验证20261106.md](D:/xikao/xikao1_-app/backend/evaluations/DeepSeekFlash_T1真实生产验证20261106.md)

## 结论

当前单圆连续编辑闭环已在确定性自然语言路由下验证：T1、T4、T5 通过；T2、T3 按规则澄清。T1～T5 全部没有真实 DeepSeek 参与，因此这些结果不能作为 DeepSeek CAD 规划能力通过率。

T6 仍保持 `blocked`：其创建结果是 `review_required` 草稿，不能通过人工确认提升为正式编辑基线。
