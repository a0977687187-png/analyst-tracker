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

## 行情儀表板 (dashboard/)
- `dashboard/app.py`：Flask 後端，port 5177，啟動用「啟動儀表板.bat」。前端 `dashboard/static/index.html`（lightweight-charts 已 vendor 在 static/，勿用 CDN）。
- 資料源與 API 特性：
  - TWSE rwd API（加權日K `TAIEX/MI_5MINS_HIST`、個股 `afterTrading/STOCK_DAY`、法人 `fund/BFI82U`、排行 `fund/T86`）：按月查詢，ROC 民國年日期。
  - 櫃買歷史：Yahoo `^TWOII`（TPEX openapi `/tpex_index` 只回本月）。
  - 即時報價：`mis.twse.com.tw/stock/api/getStockInfo.jsp`（t00=加權、o00=櫃買）。
  - 期交所 `futContractsDateDown`：**不能跨月查詢、範圍含尚無資料日會整筆失敗**（回 HTML錯誤頁），需按月+結束日回退重試；`futDataDown` 則可跨月。散戶多空比 =（全市場OI−三大法人OI）多空差 ÷ 全市場OI。
  - 集保 TDCC opendata `getOD.ashx?id=1-5`：每週五資料，首次下載約1-3分鐘，背景執行緒處理。
- 快取在 `dashboard/cache/`（gitignore）：歷史月份永久、當期資料 10 分鐘 TTL。
- `recommendations.json`（repo 根目錄）：觀點記錄卡的結構化輸出，儀表板讀它顯示推薦標的與進出場策略。

## 已知地雷
- Chrome 的 user-data-dir 與工作路徑**不能含中文**，否則 Playwright spawn UNKNOWN。
- Windows PowerShell 5.1 環境；Python 檔案輸出一律 `encoding="utf-8"`。
- Claude Code 的沙盒開不了 GUI 瀏覽器，Dcard 抓取請使用者雙擊「抓取.bat」執行。

## GitHub
私人倉庫：https://github.com/a0977687187-png/analyst-tracker（帳號 a0977687187-png）。
