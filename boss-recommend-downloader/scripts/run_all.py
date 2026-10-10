#!/usr/bin/env python3
"""
推荐牛人简历下载一键脚本
串联 Step 1 和 Step 2，完成从获取列表到下载简历的全流程

使用统一输出路径：~/Desktop/boss-hr-output/<岗位名>/
"""

import sys
import os

# 添加 shared 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
import fix_encoding  # noqa: E402  # 强制 Windows UTF-8 stdout
from output_manager import JobOutputManager

# 添加 scripts 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recommend_list import get_recommend_candidates
from recommend_download import download_resumes


def main():
    job_name = '机械工程师'  # 默认岗位，可通过参数修改

    print('=' * 60)
    print('推荐牛人简历批量下载工具')
    print('=' * 60)
    print()

    # 初始化输出管理器
    output = JobOutputManager(job_name)
    print(f'输出目录：{output.job_dir}')
    print(f'过程文件：{output.process_dir}')
    print()

    # 检查环境变量
    if os.environ.get('PYTHONIOENCODING') != 'utf-8':
        print('️  警告：建议设置 PYTHONIOENCODING=utf-8 避免编码问题')
        print('   export PYTHONIOENCODING=utf-8')
        print()

    # Step 1: 获取候选人列表
    print('【Step 1】获取候选人列表...')
    print('-' * 40)

    geek_list = get_recommend_candidates(job_name=job_name, max_candidates=None)

    if not geek_list:
        print('错误：未获取到候选人列表')
        return

    print(f'\n成功获取 {len(geek_list)} 位候选人\n')

    # 获取 jobId
    job_id = geek_list[0].get('geekCard', {}).get('encJobId', '')
    if not job_id:
        print('错误：无法获取岗位 ID')
        return

    print(f'岗位 ID: {job_id}')
    print()

    # 确认是否继续
    print('【Step 2】批量获取完整简历...')
    print('-' * 40)
    print(f'预计耗时：{len(geek_list) * 12 / 60:.0f} - {len(geek_list) * 20 / 60:.0f} 分钟')
    print(f'随机延迟：5-20 秒/人')
    print()

    start = datetime.now()
    print(f'开始时间：{start.strftime("%H:%M:%S")}')
    print()

    # Step 2: 批量获取简历
    resumes, failed = download_resumes(job_name=job_name, max_count=None)

    # 总结
    end = datetime.now()
    duration = (end - start).total_seconds() / 60

    print()
    print('=' * 60)
    print('完成！')
    print('=' * 60)
    print(f'总耗时：{duration:.1f} 分钟')
    print(f'成功：{len(resumes)} 份简历')
    print(f'失败：{len(failed)} 份')
    print()
    print('输出文件：')
    print(f'  - 候选人列表：{output.recommend_geek_ids_path}')
    print(f'  - 完整简历：{output.resumes_path}')
    print(f'  - 失败列表：{output.get_process_path("failed_resumes.json")}')

    # 清理临时脚本
    print()
    print('清理临时脚本...')
    output.cleanup_temp_scripts()
    print('完成！')


if __name__ == '__main__':
    import json
    from datetime import datetime
    main()
