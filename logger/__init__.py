import logging
import sys
import enum

class Levels(enum.Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    FATAL = logging.FATAL


class Logger:
    def __init__(self, module, level=logging.INFO):
        self.l = logging.getLogger(module)
        for h in self.l.handlers:
            self.l.removeHandler(h)
        self.l.addHandler(logging.StreamHandler(sys.stdout))
        format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        logging.basicConfig(level=level.value, format=format)

    def info(self, m):
        self.l.info(m)

    def warning(self, m):
        self.l.warning(m)

    def debug(self, m):
        self.l.debug(m)

    def error(self, m):
        self.l.error(m)

    def fatal(self, m):
        self.l.fatal(m)