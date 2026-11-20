import json
import re
from datetime import date
from functools import wraps
from getpass import getpass
from pathlib import Path

import click
import psycopg
from flask import Flask, current_app, g, jsonify, request
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


def load_config(path):
    try:
        with path.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
    except FileNotFoundError as error:
        raise RuntimeError(f"No existe {path}; crea el fichero a partir de config.example.json") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"El fichero {path} no contiene JSON válido") from error
    except UnicodeDecodeError as error:
        raise RuntimeError(f"El fichero {path} debe estar codificado en UTF-8") from error
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
        return jsonify(access_token=token, token_type="Bearer", expires_in=3600)

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

    @app.post("/api/asignaciones")
    @authenticated()
    def create_assignment():
        data = body({"fecha", "proyecto_id", "es_prevision"}, {"fecha", "proyecto_id", "es_prevision"})
        day = valid_date(data["fecha"])
        project_id = positive_id(data["proyecto_id"])
        if type(data["es_prevision"]) is not bool:
            raise APIError("es_prevision debe ser booleano", 400)
        with get_db().transaction():
            result = get_db().execute(
                """INSERT INTO asignaciones (usuario_id, fecha, proyecto_id, es_prevision)
                   VALUES (%s, %s, %s, %s) RETURNING usuario_id, fecha, proyecto_id, es_prevision""",
                (g.user["usuario_id"], day, project_id, data["es_prevision"]),
            ).fetchone()
        result["fecha"] = result["fecha"].isoformat()
        return jsonify(result), 201

    @app.delete("/api/asignaciones/<day>/<int:project_id>/<forecast>")
    @authenticated()
    def delete_assignment(day, project_id, forecast):
        day = valid_date(day)
        positive_id(project_id)
        if forecast not in ("true", "false"):
            raise APIError("es_prevision debe ser true o false", 400)
        with get_db().transaction():
            row = get_db().execute(
                """DELETE FROM asignaciones WHERE usuario_id = %s AND fecha = %s
                   AND proyecto_id = %s AND es_prevision = %s RETURNING usuario_id""",
                (g.user["usuario_id"], day, project_id, forecast == "true"),
            ).fetchone()
            if not row:
                raise APIError("Asignación no encontrada", 404)
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

    @app.get("/api/get_years")
    @authenticated()
    def get_years():
        rows = get_db().execute(
            """SELECT EXTRACT(YEAR FROM fecha)::integer AS year FROM asignaciones WHERE usuario_id = %s
               UNION
               SELECT EXTRACT(YEAR FROM fecha)::integer AS year FROM tipados WHERE usuario_id = %s
               ORDER BY year""",
            (g.user["usuario_id"], g.user["usuario_id"]),
        ).fetchall()
        return jsonify(years=[row["year"] for row in rows])

    @app.get("/api/calendario/<int:year>")
    @authenticated()
    def get_calendar(year):
        if not 1 <= year <= 9999:
            raise APIError("year debe ser un entero entre 1 y 9999", 400)
        db = get_db()
        assignments = db.execute(
            """SELECT a.fecha, a.proyecto_id, a.es_prevision, p.nombre, p.color
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
        for row in assignments + typings:
            row["fecha"] = row["fecha"].isoformat()
        return jsonify(asignaciones=assignments, tipados=typings)

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
            result = insert_typing(db, date(year, 1, 1), kinds[0]["tipo_id"])
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


USER_FIELDS = {"nombre", "apellido1", "apellido2", "es_administrador", "activo"}
PROJECT_FIELDS = {"nombre", "descripcion", "duracion", "restantes", "color"}
TYPE_FIELDS = {"nombre", "descripcion", "color", "en_borde"}
BOOLEAN_FIELDS = {"es_administrador", "activo", "en_borde"}
TEXT_FIELDS = {"nombre", "apellido1", "apellido2", "descripcion", "color"}


def get_db():
    if "db" not in g:
        g.db = psycopg.connect(current_app.config["DATABASE_URL"], autocommit=True, row_factory=dict_row)
    return g.db


def insert_typing(db, day, type_id):
    kind = db.execute(
        "SELECT en_borde FROM tipos_fecha WHERE tipo_id = %s FOR SHARE", (type_id,)
    ).fetchone()
    if not kind:
        raise APIError("Tipo de fecha no encontrado", 404)
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
                payload = serializer().loads(token, max_age=3600)
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
