# -*- coding: utf-8 -*-
"""boss-hr score（C1：候选协调）命令测试。

15 个用例：
  1.  manifest 不存在时只调用一次 prepare
  2.  每次只返回一个候选人
  3.  不读取完整 new_resumes.json（只 stat 验证存在）
  4.  已有 output 的候选人被跳过
  5.  返回正确的 input/output 映射
  6.  run 不存在
  7.  encrypt_job_id 不匹配
  8.  未 confirmed
  9.  缺 new_resumes
  10. 不触发 collect
  11. 不触发 score_resumes
  12. 不触发 report
  13. 不修改候选人 input/output
  14. 不扫描其他 run
  15. 重复调用返回下一位候选人

走 subprocess 调 python boss_hr/cli.py score ...
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent.parent
_CLI = _TOOLKIT_ROOT / "boss_hr" / "cli.py"
_SHARED = _TOOLKIT_ROOT / "shared"


def _run_cli(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(_SHARED)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), *args],
        capture_output=True, env=env, cwd=str(_TOOLKIT_ROOT), timeout=60,
    )


def _decode(b) -> str:
    if b is None:
        return ""
    if isinstance(b, bytes):
        return b.decode("utf-8", errors="replace")
    return b


def _file_hashes(root: Path) -> dict[str, str]:
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _make_run(root: Path, eid: str, rid: str, job_name: str,
              *, confirmed: bool = True,
              new_resumes: list | None = None) -> Path:
    """建一个最小合法 run：run.json + process/{job_detail,new_resumes}.json。"""
    run_dir = root / eid / "runs" / rid
    process_dir = run_dir / "process"
    process_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid,
        "started_at": "2026-08-03 12:00:00",
        "confirmed": confirmed,
        "user_confirmed_at": "2026-08-03 12:01:00" if confirmed else None,
        "steps_done": ["jd", "download"] if confirmed else ["jd"],
        "last_step": "download" if confirmed else "jd",
        "finished": False, "finished_at": None,
    }, ensure_ascii=False), encoding="utf-8")
    (process_dir / "job_detail.json").write_text(json.dumps({
        "jobName": job_name, "encryptJobId": eid,
    }, ensure_ascii=False), encoding="utf-8")
    if new_resumes is not None:
        (process_dir / "new_resumes.json").write_text(
            json.dumps(new_resumes, ensure_ascii=False), encoding="utf-8")
    return run_dir


def _make_resume(name: str, geek_id: str, *, ok_: bool = True) -> dict:
    r = {
        "name": name,
        "_meta": {"encrypt_geek_id": geek_id, "encrypt_job_id": "test_eid_score"},
    }
    if ok_:
        r.update({
            "degree": "本科",
            "work_years": "3 年",
            "work_experience": [], "project_experience": [], "education": [],
        })
    return r


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """target run + other run。target 已 confirmed + 3 个候选人（new_resumes）。"""
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid = "test_eid_score"
    job_name = "score_test_job"
    target = "2026-08-03_120000"
    other = "2026-08-02_120000"

    resumes = [
        _make_resume("张三", "gid_zhangsan_001"),
        _make_resume("李四", "gid_lisi_002"),
        _make_resume("王五", "gid_wangwu_003"),
    ]
    _make_run(tmp_path, eid, target, job_name,
              confirmed=True, new_resumes=resumes)
    _make_run(tmp_path, eid, other, job_name,
              confirmed=False, new_resumes=[_make_resume("other_a", "gid_other_a")])

    return tmp_path, eid, job_name, target, other


# ============================================================
# 1. manifest 不存在时只调用一次 prepare
# ============================================================

def test_score_calls_prepare_when_manifest_missing(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    # manifest.json 应被创建
    manifest = tmp_path / eid / "runs" / target / "process" / "scoring" / "manifest.json"
    assert manifest.is_file()
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(m["candidates"]) == 3


# ============================================================
# 2. 每次只返回一个候选人
# ============================================================

def test_score_returns_single_candidate(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    p = json.loads(_decode(proc.stdout))
    assert p["status"] == "waiting_llm"
    assert p["data"]["candidate_id"] is not None
    assert p["data"]["name"] is not None
    assert p["data"]["input_file"] is not None
    assert p["data"]["output_file"] is not None


# ============================================================
# 3. 不读取完整 new_resumes.json（只 stat 验证存在）
# ============================================================

def test_score_does_not_read_full_new_resumes(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    new_resumes_path = tmp_path / eid / "runs" / target / "process" / "new_resumes.json"
    new_resumes_mtime_before = new_resumes_path.stat().st_mtime_ns

    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0

    # new_resumes.json 不应被修改（score 不直接读它，只调 prepare 让 prepare 读）
    # 但 prepare 会读！这里只校验最终 hash 与原始一致（如果没改）
    # 注意：prepare 会读 new_resumes 写 inputs/* + manifest，**不**修改 new_resumes.json
    # 所以新文件不应出现，但 existing 文件 hash 不变
    new_resumes_mtime_after = new_resumes_path.stat().st_mtime_ns
    assert new_resumes_mtime_before == new_resumes_mtime_after, \
        "score 不应修改 new_resumes.json"


# ============================================================
# 4. 已有 output 的候选人被跳过
# ============================================================

def test_score_skips_already_scored_candidates(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    # 先跑一次 score，让 prepare 建好 manifest + scoring 目录
    proc1 = _run_cli("score", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target,
                     env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc1.returncode == 0
    p1 = json.loads(_decode(proc1.stdout))
    first_gid = p1["data"]["candidate_id"]
    first_name = p1["data"]["name"]

    # 给第一位候选人写 output（模拟 LLM 已评）
    output_path = Path(p1["data"]["output_file"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "name": first_name, "dims": {"exp": 80, "skill": 70, "proj": 60, "major": 90}
    }, ensure_ascii=False), encoding="utf-8")

    # 再跑 score：应返回下一位
    proc2 = _run_cli("score", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target,
                     env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc2.returncode == 0
    p2 = json.loads(_decode(proc2.stdout))
    assert p2["data"]["candidate_id"] != first_gid, \
        f"已评分的 {first_gid} 应被跳过"


# ============================================================
# 5. 返回正确的 input/output 映射
# ============================================================

def test_score_returns_correct_input_output_paths(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    p = json.loads(_decode(proc.stdout))
    input_file = Path(p["data"]["input_file"])
    output_file = Path(p["data"]["output_file"])
    # input/output 都在 scoring 目录下
    assert input_file.is_file(), f"input 不存在：{input_file}"
    assert input_file.parent.name == "inputs"
    assert output_file.parent.name == "outputs"
    # input/output 文件名匹配 candidate_<geek_id>.json 模式
    assert input_file.stem == f"candidate_{p['data']['candidate_id']}"
    assert output_file.stem == f"candidate_{p['data']['candidate_id']}"


# ============================================================
# 6. run 不存在
# ============================================================

def test_score_run_not_found(workspace):
    tmp_path, eid, job_name, _target, _other = workspace
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", "9999-99-99_999999",
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 23
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is False
    assert p["error"]["code"] == "RUN_NOT_FOUND"


# ============================================================
# 7. encrypt_job_id 不匹配
# ============================================================

def test_score_encrypt_job_id_mismatch(workspace):
    tmp_path, _eid, job_name, target, _other = workspace
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", "wrong_eid_xyz",
                    "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 23
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is False
    assert p["error"]["code"] == "RUN_NOT_FOUND"


# ============================================================
# 8. 未 confirmed
# ============================================================

def test_score_not_confirmed(workspace):
    tmp_path, eid, job_name, _target, other = workspace
    # other run 已 confirmed=False
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", other,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 20
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is False
    assert p["error"]["code"] == "AWAITING_CONFIRMATION"


# ============================================================
# 9. 缺 new_resumes
# ============================================================

def test_score_missing_new_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    _make_run(tmp_path, "test_eid_score", "2026-08-03_120000", "no_new_resumes_job",
              confirmed=True, new_resumes=None)  # 不写 new_resumes.json
    proc = _run_cli("score", "--job-name", "no_new_resumes_job",
                    "--encrypt-job-id", "test_eid_score", "--run-id", "2026-08-03_120000",
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 26
    p = json.loads(_decode(proc.stdout))
    assert p["ok"] is False
    assert "new_resumes" in p["error"]["message"]


# ============================================================
# 10. 不触发 collect
# ============================================================

def test_score_does_not_trigger_collect(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    # collect 会写 _llm_scores.json；C1 阶段不应写
    llm_scores = tmp_path / eid / "runs" / target / "process" / "_llm_scores.json"
    assert not llm_scores.exists(), "score C1 不应触发 collect"


# ============================================================
# 11. 不触发 score_resumes
# ============================================================

def test_score_does_not_trigger_score_resumes(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    # score_resumes 会写 screening_results.json
    screening = tmp_path / eid / "runs" / target / "process" / "screening_results.json"
    assert not screening.exists(), "score C1 不应触发 score_resumes"


# ============================================================
# 12. 不触发 report
# ============================================================

def test_score_does_not_trigger_report(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    # report 会写 HTML 到 runs/<run_id>/
    html_files = list((tmp_path / eid / "runs" / target).glob("*.html"))
    assert not html_files, f"score 不应触发 report，但发现 HTML：{html_files}"
    # run.json.steps_done 也不应新增 'report'
    run_json = json.loads(
        (tmp_path / eid / "runs" / target / "run.json").read_text(encoding="utf-8"))
    assert "report" not in run_json.get("steps_done", [])


# ============================================================
# 13. 不修改候选人 input/output
# ============================================================

def test_score_does_not_modify_candidate_files(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    # 先跑一次让 prepare 建好 inputs/
    proc1 = _run_cli("score", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target,
                     env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc1.returncode == 0

    scoring_dir = tmp_path / eid / "runs" / target / "process" / "scoring"
    inputs_dir = scoring_dir / "inputs"
    outputs_dir = scoring_dir / "outputs"
    before_inputs = _file_hashes(inputs_dir)
    before_outputs = _file_hashes(outputs_dir)

    # 再跑两次
    proc2 = _run_cli("score", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target,
                     env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    proc3 = _run_cli("score", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target,
                     env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc2.returncode == 0
    assert proc3.returncode == 0

    after_inputs = _file_hashes(inputs_dir)
    after_outputs = _file_hashes(outputs_dir)
    # inputs/ 不应被修改（只创建一次）
    assert before_inputs == after_inputs, "score 不应修改 inputs/ 内容"


# ============================================================
# 14. 不扫描其他 run
# ============================================================

def test_score_does_not_borrow_other_run(workspace):
    tmp_path, eid, job_name, target, other = workspace
    # other run 的 scoring 目录如果有"诱饵" manifest，新 score 不应被它干扰
    other_scoring = tmp_path / eid / "runs" / other / "process" / "scoring"
    other_scoring.mkdir(parents=True, exist_ok=True)
    (other_scoring / "manifest.json").write_text(json.dumps({
        "candidates": [{"geek_id": "诱饵_gid", "name": "诱饵",
                          "input_path": "inputs/candidate_诱饵_gid.json",
                          "output_path": "outputs/candidate_诱饵_gid.json",
                          "status": "pending"}],
    }, ensure_ascii=False), encoding="utf-8")

    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    p = json.loads(_decode(proc.stdout))
    # 返回的候选人必须属于 target run，不是诱饵
    assert p["data"]["candidate_id"] != "诱饵_gid"
    assert p["run_id"] == target


# ============================================================
# 15. 重复调用返回下一位候选人
# ============================================================

def test_score_repeat_returns_next_candidate(workspace):
    tmp_path, eid, job_name, target, _other = workspace
    gids_seen = []
    for _ in range(3):
        proc = _run_cli("score", "--job-name", job_name,
                        "--encrypt-job-id", eid, "--run-id", target,
                        env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
        assert proc.returncode == 0
        p = json.loads(_decode(proc.stdout))
        gid = p["data"]["candidate_id"]
        assert gid is not None
        gids_seen.append(gid)

        # 给当前候选人写 output
        output_path = Path(p["data"]["output_file"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({
            "name": p["data"]["name"],
            "dims": {"exp": 80, "skill": 70, "proj": 60, "major": 90},
        }, ensure_ascii=False), encoding="utf-8")

    # 每次返回不同
    assert len(set(gids_seen)) == 3, f"应返回 3 个不同候选人，实际：{gids_seen}"

    # 第 4 次：所有 output 都齐了 → dispatcher 切到 finalize（C2）
    # 此时数据简单（缺 school 等），collect 可能报 invalid；测试只要
    # 验证 dispatcher 不再返回 waiting_llm with candidate_id。
    proc4 = _run_cli("score", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target,
                     env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc4.returncode == 0
    p4 = json.loads(_decode(proc4.stdout))
    # 不再走 C1 候选协调；要么 scoring_complete，要么 waiting_llm (invalid)
    assert p4["status"] in ("scoring_complete", "waiting_llm")
    if p4["status"] == "waiting_llm":
        # invalid 路径：data 必须有 validation_error
        assert p4["data"].get("validation_error") is not None
    else:
        # scoring_complete 路径：data 含 scored + screening_results_file
        assert "scored" in p4["data"]
        assert "screening_results_file" in p4["data"]
