# Community 36

Nodes: 25

## Members
- **tts_cache.py** (`backend/app/tts_cache.py`)
- **CachedTTSEntry** (`backend/app/tts_cache.py`)
- **make_cache_key()** (`backend/app/tts_cache.py`)
- **_record_error()** (`backend/app/tts_cache.py`)
- **_decode_cache_payload()** (`backend/app/tts_cache.py`)
- **_to_redis_mapping()** (`backend/app/tts_cache.py`)
- **cache_get()** (`backend/app/tts_cache.py`)
- **cache_put()** (`backend/app/tts_cache.py`)
- **TTS Redis cache layer — async, gracefully degrades if Redis is unavailable.** (`backend/app/tts_cache.py`)
- **Return the Redis key for a TTS payload.** (`backend/app/tts_cache.py`)
- **Fetch an entry from Redis. Returns None on miss or error.** (`backend/app/tts_cache.py`)
- **Store an entry in Redis. Errors are recorded and otherwise ignored.** (`backend/app/tts_cache.py`)
- **test_tts_cache.py** (`backend/tests/tts/test_tts_cache.py`)
- **TestMakeCacheKey** (`backend/tests/tts/test_tts_cache.py`)
- **.test_is_deterministic()** (`backend/tests/tts/test_tts_cache.py`)
- **.test_changes_when_input_changes()** (`backend/tests/tts/test_tts_cache.py`)
- **.test_matches_expected_sha256_format()** (`backend/tests/tts/test_tts_cache.py`)
- **test_cache_get_returns_none_when_redis_unavailable()** (`backend/tests/tts/test_tts_cache.py`)
- **test_cache_get_returns_none_on_miss()** (`backend/tests/tts/test_tts_cache.py`)
- **test_cache_get_returns_cached_entry_on_hit()** (`backend/tests/tts/test_tts_cache.py`)
- **test_cache_get_returns_none_when_redis_errors()** (`backend/tests/tts/test_tts_cache.py`)
- **test_cache_put_is_noop_when_redis_unavailable()** (`backend/tests/tts/test_tts_cache.py`)
- **test_cache_put_writes_hash_and_ttl()** (`backend/tests/tts/test_tts_cache.py`)
- **test_cache_put_is_noop_when_redis_errors()** (`backend/tests/tts/test_tts_cache.py`)
- **Tests for the Redis-backed TTS cache helpers.** (`backend/tests/tts/test_tts_cache.py`)

## Connections to other communities
- Community 0
