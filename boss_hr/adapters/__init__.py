"""boss_hr.adapters — 适配器层。

把对外部接口（BOSS HTTP / 浏览器 / 子脚本 subprocess）的访问封装到
adapter 内，业务层（application/）只通过 adapter 调用。
"""
