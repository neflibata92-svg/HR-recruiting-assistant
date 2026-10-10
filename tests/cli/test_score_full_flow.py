# -*- coding: utf-8 -*-
"""boss-hr score：完整转换测试 + 损坏 JSON 测试（C2 收口）。

新增覆盖：
  - 写完最后一位 output → 再调 score → 调 collect → 全部 scored → 调 score_resumes
    → 返回 scoring_complete
  - 所有 output 都存在但有一份 JSON 损坏 → score 调 collect → collect 标 invalid
    → CLI 返回 waiting_llm + validation_error，不调 score_resumes

后者证明：合法性判断来自 collect_llm_scores.py，scoring_service 不预判。
"""
from __future__ import annotations
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


def _make_run(root: Path, eid: str, rid: str, job_name: str,
              *, confirmed: bool = True,
              new_resumes: list | None = None) -> Path:
    run_dir = root / eid / "runs" / rid
    process_dir = run_dir / "process"
    process_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid,
        "started_at": "2026-08-03 12:00:00",
        "confirmed": confirmed,
        "user_confirmed_at": "2026-08-03 12:01:00" if confirmed else None,
        "steps_done": ["jd", "download"],
        "last_step": "download",
        "finished": False, "finished_at": None,
    }, ensure_ascii=False), encoding="utf-8")
    (process_dir / "job_detail.json").write_text(json.dumps({
        "jobName": job_name, "encryptJobId": eid,
    }, ensure_ascii=False), encoding="utf-8")
    if new_resumes is not None:
        (process_dir / "new_resumes.json").write_text(
            json.dumps(new_resumes, ensure_ascii=False), encoding="utf-8")
    return run_dir


def _make_resume(name: str, geek_id: str) -> dict:
    return {
        "name": name,
        "degree": "本科", "work_years": "3 年",
        "work_experience": [], "project_experience": [],
        "education": [{"school": "辽宁工业大学", "major": "车辆工程", "degree": "本科"}],
        "_meta": {"encrypt_geek_id": geek_id, "encrypt_job_id": "test_eid_score"},
    }


def _valid_score(name: str) -> dict:
    return {
        "name": name, "school_name": "辽宁工业大学", "school": "辽宁工业大学",
        "work_years": "3 年", "match_type": "结构设计",
        "dims": {"edu": 0, "exp": 80, "skill": 70, "proj": 60, "major": 90},
        "highlights": ["亮点"], "concerns": [],
    }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid = "test_eid_full_flow"
    job_name = "full_flow_job"
    target = "2026-08-03_120000"

    resumes = [_make_resume(f"姓名{i}", f"gid_full_{i:03d}") for i in range(3)]
    _make_run(tmp_path, eid, target, job_name,
              confirmed=True, new_resumes=resumes)
    return tmp_path, eid, job_name, target


def _setup_outputs(tmp_path: Path, eid: str, target: str,
                  *, last_output_corrupt: bool = False) -> None:
    """跑 score 让 prepare 建 manifest，然后给每位候选人写 output。

    last_output_corrupt: 最后一位候选人的 output 写坏 JSON。
    """
    proc = _run_cli("score", "--job-name", "full_flow_job",
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    scoring_dir = tmp_path / eid / "runs" / target / "process" / "scoring"
    candidates = json.loads((scoring_dir / "manifest.json").read_text(encoding="utf-8"))["candidates"]
    for i, c in enumerate(candidates):
        output_path = scoring_dir / c["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if last_output_corrupt and i == len(candidates) - 1:
            output_path.write_text("not valid json {{{", encoding="utf-8")
        else:
            output_path.write_text(
                json.dumps(_valid_score(c["name"]), ensure_ascii=False),
                encoding="utf-8")


# ============================================================
# 完整转换测试：写完最后 output → score → collect → score_resumes → scoring_complete
# ============================================================

def test_full_flow_last_output_to_scoring_complete(workspace):
    """最完整的端到端：
      1) 写完最后一位 output
      2) 再调 boss-hr score
      3) 应自动调 collect_llm_scores
      4) collect 全 scored → 调 score_resumes
      5) 返回 scoring_complete
    """
    tmp_path, eid, job_name, target = workspace
    _setup_outputs(tmp_path, eid, target, last_output_corrupt=False)

    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    p = json.loads(_decode(proc.stdout))
    # 完整链：collect → score_resumes → scoring_complete
    assert p["status"] == "scoring_complete"
    assert p["data"]["scored"] == 3
    assert p["data"]["screening_results_file"].endswith("screening_results.json")
    assert p["next_action"] == "report"

    # 验证 collect 与 score_resumes 都真跑了（看文件存在 + 时间戳顺序）
    process_dir = tmp_path / eid / "runs" / target / "process"
    llm = process_dir / "_llm_scores.json"
    screening = process_dir / "screening_results.json"
    assert llm.is_file(), "collect 没写 _llm_scores.json"
    assert screening.is_file(), "score_resumes 没写 screening_results.json"
    assert llm.stat().st_mtime_ns <= screening.stat().st_mtime_ns, \
        "顺序错：_llm_scores.json 应早于 screening_results.json"


# ============================================================
# 损坏 JSON 测试：collect 是唯一合法性来源
# ============================================================

def test_corrupt_output_triggers_collect_invalid_path(workspace):
    """所有 output 文件存在（has_output=True），
    但其中一份 JSON 损坏 → collect 应报 invalid →
    CLI 返回 waiting_llm + validation_error，不调 score_resumes。

    证明：合法性判断来自 collect_llm_scores.py，
    不是 scoring_service 自己预判（已删 _validate_score）。
    """
    tmp_path, eid, job_name, target = workspace
    _setup_outputs(tmp_path, eid, target, last_output_corrupt=True)

    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    p = json.loads(_decode(proc.stdout))
    # 路径：collect 标 invalid → waiting_llm
    assert p["status"] == "waiting_llm"
    assert p["data"]["candidate_id"] is not None
    assert p["data"]["validation_error"] is not None
    assert "JSON" in p["data"]["validation_error"] or "解析" in p["data"]["validation_error"]
    # 关键：screening_results.json 不应被写（score_resumes 未被调）
    screening = tmp_path / eid / "runs" / target / "process" / "screening_results.json"
    assert not screening.exists(), \
        "collect 标 invalid 后不应触发 score_resumes"


def test_all_outputs_present_calls_collect(workspace):
    """所有 output 文件都存在（has_output=True）→ score 调 collect；
    collect 成功（无 invalid / missing）→ 调 score_resumes → scoring_complete。"""
    tmp_path, eid, job_name, target = workspace
    _setup_outputs(tmp_path, eid, target, last_output_corrupt=False)

    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    p = json.loads(_decode(proc.stdout))
    assert p["status"] == "scoring_complete"
    # 验证 manifest.status 全是 scored（collect 写的）
    scoring_dir = tmp_path / eid / "runs" / target / "process" / "scoring"
    manifest = json.loads((scoring_dir / "manifest.json").read_text(encoding="utf-8"))
    for c in manifest["candidates"]:
        assert c["status"] == "scored", f"候选人 {c['geek_id']} 应 scored，实际 {c['status']}"


def test_empty_output_treated_as_not_scored(workspace):
    """output 文件存在但 size=0 → has_output=False → 走 waiting_llm。

    证明 scoring_service 不读 JSON 内容，只看 size>0。
    """
    tmp_path, eid, job_name, target = workspace
    # 先 setup 拿到 scoring_dir 结构
    proc = _run_cli("score", "--job-name", job_name,
                    "--encrypt-job-id", eid, "--run-id", target,
                    env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc.returncode == 0
    scoring_dir = tmp_path / eid / "runs" / target / "process" / "scoring"
    candidates = json.loads((scoring_dir / "manifest.json").read_text(encoding="utf-8"))["candidates"]
    # 给 2/3 写正常 output，给最后一位写空文件
    for i, c in enumerate(candidates):
        output_path = scoring_dir / c["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if i == len(candidates) - 1:
            output_path.write_text("", encoding="utf-8")  # 空文件
        else:
            output_path.write_text(
                json.dumps(_valid_score(c["name"]), ensure_ascii=False),
                encoding="utf-8")

    # 跑 score：空文件候选人应被当 waiting_llm
    proc2 = _run_cli("score", "--job-name", job_name,
                     "--encrypt-job-id", eid, "--run-id", target,
                     env_extra={"BOSS_HR_OUTPUT_DIR": str(tmp_path)})
    assert proc2.returncode == 0
    p = json.loads(_decode(proc2.stdout))
    assert p["status"] == "waiting_llm"
    assert p["data"]["remaining"] == 1  # 空文件候选人
    assert p["data"]["candidate_id"] is not None
