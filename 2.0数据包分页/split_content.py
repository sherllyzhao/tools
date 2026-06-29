# -*- coding: utf-8 -*-
"""
content.json 拆分工具
====================
功能：
  1. 读取 content.json（一个 JSON 数组）
  2. 按 category_id 分组（无该字段或为空 -> uncategorized）
  3. 每组内每 20 条切一个分片文件，输出到
     content_by_category/{categoryId}/content_{categoryId}_{页码}.json
     分片中删除 details 字段（正文 HTML，置空/移除）
  4. 生成 content_category_statistics.json 统计文件

运行前会清空旧的 content_by_category 目录再重建，保证与源数据完全一致。

定位规则（无需传参，双击 exe 即可）：
  - 优先在 exe/脚本所在目录找 content.json
  - 其次找 同目录/jsonDatas/content.json
  找到后，所有产物输出到 content.json 所在目录。
"""

import json
import os
import sys
import shutil
import math
import argparse
from datetime import datetime

DROP_FIELD = "details"    # 分片中需要删除的字段


def base_dir():
    """返回 exe（打包后）或脚本（源码运行）所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_source(bd):
    """按优先级查找 content.json，返回绝对路径或 None。"""
    candidates = [
        os.path.join(bd, "content.json"),
        os.path.join(bd, "jsonDatas", "content.json"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def is_frozen():
    return getattr(sys, "frozen", False)


def pause_if_exe():
    """打包成 exe 双击运行时，结束前停一下，方便看输出。"""
    if is_frozen():
        try:
            input("\n按回车键退出...")
        except EOFError:
            pass


def main():
    parser = argparse.ArgumentParser(description="content.json 拆分工具")
    parser.add_argument("--page-size", type=int, default=20,
                        help="每个分片文件最多记录数（默认：20）")
    args = parser.parse_args()
    page_size = args.page_size

    bd = base_dir()
    src = find_source(bd)
    if not src:
        print("[错误] 未找到 content.json")
        print("  请把本程序放在 content.json 同目录，或放在含 jsonDatas/ 的目录。")
        print("  查找目录：%s" % bd)
        pause_if_exe()
        sys.exit(1)

    work_dir = os.path.dirname(src)
    out_dir = os.path.join(work_dir, "content_by_category")
    stat_file = os.path.join(work_dir, "content_category_statistics.json")

    print("读取源文件: %s" % src)
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("[错误] content.json 顶层不是数组，无法处理。")
        pause_if_exe()
        sys.exit(1)

    total_records = len(data)
    print("共 %d 条记录，开始分组..." % total_records)

    # 按 category_id 分组，保持源文件中的出现顺序
    groups = {}
    for rec in data:
        cid = rec.get("category_id") if isinstance(rec, dict) else None
        if not cid:
            cid = "uncategorized"
        groups.setdefault(cid, []).append(rec)

    # 清空输出目录再重建
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    # 类别排序：categoryId 升序，uncategorized 固定排最后
    def sort_key(cid):
        return (1, "") if cid == "uncategorized" else (0, cid)

    stats = []
    total_files = 0
    for cid in sorted(groups.keys(), key=sort_key):
        recs = groups[cid]
        cat_dir = os.path.join(out_dir, cid)
        os.makedirs(cat_dir, exist_ok=True)

        page_count = math.ceil(len(recs) / page_size)
        for i in range(page_count):
            chunk = recs[i * page_size:(i + 1) * page_size]
            cleaned = []
            for r in chunk:
                if isinstance(r, dict):
                    r2 = dict(r)          # 浅拷贝，保留原字段顺序
                    r2.pop(DROP_FIELD, None)  # 删除 details
                    cleaned.append(r2)
                else:
                    cleaned.append(r)
            fn = os.path.join(cat_dir, "content_%s_%d.json" % (cid, i + 1))
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, ensure_ascii=False, indent=2)

        total_files += page_count
        stats.append({
            "recordCount": len(recs),
            "fileCount": page_count,
            "pageCount": page_count,
            "categoryId": cid,
        })

    summary = {
        "totalCategories": len(stats),
        "totalRecords": total_records,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalFiles": total_files,
        "categories": stats,
    }
    with open(stat_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("-" * 50)
    print("处理完成！")
    print("  输出目录 : %s" % out_dir)
    print("  统计文件 : %s" % stat_file)
    print("  类别数   : %d" % len(stats))
    print("  总记录数 : %d" % total_records)
    print("  总文件数 : %d" % total_files)
    pause_if_exe()


if __name__ == "__main__":
    main()
