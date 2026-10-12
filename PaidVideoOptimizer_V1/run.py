#!/usr/bin/env python3
"""Local-only runner. No automatic ad execution or external model calls."""
import argparse, os, socket, sys, threading, webbrowser
from pathlib import Path

def main():
 if sys.version_info<(3,10):raise SystemExit('需要 Python 3.10 或更新版本。')
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);p.add_argument('--no-browser',action='store_true');args=p.parse_args()
 os.chdir(Path(__file__).resolve().parent)
 try:import uvicorn
 except ImportError:raise SystemExit('请先运行：python -m pip install -r requirements.txt')
 port=args.port
 for candidate in range(port,port+10):
  with socket.socket() as s:
   try:s.bind(('127.0.0.1',candidate));port=candidate;break
   except OSError:continue
  # the socket is closed before starting the server
 else:raise SystemExit('本地端口已占用，请用 --port 指定其他端口。')
 address=f'http://127.0.0.1:{port}'
 print('\n短视频付费投流优化工作台\n本地地址：'+address+'\n数据目录：'+str(Path(os.environ.get('OPTIMIZER_DATA_DIR','data')).resolve())+'\n只提供建议，不自动操作平台。关闭终端即停止服务。\n',flush=True)
 if not args.no_browser:threading.Timer(1.3,lambda:webbrowser.open(address)).start()
 uvicorn.run('app.main:app',host='127.0.0.1',port=port,log_level='warning')
if __name__=='__main__':main()
