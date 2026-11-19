import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app import create_app


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL no está configurado")
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


if __name__ == "__main__":
    unittest.main()
