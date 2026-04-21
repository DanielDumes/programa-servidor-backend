import logging
import sys
from config import LOG_FILE, LOG_LEVEL

def setup_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL))

    # Formato profesional: [Timestamp] [Level] [Thread] [Logger] Message
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(threadName)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Handler para consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler para archivo
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# Logger global para el monitor
logger = setup_logger("ilo-monitor")
