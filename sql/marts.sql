-- Current facts, rebuilt views: late corrections update every dependent metric.
DROP VIEW IF EXISTS mart_summary;
CREATE VIEW mart_summary AS
SELECT COUNT(*) AS trips,
       ROUND(SUM(fare_usd),2) AS fare_usd,
       ROUND(AVG(fare_usd),2) AS avg_fare_usd,
       ROUND(SUM(distance_miles),2) AS distance_miles,
       SUM(CASE WHEN arrival_lag_hours>24 THEN 1 ELSE 0 END) AS late_trips,
       ROUND(100.0*SUM(CASE WHEN arrival_lag_hours>24 THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),2) AS late_trip_pct,
       SUBSTR(MIN(pickup_at),1,10) AS period_start,
       SUBSTR(MAX(pickup_at),1,10) AS period_end,
       (SELECT COALESCE(SUM(raw_rows),0) FROM batches) AS raw_rows,
       (SELECT COUNT(*) FROM quarantine) AS rejected_rows,
       (SELECT COALESCE(SUM(duplicate_rows),0) FROM batches) AS duplicate_rows,
       (SELECT COALESCE(SUM(corrected_rows),0) FROM batches) AS corrected_rows,
       (SELECT COUNT(*) FROM batches) AS committed_batches,
       ROUND(100.0*(SELECT COUNT(*) FROM quarantine)/NULLIF((SELECT SUM(raw_rows) FROM batches),0),2) AS rejection_pct
FROM trips;
DROP VIEW IF EXISTS mart_daily;
CREATE VIEW mart_daily AS
SELECT SUBSTR(pickup_at,1,10) AS date, COUNT(*) AS trips,
       ROUND(SUM(fare_usd),2) AS fare_usd,
       ROUND(AVG(fare_usd),2) AS avg_fare_usd,
       SUM(CASE WHEN arrival_lag_hours>24 THEN 1 ELSE 0 END) AS late_trips
FROM trips GROUP BY 1;
DROP VIEW IF EXISTS mart_zone;
CREATE VIEW mart_zone AS
SELECT pickup_zone, COUNT(*) AS trips, ROUND(SUM(fare_usd),2) AS fare_usd,
       ROUND(AVG(distance_miles),2) AS avg_distance_miles,
       ROUND(AVG((JULIANDAY(dropoff_at)-JULIANDAY(pickup_at))*1440),1) AS avg_duration_min,
       SUM(CASE WHEN arrival_lag_hours>24 THEN 1 ELSE 0 END) AS late_trips
FROM trips GROUP BY 1;
DROP VIEW IF EXISTS mart_hourly;
CREATE VIEW mart_hourly AS
SELECT CAST(SUBSTR(pickup_at,12,2) AS INTEGER) AS hour,
       COUNT(*) AS trips, ROUND(SUM(fare_usd),2) AS fare_usd
FROM trips GROUP BY 1;
