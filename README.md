# DILKASH HANJRAA — YouTube Music Manager

A GitHub Actions automation for existing music videos. Initial video: https://youtu.be/5-oJR6dVzhM

## What it does

- Daily snapshot of public views, likes, comments, title and description.
- A promotion-copy draft and basic metadata checks for each configured video.
- Manual application of exact title, description or tag edits from config.json.
- Metadata backups before changes, ownership checks and verification afterward.

Reports run daily at 14:23 UTC (10:23 a.m. Toronto during daylight time, 9:23 a.m. in winter). GitHub schedules can be delayed. Download each run's `youtube-report` artifact from Actions; reports are retained for 14 days. These are individual snapshots, not calculated growth or watch-time analytics.

This does not buy ads, post to social networks, create artificial engagement or guarantee increased views. Promotion text is a draft to use in your chosen publishing tool. Metadata edits are manual; the daily schedule only reads data.

## First setup — reports

1. Open https://console.cloud.google.com/apis/library/youtube.googleapis.com and enable **YouTube Data API v3** in your Google Cloud project.
2. Create an API key under **APIs & Services → Credentials**. Restrict its API access to YouTube Data API v3. A browser/referrer-restricted key will not work in GitHub Actions.
3. Open https://github.com/dilkashhanjraa/youtube-music-automation/settings/secrets/actions and choose **New repository secret**.
4. Name it `YOUTUBE_API_KEY` and paste your key as the value. Never commit keys into files or paste them in chat.
5. Open https://github.com/dilkashhanjraa/youtube-music-automation/actions → **YouTube Music Manager** → **Run workflow** → mode **report**.
6. Open the completed run and download its report artifact. The daily schedule then uses the same secret. Without the secret, report runs fail with a setup message.

Add other existing video IDs to `video_ids` in config.json (maximum 50).

## Optional setup — metadata editing

An API key cannot edit a channel. Use your own Google OAuth client and authorize the account that owns your YouTube channel with the scope `https://www.googleapis.com/auth/youtube.force-ssl` and offline access. One route is Google's OAuth Playground at https://developers.google.com/oauthplayground/ using **your own OAuth credentials** in its settings. For a web client, configure `https://developers.google.com/oauthplayground` as the authorized redirect URI. Configure the consent screen and test user as required by Google, authorize the YouTube scope, exchange the code, and store the resulting refresh token privately.

Add these repository Actions secrets:

- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

Testing-mode OAuth apps may issue short-lived refresh tokens; follow Google's consent-screen and verification requirements for sustained use. Revoked or expired credentials must be reauthorized. Use only the owning account's credentials.

Set `channel_id` in config.json to your actual YouTube channel ID. Put exact edits into `metadata_updates`, for example:

```json
"metadata_updates": {
  "5-oJR6dVzhM": {
    "title": "Your chosen song title | DILKASH HANJRAA"
  }
}
```

Replace the sample wording with the real intended title. Review your committed edits, then manually run the workflow in **apply** mode. Empty edits or a missing/mismatched channel ID stop the run. Unchanged edits are skipped. Unspecified writable snippet fields are preserved; privacy, thumbnails and monetization are not modified. A multi-video run can partially succeed if a later API call fails: inspect `applied.json` and the backup before retrying. Backups do not automatically roll back edits.

## Development

Python 3.12; no third-party runtime packages.

```bash
python -m unittest discover -s tests -v
python scripts/youtube_manager.py --mode report
```

Pushes validate code without requiring YouTube secrets. Live API functionality requires credentials and a successful report/manual run.

## References

- https://developers.google.com/youtube/v3/docs/videos/list
- https://developers.google.com/youtube/v3/docs/videos/update
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
