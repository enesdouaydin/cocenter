# --- START OF FILE memory_utils.py ---

from typing import List, Dict, Any
import logging
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

log = logging.getLogger(__name__)

# =======================================
# Memory Manager Class
# =======================================
class MemoryManager:
    """
    Manages a simple short-term conversation memory using a list.
    Stores conversation turns as dictionaries with 'role' and 'content'.
    """
    def __init__(self, max_turns: int = 3):
        """
        Initializes the memory manager.

        Args:
            max_turns: The maximum number of conversation *turns* (1 user + 1 agent = 1 turn)
                       to keep in memory. So, max_messages = max_turns * 2.
        """
        self.max_messages = max_turns * 2
        self.memory: List[Dict[str, str]] = []
        log.info(f"MemoryManager initialized. Max turns: {max_turns}, Max messages: {self.max_messages}")

    def add_message(self, role: str, content: str):
        """
        Adds a message (user or assistant) to the memory.

        Args:
            role: 'user' or 'assistant'.
            content: The text content of the message.
        """
        if not content: # Avoid adding empty messages
            log.debug("Skipping empty message addition to memory.")
            return

        message = {"role": role, "content": content}
        self.memory.append(message)
        log.debug(f"Added to memory: {message}")

        # Trim old messages if memory exceeds the maximum size
        if len(self.memory) > self.max_messages:
            excess = len(self.memory) - self.max_messages
            self.memory = self.memory[excess:]
            log.debug(f"Memory trimmed. Removed {excess} oldest messages.")

    def get_memory(self) -> List[Dict[str, str]]:
        """Returns the current conversation history."""
        return self.memory

    def get_memory_as_string(self, separator: str = "\n---\n") -> str:
        """Returns the memory concatenated into a single string."""
        return separator.join([f"{msg['role'].title()}: {msg['content']}" for msg in self.memory])

    def clear_memory(self):
        """Clears the conversation memory."""
        self.memory = []
        log.info("Memory cleared.")


# =======================================
# Memory Verifier Class
# =======================================
class MemoryVerifier:
    """
    Checks the relevance of the current user query against recent conversation memory
    using TF-IDF and Cosine Similarity.
    """
    def __init__(self, relevance_threshold: float = 0.2):
        """
        Initializes the memory verifier.

        Args:
            relevance_threshold: The cosine similarity score above which memory is
                                 considered relevant (default: 0.2). Adjust as needed.
        """
        self.threshold = relevance_threshold
        # Initialize vectorizer here to reuse it
        self.vectorizer = TfidfVectorizer()
        log.info(f"MemoryVerifier initialized. Relevance threshold: {self.threshold}")

    def is_memory_relevant(self, current_query: str, memory: List[Dict[str, str]]) -> bool:
        """
        Checks if the conversation memory is relevant to the current query.

        Args:
            current_query: The latest user message.
            memory: The list of conversation history dictionaries from MemoryManager.

        Returns:
            True if memory is considered relevant, False otherwise.
        """
        if not memory or not current_query:
            log.debug("Memory relevance check: No memory or query provided. Returning False.")
            return False

        # Combine memory messages into a single string
        # Only include content from messages that have content
        history_text = "\n".join([msg.get('content', '') for msg in memory if msg.get('content')])
        if not history_text.strip():
             log.debug("Memory relevance check: Memory contains only empty strings. Returning False.")
             return False

        try:
            # Fit and transform using the current query and the combined history
            # Use the instance vectorizer
            tfidf_matrix = self.vectorizer.fit_transform([current_query, history_text])

            # Calculate cosine similarity between the query vector (index 0) and the history vector (index 1)
            # Ensure matrix shape allows comparison
            if tfidf_matrix.shape[0] < 2:
                log.warning("TF-IDF matrix has less than 2 rows, cannot compute similarity.")
                return False

            similarity_score = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]

            log.debug(f"Memory relevance check: Similarity score = {similarity_score:.4f}")

            # Compare score against the threshold
            is_relevant = similarity_score > self.threshold
            log.info(f"Memory relevance: {'Relevant' if is_relevant else 'Not Relevant'} (Score: {similarity_score:.4f}, Threshold: {self.threshold})")
            return is_relevant

        except ValueError as ve:
             # Catch specific ValueError often related to empty vocabulary
             log.error(f"TF-IDF ValueError: {ve}. Might be due to stop words or empty input.", exc_info=False)
             return False
        except Exception as e:
            # Handle other potential errors during vectorization
            log.error(f"Error during TF-IDF/Cosine Similarity calculation: {e}", exc_info=True)
            return False # Default to not relevant in case of error

# --- END OF FILE memory_utils.py ---