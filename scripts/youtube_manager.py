"""YouTube channel-wide reporting and guarded metadata updates."""
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

FIELDS = (
    "title",
    "description",
    "tags",
    "categoryId",
    "defaultLanguage",
    "defaultAudioLanguage",
)


def request(url, data=None, headers=None, method=None):
    try:
        req = Request(
            url,
            data=data,
            headers=headers or {},
            method=method,
        )
        with urlopen(req, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(
            f"API request failed (HTTP {exc.code}); "
            "check credentials, permissions and quota."
        ) from None
    except URLError:
        raise RuntimeError("API network request failed.") from None


def token():
    names = (
        "YOUTUBE_CLIENT_ID",
        "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
    )

    if not all(os.environ.get(name) for name in names):
        raise RuntimeError(
            "Metadata edits require all three YouTube OAuth secrets."
        )

    data = {
        "client_id": os.environ["YOUTUBE_CLIENT_ID"],
        "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }

    return request(
        "https://oauth2.googleapis.com/token",
        urlencode(data).encode(),
    )["access_token"]


def api(resource, params, access=None, body=None):
    headers = {}

    if access:
        headers["Authorization"] = "Bearer " + access
    else:
        key = os.environ.get("YOUTUBE_API_KEY")
        if not key:
            raise RuntimeError(
                "Add YOUTUBE_API_KEY to repository Actions secrets."
            )
        headers["X-Goog-Api-Key"] = key

    if body is not None:
        headers["Content-Type"] = "application/json"

    url = (
        "https://www.googleapis.com/youtube/v3/"
        + resource
        + "?"
        + urlencode(params)
    )

    return request(
        url,
        json.dumps(body).encode() if body is not None else None,
        headers,
        "PUT" if body is not None else "GET",
    )


def discover_channel_videos(channel_id, access=None):
    """Automatically discover every video in the channel uploads playlist."""

    channel_response = api(
        "channels",
        {
            "part": "contentDetails",
            "id": channel_id,
        },
        access,
    )

    items = channel_response.get("items", [])

    if not items:
        raise RuntimeError(
            "YouTube channel was not found. Check channel_id in config.json."
        )

    uploads_playlist = (
        items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    )

    video_ids = []
    page_token = None

    while True:
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist,
            "maxResults": 50,
        }

        if page_token:
            params["pageToken"] = page_token

        response = api("playlistItems", params, access)

        for item in response.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")

            if (
                video_id
                and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
                and video_id not in video_ids
            ):
                video_ids.append(video_id)

        page_token = response.get("nextPageToken")

        if not page_token:
            break

    if not video_ids:
        raise RuntimeError(
            "No uploaded videos were found on the configured channel."
        )

    return video_ids


def fetch_videos(video_ids, access=None):
    """Retrieve video details in batches of 50."""

    videos = []

    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]

        response = api(
            "videos",
            {
                "part": "snippet,statistics",
                "id": ",".join(batch),
            },
            access,
        )

        videos.extend(response.get("items", []))

    return videos


def edited_snippet(current, edit):
    if (
        not isinstance(edit, dict)
        or not edit
        or set(edit) - {"title", "description", "tags"}
    ):
        raise ValueError(
            "Edits may contain only title, description and/or tags."
        )

    result = {
        key: copy.deepcopy(value)
        for key, value in current.items()
        if key in FIELDS
    }

    result.update(edit)

    title = result.get("title")
    description = result.get("description", "")
    tags = result.get("tags", [])

    if (
        not isinstance(title, str)
        or not title.strip()
        or len(title) > 100
        or any(c in title for c in "<>")
    ):
        raise ValueError("Invalid YouTube title.")

    if (
        not isinstance(description, str)
        or len(description.encode("utf-8")) > 5000
        or any(c in description for c in "<>")
    ):
        raise ValueError("Invalid YouTube description.")

    if (
        not isinstance(tags, list)
        or any(
            not isinstance(tag, str) or not tag.strip()
            for tag in tags
        )
    ):
        raise ValueError("Tags must be non-empty strings.")

    tag_budget = (
        sum(len(tag) + (2 if " " in tag else 0) for tag in tags)
        + max(0, len(tags) - 1)
    )

    if tag_budget > 500:
        raise ValueError("Tags exceed YouTube's 500-character budget.")

    if not result.get("categoryId"):
        raise ValueError(
            "Existing categoryId is missing; refusing update."
        )

    return result


def generate_report(videos, channel_id):
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).isoformat()

    snapshot = {
        "recorded_at": timestamp,
        "channel_id": channel_id,
        "video_count": len(videos),
        "videos": videos,
    }

    (out / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# DILKASH HANJRAA — YouTube Channel Report",
        "",
        "Generated: " + timestamp,
        "",
        f"Videos discovered: {len(videos)}",
        "",
    ]

    for video in videos:
        snippet = video["snippet"]
        stats = video.get("statistics", {})
        video_id = video["id"]
        link = "https://youtu.be/" + video_id

        lines.extend(
            [
                "## " + snippet["title"],
                "",
                link,
                "",
                "Views: "
                + stats.get("viewCount", "unavailable")
                + " | Likes: "
                + stats.get("likeCount", "unavailable")
                + " | Comments: "
                + stats.get("commentCount", "unavailable"),
                "",
                "### Promotion draft",
                "",
                f"Listen to {snippet['title']} — "
                f"let me know your favourite part. {link}",
                "",
                "### Metadata checks",
                "",
                "- Description: "
                + (
                    "present"
                    if snippet.get("description", "").strip()
                    else "missing"
                ),
                "- Tags: "
                + (
                    "present"
                    if snippet.get("tags")
                    else "none configured"
                ),
                "",
            ]
        )

    (out / "report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(
        f"Discovered and analyzed {len(videos)} channel videos."
    )
    print("Report saved in reports/. No YouTube changes were made.")


def apply_updates(config, videos, access):
    channel_id = config["channel_id"]
    edits = config.get("metadata_updates", {})

    if not edits:
        raise ValueError(
            "No metadata_updates are configured."
        )

    found = {video["id"]: video for video in videos}

    unknown = set(edits) - set(found)

    if unknown:
        raise ValueError(
            "metadata_updates contains videos not found on this channel."
        )

    out = ROOT / "reports"
    out.mkdir(exist_ok=True)

    (out / "before-update.json").write_text(
        json.dumps(videos, indent=2),
        encoding="utf-8",
    )

    applied = []

    for video_id, edit in edits.items():
        current = found[video_id]["snippet"]

        if current["channelId"] != channel_id:
            raise RuntimeError(
                "Video ownership check failed."
            )

        proposed = edited_snippet(current, edit)

        existing = {
            key: value
            for key, value in current.items()
            if key in FIELDS
        }

        if proposed == existing:
            continue

        body = {
            "id": video_id,
            "snippet": proposed,
        }

        api(
            "videos",
            {"part": "snippet"},
            access,
            body,
        )

        verification = api(
            "videos",
            {
                "part": "snippet",
                "id": video_id,
            },
            access,
        )

        observed = verification["items"][0]["snippet"]

        if any(
            observed.get(key) != value
            for key, value in proposed.items()
        ):
            raise RuntimeError(
                "Update verification failed. Check backup."
            )

        applied.append(video_id)

        (out / "applied.json").write_text(
            json.dumps(applied, indent=2),
            encoding="utf-8",
        )

    print(
        f"Applied and verified {len(applied)} metadata updates."
    )


def run(mode):
    config = json.loads(
        (ROOT / "config.json").read_text(encoding="utf-8")
    )

    channel_id = config.get("channel_id", "").strip()

    if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id):
        raise ValueError(
            "Set a valid YouTube channel_id in config.json."
        )

    access = token() if mode == "apply" else None

    video_ids = discover_channel_videos(
        channel_id,
        access,
    )

    videos = fetch_videos(
        video_ids,
        access,
    )

    if mode == "apply":
        apply_updates(config, videos, access)
    else:
        generate_report(videos, channel_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=("report", "apply"),
        default="report",
    )

    try:
        run(parser.parse_args().mode)
    except (
        RuntimeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
