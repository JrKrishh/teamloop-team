@echo off
rem Double-click to install Super Agents for this Windows user (no admin needed).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 pause
