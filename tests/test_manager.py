import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('manager', Path(__file__).resolve().parents[1] / 'scripts/youtube_manager.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.snippet = {'title': 'Original', 'description': 'Credits', 'tags': ['music'], 'categoryId': '10', 'defaultLanguage': 'en', 'defaultAudioLanguage': 'pa', 'channelId': 'owner'}

    def test_preserves_unspecified_metadata(self):
        result = m.edited_snippet(self.snippet, {'title': 'New title'})
        self.assertEqual(result['description'], 'Credits')
        self.assertEqual(result['tags'], ['music'])
        self.assertEqual(result['defaultAudioLanguage'], 'pa')
        self.assertEqual(self.snippet['title'], 'Original')
        self.assertNotIn('channelId', result)

    def test_rejects_invalid_updates(self):
        for update in ({'title': ''}, {'description': 'é' * 2501}, {'tags': 'music'}, {'privacyStatus': 'public'}, {'tags': ['x' * 501]}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                m.edited_snippet(self.snippet, update)

    def test_report_never_writes_to_youtube(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'ROOT', Path(tmp)), patch.object(m, 'api') as api:
            Path(tmp, 'config.json').write_text(json.dumps({'video_ids': ['5-oJR6dVzhM']}))
            api.return_value = {'items': [{'id': '5-oJR6dVzhM', 'snippet': self.snippet, 'statistics': {'viewCount': '42'}}]}
            m.run('report')
            self.assertEqual(api.call_count, 1)
            self.assertIn('Views: 42', Path(tmp, 'reports/report.md').read_text())

    def test_wrong_channel_prevents_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'ROOT', Path(tmp)), patch.object(m, 'token', return_value='fake'), patch.object(m, 'api') as api:
            Path(tmp, 'config.json').write_text(json.dumps({'video_ids': ['5-oJR6dVzhM'], 'channel_id': 'other', 'metadata_updates': {'5-oJR6dVzhM': {'title': 'New'}}}))
            api.side_effect = [{'items': [{'id': '5-oJR6dVzhM', 'snippet': self.snippet}]}, {'items': [{'id': 'owner'}]}]
            with self.assertRaises(RuntimeError):
                m.run('apply')
            self.assertEqual(api.call_count, 2)

    def test_apply_backs_up_then_verifies(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'ROOT', Path(tmp)), patch.object(m, 'token', return_value='fake'), patch.object(m, 'api') as api:
            Path(tmp, 'config.json').write_text(json.dumps({'video_ids': ['5-oJR6dVzhM'], 'channel_id': 'owner', 'metadata_updates': {'5-oJR6dVzhM': {'title': 'New'}}}))
            proposed = m.edited_snippet(self.snippet, {'title': 'New'})
            def response(resource, params, access=None, body=None):
                if body:
                    self.assertTrue(Path(tmp, 'reports/before-update.json').exists())
                    self.assertEqual(params, {'part': 'snippet'})
                    return body
                if resource == 'channels':
                    return {'items': [{'id': 'owner'}]}
                return {'items': [{'id': '5-oJR6dVzhM', 'snippet': proposed if params['part'] == 'snippet' else self.snippet}]}
            api.side_effect = response
            m.run('apply')
            self.assertEqual(json.loads(Path(tmp, 'reports/applied.json').read_text()), ['5-oJR6dVzhM'])

if __name__ == '__main__':
    unittest.main()
