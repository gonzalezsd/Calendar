import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app import CONFIG_PATH, create_app, load_config


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = load_config(CONFIG_PATH).get("TEST_DATABASE_URL") if CONFIG_PATH.exists() else None
if TEST_DATABASE_URL is not None and not isinstance(TEST_DATABASE_URL, str):
    raise RuntimeError("TEST_DATABASE_URL debe ser una cadena de conexión")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL no está configurado en config.json")
class APITests(unittest.TestCase):
    def setUp(self):
        self.schema = "calendar_test_" + uuid.uuid4().hex
        self.admin_db = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        self.admin_db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.url = make_conninfo(TEST_DATABASE_URL, options=f"-c search_path={self.schema}")
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute((ROOT / "DB/02_crear_tablas.sql").read_text())
            db.execute((ROOT / "DB/03_crear_tipo_festivo.sql").read_text())
            db.execute((ROOT / "DB/04_crear_proyecto_vacaciones.sql").read_text())
        self.app = create_app({"TESTING": True, "DATABASE_URL": self.url, "SECRET_KEY": "test-key-" * 5})
        with patch("app.getpass", side_effect=["password123", "password123"]):
            result = self.app.test_cli_runner().invoke(
                args=["crear-administrador", "--nombre-usuario", "admin", "--nombre", "Admin"]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.client = self.app.test_client()
        self.admin = self.login("admin", "password123")

    def cleanup_schema(self):
        self.admin_db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.admin_db.close()

    def login(self, username, password):
        response = self.client.post("/api/auth/login", json={"nombre_usuario": username, "password": password})
        self.assertEqual(response.status_code, 200, response.json)
        return {"Authorization": "Bearer " + response.json["access_token"]}

    def create_user(self, username):
        response = self.client.post(
            "/api/usuarios",
            headers=self.admin,
            json={"nombre_usuario": username, "password": "password123", "nombre": username},
        )
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["usuario_id"]

    def test_auth_permissions_and_credential_revocation(self):
        user_id = self.create_user("normal")
        user_token = self.login("normal", "password123")
        self.assertEqual(self.client.post("/api/usuarios", headers=user_token, json={}).status_code, 403)
        self.assertEqual(
            self.client.post("/api/proyectos", json={"nombre": "No autorizado"}).status_code, 401
        )
        response = self.client.patch(
            f"/api/usuarios/{user_id}", headers=self.admin, json={"password": "newpassword"}
        )
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(
            self.client.post("/api/proyectos", headers=user_token, json={"nombre": "Test"}).status_code, 401
        )
        self.login("normal", "newpassword")

    def test_per_user_assignment_and_deletion(self):
        self.create_user("other")
        other = self.login("other", "password123")
        project = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Proyecto"})
        self.assertEqual(project.status_code, 201, project.json)
        project_id = project.json["proyecto_id"]
        assignment = {"fecha": "2026-01-01", "proyecto_id": project_id, "es_prevision": False}
        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json=assignment).status_code, 201)
        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json=assignment).status_code, 409)
        path = f"/api/asignaciones/2026-01-01/{project_id}/false"
        self.assertEqual(self.client.delete(path, headers=other).status_code, 404)
        self.assertEqual(self.client.post("/api/asignaciones", headers=other, json=assignment).status_code, 201)
        self.assertEqual(self.client.delete(path, headers=other).status_code, 204)
        self.assertEqual(self.client.delete(path, headers=self.admin).status_code, 204)

    def test_confirm_forecast_and_merge_existing_assignment(self):
        project = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Proyecto"})
        project_id = project.json["proyecto_id"]
        self.create_user("other")
        other = self.login("other", "password123")
        assignment = {"fecha": "2026-01-02", "proyecto_id": project_id, "es_prevision": True}
        for token in (self.admin, other):
            self.assertEqual(self.client.post("/api/asignaciones", headers=token, json=assignment).status_code, 201)
        url = f"/api/asignaciones/2026-01-02/{project_id}/confirmar"
        confirmed = self.client.post(url, headers=self.admin)
        self.assertEqual(confirmed.status_code, 200, confirmed.json)
        self.assertEqual(confirmed.json["es_prevision"], False)
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual([item["es_prevision"] for item in calendar["asignaciones"]], [False])
        other_calendar = self.client.get("/api/calendario/2026", headers=other).json
        self.assertEqual([item["es_prevision"] for item in other_calendar["asignaciones"]], [True])
        self.assertEqual(self.client.post(url, headers=self.admin).status_code, 404)

        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json=assignment).status_code, 201)
        self.assertEqual(self.client.post(url, headers=self.admin).status_code, 200)
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual([item["es_prevision"] for item in calendar["asignaciones"]], [False])
        self.assertEqual(self.client.post(f"/api/asignaciones/2026-02-30/{project_id}/confirmar", headers=self.admin).status_code, 400)
        self.assertEqual(self.client.post(url).status_code, 401)

    def test_multiple_assignments(self):
        project_ids = [
            self.client.post("/api/proyectos", headers=self.admin, json={"nombre": name}).json["proyecto_id"]
            for name in ("Uno", "Dos")
        ]
        type_ids = [
            self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": border}).json["tipo_id"]
            for border in (True, False)
        ]
        payload = {
            "fechas": ["2026-01-02", "2026-01-03"],
            "proyectos": project_ids,
            "tipos": type_ids,
            "es_prevision": True,
        }
        response = self.client.post("/api/asignaciones/multiples", headers=self.admin, json=payload)
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(response.json, {"fechas": 2, "asignaciones": 4, "tipados": 4})
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual(len(calendar["asignaciones"]), 4)
        self.assertTrue(all(item["es_prevision"] for item in calendar["asignaciones"]))
        self.assertEqual(len(calendar["tipados"]), 4)
        self.create_user("other")
        other = self.login("other", "password123")
        self.assertEqual(self.client.get("/api/calendario/2026", headers=other).json, {"asignaciones": [], "tipados": []})
        self.assertEqual(self.client.post("/api/asignaciones/multiples", json=payload).status_code, 401)
        for invalid in (
            {**payload, "fechas": ["2026-01-02"]},
            {**payload, "fechas": ["2026-01-02", "2027-01-02"]},
            {**payload, "proyectos": [], "tipos": []},
            {**payload, "proyectos": [project_ids[0], project_ids[0]]},
            {**payload, "es_prevision": 1},
        ):
            with self.subTest(payload=invalid):
                self.assertEqual(self.client.post("/api/asignaciones/multiples", headers=self.admin, json=invalid).status_code, 400)

    def test_multiple_assignments_roll_back_on_conflict(self):
        project_id = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Proyecto"}).json["proyecto_id"]
        type_id = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True}).json["tipo_id"]
        existing_type = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True}).json["tipo_id"]
        payload = {
            "fechas": ["2026-02-01", "2026-02-02"],
            "proyectos": [project_id],
            "tipos": [type_id],
            "es_prevision": False,
        }
        existing = {"fecha": "2026-02-02", "proyecto_id": project_id, "es_prevision": False}
        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json=existing).status_code, 201)
        conflict = self.client.post("/api/asignaciones/multiples", headers=self.admin, json=payload)
        self.assertEqual(conflict.status_code, 409, conflict.json)
        self.assertIn("2026-02-02", conflict.json["error"])
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual(len(calendar["asignaciones"]), 1)
        self.assertEqual(calendar["tipados"], [])

        self.assertEqual(self.client.delete(f"/api/asignaciones/2026-02-02/{project_id}/false", headers=self.admin).status_code, 204)
        self.assertEqual(self.client.post("/api/tipados", headers=self.admin, json={"fecha": "2026-02-02", "tipo_id": existing_type}).status_code, 201)
        conflict = self.client.post("/api/asignaciones/multiples", headers=self.admin, json=payload)
        self.assertEqual(conflict.status_code, 409, conflict.json)
        self.assertIn("2026-02-02", conflict.json["error"])
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual(calendar["asignaciones"], [])
        self.assertEqual(len(calendar["tipados"]), 1)

    def test_multiple_assignments_serialize_with_single_typing(self):
        ids = [
            self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True}).json["tipo_id"]
            for _ in range(2)
        ]
        def assign(bulk):
            with self.app.test_client() as client:
                if bulk:
                    return client.post("/api/asignaciones/multiples", headers=self.admin, json={
                        "fechas": ["2026-03-01", "2026-03-02"], "proyectos": [], "tipos": [ids[0]], "es_prevision": False
                    }).status_code
                return client.post("/api/tipados", headers=self.admin, json={"fecha": "2026-03-01", "tipo_id": ids[1]}).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(assign, (True, False))), [201, 409])
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual(sum(item["fecha"] == "2026-03-01" for item in calendar["tipados"]), 1)

    def test_typing_rules_and_type_changes(self):
        def create_type(border):
            response = self.client.post(
                "/api/tipos-fecha", headers=self.admin, json={"en_borde": border, "color": "#aAbBcC"}
            )
            self.assertEqual(response.status_code, 201, response.json)
            return response.json["tipo_id"]

        edge, another_edge, inside = create_type(True), create_type(True), create_type(False)
        def assign(type_id):
            return self.client.post(
                "/api/tipados", headers=self.admin, json={"fecha": "2026-02-01", "tipo_id": type_id}
            )
        self.assertEqual(assign(edge).status_code, 201)
        self.assertEqual(assign(another_edge).status_code, 409)
        self.assertEqual(assign(inside).status_code, 201)
        self.assertEqual(
            self.client.patch(f"/api/tipos-fecha/{inside}", headers=self.admin, json={"en_borde": True}).status_code,
            409,
        )
        self.assertEqual(self.client.delete(f"/api/tipados/2026-02-01/{inside}", headers=self.admin).status_code, 204)
        self.assertEqual(
            self.client.patch(f"/api/tipos-fecha/{inside}", headers=self.admin, json={"en_borde": True}).status_code,
            200,
        )

    def test_concurrent_typings_cannot_repeat_border(self):
        ids = []
        for _ in range(2):
            response = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True})
            ids.append(response.json["tipo_id"])

        def assign(type_id):
            with self.app.test_client() as client:
                return client.post(
                    "/api/tipados", headers=self.admin, json={"fecha": "2026-03-01", "tipo_id": type_id}
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(assign, ids)), [201, 409])

    def test_invalid_input_and_absent_records(self):
        self.assertEqual(
            self.client.post("/api/proyectos", headers=self.admin, json={"color": "#123"}).status_code, 400
        )
        self.assertEqual(
            self.client.post("/api/proyectos", headers=self.admin, json={"duracion": 881}).status_code, 400
        )
        self.assertEqual(
            self.client.post("/api/tipados", headers=self.admin, json={"fecha": "2026-02-30", "tipo_id": 1}).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch("/api/proyectos/999999", headers=self.admin, json={"nombre": "x"}).status_code, 404
        )

    def test_project_update_and_user_deactivation(self):
        project = self.client.post(
            "/api/proyectos", headers=self.admin, json={"nombre": "Antes", "duracion": 10}
        )
        project_id = project.json["proyecto_id"]
        updated = self.client.patch(
            f"/api/proyectos/{project_id}", headers=self.admin, json={"nombre": "Después"}
        )
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertEqual(updated.json["nombre"], "Después")
        self.assertEqual(updated.json["duracion"], 10)

        user_id = self.create_user("inactive")
        token = self.login("inactive", "password123")
        self.assertEqual(
            self.client.patch(f"/api/usuarios/{user_id}", headers=self.admin, json={"activo": False}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post("/api/proyectos", headers=token, json={"nombre": "Test"}).status_code, 401
        )
        self.assertEqual(
            self.client.post("/api/auth/login", json={"nombre_usuario": "inactive", "password": "password123"}).status_code,
            401,
        )

    def test_project_laborable(self):
        created = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Trabajo"})
        self.assertEqual(created.status_code, 201, created.json)
        self.assertIs(created.json["laborable"], True)
        project_id = created.json["proyecto_id"]

        updated = self.client.patch(f"/api/proyectos/{project_id}", headers=self.admin, json={"laborable": False})
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertIs(updated.json["laborable"], False)
        projects = self.client.get("/api/proyectos", headers=self.admin).json
        self.assertIs(next(p for p in projects if p["proyecto_id"] == project_id)["laborable"], False)
        assignment = {"fecha": "2026-01-02", "proyecto_id": project_id, "es_prevision": False}
        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json=assignment).status_code, 201)
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertIs(calendar["asignaciones"][0]["laborable"], False)

        created = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Otro", "laborable": False})
        self.assertEqual(created.status_code, 201, created.json)
        self.assertIs(created.json["laborable"], False)
        for invalid in (None, 0, "true"):
            with self.subTest(laborable=invalid):
                self.assertEqual(
                    self.client.patch(f"/api/proyectos/{project_id}", headers=self.admin, json={"laborable": invalid}).status_code,
                    400,
                )

    def test_creation_schema_enforces_calendar_constraints(self):
        with psycopg.connect(self.url, autocommit=True) as db:
            for statement in (
                "INSERT INTO asignaciones (fecha, proyecto_id, es_prevision) VALUES ('2026-01-01', 1, false)",
                "INSERT INTO tipados (fecha, tipo_id) VALUES ('2026-01-01', 1)",
            ):
                with self.subTest(statement=statement), self.assertRaises(psycopg.errors.NotNullViolation):
                    db.execute(statement)
            for statement in (
                "INSERT INTO asignaciones VALUES ('2026-01-01', 999, false, 1)",
                "INSERT INTO tipados VALUES ('2026-01-01', 999, 1)",
                "INSERT INTO credenciales (usuario_id, nombre_usuario, password_hash) VALUES (999, 'missing', 'hash')",
            ):
                with self.subTest(statement=statement), self.assertRaises(psycopg.errors.ForeignKeyViolation):
                    db.execute(statement)
            kind = db.execute("INSERT INTO tipos_fecha (en_borde) VALUES (true) RETURNING tipo_id").fetchone()[0]
            db.execute("INSERT INTO tipados VALUES ('2026-01-01', %s, 1)", (kind,))
            with self.assertRaises(psycopg.errors.UniqueViolation):
                db.execute("INSERT INTO tipados VALUES ('2026-01-01', %s, 1)", (kind,))

    def test_seed_and_new_year(self):
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute((ROOT / "DB/03_crear_tipo_festivo.sql").read_text())
            rows = db.execute(
                "SELECT tipo_id, nombre, descripcion, color, en_borde FROM tipos_fecha WHERE nombre = 'Festivo'"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        kind_id, nombre, description, color, border = rows[0]
        self.assertEqual((nombre, description, color, border), ("Festivo", "Día festivo", "#FF0000", False))
        self.assertEqual(self.client.post("/api/new_year", json={"year": 2026}).status_code, 401)
        response = self.client.post("/api/new_year", headers=self.admin, json={"year": 2026})
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(response.json, {"usuario_id": 1, "fecha": "2026-01-01", "tipo_id": kind_id})
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2026}).status_code, 409)
        for invalid in (0, 10000, True, "2026", 2026.5):
            with self.subTest(year=invalid):
                self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": invalid}).status_code, 400)
        self.assertEqual(self.client.post("/api/tipos-fecha", headers=self.admin, json={"nombre": "Festivo", "en_borde": False}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/tipos-fecha/{kind_id}", headers=self.admin, json={"nombre": "Otro"}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/tipos-fecha/{kind_id}", headers=self.admin, json={"en_borde": True}).status_code, 409)

    def test_seed_rejects_conflicting_existing_data(self):
        seed = (ROOT / "DB/03_crear_tipo_festivo.sql").read_text()
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute("UPDATE tipos_fecha SET color = '#000000' WHERE nombre = 'Festivo'")
            with self.assertRaises(psycopg.errors.RaiseException):
                db.execute(seed)
            db.execute("ROLLBACK")
            self.assertEqual(db.execute("SELECT color FROM tipos_fecha WHERE nombre = 'Festivo'").fetchone()[0], "#000000")

            db.execute("DROP INDEX tipos_fecha_festivo_unico")
            db.execute("INSERT INTO tipos_fecha (nombre, en_borde) VALUES ('Festivo', false)")
            with self.assertRaises(psycopg.errors.UniqueViolation):
                db.execute(seed)
            db.execute("ROLLBACK")
            self.assertEqual(db.execute("SELECT count(*) FROM tipos_fecha WHERE nombre = 'Festivo'").fetchone()[0], 2)

    def test_vacaciones_project_seed(self):
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute((ROOT / "DB/04_crear_proyecto_vacaciones.sql").read_text())
            project = db.execute(
                "SELECT nombre, duracion, restantes, color FROM proyectos WHERE nombre = 'Vacaciones'"
            ).fetchone()
        self.assertEqual(project, ("Vacaciones", None, None, "#FF7800"))

    def test_years_are_unique_sorted_and_private(self):
        self.create_user("other")
        other = self.login("other", "password123")
        self.assertEqual(self.client.get("/api/get_years").status_code, 401)
        self.assertEqual(self.client.get("/api/get_years", headers=self.admin).json, {"years": []})
        project = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Proyecto"})
        project_id = project.json["proyecto_id"]
        for year in (2028, 2025):
            response = self.client.post("/api/asignaciones", headers=self.admin, json={
                "fecha": f"{year}-06-01", "proyecto_id": project_id, "es_prevision": False,
            })
            self.assertEqual(response.status_code, 201, response.json)
        for year, token in ((2025, self.admin), (2027, self.admin), (2030, other)):
            self.assertEqual(self.client.post("/api/new_year", headers=token, json={"year": year}).status_code, 201)
        self.assertEqual(self.client.get("/api/get_years", headers=self.admin).json, {"years": [2025, 2027, 2028]})
        self.assertEqual(self.client.get("/api/get_years", headers=other).json, {"years": [2030]})

    def test_new_year_respects_typing_conflicts(self):
        border = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True}).json["tipo_id"]
        inside = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": False}).json["tipo_id"]
        for kind_id, day in ((border, "2026-01-01"), (inside, "2027-01-01")):
            self.assertEqual(self.client.post(
                "/api/tipados", headers=self.admin, json={"fecha": day, "tipo_id": kind_id},
            ).status_code, 201)
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2026}).status_code, 201)
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2027}).status_code, 409)
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute("DELETE FROM tipos_fecha WHERE nombre = 'Festivo' AND tipo_id NOT IN (SELECT tipo_id FROM tipados)")
            db.execute("UPDATE tipos_fecha SET nombre = 'No festivo' WHERE nombre = 'Festivo'")
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2028}).status_code, 409)

    def test_new_year_concurrent_with_typing(self):
        kind = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": False}).json["tipo_id"]
        def assign(path, payload):
            with self.app.test_client() as client:
                return client.post(path, headers=self.admin, json=payload).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(assign, "/api/new_year", {"year": 2032})
            second = executor.submit(assign, "/api/tipados", {"fecha": "2032-01-01", "tipo_id": kind})
            self.assertEqual(sorted([first.result(), second.result()]), [201, 409])

    def test_read_endpoints_respect_permissions_and_calendar_ownership(self):
        self.create_user("other")
        other = self.login("other", "password123")
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertTrue(self.client.get("/api/me", headers=self.admin).json["es_administrador"])
        self.assertFalse(self.client.get("/api/me", headers=other).json["es_administrador"])
        self.assertEqual(self.client.get("/api/usuarios", headers=other).status_code, 403)
        users = self.client.get("/api/usuarios", headers=self.admin).json
        self.assertEqual(len(users), 2)
        self.assertNotIn("password_hash", users[0])
        project = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Trabajo", "color": "#123456"}).json
        self.assertEqual(self.client.get("/api/proyectos", headers=other).json[0]["nombre"], "Trabajo")
        self.assertEqual(self.client.get("/api/tipos-fecha", headers=other).json[0]["nombre"], "Festivo")
        self.assertEqual(self.client.post("/api/new_year", headers=other, json={"year": 2026}).status_code, 201)
        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json={
            "fecha": "2026-03-01", "proyecto_id": project["proyecto_id"], "es_prevision": False,
        }).status_code, 201)
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual(len(calendar["asignaciones"]), 1)
        self.assertEqual(calendar["asignaciones"][0]["fecha"], "2026-03-01")
        self.assertEqual(calendar["tipados"], [])
        other_calendar = self.client.get("/api/calendario/2026", headers=other).json
        self.assertEqual(other_calendar["asignaciones"], [])
        self.assertEqual(other_calendar["tipados"][0]["nombre"], "Festivo")
        self.assertEqual(self.client.get("/api/calendario/2027", headers=other).json, {"asignaciones": [], "tipados": []})
        self.assertEqual(self.client.get("/api/calendario/10000", headers=other).status_code, 400)


if __name__ == "__main__":
    unittest.main()
