#!/bin/bash
cd "$(dirname "$0")"
bash start.sh
if [ $? -ne 0 ]; then echo '启动失败。可参照 README.md 排查。按回车关闭。'; read; fi
