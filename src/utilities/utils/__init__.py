import os
import logging

from utilities.constant import SPECIFIC_PATH

logger = logging.getLogger(__name__)

def utilities_specific_folder(folder_to_create):
    full_path = os.path.join(SPECIFIC_PATH, folder_to_create)
    os.makedirs(full_path, exist_ok=True)
    return full_path