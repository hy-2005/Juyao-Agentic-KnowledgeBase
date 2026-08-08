@echo off
chcp 65001 >nul
title JuYao RAG 启动器
echo ============================================
echo   JuYao Agentic RAG 一键启动
echo   引擎(FastAPI:8000) + Kafka 消费者
echo ============================================
echo.

cd /d "%~dp0juyao-agentic-rag"

echo [1/2] 启动 RAG 引擎 (http://localhost:8000) ...
start "RAG-Engine" ..\venv\Scripts\python.exe -m uvicorn rag_core.api.app:app --host 0.0.0.0 --port 8000

echo [2/2] 启动 Kafka 消费者 ...
start "RAG-Kafka-Consumer" ..\venv\Scripts\python.exe -m rag_core.cli.kafka_consumer

echo.
echo 已启动。两个窗口独立运行,请勿关闭。
echo 停止方式:关闭对应窗口,或 taskkill /IM python.exe
echo.
pause
