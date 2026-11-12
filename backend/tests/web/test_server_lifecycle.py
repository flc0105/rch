"""Pure lifecycle handoff tests; no Flask server required."""

import threading
import unittest

from server.runtime.server_lifecycle import ServerLifecycle


class LifecycleHandoffTests(unittest.TestCase):
    def test_reservation_does_not_trigger_shutdown_before_response_close(self):
        lifecycle = ServerLifecycle()
        self.assertTrue(lifecycle.reserve('restart'))
        self.assertFalse(lifecycle._ready.is_set())
        self.assertEqual(lifecycle.action, 'restart')
        self.assertFalse(lifecycle.reserve('shutdown'))
        lifecycle.activate()
        self.assertEqual(lifecycle.wait(), 'restart')

    def test_concurrent_requests_only_one_can_reserve(self):
        lifecycle = ServerLifecycle()
        results = []
        threads = [threading.Thread(target=lambda: results.append(lifecycle.reserve('shutdown')))
                   for _ in range(20)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 19)

    def test_invalid_action_does_not_claim_reservation(self):
        lifecycle = ServerLifecycle()
        with self.assertRaises(ValueError):
            lifecycle.reserve('reload')
        self.assertIsNone(lifecycle.action)
        self.assertTrue(lifecycle.reserve('shutdown'))

    def test_instance_identity_is_unique(self):
        self.assertNotEqual(ServerLifecycle().instance_id, ServerLifecycle().instance_id)



if __name__ == '__main__':
    unittest.main()
