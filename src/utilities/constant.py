import os
import sys

if sys.platform.startswith("win"):
    UTILITIES_PATH = "C:/utilities"
else:
    UTILITIES_PATH = os.path.expanduser("~/utilities")

CONFIG_PATH = os.path.join(UTILITIES_PATH, "config")
LOGS_PATH = os.path.join(UTILITIES_PATH, "logs")
SPECIFIC_PATH = os.path.join(UTILITIES_PATH, "specific")