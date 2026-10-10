#!/usr/bin/env python3
"""
推荐牛人候选人列表获取脚本（支持分批）
Step 1: 通过浏览器滚动拦截 API 获取候选人 ID 列表

分批模式：
  --batch-size 25 --batch 1  收集前25人，保存batch_1_ids.json
  --batch-size 25 --batch 2  继续滚动，收集下25人，保存batch_2_ids.json
  ...
  不刷新页面，顺序固定。batch 1 会打开页面，batch 2+ 连接已有页面继续滚动。

使用统一输出路径：~/Desktop/boss-hr-output/<岗位名>/process/
"""

import sys
import os

# 添加 shared 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
import fix_encoding  # noqa: E402  # 强制 Windows UTF-8 stdout
from output_manager import JobOutputManager
from run_orchestrator import RunOrchestrator

from patchright.sync_api import sync_playwright
from human_interaction import human_scroll
import time
import json
import random
import argparse


def get_recommend_candidates(job_name='机械工程师', max_candidates=None,
                             batch_size=None, batch_number=None,
                             run_id=None, encrypt_job_id=None):
    """
    获取推荐牛人候选人列表

    Args:
        job_name:        岗位名称（jobs.json metadata）
        max_candidates:  最大获取数量（None 为全部，与分批互斥）
        batch_size:      每批收集人数（分批模式）
        batch_number:    第几批，从 1 开始（分批模式）
        run_id:          本次 run ID（必填；数据边界）
        encrypt_job_id:  BOSS encryptJobId（推荐；env BOSS_HR_ENCRYPT_JOB_ID 可兑底）
    """
    # 2026-07-28 修复：跟走 RunOrchestrator，让 list 落到跟前面 step 同一 run_id，
    #   避免每次 skill 默认开新 run 目录。
    from output_manager import resolve_encrypt_job_id
    encrypt_job_id = resolve_encrypt_job_id(encrypt_job_id)
    if not encrypt_job_id:
        raise ValueError("缺少 encrypt_job_id。\n  传 --encrypt-job-id，或设置 env BOSS_HR_ENCRYPT_JOB_ID")
    orch = RunOrchestrator(job_name, encrypt_job_id=encrypt_job_id)
    # 2026-07-30 重构：run_id 是数据边界，必须显式传。
    # --run-id 已设为 required=True，argparse 会保证 run_id 非空。
    # bind_existing_run 校验 run_dir 存在 + encrypt_job_id 匹配，不通过报错。
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

    # 分批状态文件
    state_path = output.get_process_path('batch_state.json')

    # 读取已有状态（batch 2+ 需要）
    seen_ids = set()
    all_geeks = []
    prev_total = 0

    if batch_number and batch_number > 1 and os.path.exists(state_path):
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        seen_ids = set(state.get('seen_ids', []))
        prev_total = state.get('total_collected', 0)
        print(f'[分批模式] 第 {batch_number} 批，前 {prev_total} 人已收集，继续滚动...')

    # 本批收集的新候选人
    batch_geeks = []

    def on_response(resp):
        """拦截 geek/list API 响应"""
        if 'geek/list' in resp.url:
            try:
                data = resp.json()
                for g in data.get('zpData', {}).get('geekList', []):
                    gid = g.get('encryptGeekId', '')
                    if gid and gid not in seen_ids:
                        seen_ids.add(gid)
                        all_geeks.append(g)
                        batch_geeks.append(g)
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://localhost:9222')
        ctx = browser.contexts[0]
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()

        pg.on('response', on_response)

        if batch_number and batch_number > 1:
            # batch 2+：连接已有页面，不重新加载
            print('连接已有推荐牛人页面（不刷新）...')
            time.sleep(3)
        else:
            # batch 1 / 普通模式：先检查当前页面 URL，避免覆盖用户在 BOSS 调好的筛选条件
            current_url = (pg.url or '')
            if 'zhipin.com/web/chat/recommend' in current_url:
                # 当前已在推荐牛人页面 → 复用用户在 BOSS 调整好的筛选条件
                print(f'当前已在推荐牛人页面（{current_url}），不刷新直接复用用户的筛选条件...')
                time.sleep(3)
            else:
                # 不在 → 才 goto（保留"冷启动"能力）
                print('打开推荐牛人页面...')
                pg.goto('https://www.zhipin.com/web/chat/recommend',
                        wait_until='networkidle', timeout=60000)
                time.sleep(5)

        # 等待 iframe 出现（最多 15 秒）
        iframe = None
        for wait in range(15):
            try:
                iframe = pg.query_selector('iframe')
                if iframe:
                    break
            except Exception:
                pass
            time.sleep(1)

        if not iframe:
            print('错误：未找到 iframe，请确认已登录 BOSS 直聘招聘者账号')
            print('当前页面 URL:', pg.url)
            return

        frame = iframe.content_frame()
        iframe_box = iframe.bounding_box()

        # 确定本批目标数量
        if batch_size and batch_number:
            target = batch_size
            print(f'本批目标：收集 {target} 位新候选人')
        else:
            target = max_candidates  # 普通模式

        # 滚动
        no_new_count = 0
        while no_new_count < 5:
            # 分批模式：达到本批目标就停
            if target and len(batch_geeks) >= target:
                print(f'本批已收集 {len(batch_geeks)} 人，停止滚动')
                break

            prev = len(batch_geeks)

            # 改法1:用真实滚轮替代 evaluate(scrollBy),制造真实输入事件(拟人)
            human_scroll(pg, iframe_box, min_delta=1200, max_delta=1800)
            delay = random.uniform(3, 6)
            time.sleep(delay)

            if len(batch_geeks) == prev:
                no_new_count += 1
            else:
                no_new_count = 0

            total_now = prev_total + len(batch_geeks)
            print(f'{total_now} 位候选人 (本批新增：{len(batch_geeks)}，连续无新增：{no_new_count}/5)')

        # 保存结果
        if batch_size and batch_number:
            # 分批模式：保存 batch_N_ids.json + 更新累计文件 + 更新状态
            batch_path = output.get_process_path(f'batch_{batch_number}_ids.json')
            with open(batch_path, 'w', encoding='utf-8') as f:
                json.dump(batch_geeks, f, ensure_ascii=False, indent=2)
            print(f'\n本批 {len(batch_geeks)} 人已保存到：{batch_path}')

            # 累计所有候选人（去重）
            all_cumulative = all_geeks  # all_geeks 包含了历史 seen 的 + 本批新的
            # 但 all_geeks 只包含本批新加入的（seen_ids 过滤了旧的）
            # 需要重新从累计文件加载旧的
            cumulative_path = output.recommend_geek_ids_path
            existing = []
            if os.path.exists(cumulative_path):
                with open(cumulative_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            existing_ids = {g.get('encryptGeekId', '') for g in existing}
            for g in batch_geeks:
                gid = g.get('encryptGeekId', '')
                if gid not in existing_ids:
                    existing.append(g)
                    existing_ids.add(gid)

            with open(cumulative_path, 'w', encoding='utf-8') as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            print(f'累计 {len(existing)} 人已保存到：{cumulative_path}')

            # 更新状态文件
            new_state = {
                'total_collected': len(existing),
                'seen_ids': list(seen_ids),
                'last_batch': batch_number,
            }
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(new_state, f, ensure_ascii=False, indent=2)

            return batch_geeks
        else:
            # 普通模式：保存全部
            output_path = output.recommend_geek_ids_path
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(all_geeks, f, ensure_ascii=False, indent=2)
            print(f'\n总共获取：{len(all_geeks)} 位候选人')
            print(f'已保存到：{output_path}')
            return all_geeks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='获取推荐牛人候选人列表（支持分批）')
    parser.add_argument('--job-name', default='机械工程师', help='岗位名称（jobs.json metadata）')
    parser.add_argument('--encrypt-job-id', default=None,
                        help='BOSS encryptJobId（推荐；新设计目录名依此定位；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）')
    parser.add_argument('--max', type=int, default=None, help='最大获取数量（普通模式）')
    parser.add_argument('--batch-size', type=int, default=None, help='每批收集人数（分批模式）')
    parser.add_argument('--batch', type=int, default=None, help='第几批，从1开始（分批模式）')
    parser.add_argument('--run-id', required=True,
                        help='【必填】run_id 是数据边界。新任务先跑 boss_jd.py 创建 run；不传直接报错。')

    args = parser.parse_args()

    if args.batch_size and args.batch:
        get_recommend_candidates(args.job_name,
                                 batch_size=args.batch_size,
                                 batch_number=args.batch,
                                 run_id=args.run_id,
                                 encrypt_job_id=args.encrypt_job_id)
    else:
        get_recommend_candidates(args.job_name,
                                 max_candidates=args.max,
                                 run_id=args.run_id,
                                 encrypt_job_id=args.encrypt_job_id)
