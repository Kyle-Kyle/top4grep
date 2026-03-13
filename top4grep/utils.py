import html
import os
import logging
import re
import tempfile
import uuid
from contextlib import contextmanager

import colorlog

# color and format
logger_formatter = colorlog.ColoredFormatter(
    '[%(name)s][%(levelname)s]%(asctime)s %(log_color)s%(message)s',
    datefmt='%m-%d %H:%M')
WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value):
    if value is None:
        return ""
    return WHITESPACE_RE.sub(" ", html.unescape(str(value))).strip()


def normalize_title(value):
    return normalize_text(value)

def new_logger(name, level='DEBUG', new=True):
    # add custom level "VERBOSE"
    VERBOSE = 5
    logging.addLevelName(VERBOSE, "VERBOSE")
    logging.Logger.verbose = lambda inst, msg, *args, **kwargs: inst.log(VERBOSE, msg, *args, **kwargs)

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(logger_formatter)

    logger = logging.getLogger(name)
    if new: logger.handlers = []

    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    return logger

@contextmanager
def path_context(path):
    cwd = os.getcwd()
    try:
        os.chdir(path)
        yield path
    finally:
        os.chdir(cwd)

@contextmanager
def tmpdir_ctx():
    try:
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
    finally:
        os.system("rm -rf %s" % tmpdir)

@contextmanager
def tmpfile_ctx(prefix=None):
    fname = str(uuid.uuid4())
    if prefix:
        fpath = os.path.join(prefix, fname)
    else:
        fpath = fname
    fpath = os.path.abspath(fpath)


    try:
        os.system("touch %s" % fpath)
        yield fpath
    finally:
        os.system("rm %s" % fpath)
