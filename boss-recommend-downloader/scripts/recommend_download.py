#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推荐牛人简历下载脚本（patchright + fetch 版本）

特性：
- 启动前读 download_state.json，跳过 status=success / limit_hit 的候选人
- 成功简历：调 store.save_resume()，写入 _meta 并落到 resumes_master.json
- 本次新增简历落 runs/<run_id>/process/new_resumes.json
- 失败时区分：临时失败 → mark_failed；触发"上限" → mark_limit_hit 并立即停止
- "没有新候选人要下"时直接退出（不浪费调用）
"""
import sys
import os
import json
import time
import random
import argparse
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
import fix_encoding  # noqa: E402
from output_manager import JobOutputManager
from job_resume_store import JobResumeStore, candidate_key

from patchright.sync_api import sync_playwright
from human_interaction import human_browse_context


FETCH_JS = """async (params) => {
    try {
        const url = '/wapi/zpjob/view/geek/info?encryptGeekId=' + params.geek_id
            + '&encryptJobId=' + params.job_id
            + '&securityId=' + encodeURIComponent(params.sec_id);
        const resp = await fetch(url, {credentials: 'include'});
        const data = await resp.json();
        if (data.code !== 0 || !data.zpData) {
            return {ok: false, error: data.message || 'unknown'};
        }
        const zp = data.zpData;
        if (zp.blockDialog && zp.blockDialog.title) {
            return {ok: false, error: zp.blockDialog.title, limit: true};
        }
        const d = zp.geekDetailInfo || {};
        const b = d.geekBaseInfo || {};
        return {
            ok: true,
            name: b.name || '',
            age: b.ageDesc || '',
            degree: b.degreeCategory || '',
            work_years: b.workYearDesc || '',
            expectation: d.anonymousGeekExpect || d.geekExpect || null,
            work_experience: (d.geekWorkExpList || []).map(w => ({
                company: w.company || '',
                position: w.positionName || '',
                department: w.department || '',
                start: w.startDate || '',
                end: w.endDate || '',
                duration: w.workYearDesc || '',
                responsibility: w.responsibility || '',
                performance: w.performance || '',
                keywords: w.tagList || w.keywords || []
            })),
            project_experience: (d.geekProjExpList || []).map(p => ({
                name: p.projName || p.name || '',
                role: p.projRole || p.role || '',
                start: p.startDate || '',
                end: p.endDate || '',
                duration: p.projYearDesc || '',
                description: p.projDesc || p.description || '',
                achievement: p.projAchieve || p.achievement || ''
            })),
            education: (d.geekEduExpList || []).map(e => ({
                school: e.school || '',
                major: e.major || '',
                degree: e.degreeName || '',
                start: e.startDate || '',
                end: e.endDate || ''
            })),
            certifications: (d.geekCertificationList || []).map(c => c.certName || c.name || ''),
            skills: d.professionalSkill || '',
            active_status: b.activeTimeDesc || ''
        };
    } catch(e) {
        return {ok: false, error: e.message};
    }
}"""


def download_resumes(job_name, batch_number=None, max_count=None,
                     pause_every=5, pause_min=60, pause_max=120,
                     run_id=None, from_pool=False, encrypt_job_id=None):
    # 默认走 orchestrator，自动跟走上游创建的 run_id
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
    from run_orchestrator import RunOrchestrator
    from output_manager import resolve_encrypt_job_id
    encrypt_job_id = resolve_encrypt_job_id(encrypt_job_id)
    if not encrypt_job_id:
        raise ValueError("缺少 encrypt_job_id。\n  传 --encrypt-job-id，或设置 env BOSS_HR_ENCRYPT_JOB_ID")
    orch = RunOrchestrator(job_name, encrypt_job_id=encrypt_job_id)
    # 2026-07-30 重构：run_id 是数据边界，必须显式传（--run-id required=True）
    run_id = orch.bind_existing_run(run_id)
    # 用户确认守卫（2026-07-30）：未确认直接 SystemExit(20)
    if not orch.is_confirmed(run_id):
        print(json.dumps({
            "status": "blocked",
            "exit_code": 20,
            "run_id": run_id,
            "message": (f"用户尚未确认，禁止执行 Step 2。"
                         "Step 1 完成后必须等用户在 BOSS 调整完筛选条件，"
                         "然后调 shared/confirm_run.py --run-id {run_id} "
                         "--encrypt-job-id {encrypt_job_id} --job-name {job_name} "
                         "把 run.json.confirmed 切到 true。"),
        }, ensure_ascii=False))
        raise SystemExit(20)

    output = JobOutputManager(job_name, encrypt_job_id=encrypt_job_id, run_id=run_id)
    output.ensure_run_dir()
    store = JobResumeStore(job_name, encrypt_job_id=encrypt_job_id)

    # 异常护栏：脚本崩溃时若没写出 new_resumes.json，自动清空 run_dir
    import atexit
    _SAVED = False

    def _auto_prune():
        if not _SAVED and output.prune_if_empty():
            print(f'⚠️  本次 run 未产生 new_resumes.json，已清理: {output.run_dir}')

    atexit.register(_auto_prune)

    # 1) 选定输入：
    #    - from_pool=True：从 state/candidate_pool.json 取未尝试的（跨 run 通杀）
    #    - 否则：本次 run 的新增候选人（list 阶段刚写）
    if from_pool:
        pool = store.untried_geeks()
        # 截到 max_count
        if max_count:
            pool = pool[:max_count]
        # 写到系统临时目录（不污染 process/）
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix="boss_dl_input_", suffix=".json")
        os.close(fd)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(pool, f, ensure_ascii=False)
        input_path = tmp
    elif batch_number:
        input_path = output.get_process_path(f'batch_{batch_number}_ids.json')
    else:
        input_path = output.recommend_geek_ids_path

    if not os.path.exists(input_path):
        print(f'错误：候选人列表文件不存在：{input_path}')
        return [], []

    with open(input_path, 'r', encoding='utf-8') as f:
        geek_list = json.load(f)

    if not geek_list:
        print('本次 run 候选人为空（无需下载）')
        return [], []

    # 2) 提取 job_id
    gc0 = geek_list[0].get('geekCard', {}) if isinstance(geek_list[0], dict) else {}
    job_id = gc0.get('encryptJobId', '') or str(gc0.get('jobId', ''))
    if not job_id:
        job_id = store.encrypt_job_id

    # 3) 过滤：跳过已 success / limit_hit 的
    todo = []
    skipped = 0
    for g in geek_list:
        gid = g.get('encryptGeekId', '')
        if not gid:
            continue
        st = store.get_status(job_id, gid)
        if st in ('success', 'limit_hit'):
            skipped += 1
            continue
        todo.append(g)

    if skipped:
        print(f'⏭ 跳过已成功/触限的候选人 {skipped} 人（来自 state/download_state.json）')

    if not todo:
        print('✓ 本次 run 所有候选人都已成功下载或触限，无新增可下')
        return [], []

    if batch_number:
        print(f'[分批模式] 第 {batch_number} 批')
    print(f'岗位：{job_name}')
    print(f'岗位 ID：{job_id}')
    print(f'候选人：{len(geek_list)} 人（待下载 {len(todo)}，已跳 {skipped}）')
    if max_count:
        print(f'最大下载：{max_count}')

    new_resumes = []
    failed = []
    start_time = datetime.now()
    print(f'\n开始时间：{start_time.strftime("%H:%M:%S")}\n')

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://localhost:9222')
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if 'zhipin.com' not in page.url:
            print('导航到 BOSS 直聘...')
            page.goto('https://www.zhipin.com/web/chat/recommend',
                       wait_until='domcontentloaded', timeout=20000)
            time.sleep(3)

        try:
            iframe = page.query_selector('iframe')
            iframe_box = iframe.bounding_box() if iframe else None
        except Exception:
            iframe_box = None

        for i, g in enumerate(todo):
            if max_count and len(new_resumes) + len(failed) >= max_count:
                break

            geek_id = g.get('encryptGeekId', '')
            gcard = g.get('geekCard', {})
            sec_id = gcard.get('securityId', '')
            name = gcard.get('geekName', '')

            if not geek_id or not sec_id:
                failed.append({'name': name or 'Unknown', 'reason': '缺少 ID', 'encrypt_geek_id': ''})
                if geek_id:
                    store.mark_failed(job_id, geek_id, '缺少 securityId', run_id)
                continue

            elapsed = (datetime.now() - start_time).total_seconds() / 60
            print(f'[{elapsed:.1f}分钟] #{i + 1}: {name}...', end=' ', flush=True)

            try:
                human_browse_context(page, iframe_box)
            except Exception as e:
                print(f'  [上下文] 跳过:{str(e)[:40]}')

            try:
                result = page.evaluate(FETCH_JS, {
                    'geek_id': geek_id,
                    'job_id': job_id,
                    'sec_id': sec_id
                })

                if result.get('ok'):
                    # 注入 _meta
                    result['_meta'] = {
                        'candidate_key': candidate_key(job_id, geek_id),
                        'encrypt_job_id': job_id,
                        'encrypt_geek_id': geek_id,
                        'downloaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'first_run_id': run_id,
                    }
                    # 写入累计（去重）
                    if store.save_resume(result, job_id, geek_id, run_id):
                        new_resumes.append(result)
                        store.mark_success(job_id, geek_id, run_id)
                        print('OK')
                    else:
                        # 已存在（理论上不会到这里，前面已过滤，但保险）
                        print('已在累计')
                        store.mark_success(job_id, geek_id, run_id)
                else:
                    err = result.get('error', 'unknown')
                    # BOSS 触发查看上限的多种文案
                    is_limit = (
                        result.get('limit', False)
                        or ('上限' in err)
                        or ('查看已达' in err)
                        or ('今日已达' in err)
                        or ('limit reached' in err.lower())
                    )
                    print(f'失败：{err[:50]}')
                    failed.append({
                        'name': name,
                        'encrypt_geek_id': geek_id,
                        'reason': err[:80],
                        'limit_hit': is_limit,
                    })
                    if is_limit:
                        store.mark_limit_hit(job_id, geek_id, run_id)
                        print('已达查看上限，停止下载')
                        break
                    else:
                        store.mark_failed(job_id, geek_id, err, run_id)
            except Exception as e:
                print(f'异常：{str(e)[:50]}')
                failed.append({'name': name, 'encrypt_geek_id': geek_id, 'reason': str(e)[:80]})
                store.mark_failed(job_id, geek_id, str(e), run_id)

            if i < len(todo) - 1:
                time.sleep(random.uniform(5, 15))

            processed = i + 1
            if pause_every and processed % pause_every == 0 and i < len(todo) - 1:
                wait = random.uniform(pause_min, pause_max)
                print(f'  ⏸ 已处理 {processed} 份，节流等待 {wait:.0f} 秒...')
                time.sleep(wait)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() / 60

    print(f'\n{"=" * 40}')
    print(f'结束时间：{end_time.strftime("%H:%M:%S")}')
    print(f'总耗时：{duration:.1f} 分钟')
    print(f'本次新增：{len(new_resumes)} 份简历')
    print(f'本次失败：{len(failed)} 份')
    print(f'累计下载：{store.count_resumes()} 份')

    # 保存本次 run 的新增简历
    with open(output.new_resumes_path, 'w', encoding='utf-8') as f:
        json.dump(new_resumes, f, ensure_ascii=False, indent=2)
    print(f'本次新增 → {output.new_resumes_path}')

    # 失败列表
    with open(output.failed_resumes_path, 'w', encoding='utf-8') as f:
        json.dump(failed, f, ensure_ascii=False, indent=2)
    print(f'失败列表 → {output.failed_resumes_path}')

    _SAVED = True  # 成功落盘，保留 run
    orch.mark_done('download', run_id=run_id)  # 标记 download 步骤完成
    return new_resumes, failed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='推荐牛人简历下载（去重 + 三态）')
    parser.add_argument('--job-name', default='结构设计、研发工程师')
    parser.add_argument('--encrypt-job-id', default=None,
                        help='BOSS encryptJobId（推荐；新设计目录名依此定位；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）')
    parser.add_argument('--batch', type=int, default=None)
    parser.add_argument('--max', type=int, default=None)
    parser.add_argument('--pause-every', type=int, default=5)
    parser.add_argument('--pause-min', type=int, default=60)
    parser.add_argument('--pause-max', type=int, default=120)
    parser.add_argument('--run-id', required=True,
                        help='【必填】run_id 是数据边界。新任务先跑 boss_jd.py 创建 run；不传直接报错。')
    parser.add_argument('--from-pool', action='store_true',
                        help='从 state/candidate_pool.json 取未尝试的（跨 run 通杀）')

    args = parser.parse_args()
    download_resumes(args.job_name, args.batch, args.max,
                     pause_every=args.pause_every,
                     pause_min=args.pause_min,
                     pause_max=args.pause_max,
                     run_id=args.run_id,
                     from_pool=args.from_pool,
                     encrypt_job_id=args.encrypt_job_id)
