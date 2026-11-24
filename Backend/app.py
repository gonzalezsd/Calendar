import csv
import io
import json
import re
import sys
from datetime import date, time, timedelta
from functools import wraps
from getpass import getpass
from pathlib import Path

import click
import psycopg
from flask import Flask, Response, current_app, g, jsonify, request
from flask_cors import CORS
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from psycopg import errors, sql
from psycopg.rows import dict_row
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash


class APIError(Exception):
    def __init__(self, message, status):
        self.message = message
        self.status = status


CONFIG_PATH = Path(__file__).resolve().with_name("config.json")
TOKEN_MAX_AGE_SECONDS = 10 * 60 * 60
# Las notas y los recordatorios no tienen un límite de tamaño en la base de datos.
csv.field_size_limit(sys.maxsize)


def load_config(path):
    try:
        with path.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
    except FileNotFoundError as error:
        raise RuntimeError(f"No existe {path}; crea el fichero a partir de config.example.json") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"El fichero {path} no contiene JSON válido") from error
    except OSError as error:
        raise RuntimeError(f"No se puede leer el fichero de configuración {path}") from error
    if not isinstance(config, dict):
        raise RuntimeError(f"El fichero {path} debe contener un objeto JSON")
    return config


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=None,
        SECRET_KEY=None,
        CORS_ORIGINS="",
    )
    app.config.update(load_config(CONFIG_PATH) if test_config is None else test_config)
    if not isinstance(app.config["DATABASE_URL"], str) or not app.config["DATABASE_URL"].strip():
        raise RuntimeError("DATABASE_URL debe ser una cadena de conexión no vacía")
    if not isinstance(app.config["SECRET_KEY"], str) or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("SECRET_KEY debe contener al menos 32 caracteres")
    if not isinstance(app.config["CORS_ORIGINS"], str):
        raise RuntimeError("CORS_ORIGINS debe ser una cadena de orígenes separados por comas")
    origins = [origin.strip() for origin in app.config["CORS_ORIGINS"].split(",") if origin.strip()]
    if origins:
        CORS(app, resources={r"/api/*": {"origins": origins}})

    @app.teardown_appcontext
    def close_db(_error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.errorhandler(APIError)
    def api_error(error):
        return jsonify(error=error.message), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(errors.UniqueViolation)
    def unique_error(_error):
        return jsonify(error="El registro ya existe"), 409

    @app.errorhandler(errors.ForeignKeyViolation)
    def foreign_key_error(_error):
        return jsonify(error="El registro relacionado no existe"), 404

    @app.errorhandler(psycopg.Error)
    def database_error(error):
        app.logger.exception("Error de base de datos", exc_info=error)
        return jsonify(error="Error de base de datos"), 500

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception("Error inesperado", exc_info=error)
        return jsonify(error="Error interno"), 500

    @app.cli.command("crear-administrador")
    @click.option("--nombre-usuario", required=True)
    @click.option("--nombre", required=True)
    def create_admin(nombre_usuario, nombre):
        try:
            username = valid_username(nombre_usuario)
        except APIError as error:
            raise click.ClickException(error.message) from error
        password = getpass("Contraseña: ")
        if password != getpass("Repite la contraseña: "):
            raise click.ClickException("Las contraseñas no coinciden")
        try:
            valid_password(password)
        except APIError as error:
            raise click.ClickException(error.message) from error
        db = get_db()
        with db.transaction():
            db.execute("LOCK TABLE usuarios, credenciales IN SHARE ROW EXCLUSIVE MODE")
            if db.execute("SELECT 1 FROM credenciales LIMIT 1").fetchone():
                raise click.ClickException("Ya existen credenciales; crea usuarios mediante la API")
            user = db.execute(
                "INSERT INTO usuarios (nombre, es_administrador, activo) VALUES (%s, true, true) RETURNING usuario_id",
                (nombre,),
            ).fetchone()
            db.execute(
                "INSERT INTO credenciales (usuario_id, nombre_usuario, password_hash) VALUES (%s, %s, %s)",
                (user["usuario_id"], username, generate_password_hash(password)),
            )
        click.echo(f"Administrador creado: {user['usuario_id']}")

    @app.post("/api/auth/login")
    def login():
        data = body({"nombre_usuario", "password"}, {"nombre_usuario", "password"})
        username = valid_username(data["nombre_usuario"])
        if not isinstance(data["password"], str):
            raise APIError("password debe ser una cadena", 400)
        user = get_db().execute(
            """SELECT u.usuario_id, u.activo, c.password_hash, c.version
               FROM usuarios u JOIN credenciales c USING (usuario_id)
               WHERE c.nombre_usuario = %s""",
            (username,),
        ).fetchone()
        if not user or not user["activo"] or not check_password_hash(user["password_hash"], data["password"]):
            raise APIError("Credenciales incorrectas", 401)
        token = serializer().dumps({"usuario_id": user["usuario_id"], "version": user["version"]})
        return jsonify(access_token=token, token_type="Bearer", expires_in=TOKEN_MAX_AGE_SECONDS)

    @app.get("/api/me")
    @authenticated()
    def current_user():
        return jsonify(g.user)

    @app.get("/api/usuarios")
    @authenticated(admin=True)
    def list_users():
        rows = get_db().execute(
            """SELECT u.usuario_id, u.nombre, u.apellido1, u.apellido2,
                      u.es_administrador, u.activo, c.nombre_usuario
               FROM usuarios u LEFT JOIN credenciales c USING (usuario_id)
               ORDER BY u.usuario_id"""
        ).fetchall()
        return jsonify(rows)

    @app.post("/api/usuarios")
    @authenticated(admin=True)
    def create_user():
        data = body(USER_FIELDS | {"nombre_usuario", "password"}, {"nombre_usuario", "password"})
        values = validate_fields(data, USER_FIELDS)
        values.setdefault("activo", True)
        values.setdefault("es_administrador", False)
        username = valid_username(data["nombre_usuario"])
        password = valid_password(data["password"])
        db = get_db()
        with db.transaction():
            user = insert("usuarios", values)
            db.execute(
                "INSERT INTO credenciales (usuario_id, nombre_usuario, password_hash) VALUES (%s, %s, %s)",
                (user["usuario_id"], username, generate_password_hash(password)),
            )
        return jsonify(user), 201

    @app.patch("/api/usuarios/<int:user_id>")
    @authenticated(admin=True)
    def update_user(user_id):
        positive_id(user_id)
        data = body(USER_FIELDS | {"nombre_usuario", "password"}, set())
        values = validate_fields(data, USER_FIELDS)
        username = valid_username(data["nombre_usuario"]) if "nombre_usuario" in data else None
        password = valid_password(data["password"]) if "password" in data else None
        db = get_db()
        with db.transaction():
            user = update("usuarios", "usuario_id", user_id, values)
            if username is not None or password is not None:
                credential = db.execute(
                    "SELECT usuario_id FROM credenciales WHERE usuario_id = %s FOR UPDATE", (user_id,)
                ).fetchone()
                if not credential:
                    if username is None or password is None:
                        raise APIError("El usuario necesita nombre_usuario y password", 400)
                    db.execute(
                        "INSERT INTO credenciales (usuario_id, nombre_usuario, password_hash) VALUES (%s, %s, %s)",
                        (user_id, username, generate_password_hash(password)),
                    )
                else:
                    changes = {}
                    if username is not None:
                        changes["nombre_usuario"] = username
                    if password is not None:
                        changes["password_hash"] = generate_password_hash(password)
                    db.execute(
                        sql.SQL("UPDATE credenciales SET {}, version = version + 1 WHERE usuario_id = %s").format(
                            sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in changes)
                        ),
                        (*changes.values(), user_id),
                    )
        return jsonify(user)

    @app.post("/api/proyectos")
    @authenticated()
    def create_project():
        values = validate_fields(body(PROJECT_FIELDS, set()), PROJECT_FIELDS)
        with get_db().transaction():
            result = insert("proyectos", values)
        return jsonify(result), 201

    @app.get("/api/proyectos")
    @authenticated()
    def list_projects():
        return jsonify(get_db().execute("SELECT * FROM proyectos ORDER BY proyecto_id").fetchall())

    @app.patch("/api/proyectos/<int:project_id>")
    @authenticated()
    def update_project(project_id):
        positive_id(project_id)
        values = validate_fields(body(PROJECT_FIELDS, set()), PROJECT_FIELDS)
        with get_db().transaction():
            result = update("proyectos", "proyecto_id", project_id, values)
        return jsonify(result)

    @app.post("/api/tipos-fecha")
    @authenticated()
    def create_date_type():
        values = validate_fields(body(TYPE_FIELDS, {"en_borde"}), TYPE_FIELDS)
        if values.get("nombre") == "Festivo":
            raise APIError("El nombre Festivo está reservado", 409)
        with get_db().transaction():
            result = insert("tipos_fecha", values)
        return jsonify(result), 201

    @app.get("/api/tipos-fecha")
    @authenticated()
    def list_date_types():
        return jsonify(get_db().execute("SELECT * FROM tipos_fecha ORDER BY tipo_id").fetchall())

    @app.patch("/api/tipos-fecha/<int:type_id>")
    @authenticated()
    def update_date_type(type_id):
        positive_id(type_id)
        values = validate_fields(body(TYPE_FIELDS, set()), TYPE_FIELDS)
        db = get_db()
        with db.transaction():
            old = db.execute("SELECT nombre, en_borde FROM tipos_fecha WHERE tipo_id = %s FOR UPDATE", (type_id,)).fetchone()
            if not old:
                raise APIError("Tipo de fecha no encontrado", 404)
            if old["nombre"] != "Festivo" and values.get("nombre") == "Festivo":
                raise APIError("El nombre Festivo está reservado", 409)
            if old["nombre"] == "Festivo" and (
                ("nombre" in values and values["nombre"] != "Festivo")
                or ("en_borde" in values and values["en_borde"] is not False)
            ):
                raise APIError("El nombre y en_borde del tipo Festivo están reservados", 409)
            if "en_borde" in values and values["en_borde"] != old["en_borde"]:
                if db.execute("SELECT 1 FROM tipados WHERE tipo_id = %s LIMIT 1", (type_id,)).fetchone():
                    raise APIError("No se puede cambiar en_borde mientras el tipo esté asignado", 409)
            result = update("tipos_fecha", "tipo_id", type_id, values)
        return jsonify(result)

    @app.post("/api/asignaciones/multiples")
    @authenticated()
    def create_multiple_assignments():
        fields = {"fechas", "proyectos", "tipos", "es_prevision"}
        data = body(fields, fields)
        if not isinstance(data["fechas"], list) or not isinstance(data["proyectos"], list) or not isinstance(data["tipos"], list):
            raise APIError("fechas, proyectos y tipos deben ser listas", 400)
        days = [valid_date(value) for value in data["fechas"]]
        projects = [positive_id(value) for value in data["proyectos"]]
        types = [positive_id(value) for value in data["tipos"]]
        if len(days) < 2 or len(set(days)) != len(days) or len({day.year for day in days}) != 1:
            raise APIError("Selecciona al menos dos fechas distintas del mismo año", 400)
        if len(set(projects)) != len(projects) or len(set(types)) != len(types):
            raise APIError("Los proyectos y tipos no pueden repetirse", 400)
        if not projects and not types:
            raise APIError("Selecciona al menos un proyecto o tipo de fecha", 400)
        if type(data["es_prevision"]) is not bool:
            raise APIError("es_prevision debe ser booleano", 400)

        db = get_db()
        with db.transaction():
            existing_types = db.execute(
                "SELECT tipo_id, activo FROM tipos_fecha WHERE tipo_id = ANY(%s) ORDER BY tipo_id FOR SHARE", (types,)
            ).fetchall()
            if len(existing_types) != len(types):
                raise APIError("Tipo de fecha no encontrado", 404)
            if any(not kind["activo"] for kind in existing_types):
                raise APIError("Solo se pueden asignar tipos de fecha activos", 409)
            existing_projects = db.execute(
                "SELECT proyecto_id, activo FROM proyectos WHERE proyecto_id = ANY(%s) ORDER BY proyecto_id FOR UPDATE",
                (projects,),
            ).fetchall()
            if len(existing_projects) != len(projects):
                raise APIError("Proyecto no encontrado", 404)
            if any(not project["activo"] for project in existing_projects):
                raise APIError("Solo se pueden asignar proyectos activos", 409)
            db.execute("SELECT usuario_id FROM usuarios WHERE usuario_id = %s FOR UPDATE", (g.user["usuario_id"],))
            for day in sorted(days):
                for project_id in sorted(projects):
                    inserted = db.execute(
                        """INSERT INTO asignaciones (usuario_id, fecha, proyecto_id, es_prevision)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (usuario_id, fecha, proyecto_id, es_prevision) DO NOTHING
                           RETURNING proyecto_id""",
                        (g.user["usuario_id"], day, project_id, data["es_prevision"]),
                    ).fetchone()
                    if not inserted:
                        raise APIError(f"{day.isoformat()}: el proyecto {project_id} ya está asignado", 409)
                    if not data["es_prevision"]:
                        change_remaining(db, project_id, -1)
                for type_id in sorted(types):
                    try:
                        insert_typing(db, day, type_id)
                    except APIError as error:
                        raise APIError(f"{day.isoformat()}: {error.message}", error.status) from error
        return jsonify(fechas=len(days), asignaciones=len(days) * len(projects), tipados=len(days) * len(types)), 201

    @app.post("/api/asignaciones")
    @authenticated()
    def create_assignment():
        data = body({"fecha", "proyecto_id", "es_prevision"}, {"fecha", "proyecto_id", "es_prevision"})
        day = valid_date(data["fecha"])
        project_id = positive_id(data["proyecto_id"])
        if type(data["es_prevision"]) is not bool:
            raise APIError("es_prevision debe ser booleano", 400)
        db = get_db()
        with db.transaction():
            lock_project(db, project_id, require_active=True)
            result = db.execute(
                """INSERT INTO asignaciones (usuario_id, fecha, proyecto_id, es_prevision)
                   VALUES (%s, %s, %s, %s) RETURNING usuario_id, fecha, proyecto_id, es_prevision""",
                (g.user["usuario_id"], day, project_id, data["es_prevision"]),
            ).fetchone()
            if not data["es_prevision"]:
                change_remaining(db, project_id, -1)
        result["fecha"] = result["fecha"].isoformat()
        return jsonify(result), 201

    @app.post("/api/asignaciones/<day>/<int:project_id>/confirmar")
    @authenticated()
    def confirm_assignment(day, project_id):
        day = valid_date(day)
        positive_id(project_id)
        db = get_db()
        with db.transaction():
            lock_project(db, project_id)
            row = db.execute(
                """DELETE FROM asignaciones WHERE usuario_id = %s AND fecha = %s
                   AND proyecto_id = %s AND es_prevision = true RETURNING usuario_id""",
                (g.user["usuario_id"], day, project_id),
            ).fetchone()
            if not row:
                raise APIError("Previsión no encontrada", 404)
            inserted = db.execute(
                """INSERT INTO asignaciones (usuario_id, fecha, proyecto_id, es_prevision)
                   VALUES (%s, %s, %s, false)
                   ON CONFLICT (usuario_id, fecha, proyecto_id, es_prevision) DO NOTHING
                   RETURNING proyecto_id""",
                (g.user["usuario_id"], day, project_id),
            ).fetchone()
            if inserted:
                change_remaining(db, project_id, -1)
        return jsonify(usuario_id=g.user["usuario_id"], fecha=day.isoformat(), proyecto_id=project_id, es_prevision=False)

    @app.delete("/api/asignaciones/<day>/<int:project_id>/<forecast>")
    @authenticated()
    def delete_assignment(day, project_id, forecast):
        day = valid_date(day)
        positive_id(project_id)
        if forecast not in ("true", "false"):
            raise APIError("es_prevision debe ser true o false", 400)
        db = get_db()
        with db.transaction():
            lock_project(db, project_id)
            row = db.execute(
                """DELETE FROM asignaciones WHERE usuario_id = %s AND fecha = %s
                   AND proyecto_id = %s AND es_prevision = %s RETURNING usuario_id""",
                (g.user["usuario_id"], day, project_id, forecast == "true"),
            ).fetchone()
            if not row:
                raise APIError("Asignación no encontrada", 404)
            if forecast == "false":
                change_remaining(db, project_id, 1)
        return "", 204

    @app.post("/api/tipados")
    @authenticated()
    def create_typing():
        data = body({"fecha", "tipo_id"}, {"fecha", "tipo_id"})
        day = valid_date(data["fecha"])
        type_id = positive_id(data["tipo_id"])
        db = get_db()
        with db.transaction():
            result = insert_typing(db, day, type_id)
        return jsonify(result), 201

    @app.put("/api/notas/<day>")
    @authenticated()
    def save_note(day):
        day = valid_date(day)
        data = body({"texto"}, {"texto"})
        text = data["texto"]
        if not isinstance(text, str) or not text.strip() or "\x00" in text:
            raise APIError("texto debe ser una cadena no vacía y sin caracteres nulos", 400)
        db = get_db()
        with db.transaction():
            row = db.execute(
                """INSERT INTO notas (usuario_id, fecha, texto) VALUES (%s, %s, %s)
                   ON CONFLICT (usuario_id, fecha) DO UPDATE SET texto = EXCLUDED.texto
                   RETURNING fecha, texto""",
                (g.user["usuario_id"], day, text),
            ).fetchone()
        row["fecha"] = row["fecha"].isoformat()
        return jsonify(row)

    @app.delete("/api/notas/<day>")
    @authenticated()
    def delete_note(day):
        day = valid_date(day)
        db = get_db()
        with db.transaction():
            row = db.execute(
                "DELETE FROM notas WHERE usuario_id = %s AND fecha = %s RETURNING fecha",
                (g.user["usuario_id"], day),
            ).fetchone()
            if not row:
                raise APIError("Nota no encontrada", 404)
        return "", 204

    @app.post("/api/recordatorios")
    @authenticated()
    def create_reminder():
        data = body({"fecha", "hora", "texto", "repetir"}, {"fecha", "texto", "repetir"})
        day = valid_date(data["fecha"])
        text = valid_reminder_text(data["texto"])
        if type(data["repetir"]) is not bool:
            raise APIError("repetir debe ser booleano", 400)
        hour = valid_reminder_time(data.get("hora"))
        db = get_db()
        with db.transaction():
            db.execute("SELECT usuario_id FROM usuarios WHERE usuario_id = %s FOR UPDATE", (g.user["usuario_id"],))
            row = db.execute(
                """INSERT INTO recordatorios (usuario_id, fecha, hora, texto, repetir, fecha_original)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING recordatorio_id, fecha, hora, texto, repetir""",
                (g.user["usuario_id"], day, hour, text, data["repetir"], day),
            ).fetchone()
        return jsonify(serialize_reminder(row)), 201

    @app.get("/api/recordatorios/recurrentes")
    @authenticated()
    def list_recurring_reminders():
        rows = get_db().execute(
            """SELECT DISTINCT ON (EXTRACT(MONTH FROM fecha_original), EXTRACT(DAY FROM fecha_original), hora, texto)
                      recordatorio_id, EXTRACT(MONTH FROM fecha_original)::integer AS mes,
                      EXTRACT(DAY FROM fecha_original)::integer AS dia, hora, texto, repetir
               FROM recordatorios WHERE usuario_id = %s AND repetir = true
               ORDER BY EXTRACT(MONTH FROM fecha_original), EXTRACT(DAY FROM fecha_original),
                        hora NULLS FIRST, texto, recordatorio_id""",
            (g.user["usuario_id"],),
        ).fetchall()
        for row in rows:
            row["hora"] = row["hora"].strftime("%H:%M") if row["hora"] is not None else None
        return jsonify(rows)

    @app.patch("/api/recordatorios/<int:reminder_id>")
    @authenticated()
    def update_recurring_reminder(reminder_id):
        positive_id(reminder_id)
        data = body({"mes", "dia", "hora", "texto", "repetir"}, {"mes", "dia", "hora", "texto", "repetir"})
        if (type(data["mes"]) is not int or not 1 <= data["mes"] <= 12 or
                type(data["dia"]) is not int or not 1 <= data["dia"] <= 31):
            raise APIError("mes y dia deben ser enteros válidos", 400)
        try:
            new_original = date(2000, data["mes"], data["dia"])
        except ValueError:
            raise APIError("El día y el mes no corresponden a una fecha válida", 400)
        hour = valid_reminder_time(data["hora"])
        text = valid_reminder_text(data["texto"])
        if type(data["repetir"]) is not bool:
            raise APIError("repetir debe ser booleano", 400)
        db = get_db()
        with db.transaction():
            db.execute("SELECT usuario_id FROM usuarios WHERE usuario_id = %s FOR UPDATE", (g.user["usuario_id"],))
            original = db.execute(
                """SELECT fecha_original, hora, texto FROM recordatorios
                   WHERE usuario_id = %s AND recordatorio_id = %s AND repetir = true""",
                (g.user["usuario_id"], reminder_id),
            ).fetchone()
            if not original:
                raise APIError("Recordatorio recurrente no encontrado", 404)
            if not (new_original.month == 2 and new_original.day == 29 and
                    reminder_date(original["fecha_original"].year, new_original).day == 28):
                new_original = new_original.replace(year=original["fecha_original"].year)
            rows = db.execute(
                """SELECT recordatorio_id, fecha FROM recordatorios
                   WHERE usuario_id = %s AND repetir = true
                   AND EXTRACT(MONTH FROM fecha_original) = %s AND EXTRACT(DAY FROM fecha_original) = %s
                   AND hora IS NOT DISTINCT FROM %s AND texto = %s""",
                (g.user["usuario_id"], original["fecha_original"].month, original["fecha_original"].day,
                 original["hora"], original["texto"]),
            ).fetchall()
            ids = [row["recordatorio_id"] for row in rows]
            if data["repetir"] and db.execute(
                """SELECT 1 FROM recordatorios WHERE usuario_id = %s AND repetir = true
                   AND EXTRACT(MONTH FROM fecha_original) = %s AND EXTRACT(DAY FROM fecha_original) = %s
                   AND hora IS NOT DISTINCT FROM %s AND texto = %s AND NOT (recordatorio_id = ANY(%s))
                   LIMIT 1""",
                (g.user["usuario_id"], new_original.month, new_original.day, hour, text, ids),
            ).fetchone():
                raise APIError("Ya existe un recordatorio recurrente con esa fecha, hora y texto", 409)
            for row in rows:
                db.execute(
                    """UPDATE recordatorios SET fecha = %s, fecha_original = %s, hora = %s, texto = %s, repetir = %s
                       WHERE usuario_id = %s AND recordatorio_id = %s""",
                    (reminder_date(row["fecha"].year, new_original), new_original, hour, text, data["repetir"],
                     g.user["usuario_id"], row["recordatorio_id"]),
                )
        return jsonify(recordatorio_id=reminder_id, mes=new_original.month, dia=new_original.day,
                       hora=hour.strftime("%H:%M") if hour is not None else None, texto=text, repetir=data["repetir"])

    @app.get("/api/recordatorios/<day>")
    @authenticated()
    def get_reminders(day):
        day = valid_date(day)
        rows = get_db().execute(
            """SELECT recordatorio_id, fecha, hora, texto, repetir FROM recordatorios
               WHERE usuario_id = %s AND fecha = %s ORDER BY hora NULLS FIRST, recordatorio_id""",
            (g.user["usuario_id"], day),
        ).fetchall()
        return jsonify([serialize_reminder(row) for row in rows])

    @app.get("/api/calendario/<int:year>/exportar")
    @authenticated()
    def export_calendar(year):
        if not 1 <= year <= 9999:
            raise APIError("year debe ser un entero entre 1 y 9999", 400)
        db = get_db()
        with db.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            data = export_calendar_csv(db, g.user["usuario_id"], year)
        return Response(data, mimetype="text/csv", headers={
            "Content-Disposition": f'attachment; filename="calendario-{year}.csv"',
            "Cache-Control": "no-store",
        })

    @app.get("/api/calendario/exportar")
    @authenticated()
    def export_all_calendars():
        db = get_db()
        with db.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            data = export_calendar_csv(db, g.user["usuario_id"], None)
        return Response(data, mimetype="text/csv", headers={
            "Content-Disposition": 'attachment; filename="calendario-completo.csv"',
            "Cache-Control": "no-store",
        })

    @app.post("/api/calendario/importar")
    @authenticated()
    def import_calendar():
        content = request.get_data()
        year, records = parse_calendar_csv(content)
        db = get_db()
        with db.transaction():
            result = import_calendar_csv(db, g.user["usuario_id"], year, records)
            if year is None:
                result["years"] = sorted({
                    valid_date(row["fecha"]).year for row in records
                    if row["tipo"] in ("asignacion", "tipado", "nota", "recordatorio")
                })
            else:
                result["year"] = year
        return jsonify(result), 201

    @app.get("/api/get_years")
    @authenticated()
    def get_years():
        rows = get_db().execute(
            """SELECT EXTRACT(YEAR FROM fecha)::integer AS year FROM asignaciones WHERE usuario_id = %s
               UNION
               SELECT EXTRACT(YEAR FROM fecha)::integer AS year FROM tipados WHERE usuario_id = %s
               UNION
               SELECT EXTRACT(YEAR FROM fecha)::integer AS year FROM notas WHERE usuario_id = %s
               UNION
               SELECT EXTRACT(YEAR FROM fecha)::integer AS year FROM recordatorios WHERE usuario_id = %s
               ORDER BY year""",
            (g.user["usuario_id"], g.user["usuario_id"], g.user["usuario_id"], g.user["usuario_id"]),
        ).fetchall()
        return jsonify(years=[row["year"] for row in rows])

    @app.get("/api/calendario/<int:year>")
    @authenticated()
    def get_calendar(year):
        if not 1 <= year <= 9999:
            raise APIError("year debe ser un entero entre 1 y 9999", 400)
        db = get_db()
        assignments = db.execute(
            """SELECT a.fecha, a.proyecto_id, a.es_prevision, p.nombre, p.color, p.laborable
               FROM asignaciones a JOIN proyectos p USING (proyecto_id)
               WHERE a.usuario_id = %s AND EXTRACT(YEAR FROM a.fecha) = %s
               ORDER BY a.fecha, a.proyecto_id, a.es_prevision""",
            (g.user["usuario_id"], year),
        ).fetchall()
        typings = db.execute(
            """SELECT t.fecha, t.tipo_id, tf.nombre, tf.color, tf.en_borde
               FROM tipados t JOIN tipos_fecha tf USING (tipo_id)
               WHERE t.usuario_id = %s AND EXTRACT(YEAR FROM t.fecha) = %s
               ORDER BY t.fecha, t.tipo_id""",
            (g.user["usuario_id"], year),
        ).fetchall()
        notes = db.execute(
            """SELECT fecha, texto FROM notas
               WHERE usuario_id = %s AND EXTRACT(YEAR FROM fecha) = %s ORDER BY fecha""",
            (g.user["usuario_id"], year),
        ).fetchall()
        reminders = db.execute(
            """SELECT recordatorio_id, fecha, hora, texto, repetir FROM recordatorios
               WHERE usuario_id = %s AND EXTRACT(YEAR FROM fecha) = %s
               ORDER BY fecha, hora NULLS FIRST, recordatorio_id""",
            (g.user["usuario_id"], year),
        ).fetchall()
        for row in assignments + typings + notes:
            row["fecha"] = row["fecha"].isoformat()
        reminders = [serialize_reminder(row) for row in reminders]
        context = {"anterior": [], "posterior": []}
        for key, boundary, step in (
            ("anterior", date(year, 1, 1), -1),
            ("posterior", date(year, 12, 31), 1),
        ):
            if boundary == (date.min if step < 0 else date.max):
                continue
            context[key] = db.execute(
                """WITH RECURSIVE adyacentes(fecha) AS (
                       SELECT %s::date
                       UNION ALL
                       SELECT fecha + %s FROM adyacentes
                       WHERE fecha <> %s AND (
                           EXTRACT(ISODOW FROM fecha) IN (6, 7) OR EXISTS (
                               SELECT 1 FROM tipados t JOIN tipos_fecha tf USING (tipo_id)
                               WHERE t.usuario_id = %s AND t.fecha = adyacentes.fecha AND tf.nombre = 'Festivo'
                           )
                       )
                   )
                   SELECT DISTINCT a.es_prevision, p.color
                   FROM adyacentes d JOIN asignaciones a ON a.fecha = d.fecha
                   JOIN proyectos p USING (proyecto_id)
                   WHERE a.usuario_id = %s AND p.nombre = 'Vacaciones'""",
                (boundary + timedelta(days=step), step, date.min if step < 0 else date.max,
                 g.user["usuario_id"], g.user["usuario_id"]),
            ).fetchall()
        return jsonify(asignaciones=assignments, tipados=typings, notas=notes, recordatorios=reminders,
                       contexto_vacaciones=context)

    @app.post("/api/new_year")
    @authenticated()
    def new_year():
        data = body({"year"}, {"year"})
        year = data["year"]
        if type(year) is not int or not 1 <= year <= 9999:
            raise APIError("year debe ser un entero entre 1 y 9999", 400)
        db = get_db()
        with db.transaction():
            kinds = db.execute(
                "SELECT tipo_id, en_borde FROM tipos_fecha WHERE nombre = %s FOR SHARE", ("Festivo",)
            ).fetchall()
            if len(kinds) != 1 or kinds[0]["en_borde"] is not False:
                raise APIError("El tipo Festivo no está configurado correctamente", 409)
            first = date(year, 1, 1)
            days = [first + timedelta(days=offset) for offset in range((date(year, 12, 31) - first).days + 1)
                    if offset == 0 or (first + timedelta(days=offset)).weekday() >= 5]
            db.execute("SELECT usuario_id FROM usuarios WHERE usuario_id = %s FOR UPDATE", (g.user["usuario_id"],))
            conflict = db.execute(
                """SELECT t.fecha FROM tipados t JOIN tipos_fecha tf USING (tipo_id)
                   WHERE t.usuario_id = %s AND t.fecha = ANY(%s)
                   AND (tf.en_borde IS NULL OR tf.en_borde = false)
                   ORDER BY t.fecha LIMIT 1""",
                (g.user["usuario_id"], days),
            ).fetchone()
            if conflict:
                raise APIError(f"{conflict['fecha'].isoformat()}: la fecha ya tiene un tipo sin borde", 409)
            db.execute(
                """INSERT INTO tipados (usuario_id, fecha, tipo_id)
                   SELECT %s, fecha, %s FROM unnest(%s::date[]) AS fecha""",
                (g.user["usuario_id"], kinds[0]["tipo_id"], days),
            )
            reminders = db.execute(
                """SELECT fecha_original, hora, texto FROM recordatorios
                   WHERE usuario_id = %s AND repetir = true ORDER BY fecha_original, recordatorio_id""",
                (g.user["usuario_id"],),
            ).fetchall()
            existing = {
                (row["fecha"], row["hora"], row["texto"])
                for row in db.execute(
                    """SELECT fecha, hora, texto FROM recordatorios
                       WHERE usuario_id = %s AND EXTRACT(YEAR FROM fecha) = %s""",
                    (g.user["usuario_id"], year),
                ).fetchall()
            }
            for reminder in reminders:
                original = reminder["fecha_original"]
                target = reminder_date(year, original)
                key = (target, reminder["hora"], reminder["texto"])
                if key in existing:
                    continue
                db.execute(
                    """INSERT INTO recordatorios (usuario_id, fecha, hora, texto, repetir, fecha_original)
                       VALUES (%s, %s, %s, %s, true, %s)""",
                    (g.user["usuario_id"], target, reminder["hora"], reminder["texto"], original),
                )
                existing.add(key)
            result = {"usuario_id": g.user["usuario_id"], "fecha": first.isoformat(), "tipo_id": kinds[0]["tipo_id"]}
        return jsonify(result), 201

    @app.delete("/api/tipados/<day>/<int:type_id>")
    @authenticated()
    def delete_typing(day, type_id):
        day = valid_date(day)
        positive_id(type_id)
        with get_db().transaction():
            result = get_db().execute(
                "DELETE FROM tipados WHERE usuario_id = %s AND fecha = %s AND tipo_id = %s RETURNING usuario_id",
                (g.user["usuario_id"], day, type_id),
            ).fetchone()
            if not result:
                raise APIError("Tipado no encontrado", 404)
        return "", 204

    return app


def serialize_reminder(row):
    row["fecha"] = row["fecha"].isoformat()
    row["hora"] = row["hora"].strftime("%H:%M") if row["hora"] is not None else None
    return row


def valid_reminder_text(text):
    if not isinstance(text, str) or not text.strip() or "\x00" in text:
        raise APIError("texto debe ser una cadena no vacía y sin caracteres nulos", 400)
    return text


def valid_reminder_time(hour):
    if hour is not None:
        if not isinstance(hour, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", hour):
            raise APIError("hora debe tener el formato HH:MM o ser null", 400)
        return time.fromisoformat(hour)
    return None


def reminder_date(year, original):
    day = original.day
    if original.month == 2 and day == 29 and (year % 4 != 0 or (year % 100 == 0 and year % 400 != 0)):
        day = 28
    return date(year, original.month, day)


CSV_COLUMNS = (
    "tipo", "ref", "fecha", "fecha_original", "nombre", "descripcion", "duracion", "restantes",
    "color", "laborable", "en_borde", "es_prevision", "hora", "texto", "repetir", "version", "anio", "activo",
)
CSV_FIELDS = {
    "calendario": {"version", "anio"},
    "proyecto": {"ref", "nombre", "descripcion", "duracion", "restantes", "color", "laborable", "activo"},
    "tipo_fecha": {"ref", "nombre", "descripcion", "color", "en_borde", "activo"},
    "asignacion": {"ref", "fecha", "es_prevision"},
    "tipado": {"ref", "fecha"},
    "nota": {"fecha", "texto"},
    "recordatorio": {"fecha", "fecha_original", "hora", "texto", "repetir"},
}


def csv_encode(value):
    if value is None:
        return r"\N"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, time):
        return value.isoformat(timespec="minutes") if value.second == 0 and value.microsecond == 0 else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return str(value)
    if value.startswith("\\"):
        return "\\" + value
    if value.startswith("'") or value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def csv_decode(value):
    if value == r"\N":
        return None
    if value.startswith("\\"):
        if not value.startswith("\\\\"):
            raise APIError("Escape inválido en el CSV", 400)
        return value[1:]
    if value.startswith("''") or (value.startswith("'") and (
        value[1:].lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or value[1:].startswith(("\t", "\r", "\n"))
    )):
        return value[1:]
    return value


def export_calendar_csv(db, user_id, year):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
    writer.writeheader()

    def write(kind, **values):
        writer.writerow({"tipo": kind, **{key: csv_encode(value) for key, value in values.items()}})

    write("calendario", version=1 if year is not None else 2, anio=year)
    start = date(year or 1, 1, 1)
    end = date(year or 9999, 12, 31)
    if not db.execute(
        """SELECT 1 FROM (
               SELECT fecha FROM asignaciones WHERE usuario_id = %s
               UNION ALL SELECT fecha FROM tipados WHERE usuario_id = %s
               UNION ALL SELECT fecha FROM notas WHERE usuario_id = %s
               UNION ALL SELECT fecha FROM recordatorios WHERE usuario_id = %s
           ) AS dias WHERE fecha BETWEEN %s AND %s LIMIT 1""",
        (user_id, user_id, user_id, user_id, start, end),
    ).fetchone():
        raise APIError("No hay datos de calendario para exportar", 404)
    projects = db.execute(
        """SELECT DISTINCT p.* FROM proyectos p JOIN asignaciones a USING (proyecto_id)
           WHERE a.usuario_id = %s AND a.fecha BETWEEN %s AND %s ORDER BY p.proyecto_id""",
        (user_id, start, end),
    ).fetchall()
    types = db.execute(
        """SELECT DISTINCT tf.* FROM tipos_fecha tf JOIN tipados t USING (tipo_id)
           WHERE t.usuario_id = %s AND t.fecha BETWEEN %s AND %s ORDER BY tf.tipo_id""",
        (user_id, start, end),
    ).fetchall()
    for row in projects:
        write("proyecto", ref=f"p{row['proyecto_id']}", **{key: row[key] for key in PROJECT_FIELDS})
    for row in types:
        write("tipo_fecha", ref=f"t{row['tipo_id']}", **{key: row[key] for key in TYPE_FIELDS})
    for row in db.execute(
        """SELECT fecha, proyecto_id, es_prevision FROM asignaciones
           WHERE usuario_id = %s AND fecha BETWEEN %s AND %s ORDER BY fecha, proyecto_id, es_prevision""",
        (user_id, start, end),
    ).fetchall():
        write("asignacion", ref=f"p{row['proyecto_id']}", fecha=row["fecha"], es_prevision=row["es_prevision"])
    for row in db.execute(
        """SELECT fecha, tipo_id FROM tipados WHERE usuario_id = %s AND fecha BETWEEN %s AND %s
           ORDER BY fecha, tipo_id""",
        (user_id, start, end),
    ).fetchall():
        write("tipado", ref=f"t{row['tipo_id']}", fecha=row["fecha"])
    for row in db.execute(
        "SELECT fecha, texto FROM notas WHERE usuario_id = %s AND fecha BETWEEN %s AND %s ORDER BY fecha",
        (user_id, start, end),
    ).fetchall():
        write("nota", **row)
    for row in db.execute(
        """SELECT fecha, fecha_original, hora, texto, repetir FROM recordatorios
           WHERE usuario_id = %s AND fecha BETWEEN %s AND %s ORDER BY fecha, hora NULLS FIRST, recordatorio_id""",
        (user_id, start, end),
    ).fetchall():
        write("recordatorio", **row)
    return output.getvalue()


def parse_calendar_csv(content):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise APIError("El CSV debe estar codificado en UTF-8", 400) from error
    if "\x00" in text:
        raise APIError("El CSV no puede contener caracteres nulos", 400)
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if header not in (list(CSV_COLUMNS), list(CSV_COLUMNS[:-1])):
            raise APIError("La cabecera del CSV no corresponde al formato de Calendar", 400)
        rows = list(reader)
    except csv.Error as error:
        raise APIError(f"CSV inválido: {error}", 400) from error
    records = []
    for index, values in enumerate(rows, start=2):
        if len(values) != len(header):
            raise APIError(f"Fila {index}: número de columnas incorrecto", 400)
        row = dict(zip(header, values))
        kind = row["tipo"]
        if kind not in CSV_FIELDS:
            raise APIError(f"Fila {index}: tipo de registro desconocido", 400)
        if any(row.get(key) for key in set(CSV_COLUMNS) - CSV_FIELDS[kind] - {"tipo"}):
            raise APIError(f"Fila {index}: columnas inesperadas", 400)
        row = {key: csv_decode(row[key]) for key in CSV_FIELDS[kind] if key in row}
        row["tipo"] = kind
        records.append(row)
    if not records or records[0]["tipo"] != "calendario" or any(
        row["tipo"] == "calendario" for row in records[1:]
    ):
        raise APIError("El CSV debe comenzar con un único registro de calendario", 400)
    header = records.pop(0)
    if header["version"] == "2" and header["anio"] is None:
        year = None
    elif header["version"] == "1" and isinstance(header["anio"], str) and re.fullmatch(r"[0-9]{1,4}", header["anio"]):
        year = int(header["anio"])
        if not 1 <= year <= 9999:
            raise APIError("El año del CSV debe estar entre 1 y 9999", 400)
    else:
        raise APIError("Versión o año del CSV inválido", 400)
    if not any(row["tipo"] in ("asignacion", "tipado", "nota", "recordatorio") for row in records):
        raise APIError("El CSV no contiene datos para el año indicado", 400)
    return year, records


def csv_boolean(value, nullable=False):
    if nullable and value is None:
        return None
    if value not in ("true", "false"):
        raise APIError("El CSV contiene un valor booleano inválido", 400)
    return value == "true"


def csv_integer(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"-?[0-9]{1,5}", value):
        raise APIError("El CSV contiene un número inválido", 400)
    return int(value)


def csv_reminder_time(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9](?:\.[0-9]{1,6})?)?", value
    ):
        raise APIError("El CSV contiene una hora inválida", 400)
    return time.fromisoformat(value)


def import_calendar_csv(db, user_id, year, records):
    db.execute("LOCK TABLE tipos_fecha, proyectos IN SHARE ROW EXCLUSIVE MODE")
    project_refs = {}
    type_refs = {}
    new_projects = set()
    used_ids = {"proyecto": set(), "tipo_fecha": set()}
    for row in records:
        kind = row["tipo"]
        if kind not in ("proyecto", "tipo_fecha"):
            continue
        ref = row["ref"]
        refs = project_refs if kind == "proyecto" else type_refs
        prefix = "p" if kind == "proyecto" else "t"
        if not isinstance(ref, str) or not re.fullmatch(prefix + r"[1-9][0-9]*", ref) or ref in refs:
            raise APIError("Referencia de catálogo inválida o duplicada", 400)
        fields = PROJECT_FIELDS if kind == "proyecto" else TYPE_FIELDS
        values = {key: row[key] for key in fields if key in row}
        if "activo" in values:
            values["activo"] = csv_boolean(values["activo"])
        if kind == "proyecto":
            values["laborable"] = csv_boolean(values["laborable"])
            values["duracion"] = csv_integer(values["duracion"])
            values["restantes"] = csv_integer(values["restantes"])
            table, id_column = "proyectos", "proyecto_id"
        else:
            values["en_borde"] = csv_boolean(values["en_borde"], nullable=True)
            table, id_column = "tipos_fecha", "tipo_id"
        validated = validate_fields({key: value for key, value in values.items()
                                     if key != "en_borde" or value is not None}, fields)
        if kind == "tipo_fecha" and values["en_borde"] is None:
            validated["en_borde"] = None
        if kind == "tipo_fecha" and validated["nombre"] == "Festivo" and validated["en_borde"] is not False:
            raise APIError("El tipo Festivo no está configurado correctamente en el CSV", 409)
        matches = db.execute(
            sql.SQL("SELECT * FROM {} WHERE nombre IS NOT DISTINCT FROM %s ORDER BY {} FOR UPDATE").format(
                sql.Identifier(table), sql.Identifier(id_column)), (validated["nombre"],)
        ).fetchall()
        if len(matches) > 1:
            raise APIError(f"Hay varios registros de {kind} con el nombre {validated['nombre']!r}", 409)
        if matches:
            match = matches[0]
            if any(match[key] != value for key, value in validated.items() if key != "activo"):
                raise APIError(f"Los datos de {kind} {validated['nombre']!r} no coinciden con el catálogo existente", 409)
        else:
            match = insert(table, validated)
            if kind == "proyecto":
                new_projects.add(match[id_column])
        identifier = match[id_column]
        if identifier in used_ids[kind]:
            raise APIError(f"El CSV contiene varios registros de {kind} con el mismo nombre", 409)
        used_ids[kind].add(identifier)
        refs[ref] = identifier
    db.execute("SELECT usuario_id FROM usuarios WHERE usuario_id = %s FOR UPDATE", (user_id,))
    counts = {"asignaciones": 0, "tipados": 0, "notas": 0, "recordatorios": 0}
    existing_reminders = {
        (row["fecha"], row["hora"], row["texto"])
        for row in db.execute(
            "SELECT fecha, hora, texto FROM recordatorios WHERE usuario_id = %s AND fecha BETWEEN %s AND %s",
            (user_id, date(year or 1, 1, 1), date(year or 9999, 12, 31)),
        ).fetchall()
    }
    for row in records:
        kind = row["tipo"]
        if kind in ("proyecto", "tipo_fecha"):
            continue
        day = valid_date(row["fecha"])
        if year is not None and day.year != year:
            raise APIError("Todas las fechas del CSV deben pertenecer al año indicado", 400)
        if kind == "asignacion":
            project_id = project_refs.get(row["ref"])
            if project_id is None:
                raise APIError("La asignación referencia un proyecto inexistente en el CSV", 400)
            forecast = csv_boolean(row["es_prevision"])
            inserted = db.execute(
                """INSERT INTO asignaciones (usuario_id, fecha, proyecto_id, es_prevision) VALUES (%s, %s, %s, %s)
                   ON CONFLICT DO NOTHING RETURNING proyecto_id""",
                (user_id, day, project_id, forecast),
            ).fetchone()
            if not inserted:
                raise APIError(f"{day.isoformat()}: el proyecto ya está asignado", 409)
            if not forecast and project_id not in new_projects:
                change_remaining(db, project_id, -1)
            counts["asignaciones"] += 1
        elif kind == "tipado":
            type_id = type_refs.get(row["ref"])
            if type_id is None:
                raise APIError("El tipado referencia un tipo inexistente en el CSV", 400)
            try:
                insert_typing(db, day, type_id, require_active=False)
            except APIError as error:
                raise APIError(f"{day.isoformat()}: {error.message}", error.status) from error
            counts["tipados"] += 1
        elif kind == "nota":
            text = valid_reminder_text(row["texto"])
            inserted = db.execute(
                """INSERT INTO notas (usuario_id, fecha, texto) VALUES (%s, %s, %s)
                   ON CONFLICT DO NOTHING RETURNING fecha""", (user_id, day, text)
            ).fetchone()
            if not inserted:
                raise APIError(f"{day.isoformat()}: ya existe una nota", 409)
            counts["notas"] += 1
        elif kind == "recordatorio":
            original = valid_date(row["fecha_original"])
            hour = csv_reminder_time(row["hora"])
            text = valid_reminder_text(row["texto"])
            repeat = csv_boolean(row["repetir"])
            if repeat and reminder_date(day.year, original) != day:
                raise APIError("La fecha original del recordatorio no corresponde a su repetición", 400)
            if (day, hour, text) in existing_reminders:
                raise APIError(f"{day.isoformat()}: ya existe un recordatorio con la misma hora y texto", 409)
            db.execute(
                """INSERT INTO recordatorios (usuario_id, fecha, fecha_original, hora, texto, repetir)
                   VALUES (%s, %s, %s, %s, %s, %s)""", (user_id, day, original, hour, text, repeat)
            )
            existing_reminders.add((day, hour, text))
            counts["recordatorios"] += 1
    return counts


USER_FIELDS = {"nombre", "apellido1", "apellido2", "es_administrador", "activo"}
PROJECT_FIELDS = {"nombre", "descripcion", "duracion", "restantes", "color", "laborable", "activo"}
TYPE_FIELDS = {"nombre", "descripcion", "color", "en_borde", "activo"}
BOOLEAN_FIELDS = {"es_administrador", "activo", "en_borde", "laborable"}
TEXT_FIELDS = {"nombre", "apellido1", "apellido2", "descripcion", "color"}


def get_db():
    if "db" not in g:
        g.db = psycopg.connect(current_app.config["DATABASE_URL"], autocommit=True, row_factory=dict_row)
    return g.db


def lock_project(db, project_id, require_active=False):
    project = db.execute("SELECT activo FROM proyectos WHERE proyecto_id = %s FOR UPDATE", (project_id,)).fetchone()
    if not project:
        raise APIError("Proyecto no encontrado", 404)
    if require_active and not project["activo"]:
        raise APIError("Solo se pueden asignar proyectos activos", 409)


def change_remaining(db, project_id, amount):
    updated = db.execute(
        """UPDATE proyectos SET restantes = restantes + %s
           WHERE proyecto_id = %s AND (
               restantes IS NULL OR (%s < 0 AND restantes > 0) OR (%s > 0 AND restantes < 880)
           )
           RETURNING proyecto_id""",
        (amount, project_id, amount, amount),
    ).fetchone()
    if not updated:
        message = "El proyecto no tiene días restantes" if amount < 0 else "Los días restantes superarían el máximo de 880"
        raise APIError(message, 409)


def insert_typing(db, day, type_id, require_active=True):
    kind = db.execute(
        "SELECT en_borde, activo FROM tipos_fecha WHERE tipo_id = %s FOR SHARE", (type_id,)
    ).fetchone()
    if not kind:
        raise APIError("Tipo de fecha no encontrado", 404)
    if require_active and not kind["activo"]:
        raise APIError("Solo se pueden asignar tipos de fecha activos", 409)
    if kind["en_borde"] is None:
        raise APIError("El tipo de fecha debe tener en_borde definido", 409)
    db.execute("SELECT usuario_id FROM usuarios WHERE usuario_id = %s FOR UPDATE", (g.user["usuario_id"],))
    existing = db.execute(
        """SELECT tf.en_borde FROM tipados t JOIN tipos_fecha tf USING (tipo_id)
           WHERE t.usuario_id = %s AND t.fecha = %s""",
        (g.user["usuario_id"], day),
    ).fetchall()
    if any(row["en_borde"] is None or row["en_borde"] == kind["en_borde"] for row in existing):
        raise APIError("La fecha ya tiene un tipo con ese valor de en_borde", 409)
    result = db.execute(
        "INSERT INTO tipados (usuario_id, fecha, tipo_id) VALUES (%s, %s, %s) RETURNING usuario_id, fecha, tipo_id",
        (g.user["usuario_id"], day, type_id),
    ).fetchone()
    result["fecha"] = result["fecha"].isoformat()
    return result


def serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="calendar-access-token")


def authenticated(admin=False):
    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            authorization = request.headers.get("Authorization", "")
            scheme, separator, token = authorization.partition(" ")
            if separator != " " or scheme.lower() != "bearer" or not token:
                raise APIError("Se requiere un token Bearer", 401)
            try:
                payload = serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
                user_id, version = payload["usuario_id"], payload["version"]
            except (BadSignature, SignatureExpired, KeyError, TypeError):
                raise APIError("Token inválido o caducado", 401)
            user = get_db().execute(
                """SELECT u.usuario_id, u.es_administrador, u.activo
                   FROM usuarios u JOIN credenciales c USING (usuario_id)
                   WHERE u.usuario_id = %s AND c.version = %s""",
                (user_id, version),
            ).fetchone()
            if not user or not user["activo"]:
                raise APIError("Token inválido o usuario inactivo", 401)
            if admin and not user["es_administrador"]:
                raise APIError("Se requieren permisos de administrador", 403)
            g.user = user
            return function(*args, **kwargs)
        return wrapper
    return decorate


def body(allowed, required):
    data = request.get_json()
    if not isinstance(data, dict):
        raise APIError("Se requiere un objeto JSON", 400)
    unknown = set(data) - allowed
    missing = required - set(data)
    if unknown or missing:
        raise APIError(f"Campos desconocidos: {sorted(unknown)}; campos obligatorios ausentes: {sorted(missing)}", 400)
    if not data:
        raise APIError("El objeto JSON no puede estar vacío", 400)
    return data


def validate_fields(data, fields):
    result = {}
    for key in fields & data.keys():
        value = data[key]
        if key in BOOLEAN_FIELDS:
            if type(value) is not bool:
                raise APIError(f"{key} debe ser booleano", 400)
        elif key in TEXT_FIELDS:
            if value is not None and not isinstance(value, str):
                raise APIError(f"{key} debe ser una cadena o null", 400)
            if value is not None and key in {"nombre", "apellido1", "apellido2"} and len(value) > 255:
                raise APIError(f"{key} excede 255 caracteres", 400)
            if value is not None and key == "color" and not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                raise APIError("color debe tener el formato #RRGGBB", 400)
        elif key in {"duracion", "restantes"}:
            if value is not None and (type(value) is not int or not -32768 <= value <= 880):
                raise APIError(f"{key} debe ser un entero entre -32768 y 880, o null", 400)
        result[key] = value
    return result


def valid_username(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255 or value != value.strip():
        raise APIError("nombre_usuario debe tener entre 1 y 255 caracteres, sin espacios exteriores", 400)
    return value


def valid_password(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 1024:
        raise APIError("password debe tener entre 8 y 1024 caracteres", 400)
    return value


def valid_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise APIError("fecha debe tener el formato AAAA-MM-DD", 400)
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise APIError("fecha debe tener el formato AAAA-MM-DD", 400)
    if result.isoformat() != value:
        raise APIError("fecha debe tener el formato AAAA-MM-DD", 400)
    return result


def positive_id(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise APIError("El identificador debe ser un entero positivo", 400)
    return value


def insert(table, values):
    if values:
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        )
        return get_db().execute(query, tuple(values.values())).fetchone()
    return get_db().execute(sql.SQL("INSERT INTO {} DEFAULT VALUES RETURNING *").format(sql.Identifier(table))).fetchone()


def update(table, primary_key, identifier, values):
    if values:
        query = sql.SQL("UPDATE {} SET {} WHERE {} = %s RETURNING *").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(key)) for key in values),
            sql.Identifier(primary_key),
        )
        result = get_db().execute(query, (*values.values(), identifier)).fetchone()
    else:
        result = get_db().execute(
            sql.SQL("SELECT * FROM {} WHERE {} = %s").format(sql.Identifier(table), sql.Identifier(primary_key)),
            (identifier,),
        ).fetchone()
    if not result:
        raise APIError("Registro no encontrado", 404)
    return result
