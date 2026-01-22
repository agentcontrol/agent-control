
import os
import sys

# Add src to path
sys.path.insert(0, os.path.abspath("src"))

from agent_control_server.config import db_config

print(f"DB URL: {db_config.get_url()}")
print(f"DB User: {db_config.user}")
