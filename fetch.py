# -*- coding: utf-8 -*-
"""
分析師內容自動抓取工具
  用法:
    python fetch.py search <頻道名稱>                     # 搜尋頻道, 列出候選ID (推薦)
    python fetch.py resolve <YouTube頻道網址或@handle>   # 由網址/handle查頻道ID
    python fetch.py run                                  # 依 config.json 抓取全部來源
    python fetch.py run youtube                          # 只抓 YouTube
    python fetch.py run dcard                            # 只抓 Dcard
  輸出: data/<分析師名>/<日期>_<標題>.md  (含逐字稿/內文, 可直接餵給觀點提取)
"""
import sys, os, io, re, json, html, time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
DATA_DIR = os.path.join(BASE, "data")
SEEN_PATH = os.path.join(BASE, "seen.json")

import requests
import feedparser

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def safe_filename(s, maxlen=60):
    s = re.sub(r'[\\/:*?"<>|\r\n]', "_", s).strip()
    return s[:maxlen] if s else "untitled"


def write_md(analyst, date_str, title, url, source, body):
    folder = os.path.join(DATA_DIR, safe_filename(analyst, 30))
    os.makedirs(folder, exist_ok=True)
    fname = f"{date_str}_{safe_filename(title)}.md"
    path = os.path.join(folder, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"---\n分析師: {analyst}\n標題: {title}\n來源: {source}\n"
                f"網址: {url}\n發布日期: {date_str}\n抓取時間: {datetime.now():%Y-%m-%d %H:%M}\n---\n\n{body}\n")
    return path


# ---------------- Whisper 語音辨識 (無字幕影片的後備方案) ----------------
# 頻道設定加 "whisper": true 才啟用 (如理財達人秀關閉了字幕功能)。
# 流程: yt-dlp 下載音訊 -> faster-whisper 本地辨識 -> 逐字稿。全程在本機執行。

AUDIO_DIR = os.path.join(os.environ.get("LOCALAPPDATA", BASE), "analyst_tracker_audio")
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print("    (載入 Whisper 語音模型, 首次需下載約460MB...)")
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper_model


def transcribe_whisper(vid):
    """下載音訊並用 Whisper 辨識, 回傳逐字稿文字; 失敗回傳 None"""
    import yt_dlp
    os.makedirs(AUDIO_DIR, exist_ok=True)
    audio_path = os.path.join(AUDIO_DIR, f"{vid}.m4a")
    try:
        if not os.path.exists(audio_path):
            print("    (下載音訊中...)")
            ydl_opts = {"format": "bestaudio[ext=m4a]/bestaudio",
                        "outtmpl": os.path.join(AUDIO_DIR, f"{vid}.%(ext)s"),
                        "quiet": True, "no_warnings": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={vid}"])
            if not os.path.exists(audio_path):  # 非 m4a 時找實際下載的檔案
                cands = [f for f in os.listdir(AUDIO_DIR) if f.startswith(vid)]
                if not cands:
                    return None
                audio_path = os.path.join(AUDIO_DIR, cands[0])
        model = get_whisper_model()
        print("    (Whisper 辨識中, 依影片長度約需數分鐘...)")
        segments, info = model.transcribe(
            audio_path, language="zh", beam_size=5, vad_filter=True,
            initial_prompt="以下是台灣財經節目的逐字稿，請使用繁體中文，內容包含台股個股、代號與技術分析術語。")
        text = "\n".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text or None
    except Exception as ex:
        print(f"    ! Whisper 辨識失敗: {str(ex)[:80]}")
        return None
    finally:
        try:                              # 辨識完刪除音訊檔, 不佔硬碟
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except OSError:
            pass


# ---------------- YouTube ----------------

def resolve_channel_id(url_or_handle):
    """由 @handle 或頻道網址解析出 channel_id (UC...)"""
    s = url_or_handle.strip()
    if s.startswith("UC") and len(s) == 24:
        return s
    if not s.startswith("http"):
        s = "https://www.youtube.com/" + (s if s.startswith("@") else "@" + s)
    r = requests.get(s, headers=UA, timeout=20)
    r.raise_for_status()
    m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', r.text) or \
        re.search(r'"channelId":"(UC[\w-]{22})"', r.text)
    if not m:
        raise RuntimeError(f"無法從 {s} 解析 channelId")
    return m.group(1)


def search_channels(query):
    """用頻道名稱搜尋, 回傳 [(channel_id, 頻道名), ...] 最多5筆"""
    r = requests.get("https://www.youtube.com/results",
                     params={"search_query": query, "sp": "EgIQAg%3D%3D"},
                     headers=UA, timeout=20)
    results = []
    for m in re.finditer(r'"channelRenderer":\{"channelId":"(UC[\w-]{22})".{0,400}?"title":\{"simpleText":"([^"]+)"', r.text):
        results.append((m.group(1), m.group(2)))
    return results[:5]


def fetch_youtube(cfg, seen):
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled
    ytt = YouTubeTranscriptApi()
    new_files = []
    for ch in cfg.get("youtube", []):
        name, cid = ch["name"], ch["channel_id"]
        langs = ch.get("languages", ["zh-TW", "zh-Hant", "zh", "zh-Hans", "en"])
        maxv = ch.get("max_videos", 5)
        print(f"\n[YouTube] {name} ({cid})")
        feed = None
        for attempt in range(3):
            try:
                r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                                 headers=UA, timeout=20)
                if r.status_code == 200:
                    feed = feedparser.parse(r.content)
                    if feed.entries:
                        break
            except Exception:
                pass
            time.sleep(3)
        if not feed or not feed.entries:
            print("  ! RSS 抓取失敗 (重試3次), 請確認 channel_id 或稍後再試")
            continue
        for e in feed.entries[:maxv]:
            vid = e.yt_videoid
            if vid in seen:
                continue
            title = e.title
            date_str = e.published[:10]
            url = f"https://www.youtube.com/watch?v={vid}"
            print(f"  - {date_str} {title[:40]}")
            try:
                fetched = ytt.fetch(vid, languages=langs)
                text = "\n".join(sn.text for sn in fetched)
                body = f"## 逐字稿 (自動字幕, 語言:{fetched.language_code})\n\n{text}"
            except (NoTranscriptFound, TranscriptsDisabled):
                text = transcribe_whisper(vid) if ch.get("whisper") else None
                if text:
                    body = f"## 逐字稿 (Whisper本地語音辨識, 可能有錯字)\n\n{text}"
                else:
                    body = "(此影片無可用字幕/逐字稿 — 僅存標題與說明)\n\n" + \
                           html.unescape(getattr(e, "summary", ""))
                    print("    ! 無字幕, 僅存標題與影片說明")
            except Exception as ex:
                print(f"    ! 逐字稿抓取失敗: {ex}")
                continue
            path = write_md(name, date_str, title, url, "YouTube", body)
            print(f"    -> {os.path.relpath(path, BASE)}")
            seen[vid] = date_str
            new_files.append(path)
            time.sleep(1)
    return new_files


# ---------------- Dcard (Playwright 真實瀏覽器) ----------------
# Dcard 有 Cloudflare 人機驗證, 純 HTTP 會被 403。
# 做法: 開啟持久化瀏覽器視窗, 第一次由「你本人」點擊完成驗證,
# cookies 存在 browser_profile/ 之後就能順利抓取。

# 注意: Chrome 的 user-data-dir 不能含中文路徑, 故放在 LOCALAPPDATA
PROFILE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", BASE), "analyst_tracker_browser_profile")


def _wait_posts(page, selector, timeout_sec=120):
    """等文章連結出現; 若卡在人機驗證頁, 提示使用者手動點擊"""
    warned = False
    for _ in range(timeout_sec // 2):
        if page.locator(selector).count() > 0:
            return True
        body = ""
        try:
            body = page.inner_text("body", timeout=3000)
        except Exception:
            pass
        if ("驗證" in body or "確認您的連線" in body) and not warned:
            print("    >> 偵測到 Dcard 人機驗證, 請在開啟的瀏覽器視窗中手動點擊完成 (最多等 2 分鐘)...")
            warned = True
        time.sleep(2)
    return False


def fetch_dcard(cfg, seen):
    sources = cfg.get("dcard", [])
    if not sources:
        return []
    from playwright.sync_api import sync_playwright
    new_files = []
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                PROFILE_DIR, headless=False, locale="zh-TW",
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"])
        except Exception as ex:
            print(f"\n! 無法開啟瀏覽器視窗: {str(ex)[:80]}")
            print("  Dcard 需要開啟真實瀏覽器視窗以通過人機驗證。")
            print("  請直接雙擊「抓取.bat」或在你自己的終端機執行: python fetch.py run dcard")
            return []
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for src in sources:
            name = src["name"]
            forum = src.get("forum", "stock")
            keyword = src.get("keyword", "")
            maxp = src.get("max_posts", 10)
            print(f"\n[Dcard] {name} 看板:{forum} 關鍵字:{keyword or '(無)'}")
            if keyword:
                list_url = f"https://www.dcard.tw/search?query={requests.utils.quote(keyword)}&forum={forum}"
            else:
                list_url = f"https://www.dcard.tw/f/{forum}?tab=latest"
            try:
                page.goto(list_url, timeout=45000, wait_until="domcontentloaded")
            except Exception as ex:
                print(f"  ! 頁面載入失敗: {ex}")
                continue
            sel = f'a[href*="/f/{forum}/p/"]'
            if not _wait_posts(page, sel):
                print("  ! 等不到文章列表 (驗證未完成或版面改版), 跳過此來源")
                continue
            page.mouse.wheel(0, 2000)
            time.sleep(2)
            links = page.eval_on_selector_all(
                sel, "els => [...new Map(els.map(e=>[e.href.split('?')[0], e.textContent.trim()])).entries()]")
            count = 0
            for url, text in links:
                if count >= maxp:
                    break
                m = re.search(r"/p/(\d+)", url)
                if not m:
                    continue
                pid = m.group(1)
                if pid in seen:
                    continue
                try:
                    page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    page.wait_for_selector("article", timeout=20000)
                    title = page.locator("article h1").first.inner_text(timeout=5000) or text[:50]
                    body = page.locator("article").first.inner_text(timeout=10000)
                    date_str = ""
                    t = page.locator("article time").first
                    if t.count() > 0:
                        date_str = (t.get_attribute("datetime") or "")[:10]
                    if not date_str:
                        date_str = datetime.now().strftime("%Y-%m-%d")
                except Exception as ex:
                    print(f"  ! 內文抓取失敗 {url}: {ex}")
                    continue
                print(f"  - {date_str} {title[:40]}")
                path = write_md(name, date_str, title, url, f"Dcard/{forum}", body)
                print(f"    -> {os.path.relpath(path, BASE)}")
                seen[pid] = date_str
                new_files.append(path)
                count += 1
                time.sleep(2)
        ctx.close()
    return new_files


# ---------------- main ----------------

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "resolve":
        print(resolve_channel_id(args[1]))
        return
    if args[0] == "search":
        for cid, name in search_channels(" ".join(args[1:])):
            print(f"{cid}  {name}")
        return
    if args[0] == "run":
        target = args[1] if len(args) > 1 else "all"
        cfg = load_json(CONFIG_PATH, {})
        if not cfg:
            print(f"找不到設定檔 {CONFIG_PATH}")
            return
        seen = load_json(SEEN_PATH, {})
        new_files = []
        if target in ("all", "youtube"):
            new_files += fetch_youtube(cfg, seen)
        if target in ("all", "dcard"):
            new_files += fetch_dcard(cfg, seen)
        save_json(SEEN_PATH, seen)
        print(f"\n完成: 本次新增 {len(new_files)} 篇, 已存於 data/ 資料夾")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
