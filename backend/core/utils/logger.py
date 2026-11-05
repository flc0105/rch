import logging

def get_console_logger():
    logger = logging.getLogger("console_logger")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


logger = get_console_logger()