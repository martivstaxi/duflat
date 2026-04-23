"""Supabase client — single-module process-level singleton."""

_supabase = None


def init_supabase(url, key):
    global _supabase
    from supabase import create_client
    _supabase = create_client(url, key)
    return _supabase


def _db():
    if not _supabase:
        raise RuntimeError('cs_reviews: Supabase not initialized — set SUPABASE_URL/KEY')
    return _supabase
