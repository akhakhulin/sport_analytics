@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
echo Listen for channel events; respond when something arrives. | claude -p --channels plugin:fakechat@claude-plugins-official > logs\claude-channels-test.log 2>&1
