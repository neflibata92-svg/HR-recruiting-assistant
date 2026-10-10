# -*- coding: utf-8 -*-
"""招聘者岗位目录（2026-07-31 新增，替代 boss_agent_cli 的 hr jobs list 职责）

设计动机：
  boss_agent_cli 提供 `boss --role recruiter hr jobs list` 拿招聘者岗位列表。
  本模块通过 patchright 连 CDP，在已登录的浏览器 context 里 fetch
  /wapi/zpjob/job/chatted/jobList（GET），复用浏览器 TLS 指纹 + 自动带 cookie，
  不依赖 stoken/手写 session.enc 同步。

输出 schema 与 `boss.exe hr jobs list` 完全一致，方便老脚本无缝切换：
  {
    'ok': bool,
    'command': 'recruiter-jobs-list',
    'schema_version': '1.0',
    'data': [{'encryptJobId', 'jobId', 'jobName', 'description', ...}, ...],
    'pagination': None,
    'error': {'code': str, 'message': str} | None,
    'hints': None,
  }

用法：
  from shared.recruiter_job_catalog import (
      list_jobs, resolve_recruiter_job, fetch_job_detail,
  )

  result = list_jobs()
  if not result['ok']:
      raise RuntimeError(result['error'])

  job = resolve_recruiter_job('结构设计、研发工程师')
  # → {'encryptJobId': '...', 'jobId': 111222333, 'jobName': '...', ...}
"""
from __future__ import annotations
import json
import sys
from typing import Any

# —— BOSS 内部 API 常量（从 boss_agent_cli/api/recruiter.yaml 提取，保留可读 URL） ——
BASE_URL = "https://www.zhipin.com"
JOB_LIST_URL = f"{BASE_URL}/wapi/zpjob/job/chatted/jobList"
JOB_EDIT_URL = f"{BASE_URL}/wapi/zpjob/job/edit"

# 默认 User-Agent（与 recruiter.yaml default_headers 一致）
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

SCHEMA_VERSION = "1.0"


# ============================================================
# 浏览器内 fetch：通过 page.evaluate(fetch(...)) 复用浏览器 TLS + cookie
# ============================================================

def _fetch_via_browser(page, url: str, method: str = "GET", **kwargs) -> dict[str, Any]:
    """在浏览器 page 上下文里调 fetch，返回 {'status': int, 'headers': {...}, 'body': str}。

    不走浏览器外的 HTTP 请求 —— 复用 BOSS 域 TLS 指纹 + 自动带 cookie，
    避免触发 BOSS 风控 + 不需要单独同步 session.enc。

    超时 15s（BOSS 后端通常 < 3s，15s 足够）。
    """
    args = {"url": url, "method": method, **kwargs}
    args_json = json.dumps(args)
    script = r"""
    async ({url, method, headers, body}) => {
      try {
        const opts = {method, credentials: 'include', headers: headers || {}};
        if (body) opts.body = body;
        const r = await fetch(url, opts);
        const text = await r.text();
        const out = {};
        r.headers.forEach((v, k) => { out[k] = v; });
        return {ok: true, status: r.status, headers: out, body: text};
      } catch (e) {
        return {ok: false, error: e.message || String(e)};
      }
    }
    """
    raw = page.evaluate(script, args)
    return raw


# ============================================================
# 公开 API
# ============================================================

def list_jobs(cdp_url: str = "http://localhost:9222") -> dict[str, Any]:
    """通过 CDP 浏览器 fetch 招聘者岗位列表。

    返回与 boss.exe hr jobs list 一致的 schema（见模块 docstring）。

    失败情形：
      - CDP 不可达 → ok=False, error.code='CDP_UNREACHABLE'
      - zp_at/wt2/bst 缺失 → ok=False, error.code='AUTH_REQUIRED'
      - BOSS 后端返回非 0 → ok=False, error.code='BOSS_API_ERROR'
      - 响应解析失败 → ok=False, error.code='PARSE_ERROR'
      - 成功但列表为空 → ok=True, data=[]
    """
    from cdp_preflight import connect_cdp, check_login

    try:
        session = connect_cdp(cdp_url)
    except Exception as e:
        return _error("CDP_UNREACHABLE", str(e))

    try:
        state = check_login(session)
        if not state["logged_in"]:
            return _error(
                "AUTH_REQUIRED",
                f"缺少关键 cookie: zp_at={state['cookies']['zp_at']} "
                f"wt2={state['cookies']['wt2']} bst={state['cookies']['bst']}",
                current_url=state["current_url"],
                page_kind=state["page_kind"],
            )

        # 用浏览器内 fetch（带真实 cookie）
        raw = _fetch_via_browser(
            session.page,
            JOB_LIST_URL,
            method="GET",
            headers={
                "User-Agent": DEFAULT_UA,
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{BASE_URL}/web/chat/index",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

        if not raw.get("ok"):
            return _error("FETCH_ERROR", raw.get("error", "unknown"))

        status = raw.get("status", 0)
        body = raw.get("body", "")

        if status != 200:
            return _error(
                "BOSS_HTTP_ERROR",
                f"HTTP {status}: {body[:200]}",
                http_status=status,
            )

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as e:
            return _error("PARSE_ERROR", f"BOSS 响应非 JSON: {body[:200]} ({e})")

        # BOSS 响应 schema: {"code": 0, "message": "success", "zpData": {"list": [...]}}
        # 但很多 endpoint 用 zprelation/zpjob 包装。这里以 zhipin 实际响应为准。
        # 老 boss.exe 输出已经是 normalize 过的 list[...]，所以这里要做 normalize。
        data = _normalize_jobs_response(parsed)
        if data is None:
            return _error("PARSE_ERROR", f"BOSS 响应无法解析: {json.dumps(parsed)[:200]}")

        return {
            "ok": True,
            "command": "recruiter-jobs-list",
            "schema_version": SCHEMA_VERSION,
            "data": data,
            "pagination": None,
            "error": None,
            "hints": None,
        }
    finally:
        session.disconnect()


def _normalize_jobs_response(parsed: dict) -> list[dict] | None:
    """把 BOSS 各种可能形态的响应 normalize 成 [{encryptJobId, jobId, jobName, ...}, ...]。

    BOSS 实际 schema（已验证）：{"code":0,"zpData":[...]}（zpData 直接是数组！）
    老 boss.exe 输出是已经 normalize 过的 {"data":[...]}。
    """
    if not isinstance(parsed, dict):
        return None
    code = parsed.get("code", 0)
    if code != 0:
        return None  # 非 0 视为失败
    # 尝试多种包装层（按可能性从高到低）
    for path in [
        ("zpData",),               # 实际 BOSS 响应：zpData 直接是 list
        ("data",),                 # 老 boss.exe 输出（已经是 list）
        ("zpData", "list"),        # 防御：万一哪天 BOSS 又包一层
        ("data", "list"),
        ("result", "list"),
    ]:
        node = parsed
        ok = True
        for k in path:
            if not isinstance(node, dict) or k not in node:
                ok = False
                break
            node = node[k]
        if ok and isinstance(node, list):
            return node
    return None


def _error(code: str, message: str, **extra) -> dict[str, Any]:
    return {
        "ok": False,
        "command": "recruiter-jobs-list",
        "schema_version": SCHEMA_VERSION,
        "data": None,
        "pagination": None,
        "error": {"code": code, "message": message, **extra},
        "hints": None,
    }


def resolve_recruiter_job(query: str, cdp_url: str = "http://localhost:9222") -> dict[str, Any] | None:
    """根据 query 定位岗位。query 可以是：
      - encryptJobId（如 'DemoJobId000000000000000000001'）→ 精确
      - 数字 jobId（如 '111222333'）→ 精确
      - 岗位名 → 精确优先，模糊兜底（含 query 子串的第一个）

    返回首个匹配的 {'encryptJobId', 'jobId', 'jobName', 'address', 'salaryDesc', ...}，
    无匹配返回 None。
    """
    result = list_jobs(cdp_url)
    if not result["ok"]:
        raise RuntimeError(f"list_jobs 失败: {result['error']}")

    return _resolve_in_list(query, result["data"])


def _resolve_in_list(query: str, jobs: list[dict]) -> dict[str, Any] | None:
    """从岗位列表中找匹配。匹配规则：
      1) encryptJobId 精确
      2) jobId 精确（str/int 兼容）
      3) jobName 精确
      4) jobName 含 query 子串（模糊，第一个匹配）
    """
    if not query:
        return None

    exact_eid = None
    exact_jid = None
    exact_name = None
    partial = None

    for job in jobs:
        eid = job.get("encryptJobId", "") or ""
        jid_raw = job.get("jobId", "") or ""
        jid = str(jid_raw)
        name = job.get("jobName", "") or ""

        if query == eid:
            exact_eid = job
            break  # eid 是最权威的 unique id，立刻返回
        if query == jid and exact_jid is None:
            exact_jid = job
        if query == name and exact_name is None:
            exact_name = job
        if query in name and partial is None:
            partial = job

    return exact_eid or exact_jid or exact_name or partial


def fetch_job_detail(encrypt_job_id: str, cdp_url: str = "http://localhost:9222") -> dict[str, Any]:
    """通过 CDP fetch /wapi/zpjob/job/edit?encJobId=...&lid=&encAtsJobId=，返回 BOSS 原始 JSON。

    这跟 `boss_jd.py` 里通过浏览器导航 web/chat/job/edit 抓 iframe DOM 的方式是两套：
      - 本函数：拿结构化 JSON（字段有限，没有富文本描述）
      - boss_jd.py：拿完整表单 DOM（含职位描述富文本 + 关键词 + 福利）

    业务侧一般用 boss_jd.py 拿完整 JD；本函数用于「快速校验岗位存在」或「辅助对比」。
    """
    from cdp_preflight import connect_cdp, check_login

    try:
        session = connect_cdp(cdp_url)
    except Exception as e:
        return _error("CDP_UNREACHABLE", str(e))

    try:
        state = check_login(session)
        if not state["logged_in"]:
            return _error("AUTH_REQUIRED", "缺少 zp_at/wt2/bst cookie")

        url = f"{JOB_EDIT_URL}?encJobId={encrypt_job_id}&lid=&encAtsJobId="
        raw = _fetch_via_browser(
            session.page,
            url,
            method="GET",
            headers={
                "User-Agent": DEFAULT_UA,
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{BASE_URL}/web/frame/job/edit?jobversion=9921&encryptId={encrypt_job_id}&jobCreateSource=0&enterSource=6",
            },
        )

        if not raw.get("ok"):
            return _error("FETCH_ERROR", raw.get("error", "unknown"))
        if raw.get("status") != 200:
            return _error("BOSS_HTTP_ERROR", f"HTTP {raw.get('status')}")

        try:
            return {"ok": True, "data": json.loads(raw.get("body", "")), "command": "recruiter-jobs-detail"}
        except json.JSONDecodeError as e:
            return _error("PARSE_ERROR", f"BOSS 响应非 JSON: {e}")
    finally:
        session.disconnect()


__all__ = [
    "list_jobs",
    "resolve_recruiter_job",
    "fetch_job_detail",
    "JOB_LIST_URL",
    "JOB_EDIT_URL",
    "BASE_URL",
]