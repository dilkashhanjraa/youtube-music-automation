"""Daily YouTube reporting and explicit, guarded metadata updates. Standard library only."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('title', 'description', 'tags', 'categoryId', 'defaultLanguage', 'defaultAudioLanguage')

def request(url, data=None, headers=None, method=None):
    try:
        with urlopen(Request(url, data=data, headers=headers or {}, method=method), timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'API request failed (HTTP {exc.code}); check credentials, permissions and quota.') from None
    except URLError:
        raise RuntimeError('API network request failed.') from None

def token():
    names = ('YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REFRESH_TOKEN')
    if not all(os.environ.get(n) for n in names):
        raise RuntimeError('Metadata edits require all three YouTube OAuth secrets. See README.')
    data = dict(zip(('client_id', 'client_secret', 'refresh_token'), (os.environ[n] for n in names)))
    data['grant_type'] = 'refresh_token'
    return request('https://oauth2.googleapis.com/token', urlencode(data).encode())['access_token']

def api(resource, params, access=None, body=None):
    headers = {}
    if access:
        headers['Authorization'] = 'Bearer ' + access
    else:
        key = os.environ.get('YOUTUBE_API_KEY')
        if not key:
            raise RuntimeError('Add YOUTUBE_API_KEY to repository Actions secrets to enable reports.')
        headers['X-Goog-Api-Key'] = key
    if body is not None:
        headers['Content-Type'] = 'application/json'
    return request('https://www.googleapis.com/youtube/v3/' + resource + '?' + urlencode(params),
                   json.dumps(body).encode() if body is not None else None, headers,
                   'PUT' if body is not None else 'GET')

def edited_snippet(current, edit):
    if not isinstance(edit, dict) or not edit or set(edit) - {'title', 'description', 'tags'}:
        raise ValueError('Edits must contain only title, description and/or tags.')
    result = {k: copy.deepcopy(v) for k, v in current.items() if k in FIELDS}
    result.update(edit)
    title, description, tags = result.get('title'), result.get('description', ''), result.get('tags', [])
    if not isinstance(title, str) or not title.strip() or len(title) > 100 or any(c in title for c in '<>'):
        raise ValueError('Invalid title: use 1–100 characters without angle brackets.')
    if not isinstance(description, str) or len(description.encode('utf-8')) > 5000 or any(c in description for c in '<>'):
        raise ValueError('Invalid description: maximum 5000 UTF-8 bytes, without angle brackets.')
    if not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() for t in tags):
        raise ValueError('Tags must be a list of nonempty strings.')
    if sum(len(t) + (2 if ' ' in t else 0) for t in tags) + max(0, len(tags)-1) > 500:
        raise ValueError('Tags exceed the 500-character budget.')
    if not result.get('categoryId'):
        raise ValueError('Existing categoryId is missing; refusing update.')
    return result

def run(mode):
    config = json.loads((ROOT / 'config.json').read_text())
    ids = config['video_ids']
    if not ids or len(ids) > 50 or len(set(ids)) != len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]{11}', i) for i in ids):
        raise ValueError('Configure 1–50 unique valid video IDs.')
    out = ROOT / 'reports'
    out.mkdir(exist_ok=True)
    access = token() if mode == 'apply' else None
    videos = api('videos', {'part': 'snippet,statistics', 'id': ','.join(ids)}, access)['items']
    found = {v['id']: v for v in videos}
    if set(found) != set(ids):
        raise RuntimeError('Some configured videos are unavailable; check IDs and access. No edits applied.')
    if mode == 'apply':
        expected = config.get('channel_id')
        channels = api('channels', {'part': 'id', 'mine': 'true'}, access)['items']
        if not expected or expected not in {c['id'] for c in channels}:
            raise RuntimeError('Set channel_id to your authenticated YouTube channel ID before applying edits.')
        edits = config.get('metadata_updates', {})
        if not edits or set(edits) - set(ids):
            raise ValueError('Add metadata_updates for configured video IDs before applying.')
        planned = []
        for video_id, edit in edits.items():
            current = found[video_id]['snippet']
            if current['channelId'] != expected:
                raise RuntimeError('Video does not belong to the configured channel.')
            proposed = edited_snippet(current, edit)
            existing = {k: v for k, v in current.items() if k in FIELDS}
            if proposed != existing:
                planned.append({'id': video_id, 'snippet': proposed})
        # Persist the entire pre-edit response before the first mutation.
        (out / 'before-update.json').write_text(json.dumps(videos, indent=2))
        results = []
        for body in planned:
            api('videos', {'part': 'snippet'}, access, body)
            observed = api('videos', {'part': 'snippet', 'id': body['id']}, access)['items'][0]['snippet']
            if any(observed.get(k) != v for k, v in body['snippet'].items()):
                raise RuntimeError('Update verification failed; inspect saved backup before retrying.')
            results.append(body['id'])
            (out / 'applied.json').write_text(json.dumps(results))
        print(f'Applied and verified {len(results)} metadata updates.')
        return
    (out / 'snapshot.json').write_text(json.dumps({'recorded_at': datetime.now(timezone.utc).isoformat(), 'videos': videos}, indent=2))
    lines = ['# YouTube music report', '', 'Generated: ' + datetime.now(timezone.utc).isoformat(), '']
    for video in videos:
        s, stats = video['snippet'], video.get('statistics', {})
        link = 'https://youtu.be/' + video['id']
        lines += ['## ' + s['title'], '', link, '',
                  'Views: ' + stats.get('viewCount', 'unavailable') + ' | Likes: ' + stats.get('likeCount', 'unavailable') + ' | Comments: ' + stats.get('commentCount', 'unavailable'), '',
                  '### Promotion draft', '', f"Listen to {s['title']} — let me know your favourite part. {link}", '',
                  '### Metadata checks', '',
                  '- Description: ' + ('present' if s.get('description', '').strip() else 'missing; add song credits and listening links.'),
                  '- Tags: ' + ('present' if s.get('tags') else 'none configured.'), '']
    (out / 'report.md').write_text('\n'.join(lines))
    print('Report and promotion drafts saved in reports/. No posts were published.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('report', 'apply'), default='report')
    try:
        run(parser.parse_args().mode)
    except (RuntimeError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
