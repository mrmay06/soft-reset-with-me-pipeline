import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import patch

from modules import research_agent as short


OLD = "2020-01-01T00:00:00Z"


class _Request:
    def __init__(self, handler, kwargs):
        self.handler, self.kwargs = handler, kwargs

    def execute(self):
        return self.handler(**self.kwargs)


class _Resource:
    def __init__(self, client, name):
        self.client, self.name = client, name

    def list(self, **kwargs):
        self.client.calls.append((self.name, kwargs))
        return _Request(getattr(self.client, f"_{self.name}"), kwargs)


class FakeYouTube:
    """search -> (video, channel, title); videos -> (views, seconds); channels -> uploads ids."""

    def __init__(self, search, videos, uploads, fail=()):
        self.search_items, self.video_data, self.uploads = search, videos, uploads
        self.fail, self.calls = set(fail), []

    def __getattr__(self, name):
        if name in ("search", "videos", "channels", "playlistItems"):
            return lambda: _Resource(self, name)
        raise AttributeError(name)

    def _check(self, name):
        if name in self.fail:
            raise RuntimeError(f"{name} unavailable")

    def _search(self, q, **_):
        self._check("search")
        return {"items": [{"id": {"videoId": v}, "snippet": {"channelId": c, "title": t}}
                          for v, c, t in self.search_items.get(q, [])]}

    def _videos(self, id, **_):
        self._check("videos")
        items = []
        for video_id in id.split(","):
            if video_id in self.video_data:
                views, seconds = self.video_data[video_id]
                items.append({"id": video_id, "statistics": {"viewCount": str(views)},
                              "contentDetails": {"duration": f"PT{seconds // 60}M{seconds % 60}S"}})
        return {"items": items}

    def _channels(self, id, **_):
        self._check("channels")
        return {"items": [{"id": c, "contentDetails": {"relatedPlaylists": {"uploads": f"UU{c}"}}}
                          for c in id.split(",") if c in self.uploads]}

    def _playlistItems(self, playlistId, maxResults, **_):
        self._check("playlistItems")
        uploads = self.uploads[playlistId[2:]][:maxResults]
        return {"items": [{"contentDetails": {"videoId": v, "videoPublishedAt": published}}
                          for v, published in uploads]}


def _fixture(**overrides):
    search = {"relationship advice": [
        ("big1", "chanBig", "Big channel typical relationship short"),
        ("small1", "chanSmall", "Small channel breakout about rereading texts"),
        ("thin1", "chanThin", "Thin channel title that cannot be scored"),
    ], "dating advice": [
        ("mid1", "chanMid", "Mid channel modest overperformer title"),
    ]}
    videos = {
        "big1": (1_000_000, 40), "small1": (34_000, 30), "thin1": (90_000, 30), "mid1": (25_000, 50),
        # chanBig baseline ~1M: big1 is ordinary for its channel.
        **{f"big_b{i}": (900_000 + i * 50_000, 45) for i in range(5)},
        # chanSmall baseline median 10k; one long upload must not count.
        **{f"small_b{i}": (8_000 + i * 1_000, 35) for i in range(5)}, "small_long": (500_000, 900),
        # chanMid baseline 10k -> 2.5x.
        **{f"mid_b{i}": (10_000, 30) for i in range(4)},
        "thin_b0": (1_000, 30), "thin_b1": (1_000, 30),
    }
    uploads = {
        "chanBig": [("big1", OLD)] + [(f"big_b{i}", OLD) for i in range(5)],
        "chanSmall": [("small1", OLD), ("small_long", OLD)] + [(f"small_b{i}", OLD) for i in range(5)],
        "chanMid": [(f"mid_b{i}", OLD) for i in range(4)],
        "chanThin": [("thin1", OLD), ("thin_b0", OLD), ("thin_b1", OLD)],
    }
    return FakeYouTube(overrides.get("search", search), overrides.get("videos", videos),
                       overrides.get("uploads", uploads), overrides.get("fail", ()))


def _harvest(client, settings=None):
    with patch.object(short, "_youtube_client", return_value=client), redirect_stdout(io.StringIO()) as out:
        result = short._harvest_youtube(days=7, settings=settings)
    return result, out.getvalue()


class YouTubeOutlierSignalTests(unittest.TestCase):
    def test_outliers_are_ranked_by_channel_multiple_not_raw_views(self):
        result, log = _harvest(_fixture())
        self.assertEqual(result, [
            "Small channel breakout about rereading texts (3.4x channel median)",
            "Mid channel modest overperformer title (2.5x channel median)",
        ])
        self.assertIn("quota units", log)

    def test_thin_channels_and_long_uploads_are_kept_out_of_the_baseline(self):
        client = _fixture()
        outliers, scored = short._youtube_channel_outliers(
            client, short._youtube_search(client, 7, short._YouTubeQuota(30)),
            dict(short._YOUTUBE_OUTLIER_DEFAULTS), short._YouTubeQuota(30))
        self.assertEqual(scored, 3)  # chanThin has only 2 other Shorts
        small = next(o for o in outliers if o["channel_id"] == "chanSmall")
        self.assertEqual(small["channel_median"], 10_000)

    def test_young_uploads_are_excluded_from_the_baseline(self):
        client = _fixture()
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        client.uploads["chanMid"] = [(f"mid_b{i}", now) for i in range(4)]
        result, _ = _harvest(client)
        self.assertNotIn("Mid channel", " ".join(result))

    def test_threshold_is_configurable(self):
        result, _ = _harvest(_fixture(), {"youtube_outlier_min_multiple": 3.0})
        self.assertEqual(len(result), 1)

    def test_scoring_failure_falls_back_to_plain_titles(self):
        for failing in ("videos", "channels", "playlistItems"):
            with self.subTest(failing=failing):
                result, log = _harvest(_fixture(fail={failing}))
                if failing == "playlistItems":
                    # Per-channel failures leave no baseline at all, which also falls back.
                    self.assertIn("plain titles", log)
                self.assertEqual(result[0], "Big channel typical relationship short")
                self.assertTrue(all("channel median" not in title for title in result))

    def test_disabled_scoring_returns_plain_titles_without_list_calls(self):
        client = _fixture()
        result, _ = _harvest(client, {"youtube_outlier_enabled": False})
        self.assertEqual(len(result), 4)
        self.assertEqual({name for name, _ in client.calls}, {"search"})

    def test_list_call_cap_limits_channels(self):
        client = _fixture()
        _harvest(client, {"youtube_outlier_max_list_calls": 5})
        list_calls = [name for name, _ in client.calls if name != "search"]
        self.assertLessEqual(len(list_calls), 5)
        self.assertEqual(sum(name == "playlistItems" for name in list_calls), 2)

    def test_search_failure_and_missing_client_never_raise(self):
        self.assertEqual(_harvest(_fixture(fail={"search"}))[0], [])
        self.assertEqual(_harvest(None)[0], [])
        with patch.object(short, "_youtube_client", side_effect=RuntimeError("token")), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(short._harvest_youtube(), [])

    def test_quota_estimate_counts_search_and_list_calls(self):
        quota = short._YouTubeQuota(30)
        client = _fixture()
        items = short._youtube_search(client, 7, quota)
        short._youtube_channel_outliers(client, items, dict(short._YOUTUBE_OUTLIER_DEFAULTS), quota)
        self.assertEqual(quota.units, 5 * 100 + quota.list_calls)
        self.assertEqual(quota.list_calls, 1 + 1 + 4 + 1)

    def test_duration_parser(self):
        self.assertEqual(short._iso_duration_seconds("PT1M5S"), 65)
        self.assertEqual(short._iso_duration_seconds("PT45S"), 45)
        self.assertEqual(short._iso_duration_seconds("P0D"), 0)
        self.assertIsNone(short._iso_duration_seconds("garbage"))

    def test_signals_pass_configured_settings_and_annotations_reach_prompt(self):
        with patch.object(short, "_harvest_youtube", return_value=["A title (3.4x channel median)"]) as fetch:
            signals = short._harvest_signals("now 7-d", {"research_signal_sources": ["youtube"],
                                                         "youtube_outlier_min_multiple": 3})
        fetch.assert_called_once_with(days=7, settings={"youtube_outlier_min_multiple": 3})
        with patch.object(short, "_assert_gemini_key"), patch.object(short, "weekly_direction_prompt", return_value=""), \
             patch.object(short, "generate_json", return_value=[]) as model, redirect_stdout(io.StringIO()):
            short._generate_candidates.__wrapped__(signals, [], [], [], {}, "test")
        prompt = model.call_args.args[0]
        self.assertIn("- [youtube] A title (3.4x channel median)", prompt)
        self.assertIn("not proof", prompt)


if __name__ == "__main__":
    unittest.main()
