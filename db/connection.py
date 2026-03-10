from contextlib import contextmanager
import pyodbc
import config


@contextmanager
def get_connection():
    conn = pyodbc.connect(config.DB_CONNECTION_STRING, autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
