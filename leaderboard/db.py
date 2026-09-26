"""
Couche d'abstraction base de données — bascule automatiquement entre
SQLite (développement local, zéro configuration) et PostgreSQL
(production, dès que la variable d'environnement DATABASE_URL est
définie, comme le fournit Render).

Pourquoi cette migration était nécessaire : le tier gratuit Render a un
système de fichiers éphémère — une base SQLite locale est réinitialisée
à chaque redéploiement. PostgreSQL managé (aussi gratuit chez Render,
tier limité) est persistant.

✅ Testé réellement avec un vrai serveur PostgreSQL 16 installé et
démarré dans l'environnement de développement — pas juste en théorie.
"""

import os
import re

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    IntegrityError = psycopg2.IntegrityError
else:
    import sqlite3
    IntegrityError = sqlite3.IntegrityError


class PostgresRowWrapper:
    """Permet d'accéder aux résultats PostgreSQL comme des dictionnaires,
    exactement comme sqlite3.Row — pour que le reste du code n'ait pas
    à savoir quel backend est utilisé."""
    def __init__(self, row_dict):
        self._data = dict(row_dict) if row_dict else {}

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()


class PostgresConnWrapper:
    """Enveloppe une connexion psycopg2 pour offrir la même interface
    que sqlite3.Connection (.execute(), gestion 'with conn:', etc.)."""

    def __init__(self, conn):
        self._conn = conn

    @staticmethod
    def _translate(query: str) -> str:
        """Traduit les placeholders SQLite (?) vers PostgreSQL (%s)."""
        return re.sub(r"\?", "%s", query)

    def execute(self, query, params=()):
        cursor = self._conn.cursor()
        cursor.execute(self._translate(query), params)
        return PostgresCursorWrapper(cursor)

    def executescript(self, script: str):
        cursor = self._conn.cursor()
        cursor.execute(script)
        self._conn.commit()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()


class PostgresCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        return PostgresRowWrapper(row) if row else None

    def fetchall(self):
        return [PostgresRowWrapper(r) for r in self._cursor.fetchall()]


def get_db(sqlite_path: str = "leaderboard.db"):
    """Retourne une connexion — PostgreSQL si DATABASE_URL est défini,
    sinon SQLite en repli local. Interface identique dans les deux cas."""
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return PostgresConnWrapper(conn)
    else:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn


def now_expr() -> str:
    """Expression SQL pour 'maintenant', différente selon le backend."""
    # Parenthèses obligatoires en SQLite pour une expression dans DEFAULT
    # (sans elles, la création des tables échoue en local).
    return "NOW()" if USE_POSTGRES else "(datetime('now'))"


def autoincrement_pk() -> str:
    """Syntaxe de clé primaire auto-incrémentée, différente selon le backend."""
    return "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
