SELECT o.timestamp, o.limit_id, o.slot, o.plan, o.used_percent,
       o.duration_minutes, o.resets_at, o.reset_credits,
       r.read_id, r.timestamp AS retrieved_at
FROM quota_provenance p
JOIN quota_observations o USING (observation_key)
JOIN quota_reads r ON r.read_id = CAST(SUBSTR(p.source_key, 6) AS INTEGER)
WHERE p.provenance = 'live' AND p.source_key LIKE 'read:%'
  AND o.limit_id = ? AND o.duration_minutes = ? AND o.timestamp >= ?
ORDER BY r.read_id, o.timestamp;
