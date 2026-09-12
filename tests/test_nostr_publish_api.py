from pathlib import Path
import unittest


class NostrPublishApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("nostr/sync.mjs").read_text()

    def test_publish_array_is_not_passed_directly_to_promise_race(self):
        self.assertNotIn(
            "pool.publish([r], ev),",
            self.source,
            "nostr-tools 2.25.2 publish() returns Promise[], not Promise",
        )

    def test_publish_requires_exactly_one_relay_promise(self):
        self.assertIn(
            "pending.length !== 1",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
