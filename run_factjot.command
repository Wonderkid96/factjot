#!/bin/zsh
cd "$(dirname "$0")"
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/ship_first_post.py --topic biology 2>&1 | tee -a "data/last_run.log"
echo ""
echo "--- Done. Press any key to close. ---"
read -k 1
