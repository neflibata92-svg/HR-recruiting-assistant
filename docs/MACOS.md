# macOS 安装与执行

本页适用于 macOS 及已安装的 Google Chrome。Windows 仍使用 Edge；完整招聘流程此前仅在 Windows 验证。Mac 端先验证安装，再按人工确认节点运行。安装和 `doctor --skip-browser` 不会访问 BOSS。

## 1. 安装

需要 Python 3.10+、Google Chrome 和 Git。建议在终端运行：

```bash
git clone https://github.com/neflibata92-svg/HR-recruiting-assistant.git
cd HR-recruiting-assistant
git switch feat/macos-install-run  # 分支尚未合并 main 时执行
sh install-macos.sh
source .venv/bin/activate
boss-hr --help
boss-hr doctor --skip-browser
```

脚本在仓库内创建 `.venv` 并执行 editable install，还会验证从仓库外能调用 `boss-hr`。移动源码目录后重新运行脚本。`doctor --skip-browser` 只检查 Python 和依赖，不启动浏览器。
如果本机 pip 镜像缺少依赖，可临时指定官方索引运行 `PIP_INDEX_URL=https://pypi.org/simple sh install-macos.sh`。

## 2. 专用 Chrome 与登录

`boss-hr start` 在 9222 端口不可用时自动启动系统 Chrome。专用浏览器资料位于 `~/Library/Application Support/HR-recruiting-assistant/chrome-profile`，不会使用日常 Chrome profile。若需单独排查浏览器连接，运行：

```bash
boss-hr doctor --launch-browser
```

如果自动启动失败，可在终端手动开启同一专用 Chrome，再运行 `boss-hr doctor`：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/Library/Application Support/HR-recruiting-assistant/chrome-profile" \
  about:blank
```

请仅在该专用窗口中自行完成 BOSS 招聘者登录。`start` 默认不阻塞等待扫码：未登录时返回 `waiting_user_login`，登录后重试原 `start` 命令。不要把验证码、Cookie 或简历写入仓库或聊天记录。

## 3. 执行流程

建议把包含简历的输出放在仓库外，并自行控制该目录的访问权限：

```bash
mkdir -p "$HOME/Library/Application Support/HR-recruiting-assistant/output"
chmod 700 "$HOME/Library/Application Support/HR-recruiting-assistant/output"
export BOSS_HR_OUTPUT_DIR="$HOME/Library/Application Support/HR-recruiting-assistant/output"
```

以下命令中的岗位名称、加密岗位 ID、run ID 和数量需替换为实际值。`start` 会在岗位解析后返回 `run_id`，后续命令应使用相同的 `run_id` 与 `encryptJobId`：

```bash
boss-hr start "<岗位名称或 encryptJobId>"
# 如返回 waiting_user_login：在专用 Chrome 中登录后重试同一条命令
# 如返回 waiting_user_confirmation：在 BOSS 页面调整筛选条件并人工确认

boss-hr confirm --job-name "<岗位名>" --encrypt-job-id "<id>" --run-id "<rid>"
boss-hr fetch --job-name "<岗位名>" --encrypt-job-id "<id>" --run-id "<rid>" --count 1
boss-hr score --job-name "<岗位名>" --encrypt-job-id "<id>" --run-id "<rid>"
# 按 resume-screener/SKILL.md 为返回的候选人填写评分输出，再重复 score
boss-hr report --job-name "<岗位名>" --encrypt-job-id "<id>" --run-id "<rid>"
```

`greet` 会在招聘平台产生真实操作，仅在明确批准具体对象和内容后单独执行。Mac 端的真实简历获取与发送尚未完成验证，先用虚构数据完成本地评分、报告和命令状态测试。
