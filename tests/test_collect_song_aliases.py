import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import requests

from collect_song_aliases import parse_songs, parse_backlinks, collect, main, WikiClient


class CollectorTests(unittest.TestCase):
    def test_chart_suffix_variants_are_merged_before_collection(self):
        html = '''<table><tr><td>곡명</td><td>아티스트</td><td>BPM</td></tr>
        <tr><td><a href="/w/39(DX)">39(DX)</a></td><td>A</td><td>180</td></tr>
        <tr><td><a href="/w/39(STD)">39 (STD)</a></td><td>A</td><td>180</td></tr>
        <tr><td><a href="/w/39">39</a></td><td>A</td><td>180</td></tr>
        <tr><td>Song (Remix)</td><td>A</td><td>180</td></tr></table>'''
        client = Mock()
        client.get.return_value = html
        client.aliases.return_value = ['39', '별칭']
        with tempfile.TemporaryDirectory() as directory:
            result = collect(client, Path(directory) / 'cache.json')
        self.assertEqual(result, [{'title': '39', 'aliases': ['별칭']},
                                  {'title': 'Song (Remix)', 'aliases': []}])
        client.aliases.assert_called_once_with('39')

    def test_missing_song_document_does_not_stop_collection(self):
        client = WikiClient(0)
        response = Mock(status_code=404)
        error = requests.HTTPError('Not Found', response=response)
        with patch.object(client, 'get', side_effect=error):
            self.assertEqual(client.aliases('Agitation！'), [])

    def test_access_denied_is_not_treated_as_missing_document(self):
        client = WikiClient(0)
        response = Mock(status_code=403)
        error = requests.HTTPError('Forbidden', response=response)
        with patch.object(client, 'get', side_effect=error):
            with self.assertRaises(requests.HTTPError):
                client.aliases('Song')

    def test_difficulty_subheaders_are_not_song_titles(self):
        html = '''<table><tr><td>곡명</td><td>아티스트</td><td>난이도</td></tr>
        <tr><td>B</td><td>A</td><td>E</td><td>M</td><td>R</td></tr>
        <tr><td>Song</td><td>Artist</td><td>180</td></tr></table>'''
        self.assertEqual([s['title'] for s in parse_songs(html)], ['Song'])

    def test_only_song_columns_preserve_original_and_unlinked_titles(self):
        html = '''<table><tr><td>곡명</td><td>아티스트</td><td>BPM</td></tr>
        <tr><td><a href="/w/%E6%98%9F#s-2">星★</a><a href="#fn-1">[1]</a></td>
        <td><a href="/w/Artist">Artist</a></td><td>180</td></tr>
        <tr><td>Unlinked!</td><td>Artist</td><td>200</td></tr>
        <tr><td colspan="3">추가곡</td></tr></table>'''
        self.assertEqual(parse_songs(html), [
            {"title": "Unlinked!", "document": None, "fragment": ""},
            {"title": "星★", "document": "星", "fragment": "s-2"},
        ])

    def test_redirects_only_and_next_page(self):
        html = '''<h1>Song (역링크)</h1><select name="flag"><option value="8">redirect</option></select>
        <ul><li><a href="/w/Artist">Artist</a> (link)</li>
        <li><a href="/w/%EA%B8%80%ED%81%AC">글크</a> (redirect)</li></ul>
        <a href="/backlink/Song?from=Next&amp;flag=8">다음</a>'''
        self.assertEqual(parse_backlinks(html, "Song"),
                         (["글크"], "/backlink/Song?from=Next&flag=8"))

    def test_empty_backlinks_are_valid_but_changed_markup_is_not(self):
        html = '<h1>Song (역링크)</h1><select name="flag"><option>redirect</option></select>'
        self.assertEqual(parse_backlinks(html + '해당 문서의 역링크가 존재하지 않습니다.', "Song"), ([], None))
        with self.assertRaises(ValueError):
            parse_backlinks(html, "Song")
        with self.assertRaises(ValueError):
            parse_songs('<html>Checking your browser</html>')

    def test_section_links_do_not_import_album_aliases_and_cache_resumes(self):
        client = Mock()
        client.get.return_value = '''<table><tr><td>곡명</td><td>아티스트</td><td>BPM</td></tr>
        <tr><td><a href="/w/Album#s-2">Track</a></td><td>A</td><td>180</td></tr>
        <tr><td><a href="/w/Song">Song</a></td><td>A</td><td>180</td></tr></table>'''
        client.aliases.return_value = ['Song', '별칭']
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'cache.json'
            first = collect(client, cache)
            self.assertEqual(first, [{'title': 'Song', 'aliases': ['별칭']}, {'title': 'Track', 'aliases': []}])
            self.assertEqual(collect(client, cache), first)
            client.aliases.assert_called_once_with('Song')

    def test_limit_saves_local_json_without_token_configuration(self):
        client = Mock()
        client.get.return_value = """<table><tr><td>곡명</td><td>아티스트</td><td>BPM</td></tr>
        <tr><td>Song A</td><td>Artist</td><td>180</td></tr>
        <tr><td>Song B</td><td>Artist</td><td>180</td></tr></table>"""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'songs.json'
            cache = Path(directory) / 'cache.json'
            with patch('collect_song_aliases.WikiClient', return_value=client):
                self.assertEqual(main(['--limit', '1', '--output', str(output), '--cache', str(cache)]), 0)
            self.assertEqual(output.read_text(encoding='utf-8'),
                             '[\n  {\n    "title": "Song A",\n    "aliases": []\n  }\n]\n')


if __name__ == '__main__':
    unittest.main()
