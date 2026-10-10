# -*- coding: utf-8 -*-
"""6 场景验收测试（2026-07-30 run_id 数据边界重构）。

覆盖：
  1. 连续开始两次任务 → 必须生成不同的 run_id
  2. 上一个任务未完成时再开始 → 仍必须生成新 run_id
  3. 子脚本不传 run_id → 必须直接失败（argparse 或 bind_existing_run 拒绝）
  4. 当前 run 没有简历时执行评分 → 必须报错，不能读取历史简历
  5. 桌面存在旧报告 → 报告脚本仍必须根据当前 run 的 screening_results 重新生成
  6. 原有业务脚本（job_resume_store、output_manager、run_orchestrator）
     抓取/下载/评分/报告关键逻辑仍能正常运行
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

_SHARED = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
_SCRIPTS_RECOMMEND = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "boss-recommend-downloader", "scripts")
)
_SCRIPTS_SCORE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "resume-screener", "scripts")
)
_SCRIPTS_HTML = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "html-report", "scripts")
)


# ----------------------------- 子进程 helper -----------------------------

def _subproc_env(out_root):
    return {
        **os.environ,
        "BOSS_HR_OUTPUT_DIR": out_root,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONPATH": _SHARED + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }


def _subproc_run(out_root, src, cwd=None, timeout=15):
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", textwrap.dedent(src)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace",
        env=_subproc_env(out_root),
        cwd=cwd or _SHARED,
        timeout=timeout,
    )


def _run_cli(argv, out_root, cwd, timeout=15):
    return subprocess.run(
        [sys.executable, "-X", "utf8", *argv],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace",
        env=_subproc_env(out_root),
        cwd=cwd,
        timeout=timeout,
    )


def _last_json_line(text):
    for line in text.strip().splitlines()[::-1]:
        try:
            return json.loads(line)
        except Exception:
            continue
    return None


# ----------------------------- 场景 1 -----------------------------

def test_scenario_1_consecutive_starts_get_different_run_ids(tmp_path):
    """场景 1：连续 start 两次 → 必须生成不同的 run_id。"""
    src = """
        import json
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc1_job', encrypt_job_id='fake_sc1')
        a = orch.create_new_run()
        b = orch.create_new_run()
        print(json.dumps({'a': a, 'b': b, 'equal': a == b}))
    """
    r = _subproc_run(str(tmp_path), src)
    assert r.returncode == 0, f"stderr={r.stderr}"
    payload = json.loads(r.stdout.strip().splitlines()[-1])
    assert payload["a"] != payload["b"], (
        f"必须得到不同 run_id，实际 a={payload['a']} b={payload['b']}"
    )


# ----------------------------- 场景 2 -----------------------------

def test_scenario_2_unfinished_previous_still_creates_new(tmp_path):
    """场景 2：上一个任务未完成（目录存在但未 finish）→ 再开始仍必须生成新 run_id。"""
    setup_src = """
        import os, json
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc2_job', encrypt_job_id='fake_sc2')
        # 第一个任务：创建 + 留下 process/job_detail.json（模拟真实产物，但没 finish）
        rid1 = orch.create_new_run()
        run_dir = os.path.join(orch._mgr.runs_dir, rid1)
        os.makedirs(os.path.join(run_dir, 'process'), exist_ok=True)
        open(os.path.join(run_dir, 'process', 'job_detail.json'), 'w').write(
            json.dumps({'encryptJobId': 'fake_sc2'})
        )
        # 第二个任务：再来
        rid2 = orch.create_new_run()
        print(json.dumps({'rid1': rid1, 'rid2': rid2, 'equal': rid1 == rid2}))
    """
    r = _subproc_run(str(tmp_path), setup_src)
    assert r.returncode == 0, f"stderr={r.stderr}"
    payload = json.loads(r.stdout.strip().splitlines()[0])
    assert payload["rid1"] != payload["rid2"], (
        "上一个任务未完成时，必须仍创建新 run_id"
    )


# ----------------------------- 场景 3 -----------------------------

def test_scenario_3a_recommend_list_without_run_id_fails(tmp_path):
    """场景 3a：recommend_list.py 不传 --run-id → argparse 退出码 2。

    argparse 在 required=True 参数缺失时返回 rc=2（系统约定，不是我们的 EXIT_CODE）。
    错误信息写到 stderr，含 \"the following arguments are required: --run-id\"。
    """
    result = _run_cli(
        [os.path.join(_SCRIPTS_RECOMMEND, "recommend_list.py"),
         "--job-name", "sc3_job",
         "--encrypt-job-id", "fake_sc3",
         "--max", "5"],
        out_root=str(tmp_path),
        cwd=os.path.dirname(_SCRIPTS_RECOMMEND),
    )
    assert result.returncode == 2, (
        f"argparse 缺 --run-id 应返回 rc=2，实际={result.returncode}"
        f"\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    err_text = result.stderr or result.stdout
    assert "--run-id" in err_text, (
        f"错误信息应提到 --run-id，实际={err_text!r}"
    )


def test_scenario_3b_score_without_run_id_fails(tmp_path):
    """场景 3b：score_resumes.py 不传 --run-id → argparse 退出码 2。"""
    result = _run_cli(
        [os.path.join(_SCRIPTS_SCORE, "score_resumes.py"),
         "--job-name", "sc3b_job",
         "--encrypt-job-id", "fake_sc3b"],
        out_root=str(tmp_path),
        cwd=os.path.dirname(_SCRIPTS_SCORE),
    )
    assert result.returncode == 2, (
        f"argparse 缺 --run-id 应返回 rc=2，实际={result.returncode}"
        f"\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "--run-id" in (result.stderr or result.stdout)


def test_scenario_3c_html_report_without_run_id_fails(tmp_path):
    """场景 3c：generate_html_report.py 不传 --run-id → argparse 退出码 2。"""
    result = _run_cli(
        [os.path.join(_SCRIPTS_HTML, "generate_html_report.py"),
         "--job-name", "sc3c_job",
         "--encrypt-job-id", "fake_sc3c"],
        out_root=str(tmp_path),
        cwd=os.path.dirname(_SCRIPTS_HTML),
    )
    assert result.returncode == 2, (
        f"argparse 缺 --run-id 应返回 rc=2，实际={result.returncode}"
        f"\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "--run-id" in (result.stderr or result.stdout)


def test_scenario_3d_auto_greet_without_run_id_fails(tmp_path):
    """场景 3d：auto_greet.py 不传 --run-id → argparse 退出码 2。"""
    _SCRIPTS_GREET = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "boss-hr-greet", "scripts")
    )
    result = _run_cli(
        [os.path.join(_SCRIPTS_GREET, "auto_greet.py"),
         "--job-name", "sc3d_job",
         "--encrypt-job-id", "fake_sc3d"],
        out_root=str(tmp_path),
        cwd=_SCRIPTS_GREET,
    )
    assert result.returncode == 2, (
        f"argparse 缺 --run-id 应返回 rc=2，实际={result.returncode}"
        f"\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "--run-id" in (result.stderr or result.stdout)


# ----------------------------- 场景 4 -----------------------------

def test_scenario_4_score_without_current_run_resumes_fails(tmp_path):
    """场景 4：当前 run 没有 _llm_scores.json → score_resumes 必须报错，不读历史。

    即使 state/resumes_master.json 或其他 run 的 process/ 有"诱饵"简历，
    评分脚本也只读当前 run 自己的 _llm_scores.json（且必须存在）。
    """
    # setup：建一个 run（process/ 是空的）+ 写诱饵简历到 state/resumes_master.json
    setup_src = """
        import os, json
        from run_orchestrator import RunOrchestrator
        from job_resume_store import JobResumeStore

        orch = RunOrchestrator('sc4_job', encrypt_job_id='fake_sc4')
        rid = orch.create_new_run()
        # 让 run_dir 有真实产物
        run_dir = os.path.join(orch._mgr.runs_dir, rid)
        os.makedirs(os.path.join(run_dir, 'process'), exist_ok=True)
        open(os.path.join(run_dir, 'process', 'job_detail.json'), 'w').write(
            json.dumps({'encryptJobId': 'fake_sc4'})
        )

        # 诱饵：state/resume_archive.json（旧累计文件），放一份"历史"简历
        store = JobResumeStore('sc4_job', encrypt_job_id='fake_sc4')
        store.save_resume(
            {'ok': True, 'name': '历史候选人', 'age': '30', 'degree': '本科',
             'work_experience': [], 'education': [], 'project_experience': []},
            job_id='fake_sc4', geek_id='HISTORIC_GID', run_id='OLD_RUN'
        )
        print(rid)
    """
    r0 = _subproc_run(str(tmp_path), setup_src)
    assert r0.returncode == 0, r0.stderr
    rid = r0.stdout.strip().splitlines()[-1]

    # 验证诱饵已写入（文件名仍叫 resumes_master.json —— 旧累计文件保留）
    archive_path = os.path.join(tmp_path, "fake_sc4", "state", "resumes_master.json")
    assert os.path.exists(archive_path), "诱饵文件未生成"

    # 跑 score：当前 run 缺 _llm_scores.json → SystemExit(26)
    result = _run_cli(
        [os.path.join(_SCRIPTS_SCORE, "score_resumes.py"),
         "--job-name", "sc4_job",
         "--encrypt-job-id", "fake_sc4",
         "--run-id", rid],
        out_root=str(tmp_path),
        cwd=os.path.dirname(_SCRIPTS_SCORE),
    )
    assert result.returncode == 26, (
        f"预期 SystemExit(26) 缺 _llm_scores.json，实际={result.returncode}"
        f"\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    payload = _last_json_line(result.stdout)
    assert payload is not None
    assert payload["exit_code"] == 26
    assert "_llm_scores.json" in payload["message"]

    # 关键验证：当前 run 不应被凭空生成 screening_results.json
    screening = os.path.join(tmp_path, "fake_sc4", "runs", rid, "process",
                             "screening_results.json")
    assert not os.path.exists(screening), (
        "评分脚本不应跨 run / 读累计文件来凭空生成报告"
    )


# ----------------------------- 场景 5 -----------------------------

def test_scenario_5_old_html_report_does_not_block_new_report(tmp_path):
    """场景 5：旧 run 的 HTML 报告存在 → 新 run 缺 screening_results.json 时仍必须报错。

    即使桌面 / 其他 run 有旧的 .html 报告，新 run 的 generate_html_report.py
    也只读当前 run 的 process/screening_results.json。缺了就 SystemExit(27)。
    """
    setup_src = """
        import os, json
        from run_orchestrator import RunOrchestrator

        orch = RunOrchestrator('sc5_job', encrypt_job_id='fake_sc5')
        # 旧 run：写一份"历史报告"
        rid_old = orch.create_new_run()
        run_old = os.path.join(orch._mgr.runs_dir, rid_old)
        os.makedirs(os.path.join(run_old, 'process'), exist_ok=True)
        open(os.path.join(run_old, 'process', 'job_detail.json'), 'w').write(
            json.dumps({'encryptJobId': 'fake_sc5'})
        )
        open(os.path.join(run_old, 'process', 'screening_results.json'), 'w').write(
            json.dumps({'candidates': []})
        )
        with open(os.path.join(run_old, f'{rid_old}_screening_report.html'), 'w', encoding='utf-8') as f:
            f.write('<html>OLD REPORT</html>')

        # 新 run：process/ 空
        rid_new = orch.create_new_run()
        run_new = os.path.join(orch._mgr.runs_dir, rid_new)
        os.makedirs(os.path.join(run_new, 'process'), exist_ok=True)
        open(os.path.join(run_new, 'process', 'job_detail.json'), 'w').write(
            json.dumps({'encryptJobId': 'fake_sc5'})
        )
        print(rid_new)
    """
    r0 = _subproc_run(str(tmp_path), setup_src)
    rid_new = r0.stdout.strip().splitlines()[-1]

    # 跑 report：新 run 缺 screening_results.json → SystemExit(27)
    result = _run_cli(
        [os.path.join(_SCRIPTS_HTML, "generate_html_report.py"),
         "--job-name", "sc5_job",
         "--encrypt-job-id", "fake_sc5",
         "--run-id", rid_new],
        out_root=str(tmp_path),
        cwd=os.path.dirname(_SCRIPTS_HTML),
    )
    assert result.returncode == 27, (
        f"预期 SystemExit(27)，实际={result.returncode}"
        f"\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    payload = _last_json_line(result.stdout)
    assert payload is not None
    assert payload["exit_code"] == 27
    assert "screening_results.json" in payload["message"]

    # 验证新 run 没生成 HTML 报告（不能凭空生成）
    new_report = os.path.join(tmp_path, "fake_sc5", "runs", rid_new,
                              f"{rid_new}_screening_report.html")
    assert not os.path.exists(new_report), (
        "未生成 screening_results.json 时，HTML 报告不应被凭空生成"
    )


# ----------------------------- 场景 6：原有业务脚本仍能正常运行 -----------------------------

def test_scenario_6a_orchestrator_create_and_bind(tmp_path):
    """场景 6a：create_new_run → bind_existing_run 链路正常工作。"""
    src = """
        import json
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc6a_job', encrypt_job_id='fake_sc6a')
        rid = orch.create_new_run()
        # 写 job_detail.json，让 bind_existing_run 校验通过
        import os
        run_dir = os.path.join(orch._mgr.runs_dir, rid)
        os.makedirs(os.path.join(run_dir, 'process'), exist_ok=True)
        with open(os.path.join(run_dir, 'process', 'job_detail.json'), 'w', encoding='utf-8') as f:
            f.write(json.dumps({'encryptJobId': 'fake_sc6a'}))
        bound = orch.bind_existing_run(rid)
        print(json.dumps({'created': rid, 'bound': bound}))
    """
    r = _subproc_run(str(tmp_path), src)
    assert r.returncode == 0, f"stderr={r.stderr}"
    payload = json.loads(r.stdout.strip().splitlines()[-1])
    assert payload["created"] == payload["bound"]


def test_scenario_6b_bind_existing_run_with_unknown_id_raises(tmp_path):
    """场景 6b：bind_existing_run 传不存在的 run_id → 抛 FileNotFoundError。"""
    src = """
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc6b_job', encrypt_job_id='fake_sc6b')
        try:
            orch.bind_existing_run('NON_EXIST_RUN_ID_9999')
        except FileNotFoundError as e:
            print('FILENOTFOUND:' + str(e))
    """
    r = _subproc_run(str(tmp_path), src)
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "FILENOTFOUND:" in r.stdout


def test_scenario_6c_bind_existing_run_with_empty_raises_value_error(tmp_path):
    """场景 6c：bind_existing_run 不传 run_id → 抛 ValueError。"""
    src = """
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc6c_job', encrypt_job_id='fake_sc6c')
        try:
            orch.bind_existing_run('')
        except ValueError as e:
            print('VALUEERROR:' + str(e))
        except Exception as e:
            print('OTHER:' + type(e).__name__ + ':' + str(e))
    """
    r = _subproc_run(str(tmp_path), src)
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "VALUEERROR:" in r.stdout, f"stdout={r.stdout!r}"


def test_scenario_6d_bind_existing_run_mismatched_job_raises(tmp_path):
    """场景 6d：bind_existing_run 传别岗位的 run_id → 抛 RuntimeError。"""
    setup = """
        import os, json
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc6d_job', encrypt_job_id='fake_sc6d_a')
        rid = orch.create_new_run()
        run_dir = os.path.join(orch._mgr.runs_dir, rid)
        os.makedirs(os.path.join(run_dir, 'process'), exist_ok=True)
        with open(os.path.join(run_dir, 'process', 'job_detail.json'), 'w', encoding='utf-8') as f:
            f.write(json.dumps({'encryptJobId': 'fake_sc6d_a'}))
        print(rid)
    """
    r0 = _subproc_run(str(tmp_path), setup)
    rid = r0.stdout.strip().splitlines()[-1]

    src = f"""
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc6d_job', encrypt_job_id='fake_sc6d_b_DIFFERENT')
        try:
            orch.bind_existing_run({rid!r})
        except (FileNotFoundError, RuntimeError) as e:
            print('BLOCKED:' + type(e).__name__ + ':' + str(e))
    """
    r = _subproc_run(str(tmp_path), src)
    assert r.returncode == 0
    assert "BLOCKED:" in r.stdout


def test_scenario_6e_job_resume_store_basic(tmp_path):
    """场景 6e：JobResumeStore 的累计功能仍正常（仅供下载阶段去重用，不影响评分）。"""
    sys.path.insert(0, _SHARED)
    from job_resume_store import JobResumeStore, candidate_key
    store = JobResumeStore("sc6e_job", encrypt_job_id="fake_sc6e")

    # add_candidate + save_resume + is_scored 都正常
    store.add_candidate({
        "encryptGeekId": "G1",
        "geekCard": {"encryptJobId": "fake_sc6e", "geekName": "测试张三"},
    })
    store.save_resume(
        {"ok": True, "name": "测试张三", "age": "30", "degree": "本科",
         "work_experience": [], "education": [], "project_experience": []},
        job_id="fake_sc6e", geek_id="G1", run_id="R1",
    )
    # 累计简历文件（暂时保留原文件名 resumes_master.json）
    assert os.path.exists(store.resumes_master_path)
    with open(store.resumes_master_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert candidate_key("fake_sc6e", "G1") in data["items"]
    assert store.count_resumes() == 1


def test_scenario_6f_output_manager_paths(tmp_path):
    """场景 6f：JobOutputManager 仍能按 encryptJobId+run_id 定位当前 run 的目录。"""
    sys.path.insert(0, _SHARED)
    import output_manager
    output_manager.OUTPUT_ROOT = str(tmp_path)
    import importlib
    importlib.reload(output_manager)
    from output_manager import JobOutputManager
    out = JobOutputManager("sc6f_job", encrypt_job_id="fake_sc6f", run_id="2026-07-30_103000")
    # Windows 路径用 \ 而非 /，所以用 endswith 包含 "runs/2026-07-30_103000" 的反斜杠版本
    assert "runs" in str(out.run_dir) and "2026-07-30_103000" in str(out.run_dir)
    assert out.encrypt_job_id == "fake_sc6f"
    # 路径里的 process/ 子目录可定位
    assert "process" in str(out.get_process_path("anything.json"))


# ============================================================================
# 第二轮重构（2026-07-30 封死旧 run 入口 + 用户确认门）新增测试
# ============================================================================

# ----------- 场景 7: bind_or_create 已废弃 -----------

def test_scenario_7_bind_or_create_raises_runtime_error(tmp_path):
    """场景 7：调用 bind_or_create() 立即抛 RuntimeError。"""
    src = """
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc7_job', encrypt_job_id='fake_sc7')
        try:
            orch.bind_or_create()
        except RuntimeError as e:
            print('BLOCKED:' + str(e))
    """
    r = _subproc_run(str(tmp_path), src)
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "BLOCKED:" in r.stdout, f"stdout 应包含 RuntimeError 信息，实际={r.stdout!r}"
    assert "已废弃" in r.stdout


# ----------- 场景 8: recommend_list 在 confirmed=false 时 rc=20 -----------

def test_scenario_8_recommend_list_blocks_when_not_confirmed(tmp_path):
    """场景 8：confirmed=false 时调 recommend_list.py → SystemExit(20)。"""
    setup_src = """
        import os, json
        from run_orchestrator import RunOrchestrator

        orch = RunOrchestrator('sc8_job', encrypt_job_id='fake_sc8')
        rid = orch.create_new_run()
        # 模拟 Step 1 跑完：写 job_detail.json + init run.json (confirmed=false)
        run_dir = os.path.join(orch._mgr.runs_dir, rid)
        os.makedirs(os.path.join(run_dir, 'process'), exist_ok=True)
        with open(os.path.join(run_dir, 'process', 'job_detail.json'), 'w', encoding='utf-8') as f:
            f.write(json.dumps({'encryptJobId': 'fake_sc8'}))
        orch.init_run_state(rid)
        print(rid)
    """
    r0 = _subproc_run(str(tmp_path), setup_src)
    assert r0.returncode == 0, r0.stderr
    rid = r0.stdout.strip().splitlines()[-1]

    # 验证 run.json 里 confirmed=false
    run_json_path = os.path.join(tmp_path, "fake_sc8", "runs", rid, "run.json")
    with open(run_json_path, "r", encoding="utf-8") as f:
        run_data = json.load(f)
    assert run_data["confirmed"] is False

    # 跑 recommend_list → SystemExit(20)
    result = _run_cli(
        [os.path.join(_SCRIPTS_RECOMMEND, "recommend_list.py"),
         "--job-name", "sc8_job",
         "--encrypt-job-id", "fake_sc8",
         "--run-id", rid,
         "--max", "5"],
        out_root=str(tmp_path),
        cwd=os.path.dirname(_SCRIPTS_RECOMMEND),
    )
    assert result.returncode == 20, (
        f"预期 rc=20（未确认），实际={result.returncode}"
        f"\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    payload = _last_json_line(result.stdout)
    assert payload is not None
    assert payload["exit_code"] == 20
    assert "尚未确认" in payload["message"] or "用户尚未确认" in payload["message"]


# ----------- 场景 9: confirm_run.py 切 confirmed=true -----------

def test_scenario_9_confirm_run_switches_to_confirmed(tmp_path):
    """场景 9：confirm_run.py 把 confirmed 切到 true，Step 2 才能继续。"""
    # setup: 创建 run + job_detail.json + init run.json
    setup_src = """
        import os, json
        from run_orchestrator import RunOrchestrator

        orch = RunOrchestrator('sc9_job', encrypt_job_id='fake_sc9')
        rid = orch.create_new_run()
        run_dir = os.path.join(orch._mgr.runs_dir, rid)
        os.makedirs(os.path.join(run_dir, 'process'), exist_ok=True)
        with open(os.path.join(run_dir, 'process', 'job_detail.json'), 'w', encoding='utf-8') as f:
            f.write(json.dumps({'encryptJobId': 'fake_sc9'}))
        orch.init_run_state(rid)
        print(rid)
    """
    r0 = _subproc_run(str(tmp_path), setup_src)
    rid = r0.stdout.strip().splitlines()[-1]

    # 调 confirm_run.py
    result = _run_cli(
        [os.path.join(_SHARED, "confirm_run.py"),
         "--job-name", "sc9_job",
         "--encrypt-job-id", "fake_sc9",
         "--run-id", rid],
        out_root=str(tmp_path),
        cwd=os.path.dirname(_SHARED),
    )
    assert result.returncode == 0, (
        f"confirm_run.py 应成功，实际 rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    payload = _last_json_line(result.stdout)
    assert payload["status"] == "confirmed"
    assert payload["confirmed"] is True

    # 验证 run.json.confirmed=true
    run_json_path = os.path.join(tmp_path, "fake_sc9", "runs", rid, "run.json")
    with open(run_json_path, "r", encoding="utf-8") as f:
        run_data = json.load(f)
    assert run_data["confirmed"] is True
    assert run_data["user_confirmed_at"] is not None

    # 验证：is_confirmed(run_id) → True
    check_src = f"""
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc9_job', encrypt_job_id='fake_sc9')
        print('CONFIRMED:' + str(orch.is_confirmed({rid!r})))
    """
    rc = _subproc_run(str(tmp_path), check_src)
    assert "CONFIRMED:True" in rc.stdout


# ----------- 场景 10: grep 断言（生产代码无 bind_or_create） -----------

# 这个测试不需要 tmp_path；它做静态扫描
def test_scenario_10_no_bind_or_create_in_production_code():
    """场景 10：生产代码（不含 tests/）不应再调 bind_or_create。

    允许位置：
      - shared/run_orchestrator.py 里的废弃方法（调用即 raise）
      - 测试文件（含 \"bind_or_create 已废弃\" 之类的字样）
      - SKILL.md / 注释里说明已废弃
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    production_dirs = [
        "shared",
        "boss-hr-auto",
        "boss-job-detail",
        "boss-recommend-downloader",
        "boss-hr-greet",
        "resume-screener",
        "html-report",
    ]
    bad_files = []
    for d in production_dirs:
        full = os.path.join(repo_root, d)
        for root, _dirs, files in os.walk(full):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, repo_root)
                # 跳过 run_orchestrator.py（废弃方法的定义就在这里）
                if rel.endswith("run_orchestrator.py"):
                    continue
                with open(fpath, "r", encoding="utf-8") as f:
                    text = f.read()
                # 检测：生产代码不应再有 `bind_or_create(` 实际调用
                if "bind_or_create(" in text:
                    bad_files.append(f"{rel}: 调用了 bind_or_create()")

    assert not bad_files, (
        f"生产代码发现 bind_or_create 调用残留：\n  " + "\n  ".join(bad_files)
        + "\n请改用 create_new_run() / bind_existing_run(run_id)。"
    )


def test_scenario_10b_run_orchestrator_bind_or_create_raises():
    """场景 10b：bind_or_create 的实现是 raise RuntimeError，不是兼容行为。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    src = """
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc10b_job', encrypt_job_id='fake_sc10b')
        try:
            orch.bind_or_create('any_arg', 'any_other')
        except RuntimeError as e:
            print('RUNTIME_ERROR:' + str(e))
    """
    r = _subproc_run(tmp, src)
    assert "RUNTIME_ERROR:" in r.stdout, f"stdout={r.stdout}"

# ============================================================================
# 第三轮维护更新（2026-07-30 收尾）新增测试
# ============================================================================

def test_scenario_11_bind_existing_run_returns_input_run_id(tmp_path):
    """场景 11：bind_existing_run(run_id) 返回值与入参相同。

    校验通过 → 返回 str（与入参 run_id 一致）
    """
    setup_src = """
        import os, json
        from run_orchestrator import RunOrchestrator
        orch = RunOrchestrator('sc11_job', encrypt_job_id='fake_sc11')
        rid = orch.create_new_run()
        run_dir = os.path.join(orch._mgr_lazy.runs_dir, rid)
        os.makedirs(os.path.join(run_dir, 'process'), exist_ok=True)
        with open(os.path.join(run_dir, 'process', 'job_detail.json'), 'w', encoding='utf-8') as f:
            f.write(json.dumps({'encryptJobId': 'fake_sc11'}))
        bound = orch.bind_existing_run(rid)
        print(json.dumps({'input': rid, 'output': bound, 'type': type(bound).__name__, 'equal': rid == bound}))
    """
    r = _subproc_run(str(tmp_path), setup_src)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout.strip().splitlines()[-1])
    assert payload["type"] == "str"
    assert payload["equal"] is True
    assert payload["input"] == payload["output"]


def test_scenario_12_run_json_path_consistency(tmp_path):
    """场景 12：run.json 路径在 init_run_state / is_confirmed / confirm_run / mark_done / finish 之间一致。

    所有写入都通过 _save_run(run_id, state) → runs/<run_id>/run.json。
    所有读取都通过 _load_run(run_id) → 同路径。
    """
    setup_src = """
        import json
        from run_orchestrator import RunOrchestrator

        orch = RunOrchestrator('sc12_job', encrypt_job_id='fake_sc12')
        rid = orch.create_new_run()
        # init_run_state
        orch.init_run_state(rid)
        # mark_done
        orch.mark_done('jd', run_id=rid)
        # confirm_run
        orch.confirm_run(rid)
        # finish
        orch.finish(rid)

        # 读回 run.json，确认所有字段都持久化
        data = orch._load_run(rid)
        print(json.dumps({
            'run_id': data.get('run_id'),
            'encrypt_job_id': data.get('encrypt_job_id'),
            'confirmed': data.get('confirmed'),
            'user_confirmed_at': data.get('user_confirmed_at'),
            'steps_done': data.get('steps_done'),
            'last_step': data.get('last_step'),
            'finished': data.get('finished'),
            'finished_at': data.get('finished_at'),
        }, ensure_ascii=False))
    """
    r = _subproc_run(str(tmp_path), setup_src)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout.strip().splitlines()[-1])
    # 所有写入都正确持久化
    assert payload["run_id"] is not None
    assert payload["encrypt_job_id"] == "fake_sc12"
    assert payload["confirmed"] is True
    assert payload["user_confirmed_at"] is not None
    assert payload["steps_done"] == ["jd"]
    assert payload["last_step"] == "jd"
    assert payload["finished"] is True
    assert payload["finished_at"] is not None

    # 验证 run.json 物理位置是 runs/<run_id>/run.json
    run_json_path = os.path.join(
        tmp_path, "fake_sc12", "runs", payload["run_id"], "run.json"
    )
    assert os.path.exists(run_json_path), f"run.json 不在 {run_json_path}"
    with open(run_json_path, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["confirmed"] is True
    assert on_disk["steps_done"] == ["jd"]


def test_scenario_12b_run_json_filename_constant(tmp_path):
    """场景 12b：所有读写都通过 RUN_FILENAME = "run.json" 单一来源。"""
    src = """
        from run_orchestrator import RunOrchestrator
        # 类常量 RUN_FILENAME 是唯一来源
        print('FILENAME:' + RunOrchestrator.RUN_FILENAME)
    """
    r = _subproc_run(str(tmp_path), src)
    assert r.returncode == 0
    assert "FILENAME:run.json" in r.stdout
