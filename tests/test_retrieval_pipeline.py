import json
import tempfile
import unittest
from unittest.mock import Mock
from datetime import datetime
from pathlib import Path

from backend.data_models.models import TranscriptChunk, Video
from backend.ingestion.text_processor import TextProcessor
from backend.pipeline.layers.context_layer import ContextLayer
from backend.pipeline.layers.content_layer import ContentLayer
from backend.pipeline.layers.video_layer import VideoLayer
from backend.storage.transcript_store import TranscriptStore
from backend.storage.video_store import VideoStore
from backend.utils.token_budget import TokenBudgets, TokenCounter, trim_history


class RetrievalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test.db")
        self.channels_path = Path(self.temp_dir.name) / "channels.json"
        self.video_store = VideoStore(self.db_path)
        self.transcript_store = TranscriptStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def chunks(video_id="video123"):
        return [
            TranscriptChunk(video_id=video_id, text=f"chunk {index} dieting fatigue reps", start_time=index * 60, end_time=(index + 1) * 60, chunk_index=index)
            for index in range(5)
        ]

    def test_text_processor_assigns_sequential_chunk_indexes(self):
        raw = [
            TranscriptChunk(video_id="v", text=f"event {i}", start_time=i * 20, end_time=(i + 1) * 20)
            for i in range(6)
        ]
        processed = TextProcessor(max_chunk_duration=60).process_transcript(raw)
        self.assertEqual([chunk.chunk_index for chunk in processed], list(range(len(processed))))

    def test_transcript_store_replaces_searches_and_expands(self):
        chunks = self.chunks()
        self.transcript_store.replace_video_chunks("video123", chunks)
        self.assertEqual(self.transcript_store.count_chunks(), 5)

        results = self.transcript_store.search("dieting fatigue", ["video123"], limit=3)
        self.assertTrue(results)
        window = self.transcript_store.get_window("video123", 2, radius=1)
        self.assertEqual([chunk.chunk_index for chunk in window], [1, 2, 3])

        replacement = chunks[:2]
        self.transcript_store.replace_video_chunks("video123", replacement)
        self.assertEqual(self.transcript_store.count_chunks(), 2)

    def test_window_respects_video_boundaries(self):
        self.transcript_store.replace_video_chunks("video123", self.chunks())
        self.assertEqual(
            [chunk.chunk_index for chunk in self.transcript_store.get_window("video123", 0)],
            [0, 1],
        )
        self.assertEqual(
            [chunk.chunk_index for chunk in self.transcript_store.get_window("video123", 4)],
            [3, 4],
        )

    def test_video_rescan_preserves_transcript_state(self):
        video = Video(
            id="video123", channel_id="channel123", title="Original",
            url="https://youtube.com/watch?v=video123", published_at=datetime.now(),
        )
        self.video_store.add_videos([video])
        self.video_store.mark_transcript_downloaded("video123")
        refreshed = video.model_copy(update={"title": "Updated", "transcript_downloaded": False})
        self.video_store.add_videos([refreshed])
        stored = self.video_store.get_video("video123")
        self.assertEqual(stored.title, "Updated")
        self.assertTrue(stored.transcript_downloaded)

    def test_sources_group_timestamps_under_one_video(self):
        video = Video(
            id="video123", channel_id="channel123", title="Training While Cutting",
            url="https://youtube.com/watch?v=video123", published_at=datetime.now(),
        )
        self.video_store.add_videos([video])
        self.channels_path.write_text(json.dumps([
            {"id": "channel123", "name": "Example Channel", "last_scanned": None}
        ]))
        context = ContextLayer(self.video_store, str(self.channels_path))
        sources = context.build_sources(self.chunks()[:3])
        self.assertEqual(sources.count("Example Channel"), 1)
        self.assertEqual(sources.count("Training While Cutting"), 1)
        self.assertIn("[0:00]", sources)
        self.assertIn("[1:00]", sources)
        self.assertIn("[2:00]", sources)

    def test_history_budget_keeps_newest_complete_turns(self):
        counter = TokenCounter("not-a-cached-model")
        history = [
            {"role": "user", "content": "old question " * 20},
            {"role": "assistant", "content": "old answer " * 20},
            {"role": "user", "content": "What about beginners?"},
            {"role": "assistant", "content": "They need less volume."},
        ]
        trimmed = trim_history(history, counter, limit=30)
        self.assertEqual(trimmed[0]["content"], "What about beginners?")
        self.assertEqual(trimmed[-1]["content"], "They need less volume.")

    def test_history_drops_generated_sources(self):
        counter = TokenCounter("not-a-cached-model")
        history = [{
            "role": "assistant",
            "content": "The direct answer.\n\n## Sources\n- a very long citation",
        }]
        trimmed = trim_history(history, counter, limit=100)
        self.assertEqual(trimmed[0]["content"], "The direct answer.")

    def test_configured_budget_fits_observed_provider_limit(self):
        self.assertEqual(TokenBudgets().total, 8_000)

    def test_budget_preserves_late_relevant_passage_and_matching_citations(self):
        self.video_store.add_videos([Video(
            id="video123", channel_id="channel123", title="Macros",
            url="https://youtube.com/watch?v=video123", published_at=datetime.now(),
        )])
        early = self.chunks()[0].model_copy(update={"text": "Introduction " * 200})
        late = self.chunks()[4].model_copy(update={"text": "Cut fats first, then carbs; keep protein."})
        layer = ContextLayer(self.video_store, str(self.channels_path))
        counter = TokenCounter("not-a-cached-model")
        selected = layer.select_chunks([late, early], counter, 200)
        context = layer.execute([late, early], counter, 200)
        self.assertIn(late.text, context)
        self.assertNotIn(early.text, context)
        self.assertLessEqual(counter.count(context), 200)
        sources = layer.build_sources(selected)
        self.assertIn("[4:00]", sources)
        self.assertNotIn("[0:00]", sources)

    def test_direct_video_does_not_expand_to_channel_transcripts(self):
        videos, vectors, transcripts, ingestion = Mock(), Mock(), Mock(), Mock()
        videos.get_video.return_value = Mock(transcript_downloaded=True)
        vectors.search_in_videos_with_scores.return_value = []
        transcripts.search.return_value = []
        layer = ContentLayer(ingestion, vectors, videos, transcripts)
        layer.execute({"video_id": "requested", "original_question": "macros"}, ["requested"], ["channel"])
        videos.get_ready_video_ids_by_channels.assert_not_called()
        self.assertEqual(vectors.search_in_videos_with_scores.call_args.args[1], ["requested"])
        self.assertEqual(transcripts.search.call_args.args[1], ["requested"])

    def test_direct_video_overrides_channel_routing_and_never_substitutes(self):
        videos, vectors = Mock(), Mock()
        videos.get_video.return_value = Mock(channel_id="different")
        layer = VideoLayer(videos, vectors)
        self.assertEqual(layer.execute({"video_id": "requested"}, ["channel"]), ["requested"])
        videos.get_video.return_value = None
        self.assertEqual(layer.execute({"video_id": "missing"}, ["channel"]), [])
        vectors.search_video_titles.assert_not_called()


if __name__ == "__main__":
    unittest.main()
