#!/usr/bin/env python3
"""
网易云音乐 → Spotify 喜欢歌曲迁移工具

用法:
  python migrate.py               # 全流程
  python migrate.py --export-only # 只导出网易云
  python migrate.py --match-only  # 只做匹配
  python migrate.py --save-only   # 只写入 Spotify
"""

import sys
import json
from pathlib import Path

import netease
import matcher
import spotify_client


NETEASE_FILE = Path("netease_liked.json")
MATCHED_FILE = Path("matched.json")
REVIEW_FILE  = Path("review.json")
NOT_FOUND_FILE = Path("not_found.json")


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Phase 1: 导出网易云 ──────────────────────────────────────────────────────

def phase_export():
    if NETEASE_FILE.exists():
        songs = load_json(NETEASE_FILE)
        print(f"[跳过] 已有检查点，加载 {len(songs)} 首歌曲（删除 {NETEASE_FILE} 可重新导出）")
        return songs

    songs = netease.export_liked_songs()
    save_json(NETEASE_FILE, songs)
    print(f"✓ 已导出 {len(songs)} 首歌曲 → {NETEASE_FILE}")
    return songs


# ── Phase 2: 匹配 ────────────────────────────────────────────────────────────

def phase_match(songs):
    sp = spotify_client.get_spotify()

    matched   = load_json(MATCHED_FILE)   if MATCHED_FILE.exists()   else []
    review    = load_json(REVIEW_FILE)    if REVIEW_FILE.exists()    else []
    not_found = load_json(NOT_FOUND_FILE) if NOT_FOUND_FILE.exists() else []

    done_ids = {r["netease_id"] for r in matched + review + not_found}
    pending  = [s for s in songs if s["id"] not in done_ids]

    if not pending:
        print(f"[跳过] 所有歌曲已匹配完毕")
        return matched, review, not_found

    print(f"开始匹配 {len(pending)} 首歌曲（已完成 {len(done_ids)} 首）...")

    for i, song in enumerate(pending, 1):
        result = matcher.find_best_match(sp, song)
        score  = result["score"]

        if score >= matcher.AUTO_ACCEPT:
            matched.append(result)
            status = "✓"
        elif score >= matcher.REVIEW_MIN:
            review.append(result)
            status = "?"
        else:
            not_found.append(result)
            status = "✗"

        print(f"  [{i}/{len(pending)}] {status} {song['name']} - {song['artists'][0] if song['artists'] else ''}"
              f"  →  {result['spotify_name'] or '未找到'} (分数: {score})")

        # 每 50 首保存一次检查点
        if i % 50 == 0:
            save_json(MATCHED_FILE,   matched)
            save_json(REVIEW_FILE,    review)
            save_json(NOT_FOUND_FILE, not_found)

    save_json(MATCHED_FILE,   matched)
    save_json(REVIEW_FILE,    review)
    save_json(NOT_FOUND_FILE, not_found)
    return matched, review, not_found


# ── Phase 3: 写入 Spotify ────────────────────────────────────────────────────

def phase_save(matched):
    sp = spotify_client.get_spotify()
    uris = [r["spotify_uri"] for r in matched if r.get("spotify_uri")]
    print(f"正在保存 {len(uris)} 首歌曲到 Spotify 喜欢的歌曲...")
    spotify_client.save_liked_songs(sp, uris)
    print(f"✓ 保存完成")


# ── 主入口 ───────────────────────────────────────────────────────────────────

def print_summary(matched, review, not_found):
    total = len(matched) + len(review) + len(not_found)
    print()
    print("=" * 50)
    print("迁移结果汇总")
    print("=" * 50)
    print(f"  总计处理:      {total} 首")
    print(f"  ✓ 自动匹配:    {len(matched)} 首 ({len(matched)/total*100:.1f}%)")
    print(f"  ? 待人工确认:  {len(review)} 首  → 查看 {REVIEW_FILE}")
    print(f"  ✗ 未找到:      {len(not_found)} 首  → 查看 {NOT_FOUND_FILE}")
    print("=" * 50)
    if review:
        print(f"\n提示: 编辑 {REVIEW_FILE}，把想要的歌曲移到 {MATCHED_FILE} 后")
        print(f"      再运行 python migrate.py --save-only 补充保存")


def main():
    args = sys.argv[1:]
    export_only = "--export-only" in args
    match_only  = "--match-only"  in args
    save_only   = "--save-only"   in args

    if save_only:
        if not MATCHED_FILE.exists():
            print(f"错误: 找不到 {MATCHED_FILE}，请先运行匹配步骤")
            sys.exit(1)
        matched = load_json(MATCHED_FILE)
        phase_save(matched)
        return

    songs = phase_export()
    if export_only:
        return

    matched, review, not_found = phase_match(songs)
    if match_only:
        print_summary(matched, review, not_found)
        return

    phase_save(matched)
    print_summary(matched, review, not_found)


if __name__ == "__main__":
    main()
