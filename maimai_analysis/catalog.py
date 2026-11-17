"""Keep OCR and Discord selections on the existing song catalog's chart keys."""

from song_lookup import normalize, title_key

from .tracking import Chart, Frame

DIFFICULTIES = {'basic': 'BASIC', 'advanced': 'ADVANCED', 'expert': 'EXPERT',
                'master': 'MASTER', 'remaster': 'Re:MASTER'}


def chart_record(selection: str, song: dict, sheet: dict) -> Chart:
    constant = sheet.get('internalLevelValue')
    return Chart(f'{selection}:{sheet["difficulty"]}', song['title'], sheet['type'], sheet['difficulty'],
                 str(constant) if constant is not None else None)


class Catalog:
    def __init__(self, index):
        self.by_title = {}
        self.by_key = {}
        self.kinds = {}
        for value, (song, kind) in index.selections.items():
            self.kinds.setdefault(normalize(title_key(song['title'])), set()).add(kind)
            for diff in DIFFICULTIES:
                try:
                    _, sheet, fallback = index.select(value, diff)
                except ValueError:
                    continue
                if fallback:
                    continue
                chart = chart_record(value, song, sheet)
                self.by_title.setdefault((normalize(title_key(chart.title)), kind, diff), []).append(chart)
                self.by_key[chart.key] = chart

    def resolve(self, frame: Frame) -> Chart | None:
        if not frame.title or not frame.difficulty:
            return None
        name = normalize(title_key(frame.title))
        kinds = self.kinds.get(name, set())
        kind = frame.kind
        if kind is None and len(kinds) == 1:
            kind = next(iter(kinds))
        choices = self.by_title.get((name, kind, frame.difficulty), [])
        if len(choices) == 1:
            return choices[0]
        exact = [chart for chart in choices if title_key(frame.title) == title_key(chart.title)]
        return exact[0] if len(exact) == 1 else None
