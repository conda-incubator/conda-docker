import contextlib
import hashlib
import os
import platform
import time


@contextlib.contextmanager
def timer(logger, prefix):
    start_time = time.time()
    yield
    logger.info(f"{prefix} took {time.time() - start_time:.3f} [s]")


def md5_files(paths):
    h = hashlib.new("md5")
    for path in paths:
        with open(path, "rb") as fi:
            while True:
                chunk = fi.read(262144)
                if not chunk:
                    break
                h.update(chunk)
    return h.hexdigest()


def can_link(source_dir, target_dir):
    """Determines if we can link from source to target directory"""
    if platform.system() == "Windows":
        return False
    src = os.path.join(source_dir, "__try_hardlinking_source__")
    trg = os.path.join(target_dir, "__try_hardlinking_target__")
    try:
        with open(src, "w"):
            pass
        os.link(src, trg)
        linkable = True
    except OSError:
        linkable = False
    finally:
        if os.path.isfile(trg):
            os.remove(trg)
        if os.path.isfile(src):
            os.remove(src)
    return linkable
