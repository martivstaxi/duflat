@echo off
REM ====================================================================
REM Daily NOT analysis run.
REM Pulls top-9K snapshot, scans 24h CEX flow, builds diff vs yesterday,
REM merges into a daily report, then commits + pushes to GitHub Pages.
REM
REM Wired up via Task Scheduler (DuflatDailyNOT). To run manually:
REM    daily_run.bat
REM Logs go to scripts\daily_run.log (rotated by appending only).
REM ====================================================================
setlocal EnableExtensions
cd /d C:\Users\livea\duflat

set "LOG=C:\Users\livea\duflat\scripts\daily_run.log"
echo. >> "%LOG%"
echo === %DATE% %TIME% === Daily NOT analysis run >> "%LOG%"

py -u scripts\daily_snapshot.py >> "%LOG%" 2>&1
if errorlevel 1 goto :error

py -u scripts\daily_cex_flow.py >> "%LOG%" 2>&1
if errorlevel 1 goto :error

py -u scripts\daily_diff.py >> "%LOG%" 2>&1
if errorlevel 1 goto :error

py -u scripts\daily_report.py >> "%LOG%" 2>&1
if errorlevel 1 goto :error

REM stage today's outputs (idempotent — adds nothing if unchanged)
git add snapshots/ flow_reports/ >> "%LOG%" 2>&1

REM commit only if there's something staged
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "NOT analiz: daily flow report" >> "%LOG%" 2>&1
    git push origin main >> "%LOG%" 2>&1
) else (
    echo no changes to commit >> "%LOG%"
)

echo === %DATE% %TIME% === done >> "%LOG%"
exit /b 0

:error
echo === %DATE% %TIME% === FAILED >> "%LOG%"
exit /b 1
