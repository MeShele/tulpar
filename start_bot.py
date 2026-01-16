#!/usr/bin/env python3
"""Start the bot with environment from docker/.env"""
import os
import sys

# Load environment from docker/.env
env_file = os.path.join(os.path.dirname(__file__), 'docker', '.env')
with open(env_file) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, value = line.partition('=')
            os.environ[key] = value

# Now run the bot
os.chdir(os.path.dirname(__file__))
exec(open('src/main.py').read())
