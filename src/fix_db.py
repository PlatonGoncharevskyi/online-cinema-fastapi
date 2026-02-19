import sqlite3
import uuid


DB_NAME = "sql_app.db"


def fix_uuids():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("SELECT id, uuid FROM movies")
        movies = cursor.fetchall()

        fixed_count = 0
        for movie in movies:
            movie_id = movie[0]
            current_uuid = movie[1]

            if not isinstance(current_uuid, str) or len(str(current_uuid)) < 30:
                new_uid = str(uuid.uuid4())
                cursor.execute("UPDATE movies SET uuid = ? WHERE id = ?", (new_uid, movie_id))
                fixed_count += 1

        conn.commit()
        conn.close()
        print(f"✅ Успішно виправлено {fixed_count} записів!")

    except Exception as e:
        print(f"❌ Помилка: {e}")


if __name__ == "__main__":
    fix_uuids()