@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0Register-OrbikaProviderRefreshTask.ps1" %*
