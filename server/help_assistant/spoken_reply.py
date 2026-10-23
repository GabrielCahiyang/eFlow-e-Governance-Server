"""Keep voice turns concise while retaining the complete sourced written reply."""
import re

def spoken_parts(text):
    """Word-boundary chunks of the same checked summary, never invented filler."""
    remaining = spoken_summary(text)
    parts = []
    while len(remaining) > (32 if not parts else 65):
        limit = 32 if not parts else 65
        minimum = 16 if not parts else 24
        # Prefer a natural clause ending; otherwise preserve whole words.
        boundaries = [match.end() for match in re.finditer(r'[,;:!?\.]\s+', remaining[:limit + 1]) if match.end() >= minimum]
        end = boundaries[-1] if boundaries else remaining.rfind(' ', minimum, limit)
        if end < minimum:
            break  # Do not split a single long name/token.
        parts.append(remaining[:end].strip())
        remaining = remaining[end:].strip()
    if remaining:
        parts.append(remaining)
    return parts or ['Please check the written answer.']

def spoken_summary(text, limit=150):
    text = ' '.join(text.split())
    if len(text) <= limit:
        return text
    sentences = re.split(r'(?<=[.!?])\s+', text)
    # Speak one useful complete sentence first. The full sourced answer is
    # already visible, and generating a long recap delays every voice turn.
    for sentence in sentences:
        if len(sentence) <= limit:
            return sentence
        break
    # Never cut a task/person name or a currency amount into a false statement.
    return 'Please check the written answer and its sources for the full eFlow details.'
