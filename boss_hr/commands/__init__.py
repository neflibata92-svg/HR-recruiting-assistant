"""boss_hr.commands — 命令处理层。

只做 CLI 参数 → application 调用的薄层；不操作文件路径、subprocess、浏览器。
每个命令一个文件：add_arguments(parser) + run(args) -> CommandResult。
"""
