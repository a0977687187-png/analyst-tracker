# 分析師追蹤系統 — 專案說明（給 Claude Code）

## 專案是什麼
協助使用者（家祥）追蹤財經分析師/博主的投資觀點，三大功能見《分析師追蹤系統架構規劃書.md》：
1. **觀點提取**：從逐字稿/貼文提取 [分析師、標的、方向、支撐/目標價、信心分數1-10]，產出「觀點記錄卡」。
2. **技術交叉驗證**：使用者提供 RSI/MACD/MA 等數據時，與觀點比對，判斷是否為技術面買點；衝突時強制警示。
3. **績效歸因**：依歷史推薦+當前價格計算勝率/平均報酬率，並做多頭/盤整/空頭分段歸因與 A/B/C/D 可信度評級。

**紅線**：只產出「執行分析報告」（標的、進場條件、停損點、技術分析評估），永不代為下單。

## 程式架構
- `fetch.py`：抓取工具。`search <頻道名>` 查 YouTube 頻道ID；`run [youtube|dcard]` 執行抓取。
  - YouTube：RSS (`feeds/videos.xml?channel_id=`) + youtube-transcript-api 抓逐字稿，需帶瀏覽器 UA 否則偶爾 404。
  - Dcard：有 Cloudflare 真人驗證，必須用 Playwright 開「有視窗」瀏覽器由使用者點擊，cookies 存 `%LOCALAPPDATA%\analyst_tracker_browser_profile`。不可嘗試繞過驗證。
- `config.json`：追蹤來源；`seen.json`：去重記錄（gitignore）；`data/`：抓取輸出（gitignore，版權考量不上傳）。
- 輸出格式：`data/<分析師>/<日期>_<標題>.md`，含 frontmatter（分析師/標題/來源/網址/日期）。

## 已知地雷
- Chrome 的 user-data-dir 與工作路徑**不能含中文**，否則 Playwright spawn UNKNOWN。
- Windows PowerShell 5.1 環境；Python 檔案輸出一律 `encoding="utf-8"`。
- Claude Code 的沙盒開不了 GUI 瀏覽器，Dcard 抓取請使用者雙擊「抓取.bat」執行。

## GitHub
私人倉庫：https://github.com/a0977687187-png/analyst-tracker（帳號 a0977687187-png）。
