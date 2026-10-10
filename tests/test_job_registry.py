# -*- coding: utf-8 -*-
"""JobRegistry / JobOutputManager 路径定位测试（2026-07-29）

不验证：
- 真实 CDP 连接
"""
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "shared")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "resume-screener", "scripts")))

import output_manager
import job_registry


def test_registry_register_and_get():
    with tempfile.TemporaryDirectory() as t:
        output_manager.OUTPUT_ROOT = t
        job_registry.JOBS_REGISTRY_PATH = os.path.join(t, "jobs.json")
        reg = job_registry.JobRegistry()
        reg.register("job-A", name="岗位甲", company="A公司")

        got = reg.get("job-A")
        assert got["name"] == "岗位甲"
        assert got["company"] == "A公司"
        # 幂等：再注册不丢已有
        reg.register("job-A", name="岗位甲 v2")
        assert reg.get("job-A")["name"] == "岗位甲 v2"


def test_registry_by_name_reverse_lookup():
    with tempfile.TemporaryDirectory() as t:
        output_manager.OUTPUT_ROOT = t
        job_registry.JOBS_REGISTRY_PATH = os.path.join(t, "jobs.json")
        reg = job_registry.JobRegistry()
        reg.register("job-B", name="岗位乙")

        # 按名字反查 ID（迁移时用）
        hit = reg.by_name("岗位乙")
        assert hit and hit["encrypt_job_id"] == "job-B"


def test_output_manager_uses_encrypt_job_id_as_dir():
    """encrypt_job_id 优先 → 目录用 ID 而非 job_name"""
    with tempfile.TemporaryDirectory() as t:
        output_manager.OUTPUT_ROOT = t
        job_registry.JOBS_REGISTRY_PATH = os.path.join(t, "jobs.json")

        om = output_manager.JobOutputManager(
            job_name="结构设计、研发工程师",
            encrypt_job_id="DemoJobId000000000000000000001",
            run_id="2026-07-30_103000",  # 2026-07-30 重构：run_id 必填
        )
        # 目录名是 ID 不是中文
        assert om.job_dir.endswith("DemoJobId000000000000000000001")
        assert "线控" not in om.job_dir
        # 但 job_name 仍保留（用于 metadata/报告渲染）
        assert om.job_name == "结构设计、研发工程师"
        assert om.encrypt_job_id == "DemoJobId000000000000000000001"
        # jobs.json 自动登记
        meta = job_registry.JobRegistry().get("DemoJobId000000000000000000001")
        assert meta["name"] == "结构设计、研发工程师"


def test_output_manager_compat_legacy_job_name_only():
    """旧调用（仅 job_name）仍能工作 —— 用中文名作目录。

    2026-07-30 重构：run_id 必填。这里传 placeholder run_id 仅用于初始化
    （不影响路径定位，测试只验证路径和 metadata）。
    """
    with tempfile.TemporaryDirectory() as t:
        output_manager.OUTPUT_ROOT = t
        job_registry.JOBS_REGISTRY_PATH = os.path.join(t, "jobs.json")

        om = output_manager.JobOutputManager(job_name="某岗位", run_id="placeholder")
        assert om.job_dir.endswith("某岗位")
        assert om.encrypt_job_id is None  # 旧调用没传 ID


def test_output_manager_encrypt_job_id_only():
    """仅 encrypt_job_id：目录用 ID，job_name 退化"""
    with tempfile.TemporaryDirectory() as t:
        output_manager.OUTPUT_ROOT = t
        job_registry.JOBS_REGISTRY_PATH = os.path.join(t, "jobs.json")

        om = output_manager.JobOutputManager(
            encrypt_job_id="ZZZ-123",
            run_id="placeholder",
        )
        assert om.job_dir.endswith("ZZZ-123")
        # 没登记过，job_name 退化用 ID
        assert om.job_name == "ZZZ-123"


def test_resolve_job_dir_auto_registers():
    """resolve_job_dir 应在缺失时自动登记"""
    with tempfile.TemporaryDirectory() as t:
        output_manager.OUTPUT_ROOT = t
        job_registry.JOBS_REGISTRY_PATH = os.path.join(t, "jobs.json")

        path = job_registry.resolve_job_dir("job-X", name="新岗位")
        assert path.endswith("job-X")
        meta = job_registry.JobRegistry().get("job-X")
        assert meta["name"] == "新岗位"