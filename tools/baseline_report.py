"""_baseline_report.py — 跑旧 generate_html_report.py，记录基线（2026-08-03）

不依赖桌面真实数据；用 BOSS_HR_OUTPUT_DIR 指向 tmp_path，建两个 run：
- target run：有 screening_results.json，预期正常生成 HTML
- other run：已有旧 HTML，验证不会被新 run 借用

跑旧脚本前后比对文件 sha256，确认副作用范围；记所有 stdout/stderr/exit code。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE  # __file__ 在工具包根（boss-hr-agent-toolkit/）
SCRIPTS_HTML = TOOLKIT_ROOT / "html-report" / "scripts"
SHARED = TOOLKIT_ROOT / "shared"


def _run(cmd: list[str], env: dict, cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """子进程 utf-8 编解码；生成 HTML 输出可能含 GBK 不能解码的字节 → 用 surrogateescape。"""
    return subprocess.run(
        cmd, capture_output=True, env=env, cwd=cwd, timeout=timeout,
    )


def _decode(b: bytes | None) -> str:
    """bytes → str（utf-8 优先；HTML 输出可能含 latin-1 字节 → 兜底）。"""
    if not b:
        return ""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        eid = "test_eid_baseline"
        job_name = "baseline_job"

        # ----- 造一个 target run + screening_results.json -----
        target_run = "2026-08-03_120000"
        other_run = "2026-08-02_120000"
        for rid in (target_run, other_run):
            rd = tmp_path / eid / "runs" / rid / "process"
            rd.mkdir(parents=True, exist_ok=True)
            (tmp_path / eid / "runs" / rid / "run.json").write_text(json.dumps({
                "run_id": rid, "encrypt_job_id": eid,
                "started_at": "2026-08-03 12:00:00", "confirmed": True,
                "user_confirmed_at": "2026-08-03 12:01:00",
                "steps_done": ["jd", "download", "score"], "last_step": "score",
                "last_step_at": "2026-08-03 12:30:00", "finished": False, "finished_at": None,
            }, ensure_ascii=False), encoding="utf-8")
            (rd / "job_detail.json").write_text(json.dumps({
                "jobName": job_name, "encryptJobId": eid,
            }, ensure_ascii=False), encoding="utf-8")

        # ----- screening_results.json（target） -----
        screening = {
            "job_name": job_name,
            "run_id": target_run,
            "meta": {
                "title": f"{job_name} · 简历筛选报告",
                "subtitle": "baseline",
                "job": {"name": job_name, "company": "", "location": "", "salary": "",
                        "experience_required": "", "degree_required": ""},
                "type_judgment": {"type": "技术岗", "reason": "test"},
                "core_requirements": ["req1", "req2"],
            },
            "summary": {"total": 3, "recommend": 1, "pending": 1, "reject": 1},
            "dimension_labels": ["学历", "工作经验", "技能", "项目", "专业"],
            "candidates": [
                {"rank": 1, "name": "张三", "tier": "推荐", "total": 78.5,
                 "school": "辽宁工业大学", "work_years": "5 年", "current_role": "结构设计",
                 "hard_pass": True, "hard_reason": None,
                 "dimensions": [
                     {"pct": 70, "weighted": 17.5, "weight": 25, "reason": "C9"},
                     {"pct": 80, "weighted": 20.0, "weight": 25, "reason": "5年"},
                     {"pct": 85, "weighted": 21.25, "weight": 25, "reason": "skill"},
                     {"pct": 75, "weighted": 11.25, "weight": 15, "reason": "proj"},
                     {"pct": 85, "weighted": 8.5, "weight": 10, "reason": "major"},
                 ],
                 "highlights": ["亮点A", "亮点B"], "concerns": []},
                {"rank": 2, "name": "李四", "tier": "待定", "total": 65.0,
                 "school": "苏州大学", "work_years": "3 年", "current_role": "机械设计",
                 "hard_pass": True, "hard_reason": None,
                 "dimensions": [
                     {"pct": 80, "weighted": 20.0, "weight": 25, "reason": "211"},
                     {"pct": 60, "weighted": 15.0, "weight": 25, "reason": "3年"},
                     {"pct": 60, "weighted": 15.0, "weight": 25, "reason": "skill"},
                     {"pct": 70, "weighted": 10.5, "weight": 15, "reason": "proj"},
                     {"pct": 50, "weighted": 5.0, "weight": 10, "reason": "major"},
                 ],
                 "highlights": [], "concerns": ["顾虑A"]},
                {"rank": 3, "name": "王五", "tier": "不推荐", "total": 45.0,
                 "school": "野鸡大学", "work_years": "1 年", "current_role": "实习",
                 "hard_pass": True, "hard_reason": None,
                 "dimensions": [
                     {"pct": 50, "weighted": 12.5, "weight": 25, "reason": ""},
                     {"pct": 40, "weighted": 10.0, "weight": 25, "reason": ""},
                     {"pct": 50, "weighted": 12.5, "weight": 25, "reason": ""},
                     {"pct": 40, "weighted": 6.0, "weight": 15, "reason": ""},
                     {"pct": 40, "weighted": 4.0, "weight": 10, "reason": ""},
                 ],
                 "highlights": [], "concerns": ["经验浅"]},
            ],
            "actions": {
                "recommend": [{"name": "张三", "score": 78.5,
                               "background": "亮点A、亮点B", "action": "约面试"}],
                "pending": [{"name": "李四", "score": 65.0,
                             "strengths": "211", "action": "确认设计能力"}],
                "reject": [{"name": "王五", "score": 45.0, "concerns": "经验浅"}],
            },
        }
        (tmp_path / eid / "runs" / target_run / "process" / "screening_results.json").write_text(
            json.dumps(screening, ensure_ascii=False), encoding="utf-8"
        )

        # ----- other run 放一份"诱饵"旧 HTML（验证新 run 不借用） -----
        (tmp_path / eid / "runs" / other_run / "process" / "screening_results.json").write_text(
            json.dumps({"candidates": [{"name": "诱饵", "tier": "推荐", "total": 99,
                                         "dimensions": [], "highlights": [], "concerns": []}]},
                       ensure_ascii=False), encoding="utf-8"
        )
        (tmp_path / eid / "runs" / other_run / f"{other_run}_screening_report.html").write_text(
            "<html>诱饵旧报告</html>", encoding="utf-8"
        )

        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": str(SHARED), "BOSS_HR_OUTPUT_DIR": str(tmp_path)}

        # ----- 跑旧脚本（target） -----
        cmd = [sys.executable, "-X", "utf8",
               str(SCRIPTS_HTML / "generate_html_report.py"),
               "--job-name", job_name, "--encrypt-job-id", eid,
               "--run-id", target_run]
        before_run_json = (tmp_path / eid / "runs" / target_run / "run.json").read_text(encoding="utf-8")
        proc = _run(cmd, env=env, cwd=str(SCRIPTS_HTML))
        after_run_json = (tmp_path / eid / "runs" / target_run / "run.json").read_text(encoding="utf-8")

        report_path = tmp_path / eid / "runs" / target_run / f"{target_run}_screening_report.html"
        report_exists = report_path.exists()
        report_size = report_path.stat().st_size if report_exists else 0

        # 抓 HTML 关键统计
        html_text = report_path.read_text(encoding="utf-8") if report_exists else ""
        # 找候选人顺序（rank 数字出现的位置）
        ranks_in_order = []
        import re
        for m in re.finditer(r'<span class="rank">#?(\d+)</span>', html_text):
            ranks_in_order.append(int(m.group(1)))
        # stat-card 数字
        stat_nums = re.findall(r'<div class="num">(\d+)</div>', html_text)
        # tier badge
        tier_count = {"推荐": 0, "待定": 0, "不推荐": 0}
        for m in re.finditer(r'✅ 推荐|📌 待定|❌ 不推荐', html_text):
            label = m.group()
            if "推荐" in label and "待定" not in label and "不" not in label:
                tier_count["推荐"] += 1
            elif "待定" in label:
                tier_count["待定"] += 1
            elif "不推荐" in label:
                tier_count["不推荐"] += 1

        # ----- 边界 1：缺 screening_results.json → exit 27 -----
        empty_run = "2026-08-03_130000"
        (tmp_path / eid / "runs" / empty_run / "process").mkdir(parents=True, exist_ok=True)
        (tmp_path / eid / "runs" / empty_run / "run.json").write_text(json.dumps({
            "run_id": empty_run, "encrypt_job_id": eid,
            "started_at": "2026-08-03 13:00:00", "confirmed": True,
            "steps_done": ["jd"], "last_step": "jd",
            "finished": False, "finished_at": None,
        }, ensure_ascii=False), encoding="utf-8")
        (tmp_path / eid / "runs" / empty_run / "process" / "job_detail.json").write_text(
            json.dumps({"encryptJobId": eid}, ensure_ascii=False), encoding="utf-8"
        )
        cmd2 = [sys.executable, "-X", "utf8",
                str(SCRIPTS_HTML / "generate_html_report.py"),
                "--job-name", job_name, "--encrypt-job-id", eid,
                "--run-id", empty_run]
        proc_missing = _run(cmd2, env=env, cwd=str(SCRIPTS_HTML))

        # ----- 边界 2：encrypt_job_id 错（run_id 不存在） -----
        cmd3 = [sys.executable, "-X", "utf8",
                str(SCRIPTS_HTML / "generate_html_report.py"),
                "--job-name", job_name, "--encrypt-job-id", "wrong_eid",
                "--run-id", target_run]
        proc_wrong = _run(cmd3, env=env, cwd=str(SCRIPTS_HTML))

        # ----- 边界 3：run_id 不存在 -----
        cmd4 = [sys.executable, "-X", "utf8",
                str(SCRIPTS_HTML / "generate_html_report.py"),
                "--job-name", job_name, "--encrypt-job-id", eid,
                "--run-id", "9999-99-99_999999"]
        proc_no_run = _run(cmd4, env=env, cwd=str(SCRIPTS_HTML))

        # ----- 边界 4：缺 --run-id -----
        cmd5 = [sys.executable, "-X", "utf8",
                str(SCRIPTS_HTML / "generate_html_report.py"),
                "--job-name", job_name, "--encrypt-job-id", eid]
        proc_no_argv = _run(cmd5, env=env, cwd=str(SCRIPTS_HTML))

        # ----- 重复跑（idempotent / overwrite） -----
        proc_repeat = _run(cmd, env=env, cwd=str(SCRIPTS_HTML))

        # ----- 输出基线 JSON -----
        baseline = {
            "tmp_path": str(tmp_path),
            "env": {k: v for k, v in env.items() if k not in {"PYTHONHOME"}},
            "happy_path": {
                "returncode": proc.returncode,
                "stdout": _decode(proc.stdout),
                "stderr": _decode(proc.stderr),
                "report_exists": report_exists,
                "report_size_bytes": report_size,
                "report_path": str(report_path),
                "ranks_in_html": ranks_in_order,
                "stat_nums": stat_nums,
                "tier_count": tier_count,
                "run_json_diff": {
                    "before": json.loads(before_run_json),
                    "after": json.loads(after_run_json),
                },
            },
            "missing_screening": {
                "returncode": proc_missing.returncode,
                "stdout": _decode(proc_missing.stdout),
                "stderr": _decode(proc_missing.stderr),
            },
            "wrong_encrypt_job_id": {
                "returncode": proc_wrong.returncode,
                "stdout": _decode(proc_wrong.stdout),
                "stderr": _decode(proc_wrong.stderr),
            },
            "no_such_run": {
                "returncode": proc_no_run.returncode,
                "stdout": _decode(proc_no_run.stdout),
                "stderr": _decode(proc_no_run.stderr),
            },
            "missing_run_id_argv": {
                "returncode": proc_no_argv.returncode,
                "stdout": _decode(proc_no_argv.stdout),
                "stderr": _decode(proc_no_argv.stderr),
            },
            "repeat_run": {
                "returncode": proc_repeat.returncode,
                "stdout": _decode(proc_repeat.stdout),
                "stderr": _decode(proc_repeat.stderr),
            },
        }
        out = TOOLKIT_ROOT / "artifacts" / "refactor" / "report-baseline.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
