import time
import functools


def retry(max_attempts: int = 3, wait_seconds: int = 60, exceptions: tuple = (Exception,)):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        raise
                    print(f"[retry] {fn.__name__} failed (attempt {attempt}/{max_attempts}): {e}. Retrying in {wait_seconds}s...")
                    time.sleep(wait_seconds)
        return wrapper
    return decorator
