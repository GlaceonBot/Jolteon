#!/bin/bash
git reset --hard origin/master
chmod +x start.sh
chmod +x update.sh
chmod +x main.py
systemctl restart jolteon
