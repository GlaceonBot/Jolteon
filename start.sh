#!/bin/bash
cd $HOME/Jolteon
./venv/bin/pip install -r requirements.txt > jolteon.log 2>&1
./main.py --loglevel=INFO
