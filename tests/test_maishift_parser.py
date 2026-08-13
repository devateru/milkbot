from __future__ import annotations

import unittest

from maishift.parser import (
    MaishiftInvalidOrPrivateError,
    MaishiftParseError,
    parse_maishift_profile,
)


def _card(
    title: str,
    chart_type: str,
    achievement: str,
    grade: str,
    rating: int,
    level: str,
    image: str,
) -> str:
    return f"""
    <div tabindex="0">
      <div><img src="/api/image-relay?url={image}"><img alt="{chart_type}"></div>
      <div><span>{rating}</span><div><div><div>{level}</div></div></div></div>
      <div><span>{title}</span></div>
      <div><span>{achievement}%</span><span>{grade}</span></div>
    </div>
    """


def public_html() -> str:
    tracks = [
        (101, "MASTER", "鬼女紅妖", "DX", "1005000", "SSS+", "320.25", "a.png"),
        (102, "MASTER", "Re：End of a Dream", "STANDARD", "1007000", "SSS+", "317.9", "b.png"),
        (103, "EXPERT", "Åntinomiε", "DX", "995000", "SS+", "300.0", "c.png"),
        (104, "MASTER", "Credits", "STANDARD", "1001000", "SSS", "303.4", "d.png"),
    ]
    objects = []
    for index, difficulty, title, chart_type, achievement, grade, rating, image in tracks:
        objects.append(
            f'$R[{index}]={{trackId:{index},difficulty:"{difficulty}",artist:"x",'
            f'jacketUrl:"https://img/{image}",genre:"x",version:1,displayLevel:"x",'
            f'internalLevel:140,internalLevelIsAccurate:!0,internalLevelDelta:0,'
            f'title:"{title}",titleRuby:void 0,titleTranslations:$R[900]=[],type:"{chart_type}",'
            f'mp:void 0,versionFolderOrder:1,record:$R[800]={{achievement:{achievement},'
            f'dxScore:$R[700]={{score:1,max:2,percentage:50}},combo:"PLAYED",sync:"PLAYED",'
            f'clear:!0,rank:"{grade}",dxRank:1,rating:{rating},isRatingAccurate:!0}}}}'
        )
    script = (
        'profile:$R[1]={name:"ＰＬＡＹＥＲ",rating:1240,profileImageSrc:"x",friendCode:void 0,'
        'trophy:$R[3]={tier:"NORMAL",title:"x"},courseRank:1,classRank:1,stars:1,'
        'playCount:$R[2]={total:42,current:7},createdAt:$R[4]=new Date("2026-08-12T05:31:00.000Z"),'
        'updatedAt:$R[5]=new Date("2026-08-12T05:32:00.000Z")};' + ';'.join(objects)
    )
    new_cards = _card("鬼女紅妖", "DX", "100.5000", "SSS+", 320, "14.0", "https%3A%2F%2Fimg%2Fa.png")
    new_cards += _card("Re：End of a Dream", "STANDARD", "100.7000", "SSS+", 317, "14.1", "https%3A%2F%2Fimg%2Fb.png")
    old_cards = _card("Åntinomiε", "DX", "99.5000", "SS+", 300, "13.9+", "https%3A%2F%2Fimg%2Fc.png")
    old_cards += _card("Credits", "STANDARD", "100.1000", "SSS", 303, "14.2", "https%3A%2F%2Fimg%2Fd.png")
    return f"""
    <html><body>
      <span>8/12/2026, 2:31:00 PM · CiRCLE PLUS week #2 · CiRCLE PLUS</span>
      <main>
        <div><h2>New Songs</h2></div><div>{new_cards}</div>
        <div><h2>Old Songs</h2></div><div>{old_cards}</div>
      </main>
      <script>{script}</script>
    </body></html>
    """


class MaishiftParserTests(unittest.TestCase):
    def parse(self, source: str | None = None):
        return parse_maishift_profile(
            source or public_html(),
            profile_key="sample",
            profile_name=" sample ",
            profile_url="https://example/profile/sample/home",
        )

    def test_public_profile_and_best_sections(self) -> None:
        snapshot = self.parse()
        self.assertEqual(snapshot.player_name, "ＰＬＡＹＥＲ")
        self.assertEqual(snapshot.total_rating, 1240)
        self.assertEqual(snapshot.play_count, 42)
        self.assertEqual(snapshot.secondary_play_count, 7)
        self.assertEqual(snapshot.last_update_datetime.isoformat(), "2026-08-12T05:31:00+00:00")
        self.assertEqual(snapshot.created_at.isoformat(), "2026-08-12T05:31:00+00:00")
        self.assertEqual(snapshot.updated_at.isoformat(), "2026-08-12T05:32:00+00:00")
        self.assertEqual(snapshot.last_update_raw, "8/12/2026, 2:31:00 PM")
        self.assertEqual(snapshot.game_version, "CiRCLE PLUS week #2 · CiRCLE PLUS")
        self.assertEqual(len(snapshot.new_best), 2)
        self.assertEqual(len(snapshot.old_best), 2)

    def test_special_titles_types_and_chart_ids(self) -> None:
        snapshot = self.parse()
        self.assertEqual(snapshot.new_best[0].title, "鬼女紅妖")
        self.assertEqual(snapshot.new_best[0].stable_key, "chart:101")
        self.assertEqual(snapshot.new_best[1].chart_type, "STANDARD")
        self.assertEqual(snapshot.old_best[0].title, "Åntinomiε")
        self.assertEqual(snapshot.old_best[0].stable_key, "chart:103")

    def test_private_or_missing_profile(self) -> None:
        with self.assertRaises(MaishiftInvalidOrPrivateError):
            self.parse("<html><h1>No Record Found or Profile is Private</h1></html>")

    def test_changed_or_broken_structure_is_temporary_parse_failure(self) -> None:
        with self.assertRaises(MaishiftParseError) as caught:
            self.parse("<html><h2>New Songs</h2><h2>Old Songs</h2></html>")
        self.assertNotIsInstance(caught.exception, MaishiftInvalidOrPrivateError)

    def test_rating_integrity_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(MaishiftParseError, "rating integrity mismatch"):
            self.parse(public_html().replace("rating:1240", "rating:9999", 1))

    def test_missing_updated_at_safely_keeps_displayed_created_at(self) -> None:
        source = public_html().replace(
            ',updatedAt:$R[5]=new Date("2026-08-12T05:32:00.000Z")',
            "",
            1,
        )
        snapshot = self.parse(source)
        self.assertIsNone(snapshot.updated_at)
        self.assertEqual(snapshot.last_update_datetime, snapshot.created_at)
