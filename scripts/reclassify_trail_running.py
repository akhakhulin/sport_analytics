"""Переклассифицировать 6 беговых активностей с 01.04.2026 в trail_running.
Критерий: elevation per km >= 8 ИЛИ (км >= 8 + elev >= 100).

Также вывести список activity_id + URL Garmin Connect для ручной правки в mobile app.
"""
import sqlite3

DB = 'data/garmin.db'
c = sqlite3.connect(DB)

# Найти кандидатов
rows = c.execute("""
    SELECT activity_id, substr(start_time_local,1,10) as day,
           activity_name, distance_m/1000.0 as km,
           elevation_gain_m,
           ROUND(elevation_gain_m * 1000.0 / NULLIF(distance_m,0), 1) as elev_per_km
    FROM activities
    WHERE athlete_id='akhakhulin'
      AND activity_type='running'
      AND substr(start_time_local,1,10) >= '2026-04-01'
      AND distance_m > 0
      AND (
          elevation_gain_m * 1000.0 / distance_m >= 8
          OR (distance_m >= 8000 AND elevation_gain_m >= 100)
      )
    ORDER BY day
""").fetchall()

ids = [r[0] for r in rows]
print(f'Кандидатов: {len(ids)}')
print()
print('=== Будут изменены ===')
for r in rows:
    print(f'{r[1]} | id={r[0]} | {r[3]:.1f}км / {int(r[4])}м el ({r[5]}м/км) | {r[2]}')
    print(f'  Garmin Connect: https://connect.garmin.com/app/activity/{r[0]}')
print()

# UPDATE
placeholders = ','.join('?' * len(ids))
c.execute(
    f"UPDATE activities SET activity_type='trail_running' WHERE activity_id IN ({placeholders})",
    ids,
)
c.commit()
print(f'UPDATED {c.total_changes} rows in activities')

# Проверка
print()
print('=== После UPDATE — проверка ===')
res = c.execute(f"""
    SELECT activity_id, activity_type, activity_name
    FROM activities WHERE activity_id IN ({placeholders})
""", ids).fetchall()
for r in res:
    print(f'  {r[0]} | type={r[1]} | {r[2]}')

c.close()
print()
print('Done!')
