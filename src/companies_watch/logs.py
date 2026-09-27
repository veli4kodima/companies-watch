import logging
import sys

LOG_FORMAT_TTY = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
LOG_FORMAT_PLAIN = "%(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    fmt = LOG_FORMAT_TTY if sys.stderr.isatty() else LOG_FORMAT_PLAIN
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
