SELECT o.*, JSON_GROUP_ARRAY(DISTINCT p.provenance) AS origins
FROM quota_observations o
JOIN quota_provenance p USING (observation_key)
WHERE o.limit_id = ? AND o.duration_minutes = ? AND o.last_timestamp >= ?
GROUP BY o.observation_key
ORDER BY o.timestamp, o.rowid;
