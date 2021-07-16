#!/bin/bash
cd /home/Glaceon/Jolteon
./venv/bin/python -m pip install -r requirements.txt > jolteon.log 2>&1
./main.py --logginglevel=INFO
