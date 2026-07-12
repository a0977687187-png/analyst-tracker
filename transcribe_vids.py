# -*- coding: utf-8 -*-
"""手動對指定 YouTube 影片跑 Whisper 辨識 (給無字幕的完整版節目用)
用法: python transcribe_vids.py <video_id> [<video_id> ...]
輸出與 fetch.py 相同格式, 存進 data/<頻道名>/, 並記入 seen.json
"""
import sys, io, re, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import requests
import fetch as F

UA = F.UA


def video_info(vid):
    """從 oEmbed 取標題, 從 watch 頁取發布日期"""
    r = requests.get("https://www.youtube.com/oembed",
                     params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"},
                     headers=UA, timeout=20)
    title = r.json().get("title", vid)
    date_str = ""
    try:
        w = requests.get(f"https://www.youtube.com/watch?v={vid}", headers=UA, timeout=20)
        m = re.search(r'"publishDate":\{?"?(?:simpleText"?:")?(\d{4}-\d{2}-\d{2})', w.text) or \
            re.search(r'"uploadDate":"(\d{4}-\d{2}-\d{2})', w.text)
        if m:
            date_str = m.group(1)
    except Exception:
        pass
    return title, date_str or "unknown"


def main():
    vids = sys.argv[1:]
    if not vids:
        print(__doc__)
        return
    seen = F.load_json(F.SEEN_PATH, {})
    for vid in vids:
        title, date_str = video_info(vid)
        print(f"\n[{vid}] {date_str} {title[:50]}")
        text = F.transcribe_whisper(vid)
        if not text:
            print("  ! 辨識失敗, 跳過")
            continue
        body = f"## 逐字稿 (Whisper本地語音辨識, 可能有錯字)\n\n{text}"
        path = F.write_md("理財達人秀", date_str, title,
                          f"https://www.youtube.com/watch?v={vid}", "YouTube", body)
        print(f"  -> {os.path.relpath(path, F.BASE)}")
        seen[vid] = date_str
    F.save_json(F.SEEN_PATH, seen)
    print("\n完成")


if __name__ == "__main__":
    main()
