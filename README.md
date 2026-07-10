# 分析師內容自動抓取工具 — 使用說明

## 在新電腦上安裝（轉移用）
1. 安裝 [Python 3.12+](https://www.python.org/downloads/)（安裝時勾選 **Add python.exe to PATH**）與 [Git](https://git-scm.com/download/win)。
2. 開啟 PowerShell，下載本專案（私人倉庫，需登入 GitHub）：
   ```powershell
   winget install GitHub.cli
   gh auth login          # 選 GitHub.com -> HTTPS -> Login with a web browser
   gh repo clone a0977687187-png/analyst-tracker "$HOME\Desktop\analyst-tracker"
   ```
3. 進入資料夾，雙擊 **安裝.bat**（安裝 Python 套件與 Playwright 瀏覽器）。
4. 雙擊 **抓取.bat** 開始抓取；第一次 Dcard 需重新點一次人機驗證。
5. （選用）舊電腦的 `data/` 與 `seen.json` 若要保留歷史，用隨身碟複製到新資料夾即可。
   注意：資料夾路徑建議用英文，避免中文路徑造成瀏覽器啟動問題。

## 一鍵執行
直接雙擊 **抓取.bat**，會自動抓取 `config.json` 裡所有來源，存到 `data/` 資料夾。

- **YouTube**：全自動，抓每個頻道的最新影片＋逐字稿（自動字幕）。
- **Dcard**：會開啟一個瀏覽器視窗。**第一次執行**若出現「Dcard 需要確認您的連線」畫面，請手動點一下驗證（只需一次，之後會記住）。

已抓過的影片/文章記錄在 `seen.json`，不會重複抓。

## 新增想追蹤的分析師

### YouTube 頻道
1. 先搜尋頻道 ID（在此資料夾開終端機執行）：
   ```
   python fetch.py search 頻道名稱
   ```
   或用頻道網址／@handle：
   ```
   python fetch.py resolve https://www.youtube.com/@xxxx
   ```
2. 把結果加進 `config.json` 的 `youtube` 陣列：
   ```json
   { "name": "分析師名稱", "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx", "max_videos": 3 }
   ```

### Dcard 來源
在 `config.json` 的 `dcard` 陣列加入：
```json
{ "name": "來源名稱", "forum": "stock", "keyword": "台積電", "max_posts": 10 }
```
- `forum`：看板代號（如 stock、investment）
- `keyword`：留空 `""` 則抓看板最新文章；填關鍵字則抓搜尋結果

## 排程自動抓取（每天早上自動執行）
在 PowerShell 執行一次即可（範例：每天 08:00）：
```powershell
schtasks /Create /TN "分析師抓取" /TR "C:\Users\cai\Desktop\家祥\分析師追蹤系統\抓取.bat" /SC DAILY /ST 08:00
```

## 抓完之後
把 `data/` 裡的新檔案丟給 Claude 說「**提取觀點**」，就會依《分析師追蹤系統架構規劃書》產出觀點記錄卡。

## 限制與注意
- YouTube 逐字稿來自自動字幕，若影片無字幕則只存標題與影片說明。
- Dcard 的人機驗證必須由真人點擊，本工具不會也不應繞過；驗證通過後 cookies 會保存在
  `%LOCALAPPDATA%\analyst_tracker_browser_profile`，一段時間後過期需再點一次。
- 請適量抓取（腳本已內建延遲），避免對網站造成負擔。
