"""Bound independent native jobs; commit their results on the coordinator."""
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from time import monotonic

from .source import OriginalInputError, check_cancel


def run_parallel(items, convert, commit, *, capacity, worker_limit, cancel, stop):
    remaining = deque(items)
    pending = {}
    peak = 0
    next_sample = 0.0
    with ThreadPoolExecutor(max_workers=capacity, thread_name_prefix='cinder-convert') as pool:
        try:
            while remaining or pending:
                check_cancel(cancel)
                now = monotonic()
                if remaining and now >= next_sample:
                    limit = worker_limit()
                    if type(limit) is not int or not 1 <= limit <= capacity:
                        raise OriginalInputError('Invalid conversion worker limit')
                    next_sample = now + 1.0

                # A lower limit drains running work before admitting more. Keep
                # completed jobs available to commit, even when under pressure.
                while remaining and len(pending) < limit:
                    check_cancel(cancel)
                    item = remaining.popleft()
                    pending[pool.submit(convert, item)] = item
                peak = max(peak, len(pending))
                ready, _ = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for future in ready:
                    check_cancel(cancel)
                    commit(pending.pop(future), future.result())
        finally:
            stop()
            for future in pending:
                future.cancel()
    return peak
