from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from maimai_analysis.simai import parse_simai, parse_sections, note_at, adjustment_footer
from maimai_analysis.alignment import align_from_gain, align_from_judgments
from maimai_analysis.scoring import Sample, evaluate
from maimai_analysis.youtube import parse_video, video_link, parse_hls
from maimai_analysis.store import Store
from maimai_analysis.tracking import Tracker, Frame, Chart, identity_key


class CoreTests(unittest.TestCase):
    def test_first_judgment_sets_origin_even_with_simai_lead_in(self):
        chart = parse_simai("(120){4},,12,3,E")
        origin, error = align_from_judgments(chart, [(10.9, 0), (11.1, 2)], 9)
        self.assertAlmostEqual(origin, 10)
        self.assertAlmostEqual(error, .1)
        self.assertIsNone(align_from_judgments(chart, [(10.9, 0), (11.1, 3)], 9))
        hold = parse_simai("(120){4},1h[4:1],2,E")
        self.assertIsNone(align_from_judgments(hold, [(10.9, 0), (11.1, 1)], 9))

    def test_goals_accept_section_note_counts(self):
        chart = parse_simai("(120){4}1,2,3,4,E")
        self.assertEqual(parse_sections("2개:-0.1, 나머지:-0.05", chart),
                         parse_sections("1:-0.1, 3:-0.05", chart))
        with self.assertRaises(ValueError):
            parse_sections("2개:-0.1, 1개:-0.05", chart)

    def test_gain_alignment_checks_first_gain_and_later_judgments(self):
        chart = parse_simai("(120){4},,1,2,3,4,E")
        samples = [Sample(time, '+', score) for time, score in
                   [(10.9, '0'), (11.1, '25'), (11.4, '25'), (11.6, '50'), (11.9, '50'), (12.1, '75')]]
        origin, _ = align_from_gain(chart, samples, 9)
        self.assertAlmostEqual(origin, 10)
        self.assertIsNone(align_from_gain(chart, samples[:2], 9))
        self.assertIsNone(align_from_gain(chart, samples[1:], 9))

    def test_parses_chart_notes_and_adjacent_judgments(self):
        chart = parse_simai("(120){4}12,3h[4:2],1-5[4:1],C,3b,4,E")
        self.assertEqual(chart.counts,
                         {"tap": 4, "hold": 1, "slide": 1, "touch": 1, "break": 1})
        self.assertEqual(note_at(chart, 0), (1, 2))
        self.assertEqual(note_at(chart, .2), (3, 3))
        sections = parse_sections("1:-0.1000, 2:-0.0500, 4:-0.1100", chart)
        self.assertEqual([(s.original, s.first, s.last) for s in sections],
                         [(1, 1, 2), (2, 3, 7), (4, 8, 8)])
        self.assertEqual(adjustment_footer(sections),
                         "* 시작 노트 조정됨 [구간 2: 2 → 3] [구간 3: 4 → 8]")
        for invalid in ("2:-.1", "1:-.1,1:-.2", "1:-.1,20:-.1", "1:NaN", "1:-.1,3:-.1,2:-.2"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_sections(invalid, chart)

    def test_score_types_skip_and_uncertainty(self):
        chart = parse_simai("(120){4},1,2,3,4,E")
        sections = parse_sections("1:-.2,3:-.1,4:-.1", chart)
        plus = [Sample(t, "+", str(value)) for t, value in
                [(10, 0), (11.25, 50), (11.75, "74.8260"), (12.25, "99.8260")]]
        minus = [Sample(t, "-", str(value)) for t, value in
                 [(10, 100), (11.25, 100), (11.75, "99.8260"), (12.25, "99.8260")]]
        for samples in (plus, minus):
            result = evaluate(chart, sections, samples, 10, 12.6)
            self.assertEqual([x.status for x in result], ["passed", "failed", "passed"])
            self.assertEqual(result[1].loss, Decimal("0.1740"))
            self.assertEqual(result[1].timestamp, 9)
        result = evaluate(chart, sections, minus[:2], 10, 11.7, skipped=True)
        self.assertEqual([x.status for x in result], ["passed", "skip-failed", "skipped"])
        self.assertIsNone(result[1].loss)
        self.assertTrue(all(x.status == "uncertain" for x in evaluate(chart, sections, [], None, 15)))

    def test_youtube_timeline(self):
        video = parse_video("https://youtu.be/lxMVGRpRHiM?t=1h2m3s")
        self.assertEqual(video.start, 3723)
        self.assertEqual(video_link(video.id, 343.9), "https://www.youtube.com/watch?v=lxMVGRpRHiM&t=343")
        with self.assertRaises(ValueError):
            parse_video("https://youtube.com.example/watch?v=lxMVGRpRHiM")
        segments, ended = parse_hls(
            "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:7\n#EXT-X-PROGRAM-DATE-TIME:2026-11-16T00:00:03Z\n"
            "#EXTINF:2.0,\na.ts\n#EXTINF:2.0,\nb.ts\n#EXT-X-ENDLIST",
            "https://example.com/live/path.m3u8")
        self.assertTrue(ended)
        self.assertEqual(segments[1].sequence, 8)
        self.assertEqual(segments[1].epoch - segments[0].epoch, 2)

    def test_repeated_plays_identity_and_targets(self):
        chart = Chart("std:abc:master", "Credits", "std", "master", "14.6")
        tracker = Tracker(lambda _: chart, lambda play: play.nickname == "MI LK")
        plays = []
        for frame in (
            Frame(0, "profile", nickname="ＭＩ ＬＫ", confidence=97),
            Frame(0.5, "profile", nickname="ＭＩ ＬＫ", confidence=96),
            Frame(1, "ready", title="Credits"),
            Frame(2, "start", origin=2),
            Frame(3, "playing", samples=(Sample(3, "-", "100"),)),
            Frame(4, "result"),
            Frame(5, "ready", title="Credits"),
            Frame(6, "start", origin=6),
            Frame(7, "result"),
            Frame(8, "credit_end"),
            Frame(9, "profile", nickname="MI", confidence=99),
            Frame(10, "profile", nickname="MI", confidence=99),
            Frame(11, "ready", title="Credits"),
            Frame(12, "start"),
            Frame(13, "result"),
            Frame(14, "credit_end"),
            Frame(15, "ready", title="Credits"),
            Frame(16, "start"),
            Frame(17, "skip"),
        ):
            _, finished = tracker.feed(frame)
            if finished:
                plays.append(finished)
        self.assertEqual(len(plays), 4)
        self.assertEqual([p.nickname for p in plays], ["MI LK", "MI LK", "MI", None])
        self.assertEqual([len(p.samples) for p in plays], [1, 0, 0, 0])
        self.assertEqual(plays[-1].status, "skipped")
        self.assertNotEqual(identity_key("MI"), identity_key("MI LK"))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.sqlite3"
            store = Store(path)
            store.set_nickname(1, "ＭＩ ＬＫ")
            reopened = Store(path)
            self.assertEqual(reopened.nickname(1), "MI LK")
