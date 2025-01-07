#!/usr/bin/python3
# Copyright (c) BDist Development Team
# Distributed under the terms of the Modified BSD License.
import os
from logging.config import dictConfig

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from psycopg.rows import namedtuple_row
from psycopg_pool import ConnectionPool

from datetime import datetime

dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s:%(lineno)s - %(funcName)20s(): %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
    }
)

RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

app = Flask(__name__)
app.config.from_prefixed_env()
log = app.logger
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=RATELIMIT_STORAGE_URI,
)

# Use the DATABASE_URL environment variable if it exists, otherwise use the default.
# Use the format postgres://username:password@hostname/database_name to connect to the database.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://db:db@postgres/db")

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    kwargs={
        "autocommit": True,  # If True don’t start transactions automatically.
        "row_factory": namedtuple_row,
    },
    min_size=4,
    max_size=10,
    open=True,
    # check=ConnectionPool.check_connection,
    name="postgres_pool",
    timeout=5,
)


def is_valid_date(s):
    """Returns True if string is in date number."""    
    try:
        print("Date:", s)
        datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        return True
    except ValueError:
        return False


@app.route("/", methods=("GET",))
@app.route("/players", methods=("GET",))
@limiter.limit("1 per second")
def players_index():
    """Show all the players, most recent date first."""

    with pool.connection() as conn:
        with conn.cursor() as cur:
            players = cur.execute(
                """
                SELECT p.player_api_id, p.player_name, pa.max_date AS date
                FROM player p
                JOIN (
                    SELECT player_api_id, MAX(date) AS max_date
                    FROM player_attributes
                    GROUP BY player_api_id
                ) pa ON p.player_api_id = pa.player_api_id
                ORDER BY pa.max_date DESC
                LIMIT 20;
                """,
                {},
            ).fetchall()
            log.debug(f"Found {cur.rowcount} rows.")

    return render_template("players/index.html", players=players)


@app.route("/players/<player_api_id>/update", methods=("GET",))
@limiter.limit("1 per second")
def player_update_view(player_api_id):
    """Show the page to update the player date."""

    with pool.connection() as conn:
        with conn.cursor() as cur:
            player = cur.execute(
                """
                SELECT player_api_id
                FROM player_attributes
                WHERE player_api_id = %(player_api_id)s;
                """,
                {"player_api_id": player_api_id},
            ).fetchone()
            log.debug(f"Found {cur.rowcount} rows.")

    # At the end of the `connection()` context, the transaction is committed
    # or rolled back, and the connection returned to the pool.

    return render_template("players/update.html", player=player)

@app.route("/players/<player_api_id>", methods=("GET",))
def player_info(player_api_id):
    """Show the page with all the players attributes."""

    with pool.connection() as conn:
        with conn.cursor() as cur:
            player = cur.execute(
                """
                SELECT
                    p.player_api_id,
                    p.player_name,
                    p.height,
                    p.weight,
                    p.birthday,
                    pa.date,
                    pa.overall_rating,
                    pa.potential,
                    pa.preferred_foot,
                    pa.attacking_work_rate,
                    pa.defensive_work_rate,
                    pa.crossing,
                    pa.finishing,
                    pa.short_passing,
                    pa.dribbling,
                    pa.acceleration,
                    pa.sprint_speed,
                    pa.agility,
                    pa.stamina
                FROM player p
                JOIN (
                    SELECT DISTINCT ON (player_api_id)
                        player_api_id,
                        date,
                        overall_rating,
                        potential,
                        preferred_foot,
                        attacking_work_rate,
                        defensive_work_rate,
                        crossing,
                        finishing,
                        short_passing,
                        dribbling,
                        acceleration,
                        sprint_speed,
                        agility,
                        stamina
                    FROM player_attributes
                    ORDER BY player_api_id, date DESC
                ) pa ON p.player_api_id = pa.player_api_id
                WHERE p.player_api_id = %(player_api_id)s;
                """,
                {"player_api_id": player_api_id},
            ).fetchone()
            log.debug(f"Found {cur.rowcount} rows.")

    # At the end of the `connection()` context, the transaction is committed
    # or rolled back, and the connection returned to the pool.

    return render_template("players/info.html", player=player)

@app.route("/players/<player_api_id>/update", methods=("POST",))
def player_update_save(player_api_id):
    """Update the player date."""

    date = request.form["date"]

    error = None

    if date == "":
        error = "Date is required."
    elif not is_valid_date(date):
        error = "Date is required to be in the format 'DD/MM/YYYY, HH:MM:SS'."

    if error is not None:
        flash(error)
    else:
        date = date.replace("T", " ")   # Replace 'T' with a space
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE player_attributes
                    SET date = %(date)s
                    WHERE player_api_id = %(player_api_id)s;
                    """,
                    {"player_api_id": player_api_id, "date": date},
                )
                # The result of this statement is persisted immediately by the database
                # because the connection is in autocommit mode.

        # The connection is returned to the pool at the end of the `connection()` context but,
        # because it is not in a transaction state, no COMMIT is executed.

    return redirect(url_for("players_index"))

@app.route("/ping", methods=("GET",))
@limiter.exempt
def ping():
    log.debug("ping!")
    return jsonify({"message": "pong!", "status": "success"})


if __name__ == "__main__":
    app.run()
