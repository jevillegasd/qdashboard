import logging
import os

# Define the log file path
LOG_FILE_PATH = os.path.join(os.path.dirname(__file__), '../../qdashboard.log')

# Configure the logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler()
    ]
)

def get_logger(name):
    """Returns a logger instance with the given name."""
    return logging.getLogger(name)
