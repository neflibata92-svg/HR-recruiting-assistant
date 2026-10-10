"""boss_hr.application — 业务编排层。

负责状态校验 / 执行顺序 / 返回结构化业务结果；不解析旧脚本 stdout
（那是 adapter 的活），不直接调用 subprocess（统一走 adapters/）。

每个 service 函数返回 boss_hr.contracts.CommandResult 或其子类。
"""
