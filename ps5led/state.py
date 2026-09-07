"""The one object shared between threads.

Everything else in the engine is single-owner. Readers take a snapshot and hold
a plain dict; nobody hands a callback across a thread boundary.
"""

import threading
import time


class AppState(object):
    def __init__(self):
        self._condition = threading.Condition()
        self._fields = {}
        self._seq = 0

    @property
    def seq(self):
        with self._condition:
            return self._seq

    def update(self, **fields):
        """Merge fields in. Returns the sequence number after the merge.

        A field written with the value it already holds is not a change, so the
        sequence does not advance — otherwise a motionless controller would still
        push sixty identical frames a second down the stream.
        """
        with self._condition:
            changed = False
            for key, value in fields.items():
                if key not in self._fields or self._fields[key] != value:
                    self._fields[key] = value
                    changed = True
            if changed:
                self._seq += 1
                self._condition.notify_all()
            return self._seq

    def snapshot(self):
        with self._condition:
            snap = dict(self._fields)
            snap["seq"] = self._seq
            return snap

    def wait_for_change(self, last_seq, timeout=25.0):
        """Snapshot once the sequence passes ``last_seq``, or None on timeout."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._seq <= last_seq:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            snap = dict(self._fields)
            snap["seq"] = self._seq
            return snap
