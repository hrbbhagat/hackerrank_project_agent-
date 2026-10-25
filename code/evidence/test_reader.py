import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reader import parse_log_line, extract_identifiers


class TestLogParser(unittest.TestCase):

    def test_key_value_log_extracts_trace_and_identifier(self):
        line = (
            '2026-09-15T08:51:45Z level=DEBUG '
            'service=search_service trace_id=tr-5887496 '
            'event=index_query_started '
            'match_key="g.silva76.jr@gmail.com" attempt=1'
        )
        record = parse_log_line(line)

        self.assertEqual(record["event_timestamp"], "2026-09-15T08:51:45Z")
        self.assertEqual(record["fields"]["trace_id"], "tr-5887496")
        self.assertEqual(record["fields"]["service"], "search_service")
        self.assertEqual(record["fields"]["event"], "index_query_started")
        self.assertEqual(record["resource_id"], None)
        self.assertEqual(record["raw_text"], line)

        identifiers = extract_identifiers(record)
        self.assertIn(
            {"field": "match_key", "value": "g.silva76.jr@gmail.com"},
            identifiers,
        )

    def test_bracketed_log_does_not_misclassify_collector_id(self):
        line = (
            '2026-07-28T05:51:16Z [DEBUG] [log_router] '
            '[collector-9] export_started: instance="collector-9" '
            'sources="platform_services" expected_source_events="87"'
        )
        record = parse_log_line(line)

        self.assertEqual(record["fields"]["service"], "log_router")
        self.assertEqual(record["fields"]["bracket_id"], "collector-9")
        self.assertNotIn("trace_id", record["fields"])
        self.assertEqual(record["fields"]["event"], "export_started")
        self.assertEqual(record["raw_text"], line)

    def test_resource_id_is_extracted_when_present(self):
        line = (
            "2026-09-15T08:51:57Z level=INFO "
            "service=search_service trace_id=tr-5887496 "
            "resource_id=search_1874 event=index_query_completed result=hit"
        )
        record = parse_log_line(line)

        self.assertEqual(record["resource_id"], "search_1874")
        self.assertEqual(record["fields"]["trace_id"], "tr-5887496")
        self.assertEqual(record["fields"]["event"], "index_query_completed")

    def test_missing_timestamp_is_not_invented(self):
        line = "level=INFO service=account_service event=profile_lookup_started"
        record = parse_log_line(line)

        self.assertIsNone(record["event_timestamp"])
        self.assertEqual(record["raw_text"], line)

    def test_quoted_value_with_spaces_is_preserved(self):
        line = (
            '2026-09-15T08:51:55Z level=WARN service=search_service '
            'event=dependency_retry reason="read timeout" attempt=1'
        )
        record = parse_log_line(line)

        self.assertEqual(record["fields"]["reason"], "read timeout")
        self.assertEqual(record["fields"]["attempt"], "1")

    def test_trace_id_is_not_a_resource_id(self):
        line = (
            "2026-09-15T08:51:45Z level=DEBUG "
            "service=search_service trace_id=tr-5887496 "
            "event=index_query_started"
        )
        record = parse_log_line(line)

        self.assertEqual(record["fields"]["trace_id"], "tr-5887496")
        self.assertIsNone(record["resource_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
