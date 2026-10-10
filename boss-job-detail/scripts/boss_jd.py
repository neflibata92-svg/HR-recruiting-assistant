"""Get BOSS job detail (JD) via CDP browser.

Usage:
  python boss_jd.py <encryptJobId|jobId|职位名> [--job-name <name>]

Output: <job-name>/process/job_detail.json

依赖（2026-07-31 替换）：
  - 不再依赖 boss_agent_cli（boss.exe）。
  - 岗位列表查询改用 shared/recruiter_job_catalog.py（在已登录的 CDP 浏览器里 fetch BOSS 后端 API）。
  - 登录态检查由 shared/cdp_preflight.py 提供。
  - 完整 JD 抓取仍走 patchright 直连 BOSS web/chat/job/edit iframe（真实 Edge TLS 指纹）。
"""
import json, sys, time, os, re, argparse
from pathlib import Path
from patchright.sync_api import sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
import fix_encoding  # noqa: E402  # 强制 Windows UTF-8 stdout
from output_manager import JobOutputManager
from recruiter_job_catalog import resolve_recruiter_job  # 2026-07-31 替代 boss.exe 调用

CDP_URL = "http://localhost:9222"


def _safe_name(name: str) -> str:
    """清洗岗位名为合法目录名"""
    return re.sub(r'[\\/:*?"<>|\s]+', '-', name).strip('-') or 'job'


def resolve_encrypt_id(query):
    """根据 query 定位岗位，返回 (encryptJobId, jobName)。

    2026-07-31 重构：直接调 shared/recruiter_job_catalog.resolve_recruiter_job，
    不再 subprocess 'boss hr jobs list'。查询规则保留原逻辑：
      - encryptJobId 精确 / jobId 精确 / jobName 精确优先
      - jobName 模糊（含 query 子串）兜底
    """
    job = resolve_recruiter_job(query)
    if not job:
        return None, None
    return job.get("encryptJobId"), job.get("jobName")


def fetch_jd(encrypt_job_id):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)

        pages = browser.contexts[0].pages if browser.contexts else []
        page = pages[0] if pages else browser.contexts[0].new_page()

        target = f"https://www.zhipin.com/web/chat/job/edit?encryptId={encrypt_job_id}&jobCreateSource=0&enterSource=6"
        # BOSS 该页是 iframe + 长轮询（IM 心跳），networkidle 常等不到 → 只等 DOM ready
        page.goto(target, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass  # 长轮询导致 networkidle 永不触发，属正常

        body_text = ""
        form_vals = []

        try:
            iframe = page.wait_for_selector("iframe", timeout=15000)
            frame = iframe.content_frame()
            frame.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception as e:
            print(f"  iframe wait: {e}")

        # Extract from iframe
        iframe_el = page.query_selector("iframe")
        if iframe_el:
            frame = iframe_el.content_frame()
            if frame:
                body_text = frame.evaluate("document.body.innerText")

                # Retry if loading
                if not body_text or "正在加载" in body_text:
                    time.sleep(3)
                    body_text = frame.evaluate("document.body.innerText")

                # Get all form values
                form_vals = frame.evaluate("""(() => {
                    const r = [];
                    document.querySelectorAll('input:not([type=hidden]), textarea, [contenteditable]').forEach(el => {
                        const v = el.value || el.innerText || '';
                        if (v && v.length > 3 && v !== '保存') r.push(v);
                    });
                    return r;
                })()""")

        if not body_text:
            body_text = page.evaluate("document.body.innerText")

        browser.close()
        return {"bodyText": body_text, "formValues": form_vals}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Get BOSS job detail (JD) via CDP')
    parser.add_argument('query', help='encryptJobId | jobId | 职位名')
    parser.add_argument('--job-name', default=None,
                        help='人类可读岗位名（写到 jobs.json metadata）')
    parser.add_argument('--encrypt-job-id', default=None,
                        help='BOSS encryptJobId（新设计：用于目录命名；推荐传；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）')
    parser.add_argument('--run-id', default=None,
                        help='本次 run ID（默认自动生成；同一 run 内的所有产物落同一 runs/<run_id>/）')
    parser.add_argument('--force', action='store_true',
                        help='强制覆盖已有 run（同 run 内补写 job_detail.json 用）')
    args = parser.parse_args()

    eid, name = resolve_encrypt_id(args.query)
    if not eid:
        print(f"Job not found: {args.query}")
        sys.exit(1)

    print(f"Found: {name} ({eid})")
    raw = fetch_jd(eid)

    # 新设计：encrypt_job_id 是关键定位依据。从 CLI/env/反查 三级取，取不到直接报错
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
    from output_manager import resolve_encrypt_job_id
    encrypt_job_id = resolve_encrypt_job_id(args.encrypt_job_id)
    # 如果 query 本身就是 encryptJobId，统一用它
    if not encrypt_job_id:
        encrypt_job_id = eid
    if not encrypt_job_id:
        raise ValueError("缺少 encrypt_job_id，无法确定工作区目录。\n  传 --encrypt-job-id，或设置 env BOSS_HR_ENCRYPT_JOB_ID")

    job_name = args.job_name or name  # 默认用人可读 jobName 作为 jobs.json name

    # 2026-07-30 重构：run_id 是数据边界。
    # 新任务（不传 --run-id）→ create_new_run() 创建新 run
    # 继续旧任务（传 --run-id）→ bind_existing_run() 校验后绑定
    from run_orchestrator import RunOrchestrator
    orch = RunOrchestrator(job_name, encrypt_job_id=encrypt_job_id)
    if args.run_id:
        run_id = orch.bind_existing_run(args.run_id)
    else:
        run_id = orch.create_new_run()

    output = JobOutputManager(job_name, encrypt_job_id=encrypt_job_id, run_id=run_id)
    output.ensure_run_dir()
    print(f"run_id: {run_id}（orchestrator 创建）")

    # 异常护栏：脚本崩溃时若没写出 job_detail.json，自动清空 run_dir
    import atexit
    _SAVED = False

    def _auto_prune():
        if not _SAVED and output.prune_if_empty():
            print(f'⚠️  本次 run 未产生 job_detail.json，已清理: {output.run_dir}')

    atexit.register(_auto_prune)

    save_data = {
        "jobName": name,
        "encryptJobId": eid,
        "bodyText": raw.get("bodyText", ""),
        "formValues": raw.get("formValues", []),
        "_meta": {
            "run_id": output.run_id,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
    out_path = Path(output.jd_path)
    out_path.write_text(json.dumps(save_data, ensure_ascii=False, indent=2), encoding="utf-8")
    _SAVED = True  # 成功落盘，保留 run
    orch.mark_done('jd', run_id=run_id)

    # 2026-07-30 重构：Step 1 完成后初始化 run.json（confirmed=false），
    # 打印等用户确认的提示，退出 0。
    # 智能体看到这里的提示必须停下，等用户回复『继续』后调 confirm_run.py。
    orch.init_run_state(run_id)

    print(json.dumps({
        "status": "waiting_user_confirmation",
        "run_id": run_id,
        "stage": "awaiting_user_confirmation",
        "message": (
            "Step 1（提取 JD）已完成。"
            "请在 BOSS 直聘『推荐牛人』页面调整筛选条件"
            "（关键词、年龄、薪资、经验等），确保命中率。"
            "调整完成后回复『继续』，我会调用：\n"
            "  python shared/confirm_run.py "
            f"--job-name \"{job_name}\" --encrypt-job-id \"{encrypt_job_id}\" --run-id \"{run_id}\"\n"
            "把 run.json 的 confirmed 切到 true，再继续 Step 2~5。"
        ),
    }, ensure_ascii=False, indent=2))
    print(f"Saved to {out_path}")
    print(f"run_id: {output.run_id}")
    print("OK")
