"""Retention affects capture bodies only, never execution or conversation rows."""

EXPIRE_CAPTURE_AGE = """
UPDATE model_request_captures
SET payload = NULL, payload_bytes = 0, state = 'expired',
    expired_at = :now, expiry_reason = 'age_limit'
WHERE payload IS NOT NULL AND created_at < :cutoff
"""

RETAINED_CAPTURE_BYTES = """
SELECT COALESCE(SUM(payload_bytes), 0)
FROM model_request_captures
WHERE payload IS NOT NULL
"""

OLDEST_CAPTURE_BODIES = """
SELECT id, payload_bytes
FROM model_request_captures
WHERE payload IS NOT NULL
ORDER BY created_at, id
"""

EXPIRE_CAPTURE_STORAGE = """
UPDATE model_request_captures
SET payload = NULL, payload_bytes = 0, state = 'expired',
    expired_at = :now, expiry_reason = 'storage_limit'
WHERE id = :capture_id AND payload IS NOT NULL
"""
