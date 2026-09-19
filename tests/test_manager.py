import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "manager",
    Path(__file__).resolve().parents[1] / "scripts/youtube_manager.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ManagerTests(unittest.TestCase):

    def setUp(self):
        self.channel_id = "UCIleGrAWD629ZVUhd4N4mFw"

        self.snippet = {
            "title": "Original",
            "description": "Credits",
            "tags": ["music"],
            "categoryId": "10",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "pa",
            "channelId": self.channel_id,
        }

    def test_preserves_unspecified_metadata(self):
        result = m.edited_snippet(
            self.snippet,
            {"title": "New title"},
        )

        self.assertEqual(result["description"], "Credits")
        self.assertEqual(result["tags"], ["music"])
        self.assertEqual(
            result["defaultAudioLanguage"],
            "pa",
        )
        self.assertEqual(
            self.snippet["title"],
            "Original",
        )
        self.assertNotIn("channelId", result)

    def test_rejects_invalid_updates(self):
        invalid_updates = (
            {"title": ""},
            {"description": "é" * 2501},
            {"tags": "music"},
            {"privacyStatus": "public"},
            {"tags": ["x" * 501]},
        )

        for update in invalid_updates:
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    m.edited_snippet(
                        self.snippet,
                        update,
                    )

    def test_discovers_channel_uploads(self):
        responses = [
            {
                "items": [
                    {
                        "contentDetails": {
                            "relatedPlaylists": {
                                "uploads": "UPLOADS123"
                            }
                        }
                    }
                ]
            },
            {
                "items": [
                    {
                        "contentDetails": {
                            "videoId": "5-oJR6dVzhM"
                        }
                    }
                ]
            },
        ]

        with patch.object(
            m,
            "api",
            side_effect=responses,
        ) as api:
            result = m.discover_channel_videos(
                self.channel_id
            )

        self.assertEqual(
            result,
            ["5-oJR6dVzhM"],
        )

        self.assertEqual(api.call_count, 2)

    def test_discovers_multiple_pages(self):
        responses = [
            {
                "items": [
                    {
                        "contentDetails": {
                            "relatedPlaylists": {
                                "uploads": "UPLOADS123"
                            }
                        }
                    }
                ]
            },
            {
                "items": [
                    {
                        "contentDetails": {
                            "videoId": "5-oJR6dVzhM"
                        }
                    }
                ],
                "nextPageToken": "PAGE2",
            },
            {
                "items": [
                    {
                        "contentDetails": {
                            "videoId": "abcdefghijk"
                        }
                    }
                ]
            },
        ]

        with patch.object(
            m,
            "api",
            side_effect=responses,
        ):
            result = m.discover_channel_videos(
                self.channel_id
            )

        self.assertEqual(
            result,
            [
                "5-oJR6dVzhM",
                "abcdefghijk",
            ],
        )

    def test_fetch_videos_batches_over_50(self):
        ids = [
            f"VID{i:08d}"
            for i in range(51)
        ]

        self.assertTrue(
            all(len(video_id) == 11 for video_id in ids)
        )

        with patch.object(
            m,
            "api",
        ) as api:

            api.side_effect = [
                {
                    "items": [
                        {"id": video_id}
                        for video_id in ids[:50]
                    ]
                },
                {
                    "items": [
                        {"id": ids[50]}
                    ]
                },
            ]

            videos = m.fetch_videos(ids)

        self.assertEqual(len(videos), 51)
        self.assertEqual(api.call_count, 2)

    def test_report_creates_channel_report(self):
        video = {
            "id": "5-oJR6dVzhM",
            "snippet": self.snippet,
            "statistics": {
                "viewCount": "42",
                "likeCount": "10",
                "commentCount": "3",
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                m,
                "ROOT",
                Path(tmp),
            ):
                m.generate_report(
                    [video],
                    self.channel_id,
                )

                report = Path(
                    tmp,
                    "reports",
                    "report.md",
                ).read_text()

                snapshot = json.loads(
                    Path(
                        tmp,
                        "reports",
                        "snapshot.json",
                    ).read_text()
                )

        self.assertIn(
            "Videos discovered: 1",
            report,
        )

        self.assertIn(
            "Views: 42",
            report,
        )

        self.assertEqual(
            snapshot["channel_id"],
            self.channel_id,
        )

        self.assertEqual(
            snapshot["video_count"],
            1,
        )

    def test_wrong_channel_prevents_update(self):
        video = {
            "id": "5-oJR6dVzhM",
            "snippet": {
                **self.snippet,
                "channelId": "UCwrongchannel00000000000",
            },
        }

        config = {
            "channel_id": self.channel_id,
            "metadata_updates": {
                "5-oJR6dVzhM": {
                    "title": "New title"
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                m,
                "ROOT",
                Path(tmp),
            ):
                with self.assertRaises(
                    RuntimeError
                ):
                    m.apply_updates(
                        config,
                        [video],
                        "fake-token",
                    )


if __name__ == "__main__":
    unittest.main()
