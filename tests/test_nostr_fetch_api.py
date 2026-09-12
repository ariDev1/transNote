from pathlib import Path
import unittest


class NostrFetchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("nostr/sync.mjs").read_text()

    def test_query_sync_never_receives_filter_array(self):
        self.assertNotIn(
            "pool.querySync(relays, filters)",
            self.source,
            "nostr-tools 2.25.2 querySync accepts one Filter, not Filter[]",
        )

    def test_addressed_query_combines_supported_kinds(self):
        self.assertIn(
            "kinds: [NOTE_KIND, 1]",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
