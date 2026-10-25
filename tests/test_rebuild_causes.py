"""Why an expired cache was rewritten, turns per request, fixed overhead and cache lifetime."""
import datetime
import unittest

from token_report.naming import Namer
from token_report.stats import CAUSE_COMPACT, CAUSE_EXPIRED, CAUSE_MODEL, CAUSE_OTHER, aggregate
from token_report.transcripts import Call, Prompt, SessionMeta

T0 = datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.timezone.utc)
KEY = ("proj", "s1")
BIG = 200_000


def _call(minutes, cache_read=0, cache_write=0, one_hour=False, model="claude-opus-5"):
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": cache_read,
             "cache_creation_input_tokens": cache_write,
             "cache_creation": {"ephemeral_1h_input_tokens": cache_write if one_hour else 0,
                                "ephemeral_5m_input_tokens": 0 if one_hour else cache_write}}
    call = Call(time=T0 + datetime.timedelta(minutes=minutes), model=model, session_key=KEY,
                file_key=KEY + (None,), agent_id=None, is_subagent=False, usage=usage)
    call._finish()
    return call


class RebuildCausesTest(unittest.TestCase):
    def _causes(self, calls, meta=None):
        stats = aggregate(calls, {KEY: meta or SessionMeta("proj")}, Namer(False),
                          hotspots=False)
        return stats, stats.rebuilds.by_cause

    def test_model_change(self):
        calls = [_call(0, cache_write=BIG, one_hour=True),
                 _call(1, cache_read=BIG),
                 _call(2, cache_write=BIG, one_hour=True, model="claude-sonnet-5")]
        _stats, causes = self._causes(calls)
        self.assertEqual(causes[CAUSE_MODEL], 1)

    def test_compaction_between_calls(self):
        meta = SessionMeta("proj")
        meta.compactions.append((T0 + datetime.timedelta(minutes=1, seconds=30), KEY + (None,)))
        calls = [_call(0, cache_write=BIG, one_hour=True),
                 _call(1, cache_read=BIG),
                 _call(2, cache_write=BIG, one_hour=True)]
        _stats, causes = self._causes(calls, meta)
        self.assertEqual(causes[CAUSE_COMPACT], 1)

    def test_pause_longer_than_one_hour_cache(self):
        calls = [_call(0, cache_write=BIG, one_hour=True),
                 _call(70, cache_write=BIG, one_hour=True)]
        _stats, causes = self._causes(calls)
        self.assertEqual(causes[CAUSE_EXPIRED], 1)

    def test_pause_longer_than_five_minute_cache(self):
        calls = [_call(0, cache_write=BIG),
                 _call(8, cache_write=BIG)]
        _stats, causes = self._causes(calls)
        self.assertEqual(causes[CAUSE_EXPIRED], 1)

    def test_short_pause_means_the_start_changed(self):
        calls = [_call(0, cache_write=BIG, one_hour=True),
                 _call(30, cache_write=BIG, one_hour=True)]
        _stats, causes = self._causes(calls)
        self.assertEqual(causes[CAUSE_OTHER], 1)


class TurnsAndOverheadTest(unittest.TestCase):
    def test_turns_count_typed_prompts_only(self):
        meta = SessionMeta("proj", prompts=[Prompt(T0, "prompt", "a"),
                                            Prompt(T0, "notif", "b"),
                                            Prompt(T0, "prompt", "c")])
        calls = [_call(0, cache_write=BIG, one_hour=True), _call(1, cache_read=BIG)]
        stats = aggregate(calls, {KEY: meta}, Namer(False), hotspots=False)
        self.assertEqual(stats.turns, 2)

    def test_overhead_is_the_first_call_context(self):
        calls = [_call(0, cache_write=40_000, one_hour=True),
                 _call(1, cache_read=40_000)]
        stats = aggregate(calls, {KEY: SessionMeta("proj")}, Namer(False), hotspots=False)
        self.assertEqual(stats.overhead_tokens, 40_010)
        self.assertGreater(stats.overhead_weighted, 0)

    def test_cache_lifetime_per_session(self):
        calls = [_call(0, cache_write=BIG, one_hour=True), _call(1, cache_read=BIG)]
        stats = aggregate(calls, {KEY: SessionMeta("proj")}, Namer(False), hotspots=False)
        self.assertEqual(stats.ttl_sessions["1h"], 1)


if __name__ == "__main__":
    unittest.main()
