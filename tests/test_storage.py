import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from storage import decode_records, encode_records


class StorageTests(unittest.TestCase):
    def test_saved_profiles_are_json_string(self):
        records = [{
            "id": "abc", "name": "Длинная ссылка",
            "url": "https://my.example/send?p=1&long=two%20words",
            "status_url": "",
        }]
        persisted = encode_records(records, 20)
        self.assertIsInstance(persisted, str)
        self.assertEqual(decode_records(persisted, 20), records)

    def test_limits_and_bad_data(self):
        self.assertEqual(len(decode_records(encode_records([{"i": i} for i in range(30)], 20), 20)), 20)
        self.assertEqual(decode_records("not-json", 20), [])
        self.assertEqual(decode_records("{}", 20), [])

    def test_legacy_list_is_readable(self):
        self.assertEqual(decode_records([{"id": "a"}], 20), [{"id": "a"}])


if __name__ == "__main__":
    unittest.main()
