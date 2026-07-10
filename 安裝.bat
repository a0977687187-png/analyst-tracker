@echo off
cd /d %~dp0
echo === Installing Python packages ===
pip install -r requirements.txt
echo === Installing Playwright Chromium browser ===
python -m playwright install chromium
echo === Done! You can now run the fetcher (double-click the fetch bat file) ===
pause
