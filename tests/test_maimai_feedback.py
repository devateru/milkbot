import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

from maimai_analysis.hud import guest_rating_zero
from maimai_analysis.jobs import Job, choose_guest
from maimai_analysis.mai_notes import MaiNotes
from maimai_analysis.media import Image as FrameImage
from maimai_analysis.store import Store
from maimai_analysis.tracking import Chart, Frame, Play, Tracker
from maimai_analysis.vision import CabinetVision, Reading, Vision, cabinet_regions


class FeedbackTests(unittest.TestCase):
    chart = Chart('std:credits:master', 'Credits', 'std', 'master', '14.6')

    def test_find_verified_mai_notes_link_by_chart(self):
        client = MaiNotes(Mock())
        identifier = 'f4d21b1b-683b-4245-996a-dad171796d60'
        client.manifest = (
            {'std': {'title': 'Credits', 'artist': 'Frums', 'type': 'standard'},
             'dx': {'title': 'Credits', 'artist': 'Frums', 'type': 'deluxe'}},
            {identifier: {'song_id': 'std', 'difficulty': 'MASTER', 'has_chart_data': True},
             'another': {'song_id': 'dx', 'difficulty': 'MASTER', 'has_chart_data': True}}
        )
        client.expires = float('inf')
        self.assertEqual(client.find_link(self.chart, {'artist': 'Frums'}),
                         f'https://mai-notes.com/player/{identifier}')
        client.manifest[1]['duplicate'] = client.manifest[1][identifier]
        with self.assertRaisesRegex(ValueError, '채보링크'):
            client.find_link(self.chart, {'artist': 'Frums'})

    def test_guest_requires_track_one_and_zero_rating_same_seat(self):
        for track, rating, guest in ((1, 0, True), (1, None, False), (1, 21, False), (2, 0, False)):
            with self.subTest(track=track, rating=rating):
                tracker = Tracker(lambda _: self.chart, lambda _: True, seat='right')
                for t in (0, 0.5):
                    tracker.feed(Frame(t, 'ready', nickname='ＧＵＥＳＴ', confidence=98, track=track, rating=rating))
                play, _ = tracker.feed(Frame(1, 'start'))
                self.assertEqual((play.guest, play.seat), (guest, 'right'))
                tracker.feed(Frame(1.5, 'result'))
                tracker.feed(Frame(2, 'ready', track=2))
                next_play, _ = tracker.feed(Frame(3, 'start'))
                self.assertEqual(next_play.guest, guest)
                tracker.feed(Frame(3.5, 'credit_end'))
                tracker.feed(Frame(4, 'ready', track=1))
                later, _ = tracker.feed(Frame(5, 'start'))
                self.assertFalse(later.guest)

    def test_left_and_right_achievement_have_disjoint_target_regions(self):
        left, right = cabinet_regions('left'), cabinet_regions('right')
        for key in ('upper_score', 'nameplate', 'rating', 'track_number'):
            self.assertLess(left[key][2], right[key][0])
            self.assertEqual(left[key][1], right[key][1])

    def test_gameplaza_zero_rating_full_field(self):
        import numpy as np

        with Image.open(Path(__file__).parent / 'fixtures' / 'maimai-guest-rating.pgm') as fixture:
            pixels = np.array(fixture)
        self.assertTrue(guest_rating_zero(pixels[:10]))
        self.assertTrue(guest_rating_zero(pixels[10:19, :28]))
        self.assertFalse(guest_rating_zero(pixels[20:]))

    def test_symbol_name_is_read_at_both_seats_and_requires_all_symbols(self):
        import cv2
        import numpy as np

        with Image.open(Path(__file__).parent / 'fixtures' / 'maimai-name-symbols.png') as fixture:
            glyphs = np.asarray(fixture)
        plate = np.full((13, 69), 255, dtype=np.uint8)
        plate[3:9, 35:41] = 70  # End of the regular OCR prefix.
        plate[:, 41:] = glyphs
        engine = Mock()
        engine.read.side_effect = lambda crop, *_: Reading('Other', 95) if crop.shape[1] >= 260 else Reading('Paste', 95)
        for make_view in (lambda: Vision(1280, 720, ocr=engine),
                          lambda: CabinetVision(1280, 720, 'left', engine),
                          lambda: CabinetVision(1280, 720, 'right', engine)):
            view = make_view()
            canvas = np.full((720, 1280), 255, dtype=np.uint8)
            x, y, right, bottom = view.regions['nameplate']
            canvas[y:bottom, x:right] = cv2.resize(plate, (right - x, bottom - y))
            self.assertEqual(view.player_name(canvas), Reading('Paste☆ΣΣ', 95))
            # A genuine missing symbol must not match the configured full name.
            plate[:, 60:] = 255
            canvas[y:bottom, x:right] = cv2.resize(plate, (right - x, bottom - y))
            self.assertNotEqual(view.player_name(canvas).text, 'Paste☆ΣΣ')
            plate[:, 41:] = glyphs

    def test_guest_attribution_needs_one_eligible_user_and_one_identifiable_guest(self):
        guest = Play(self.chart, 'GUEST', 98, 10, seat='right', guest=True)
        left = Play(self.chart, 'Milk', 98, 10, seat='left')
        milk = Job(1, 'lxMVGRpRHiM', True, None, None, 'Milk', None)
        owner = Job(2, 'lxMVGRpRHiM', True, None, None, 'GuestOwner', None)
        third = Job(3, 'lxMVGRpRHiM', True, None, None, 'Another', None)
        self.assertEqual(choose_guest(guest, [left, guest], [milk, owner]), 2)
        self.assertIsNone(choose_guest(guest, [left, guest], [owner, third]))
        self.assertIsNone(choose_guest(guest, [left, guest], [milk]))
        left.nickname = 'GUEST'
        self.assertIsNone(choose_guest(guest, [left, guest], [owner]))
        left.nickname = None
        self.assertIsNone(choose_guest(guest, [left, guest], [owner]))
        guest.guest_user = 2
        opted_out = Job(2, owner.video, False, 0, None, owner.nickname, None)
        self.assertFalse(opted_out.matches(guest))

    def test_dual_vision_reads_only_the_selected_seats_score(self):
        import cv2
        import numpy as np

        fixture_path = Path(__file__).parent / 'fixtures' / 'maimai-gameplaza-rois.pgm'
        with Image.open(fixture_path) as fixture:
            scores = np.array(fixture)
        engine = Mock(read=Mock(return_value=Reading()))
        canvas = np.zeros((720, 1280), dtype=np.uint8)
        views = {seat: CabinetVision(1280, 720, seat, engine) for seat in ('left', 'right')}
        for i, view in enumerate(views.values()):
            x, y, right, bottom = view.regions['upper_score']
            self.assertFalse(view.hud_visible(canvas))
            start = i * 84
            canvas[y:bottom, x:right] = cv2.resize(scores[start:start + 42], (right - x, bottom - y))
            view.play_start = 3
            view.modes['upper_score'].mode = '-'
        for chosen, expected in (('left', '101.0000'), ('right', '100.8462')):
            for seat, view in views.items():
                tracker = Tracker(lambda _: self.chart, lambda p: p.nickname == 'Milk', seat)
                tracker.active = Play(self.chart, 'Milk' if seat == chosen else 'Rival', 95, 3, seat=seat)
                frame = view.inspect(FrameImage(10, canvas.tobytes()), tracker)
                self.assertEqual([sample.value for sample in frame.samples], [expected] if seat == chosen else [])
                tracker.last_track = 2
                tracker.previous = 10
                view.last_field = float('-inf')
                view.metadata = Mock(return_value=('Credits', 'std', 'master'))
                view.track_number = Mock(return_value=2)
                frame = view.inspect(FrameImage(15, canvas.tobytes(), discontinuity=True), tracker, live=True)
                self.assertEqual((frame.title, frame.track, frame.start_time), ('Credits', 2, 3))
                self.assertEqual([sample.value for sample in frame.samples], [expected] if seat == chosen else [])

    def test_sqlite_schema_keeps_only_settings_and_charts(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Store(Path(directory) / 'maimai.db')
            db.set_nickname(1, 'Milk')
            with db.connection() as sql:
                tables = {row[0] for row in sql.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables, {'profiles', 'targets', 'charts'})
