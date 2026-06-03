#!/usr/bin/env python3
"""단일 인스턴스 락 (fcntl 기반, macOS 호환).

cron 틱이 겹쳐 같은 작업이 동시에 두 번 도는 것을 방지.
예: sa-publish가 10건×Claude로 ~20분 걸려 다음 :40 틱과 겹칠 때.

사용:
    from sa_lock import single_instance
    with single_instance("sa-publish") as ok:
        if not ok:
            print("이미 실행 중 — skip"); return
        ...작업...
락을 못 잡으면 with 블록은 그대로 진입하되 ok=False (호출측이 조기 return).
"""
import fcntl
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def single_instance(name: str):
    """name별 lockfile을 비차단(LOCK_NB)으로 획득. 성공 True / 이미 점유 False."""
    lock_path = Path(tempfile.gettempdir()) / f"sa_news_{name}.lock"
    f = open(lock_path, "w")
    acquired = False
    try:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        f.close()
