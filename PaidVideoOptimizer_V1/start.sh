#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then echo '请先安装Python 3.10或更新版本。'; exit 1; fi
python3 -c 'import sys; assert sys.version_info >= (3,10), "需要Python 3.10+"'
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'import fastapi,uvicorn,multipart' >/dev/null 2>&1; then
 echo '首次启动：安装Python依赖，需要网络。文件解析与运行不向第三方上传业务数据。'
 .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python run.py
