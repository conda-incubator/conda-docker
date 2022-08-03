import logging


def init_logging(debug: bool = False):
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
