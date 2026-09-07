import threading
import time
import unittest

from ps5led.state import AppState


class TestAppState(unittest.TestCase):
    def test_starts_at_zero(self):
        self.assertEqual(AppState().seq, 0)

    def test_update_advances_seq(self):
        state = AppState()
        self.assertEqual(state.update(rgb=(1, 2, 3)), 1)
        self.assertEqual(state.seq, 1)

    def test_snapshot_carries_fields_and_seq(self):
        state = AppState()
        state.update(rgb=(1, 2, 3), battery=80)
        snap = state.snapshot()
        self.assertEqual(snap["rgb"], (1, 2, 3))
        self.assertEqual(snap["battery"], 80)
        self.assertEqual(snap["seq"], 1)

    def test_snapshot_is_a_copy(self):
        state = AppState()
        state.update(rgb=(1, 2, 3))
        snap = state.snapshot()
        snap["rgb"] = (9, 9, 9)
        self.assertEqual(state.snapshot()["rgb"], (1, 2, 3))

    def test_writing_the_same_value_does_not_advance_seq(self):
        state = AppState()
        state.update(rgb=(1, 2, 3))
        self.assertEqual(state.update(rgb=(1, 2, 3)), 1)

    def test_partial_no_op_still_advances_for_the_changed_field(self):
        state = AppState()
        state.update(rgb=(1, 2, 3), battery=80)
        self.assertEqual(state.update(rgb=(1, 2, 3), battery=79), 2)

    def test_wait_returns_immediately_when_already_ahead(self):
        state = AppState()
        state.update(rgb=(1, 2, 3))
        started = time.time()
        snap = state.wait_for_change(0, timeout=5)
        self.assertIsNotNone(snap)
        self.assertLess(time.time() - started, 0.5)

    def test_wait_times_out_when_nothing_changes(self):
        self.assertIsNone(AppState().wait_for_change(0, timeout=0.1))

    def test_wait_wakes_on_update_from_another_thread(self):
        state = AppState()
        result = []

        def waiter():
            result.append(state.wait_for_change(0, timeout=5))

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.05)
        state.update(battery=42)
        thread.join(timeout=5)
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0])
        self.assertEqual(result[0]["battery"], 42)

    def test_concurrent_updates_produce_unique_sequence_numbers(self):
        state = AppState()
        seen = []
        lock = threading.Lock()

        def worker(base):
            for i in range(50):
                seq = state.update(**{"f%d" % base: i})
                with lock:
                    seen.append(seq)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(seen), len(set(seen)), "seq must never repeat")
        self.assertEqual(state.seq, 200)


if __name__ == "__main__":
    unittest.main()
