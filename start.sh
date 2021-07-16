#!/bin/bash
cd /home/Glaceon/Jolteon
./venv/bin/python3 -m pip install -r requirements.txt > jolteon.log 2>&1
./main.py --log=INFO
