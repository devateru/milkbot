"""Full chart metadata and compact difficulty lines for song embeds."""

import re
import unicodedata


DIFFICULTY_ORDER = ('basic', 'advanced', 'expert', 'master', 'remaster')


def song_key(song):
    title = song['title']
    if song.get('sheets') and all(s['type'] == 'utage' for s in song['sheets']):
        title = re.sub(r'^\[[^\]]+\]', '', title)
    return unicodedata.normalize('NFKC', title).casefold().strip()


def enrich_song_catalog(songs, region='intl'):
    """Join separately listed UTAGE charts without changing selection sheets."""
    special = {}
    for song in songs:
        for sheet in song['sheets']:
            if sheet['type'] == 'utage':
                special.setdefault(song_key(song), []).append({**sheet, 'comment': song.get('comment') or ''})
    return [{**song, 'chart_region': region,
             'all_sheets': [s for s in song['sheets'] if s['type'] != 'utage']
                           + special.get(song_key(song), [])} for song in songs]


def format_song_constants(chart, selected_type):
    region = chart.get('chart_region', 'intl')
    sheets = []
    for sheet in chart.get('all_sheets', chart.get('sheets', [])):
        if 'type' not in sheet:
            continue
        if region and not sheet.get('regions', {}).get(region, True):
            continue
        sheets.append({**sheet, **sheet.get('regionOverrides', {}).get(region, {})})
    lines = []
    order = [selected_type] if selected_type in ('dx', 'std') else []
    order += [type_ for type_ in ('dx', 'std') if type_ not in order]
    for type_ in order:
        values = []
        for difficulty in DIFFICULTY_ORDER:
            sheet = next((s for s in sheets if s['type'] == type_ and s['difficulty'] == difficulty), None)
            if sheet is None:
                continue
            constant = sheet.get('internalLevelValue')
            values.append(f'{constant:.1f}' if constant is not None else str(sheet.get('level') or '?'))
        if values:
            lines.append(f"[{'DX' if type_ == 'dx' else 'ST'}] " + ' / '.join(values))
    seen = set()
    for sheet in sheets:
        if sheet['type'] != 'utage':
            continue
        label = sheet['difficulty'].strip('【】[]') or 'UTAGE'
        level = str(sheet.get('level') or '?').rstrip('?') or '?'
        buddy = sheet.get('isBuddy') or '🤝' in (sheet.get('comment') or '') or 'バディ' in (sheet.get('comment') or '')
        line = f'[{label}] {level}' + (' 🤝' if buddy else '')
        if line not in seen:
            lines.append(line)
            seen.add(line)
    return '\n'.join(lines)
