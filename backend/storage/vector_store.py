import chromadb
from chromadb.utils import embedding_functions
from typing import List, Tuple, Sequence
from backend.data_models.models import TranscriptChunk, Video
from backend.utils.logger import log
import os

class VectorStore:
    def __init__(self):
        # Initialize ChromaDB client (persistent storage)
        self.client = chromadb.PersistentClient(path="./chroma_db")
        
        # Use a default embedding function
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        
        # Collection for Transcript Chunks (Deep Content)
        self.chunks_collection = self.client.get_or_create_collection(
            name="learning_agent_videos",
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"} # Use cosine distance for better semantic matching
        )
        
        # Collection for Video Titles (Metadata / Semantic Discovery)
        self.titles_collection = self.client.get_or_create_collection(
            name="video_titles",
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"}
        )
        
        log(f"VectorStore initialized with collections: learning_agent_videos, video_titles")

    def save_chunks(self, chunks: List[TranscriptChunk]):
        """
        Saves transcript chunks to the vector store.
        """
        if not chunks:
            return

        ids = [f"{chunk.video_id}_{chunk.chunk_index if chunk.chunk_index is not None else i}" for i, chunk in enumerate(chunks)]
        documents = [chunk.text for chunk in chunks]
        metadatas = [
            {
                "video_id": chunk.video_id,
                "start_time": chunk.start_time,
                "end_time": chunk.end_time,
                "chunk_index": chunk.chunk_index if chunk.chunk_index is not None else i,
            } 
            for i, chunk in enumerate(chunks)
        ]

        self.chunks_collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        log(f"Saved {len(chunks)} chunks to vector store.")

    def search(self, query_text: str, top_k: int = 5) -> List[TranscriptChunk]:
        """
        Searches for relevant chunks based on a query text.
        """
        log(f"Searching chunks for: {query_text}")
        results = self.chunks_collection.query(
            query_texts=[query_text],
            n_results=top_k
        )
        
        chunks = []
        if results['documents']:
            for i in range(len(results['documents'][0])):
                chunk = TranscriptChunk(
                    video_id=results['metadatas'][0][i]['video_id'],
                    text=results['documents'][0][i],
                    start_time=results['metadatas'][0][i]['start_time'],
                    end_time=results['metadatas'][0][i]['end_time']
                )
                chunks.append(chunk)
                
        log(f"Chunk search returned {len(chunks)} results.")
        return chunks

    def search_in_videos(self, query_text: str, video_ids: List[str], top_k: int = 5, threshold: float = 0.4) -> List[TranscriptChunk]:
        """
        Searches for relevant chunks ONLY within specific videos.
        Returns chunks with distance < threshold (lower distance = better match).
        """
        if not video_ids:
            return []
            
        log(f"Searching chunks in {len(video_ids)} videos for: {query_text}")
        
        try:
            results = self.chunks_collection.query(
                query_texts=[query_text],
                n_results=top_k,
                where={"video_id": {"$in": video_ids}}, # Filter by video IDs
                include=["documents", "metadatas", "distances"] # Include distances
            )
            
            chunks = []
            if results['documents']:
                for i in range(len(results['documents'][0])):
                    distance = results['distances'][0][i]
                    
                    # Filter by threshold (cosine distance: 0=identical, 1=orthogonal, 2=opposite)
                    # Lower is better. 0.4 is a reasonable threshold for semantic similarity.
                    if distance > threshold:
                        continue
                        
                    chunk = TranscriptChunk(
                        video_id=results['metadatas'][0][i]['video_id'],
                        text=results['documents'][0][i],
                        start_time=results['metadatas'][0][i]['start_time'],
                        end_time=results['metadatas'][0][i]['end_time']
                    )
                    chunks.append(chunk)
                    
            log(f"Filtered search returned {len(chunks)} results (threshold={threshold}).")
            return chunks
            
        except Exception as e:
            log(f"Error searching in videos: {e}", "ERROR")
            return []

    # --- New Methods for Title Search ---

    def add_video_titles(self, videos: List[Video]):
        """
        Indexes video titles for semantic search.
        """
        if not videos:
            return
            
        ids = [v.id for v in videos]
        documents = [v.title for v in videos] # We embed the title
        metadatas = [{"video_id": v.id, "title": v.title} for v in videos]
        
        self.titles_collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        log(f"Indexed {len(videos)} video titles for semantic search.")

    def search_video_titles(self, query_text: str, top_k: int = 10) -> List[str]:
        """
        Searches for relevant videos based on title semantics.
        Returns a list of video_ids.
        """
        log(f"Searching titles for: {query_text}")
        results = self.titles_collection.query(
            query_texts=[query_text],
            n_results=top_k
        )
        
        video_ids = []
        if results['ids']:
            video_ids = results['ids'][0]
            
        log(f"Title search returned {len(video_ids)} relevant videos.")
        return video_ids

    def search_in_videos_with_scores(
        self,
        query_text: str,
        video_ids: Sequence[str],
        top_k: int = 40,
    ) -> List[Tuple[TranscriptChunk, float]]:
        """Return semantic candidates and cosine distances without threshold pruning."""
        if not video_ids or self.chunks_collection.count() == 0:
            return []
        result_count = min(top_k, self.chunks_collection.count())
        try:
            results = self.chunks_collection.query(
                query_texts=[query_text],
                n_results=result_count,
                where={"video_id": {"$in": list(video_ids)}},
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            log(f"Scored chunk search failed: {exc}", "ERROR")
            return []

        candidates = []
        for document, metadata, distance in zip(
            results.get("documents", [[]])[0],
            results.get("metadatas", [[]])[0],
            results.get("distances", [[]])[0],
        ):
            candidates.append((TranscriptChunk(
                video_id=metadata["video_id"],
                text=document,
                start_time=metadata["start_time"],
                end_time=metadata["end_time"],
                chunk_index=metadata.get("chunk_index"),
            ), float(distance)))
        return candidates

    def get_all_chunks(self) -> List[TranscriptChunk]:
        """Read existing Chroma chunks for one-time migration into SQLite."""
        if self.chunks_collection.count() == 0:
            return []
        results = self.chunks_collection.get(include=["documents", "metadatas"])
        chunks = []
        for document, metadata in zip(results.get("documents", []), results.get("metadatas", [])):
            chunks.append(TranscriptChunk(
                video_id=metadata["video_id"],
                text=document,
                start_time=metadata["start_time"],
                end_time=metadata["end_time"],
                chunk_index=metadata.get("chunk_index"),
            ))
        return chunks

    def delete_channel_data(self, video_ids: List[str]):
        """
        Deletes all data associated with a list of video IDs.
        """
        if not video_ids:
            return

        # Delete from titles collection
        try:
            self.titles_collection.delete(ids=video_ids)
            log(f"Deleted {len(video_ids)} titles from vector store.")
        except Exception as e:
            log(f"Error deleting titles: {e}", "ERROR")

        # Delete from chunks collection
        try:
            self.chunks_collection.delete(
                where={"video_id": {"$in": video_ids}}
            )
            log(f"Deleted chunks for {len(video_ids)} videos from vector store.")
        except Exception as e:
            log(f"Error deleting chunks: {e}", "ERROR")
