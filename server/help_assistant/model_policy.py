"""Help model choices are server-owned; only the tiny weights coexist with speech."""
CHAT_MODEL = 'qwen3.5:2b'
LIVE_MODEL = 'lfm2.5:350m'

def model_for(mode):
    return LIVE_MODEL if mode == 'live' else CHAT_MODEL

def speech_needs_unload(loaded_tag):
    return loaded_tag != LIVE_MODEL
