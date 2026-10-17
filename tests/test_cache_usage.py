"""Expired cache per session and long conversations."""
import datetime
import unittest

from token_report.naming import Namer
from token_report.session_detail import session_detail
from token_report.stats import LONG_CONTEXT, aggregate
from token_report.transcripts import Call, SessionMeta

T0 = datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.timezone.utc)
KEY = ("proj", "s1")


def _call(minutes, cache_read=0, cache_write=0):
    call = Call(time=T0 + datetime.timedelta(minutes=minutes), model="claude-opus-5",
                session_key=KEY, file_key=KEY + (None,), agent_id=None, is_subagent=False,
                usage={"input_tokens": 10, "output_tokens": 5,
                       "cache_read_input_tokens": cache_read,
                       "cache_creation_input_tokens": cache_write})
    call._finish()
    return call


class CacheUsageTest(unittest.TestCase):
    def setUp(self):
        self.calls = [_call(0, cache_write=LONG_CONTEXT),
                      _call(1, cache_read=LONG_CONTEXT),
                      _call(90, cache_write=LONG_CONTEXT),   # expired after 90 minutes
                      _call(92, cache_read=LONG_CONTEXT)]
        self.meta = {KEY: SessionMeta("proj")}

    def test_aggregate(self):
        stats = aggregate(self.calls, self.meta, Namer(False), hotspots=False)
        self.assertEqual(stats.rebuilds.count, 1)
        self.assertEqual(stats.rebuilds.by_gap["> 60"], 1)
        self.assertEqual(stats.rebuilds.by_session[KEY].longest_gap, 89)
        lc = stats.long_context
        self.assertEqual((lc.sessions, lc.uncompacted_sessions, lc.calls), (1, 1, 4))

    def test_session_detail(self):
        d = session_detail(KEY, self.calls, self.meta[KEY], Namer(False))
        self.assertEqual(d.rebuilds.count, 1)
        self.assertEqual(d.long_calls, 4)


if __name__ == "__main__":
    unittest.main()
