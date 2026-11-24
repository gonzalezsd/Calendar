import csv
import io
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
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

    def test_session_valid_for_ten_hours(self):
        start = 1_700_000_000
        with patch("itsdangerous.timed.time.time", return_value=start):
            response = self.client.post("/api/auth/login", json={"nombre_usuario": "admin", "password": "password123"})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["expires_in"], 36000)
        headers = {"Authorization": "Bearer " + response.json["access_token"]}
        with patch("itsdangerous.timed.time.time", return_value=start + 35999):
            self.assertEqual(self.client.get("/api/me", headers=headers).status_code, 200)
        with patch("itsdangerous.timed.time.time", return_value=start + 36001):
            self.assertEqual(self.client.get("/api/me", headers=headers).status_code, 401)

    def test_per_user_assignment_and_deletion(self):
        self.create_user("other")
        other = self.login("other", "password123")
        project = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Proyecto", "activo": True})
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

    def test_notes_are_unique_private_editable_and_expose_their_year(self):
        self.create_user("other")
        other = self.login("other", "password123")
        path = "/api/notas/2031-02-03"
        self.assertEqual(self.client.put(path, json={"texto": "sin sesión"}).status_code, 401)
        response = self.client.put(path, headers=self.admin, json={"texto": "Primera\nnota"})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json, {"fecha": "2031-02-03", "texto": "Primera\nnota"})
        self.assertEqual(self.client.put(path, headers=self.admin, json={"texto": " Editada "}).status_code, 200)
        self.assertEqual(self.client.put(path, headers=other, json={"texto": "Privada"}).status_code, 200)
        self.assertEqual(self.client.get("/api/calendario/2031", headers=self.admin).json["notas"],
                         [{"fecha": "2031-02-03", "texto": " Editada "}])
        self.assertEqual(self.client.get("/api/calendario/2031", headers=other).json["notas"],
                         [{"fecha": "2031-02-03", "texto": "Privada"}])
        self.assertEqual(self.client.get("/api/calendario/2032", headers=self.admin).json["notas"], [])
        self.assertEqual(self.client.get("/api/get_years", headers=self.admin).json["years"], [2031])
        with psycopg.connect(self.url, autocommit=True) as db:
            with self.assertRaises(psycopg.errors.UniqueViolation):
                db.execute("INSERT INTO notas (usuario_id, fecha, texto) VALUES (1, '2031-02-03', 'duplicada')")
        self.assertEqual(self.client.delete(path, headers=self.admin).status_code, 204)
        self.assertEqual(self.client.delete(path, headers=self.admin).status_code, 404)
        self.assertEqual(self.client.get("/api/get_years", headers=self.admin).json["years"], [])
        self.assertEqual(self.client.get("/api/calendario/2031", headers=other).json["notas"][0]["texto"], "Privada")

    def test_notes_reject_invalid_input_without_changing_existing_note(self):
        path = "/api/notas/2031-02-03"
        self.assertEqual(self.client.put(path, headers=self.admin, json={"texto": "Original"}).status_code, 200)
        for data in ({}, {"texto": None}, {"texto": ""}, {"texto": " \n\t"}, {"texto": "nul\u0000byte"},
                     {"texto": 1}, {"texto": "x", "usuario_id": 2}):
            with self.subTest(data=data):
                self.assertEqual(self.client.put(path, headers=self.admin, json=data).status_code, 400)
        self.assertEqual(self.client.put("/api/notas/2031-02-30", headers=self.admin, json={"texto": "x"}).status_code, 400)
        self.assertEqual(self.client.get("/api/calendario/2031", headers=self.admin).json["notas"][0]["texto"], "Original")

    def test_note_migration_for_existing_schema(self):
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute("DROP TABLE notas")
            db.execute((ROOT / "DB/05_crear_notas.sql").read_text())
        response = self.client.put("/api/notas/2031-02-03", headers=self.admin, json={"texto": "Migrada"})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.client.get("/api/calendario/2031", headers=self.admin).json["notas"],
                         [{"fecha": "2031-02-03", "texto": "Migrada"}])

    def test_reminders_are_private_and_validate_date_time_and_text(self):
        self.create_user("other")
        other = self.login("other", "password123")
        path = "/api/recordatorios"
        daily = {"fecha": "2031-02-03", "hora": None, "texto": "Día completo\n<literal>", "repetir": True}
        timed = {"fecha": "2031-02-03", "hora": "09:30", "texto": "Cita", "repetir": False}
        self.assertEqual(self.client.post(path, json=daily).status_code, 401)
        first = self.client.post(path, headers=self.admin, json=daily)
        second = self.client.post(path, headers=self.admin, json=timed)
        self.assertEqual(first.status_code, 201, first.json)
        self.assertEqual(second.status_code, 201, second.json)
        self.assertEqual({key: first.json[key] for key in daily}, daily)
        self.assertEqual({key: second.json[key] for key in timed}, timed)
        self.assertEqual(self.client.get(path + "/2031-02-03", headers=self.admin).json,
                         [first.json, second.json])
        self.assertEqual(self.client.get(path + "/2031-02-03", headers=other).json, [])
        self.assertEqual(self.client.get("/api/calendario/2031", headers=self.admin).json["recordatorios"],
                         [first.json, second.json])
        self.assertEqual(self.client.get("/api/calendario/2031", headers=other).json["recordatorios"], [])
        self.assertEqual(self.client.get("/api/get_years", headers=self.admin).json["years"], [2031])
        invalid = [
            {**daily, "fecha": "2031-02-30"}, {**daily, "hora": "24:00"},
            {**daily, "hora": "09:30:00"}, {**daily, "hora": 9}, {**daily, "texto": "  "},
            {**daily, "texto": "a\u0000b"}, {**daily, "repetir": 1}, {**daily, "usuario_id": 2},
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.assertEqual(self.client.post(path, headers=self.admin, json=value).status_code, 400)
        self.assertEqual(self.client.get(path + "/2031-02-30", headers=self.admin).status_code, 400)
        self.assertEqual(len(self.client.get(path + "/2031-02-03", headers=self.admin).json), 2)

    def test_new_year_copies_recurring_reminders_without_duplicates_and_preserves_leap_day(self):
        self.create_user("other")
        other = self.login("other", "password123")
        def create(token, day, text, repeat=True, hour=None):
            response = self.client.post("/api/recordatorios", headers=token, json={
                "fecha": day, "hora": hour, "texto": text, "repetir": repeat,
            })
            self.assertEqual(response.status_code, 201, response.json)
        create(self.admin, "2024-02-29", "Bisiesto")
        create(self.admin, "2024-03-05", "Cita", hour="09:30")
        create(self.admin, "2026-03-05", "Cita", hour="09:30")
        create(self.admin, "2035-05-01", "Desde el futuro")
        create(self.admin, "2024-06-01", "No repetir", repeat=False)
        create(self.admin, "2029-03-05", "Cita", repeat=False, hour="09:30")
        create(other, "2024-07-01", "Privado")
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2029}).status_code, 201)
        reminders = self.client.get("/api/calendario/2029", headers=self.admin).json["recordatorios"]
        self.assertEqual([(r["fecha"], r["texto"]) for r in reminders], [
            ("2029-02-28", "Bisiesto"), ("2029-03-05", "Cita"), ("2029-05-01", "Desde el futuro")
        ])
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2032}).status_code, 201)
        reminders = self.client.get("/api/calendario/2032", headers=self.admin).json["recordatorios"]
        self.assertEqual([(r["fecha"], r["texto"]) for r in reminders], [
            ("2032-02-29", "Bisiesto"), ("2032-03-05", "Cita"), ("2032-05-01", "Desde el futuro")
        ])
        self.assertEqual(self.client.get("/api/calendario/2032", headers=other).json["recordatorios"], [])
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2029}).status_code, 409)
        self.assertEqual(len(self.client.get("/api/calendario/2029", headers=self.admin).json["recordatorios"]), 3)

    def test_reminder_migration_for_existing_schema(self):
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute("DROP TABLE recordatorios")
            db.execute((ROOT / "DB/06_crear_recordatorios.sql").read_text())
        response = self.client.post("/api/recordatorios", headers=self.admin, json={
            "fecha": "2031-02-03", "texto": "Migrado", "repetir": False,
        })
        self.assertEqual(response.status_code, 201, response.json)
        self.assertIsNone(response.json["hora"])

    def test_edit_recurring_reminders_updates_all_occurrences_and_future_years(self):
        self.create_user("other")
        other = self.login("other", "password123")
        def create(token, day, text, repeat=True):
            response = self.client.post("/api/recordatorios", headers=token, json={
                "fecha": day, "hora": None, "texto": text, "repetir": repeat,
            })
            self.assertEqual(response.status_code, 201, response.json)
            return response.json["recordatorio_id"]
        reminder_id = create(self.admin, "2024-02-29", "Cumpleaños")
        create(self.admin, "2036-02-29", "Cumpleaños")
        create(self.admin, "2025-02-28", "Otro", repeat=False)
        other_id = create(other, "2024-02-29", "Cumpleaños")
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2025}).status_code, 201)
        listed = self.client.get("/api/recordatorios/recurrentes", headers=self.admin)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json, [{"recordatorio_id": reminder_id, "mes": 2, "dia": 29,
                                        "hora": None, "texto": "Cumpleaños", "repetir": True}])
        payload = {"mes": 3, "dia": 1, "hora": "10:15", "texto": "Actualizado", "repetir": True}
        self.assertEqual(self.client.patch(f"/api/recordatorios/{other_id}", headers=self.admin, json=payload).status_code, 404)
        response = self.client.patch(f"/api/recordatorios/{reminder_id}", headers=self.admin, json=payload)
        self.assertEqual(response.status_code, 200, response.json)
        for year in (2024, 2025, 2036):
            reminders = self.client.get(f"/api/calendario/{year}", headers=self.admin).json["recordatorios"]
            matching = [r for r in reminders if r["texto"] == "Actualizado"]
            self.assertEqual(len(matching), 1)
            self.assertEqual((matching[0]["fecha"], matching[0]["hora"], matching[0]["repetir"]),
                             (f"{year}-03-01", "10:15", True))
        self.assertEqual(self.client.get("/api/recordatorios/2024-02-29", headers=other).json[0]["texto"], "Cumpleaños")
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2026}).status_code, 201)
        self.assertEqual(self.client.get("/api/recordatorios/2026-03-01", headers=self.admin).json[0]["texto"], "Actualizado")
        payload.update({"mes": 2, "dia": 29, "hora": None, "repetir": False})
        self.assertEqual(self.client.patch(f"/api/recordatorios/{reminder_id}", headers=self.admin, json=payload).status_code, 200)
        self.assertEqual(self.client.get("/api/recordatorios/recurrentes", headers=self.admin).json, [])
        for year, day in ((2024, 29), (2025, 28), (2026, 28), (2036, 29)):
            reminders = self.client.get(f"/api/recordatorios/{year}-02-{day}", headers=self.admin).json
            self.assertEqual(sum(r["texto"] == "Actualizado" and not r["repetir"] for r in reminders), 1)
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2028}).status_code, 201)
        self.assertEqual(self.client.get("/api/recordatorios/2028-02-29", headers=self.admin).json, [])

    def test_recurring_reminder_edit_rejects_invalid_and_conflicting_updates(self):
        def create(day, text):
            return self.client.post("/api/recordatorios", headers=self.admin, json={
                "fecha": day, "texto": text, "repetir": True,
            }).json["recordatorio_id"]
        first = create("2024-02-29", "Primero")
        create("2024-03-01", "Segundo")
        payload = {"mes": 3, "dia": 1, "hora": None, "texto": "Segundo", "repetir": True}
        self.assertEqual(self.client.patch(f"/api/recordatorios/{first}", headers=self.admin, json=payload).status_code, 409)
        for change in ({"mes": 2, "dia": 30}, {"mes": True}, {"dia": 10**100},
                       {"hora": "25:00"}, {"texto": " "}, {"repetir": 1}):
            with self.subTest(change=change):
                self.assertEqual(self.client.patch(f"/api/recordatorios/{first}", headers=self.admin,
                                                   json={**payload, **change}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/recordatorios/{first}", json=payload).status_code, 401)
        self.assertEqual(self.client.get("/api/recordatorios/2024-02-29", headers=self.admin).json[0]["texto"], "Primero")

    def test_calendar_csv_round_trip_is_private_and_adjusts_existing_project_balance(self):
        self.create_user("other")
        other = self.login("other", "password123")
        project = self.client.post("/api/proyectos", headers=self.admin, json={
            "nombre": "Trabajo, especial", "descripcion": "Primera\nsegunda", "restantes": 3,
            "duracion": 10, "color": "#123456", "laborable": True, "activo": True,
        }).json
        day = "2025-03-03"
        for forecast in (False, True):
            self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json={
                "fecha": day, "proyecto_id": project["proyecto_id"], "es_prevision": forecast,
            }).status_code, 201)
        type_id = self.client.post("/api/tipos-fecha", headers=self.admin, json={
            "nombre": "Especial", "color": "#ABCDEF", "en_borde": True, "activo": True,
        }).json["tipo_id"]
        self.assertEqual(self.client.post("/api/tipados", headers=self.admin, json={
            "fecha": day, "tipo_id": type_id,
        }).status_code, 201)
        note = '=1+1, con "comillas"\ny \\N'
        self.assertEqual(self.client.put(f"/api/notas/{day}", headers=self.admin, json={"texto": note}).status_code, 200)
        self.assertEqual(self.client.post("/api/recordatorios", headers=self.admin, json={
            "fecha": day, "hora": "10:30", "texto": "\\N", "repetir": True,
        }).status_code, 201)
        self.assertEqual(self.client.post("/api/recordatorios", headers=self.admin, json={
            "fecha": day, "hora": None, "texto": "Todo el día", "repetir": False,
        }).status_code, 201)
        self.assertEqual(self.client.get("/api/calendario/2025/exportar").status_code, 401)
        exported = self.client.get("/api/calendario/2025/exportar", headers=self.admin)
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.mimetype, "text/csv")
        csv_rows = list(csv.DictReader(io.StringIO(exported.data.decode(), newline="")))
        self.assertTrue(next(row["texto"] for row in csv_rows if row["tipo"] == "nota").startswith("'=1+1"))
        result = self.client.post("/api/calendario/importar", headers=other, data=exported.data, content_type="text/csv")
        self.assertEqual(result.status_code, 201, result.json)
        self.assertEqual(result.json, {"year": 2025, "asignaciones": 2, "tipados": 1, "notas": 1, "recordatorios": 2})
        calendar = self.client.get("/api/calendario/2025", headers=other).json
        self.assertEqual(calendar["notas"], [{"fecha": day, "texto": note}])
        self.assertEqual([(r["hora"], r["texto"]) for r in calendar["recordatorios"]],
                         [(None, "Todo el día"), ("10:30", "\\N")])
        self.assertEqual({a["es_prevision"] for a in calendar["asignaciones"]}, {True, False})
        self.assertEqual(calendar["tipados"][0]["tipo_id"], type_id)
        projects = self.client.get("/api/proyectos", headers=self.admin).json
        self.assertEqual(next(p["restantes"] for p in projects if p["proyecto_id"] == project["proyecto_id"]), 1)
        repeat = self.client.post("/api/calendario/importar", headers=other, data=exported.data, content_type="text/csv")
        self.assertEqual(repeat.status_code, 409)
        projects = self.client.get("/api/proyectos", headers=self.admin).json
        self.assertEqual(next(p["restantes"] for p in projects if p["proyecto_id"] == project["proyecto_id"]), 1)
        self.assertEqual(len(self.client.get("/api/calendario/2025", headers=other).json["asignaciones"]), 2)

    def test_full_calendar_csv_round_trip_and_atomic_conflict(self):
        self.create_user("other")
        other = self.login("other", "password123")
        self.assertEqual(self.client.get("/api/calendario/exportar").status_code, 401)
        self.assertEqual(self.client.get("/api/calendario/exportar", headers=self.admin).status_code, 404)
        project_id = self.client.post("/api/proyectos", headers=self.admin, json={
            "nombre": "Trabajo", "laborable": True, "activo": True,
        }).json["proyecto_id"]
        type_id = self.client.post("/api/tipos-fecha", headers=self.admin, json={
            "nombre": "Especial", "en_borde": True, "activo": True,
        }).json["tipo_id"]
        for day in ("2024-02-29", "2025-02-28"):
            self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json={
                "fecha": day, "proyecto_id": project_id, "es_prevision": day.startswith("2025"),
            }).status_code, 201)
            self.assertEqual(self.client.post("/api/tipados", headers=self.admin, json={
                "fecha": day, "tipo_id": type_id,
            }).status_code, 201)
            self.assertEqual(self.client.put(f"/api/notas/{day}", headers=self.admin, json={"texto": day}).status_code, 200)
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute(
                """INSERT INTO recordatorios (usuario_id, fecha, fecha_original, hora, texto, repetir)
                   VALUES (1, '2024-02-29', '2024-02-29', NULL, 'Bisiesto', true),
                          (1, '2025-02-28', '2024-02-29', NULL, 'Bisiesto', true)"""
            )
        self.client.put("/api/notas/2030-01-01", headers=other, json={"texto": "Privada"})
        exported = self.client.get("/api/calendario/exportar", headers=self.admin)
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.mimetype, "text/csv")
        self.assertEqual(exported.headers["Cache-Control"], "no-store")
        self.assertIn("calendario-completo.csv", exported.headers["Content-Disposition"])
        rows = list(csv.DictReader(io.StringIO(exported.data.decode(), newline="")))
        self.assertEqual((rows[0]["version"], rows[0]["anio"]), ("2", r"\N"))
        self.assertEqual(sum(row["tipo"] == "proyecto" for row in rows), 1)
        self.assertEqual(sum(row["tipo"] == "tipo_fecha" for row in rows), 1)
        self.assertNotIn(b"Privada", exported.data)

        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=rows[0].keys(), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        writer.writerow(next(row for row in rows if row["tipo"] == "recordatorio"))
        duplicate = self.client.post("/api/calendario/importar", headers=other, data=output.getvalue().encode())
        self.assertEqual(duplicate.status_code, 409, duplicate.json)
        self.assertEqual(self.client.get("/api/calendario/2024", headers=other).json["asignaciones"], [])

        self.client.put("/api/notas/2025-02-28", headers=other, json={"texto": "Conflicto"})
        conflict = self.client.post("/api/calendario/importar", headers=other, data=exported.data)
        self.assertEqual(conflict.status_code, 409, conflict.json)
        self.assertEqual(self.client.get("/api/calendario/2024", headers=other).json["asignaciones"], [])
        self.assertEqual(self.client.get("/api/calendario/2024", headers=other).json["notas"], [])
        self.client.delete("/api/notas/2025-02-28", headers=other)
        result = self.client.post("/api/calendario/importar", headers=other, data=exported.data)
        self.assertEqual(result.status_code, 201, result.json)
        self.assertEqual(result.json, {
            "years": [2024, 2025], "asignaciones": 2, "tipados": 2, "notas": 2, "recordatorios": 2,
        })
        for day in ("2024-02-29", "2025-02-28"):
            calendar = self.client.get(f"/api/calendario/{day[:4]}", headers=other).json
            self.assertEqual(calendar["notas"], [{"fecha": day, "texto": day}])
            self.assertEqual(len(calendar["asignaciones"]), 1)
            self.assertEqual(len(calendar["tipados"]), 1)
            self.assertEqual(calendar["recordatorios"][0]["texto"], "Bisiesto")
        with psycopg.connect(self.url) as db:
            self.assertEqual(db.execute(
                "SELECT fecha_original::text FROM recordatorios WHERE usuario_id = 2 AND fecha = '2025-02-28'"
            ).fetchone()[0], "2024-02-29")

    def test_calendar_csv_new_catalog_conflicts_and_invalid_files_are_atomic(self):
        self.create_user("other")
        other = self.login("other", "password123")
        project_id = self.client.post("/api/proyectos", headers=self.admin, json={
            "nombre": "Origen", "restantes": 5, "laborable": True, "activo": True,
        }).json["proyecto_id"]
        self.client.post("/api/asignaciones", headers=self.admin, json={
            "fecha": "2031-02-03", "proyecto_id": project_id, "es_prevision": False,
        })
        self.client.put("/api/notas/2031-02-03", headers=self.admin, json={"texto": "Nota"})
        exported = self.client.get("/api/calendario/2031/exportar", headers=self.admin).data.decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(exported, newline="")))
        for row in rows:
            if row["tipo"] == "proyecto":
                row["nombre"] = "Importado"
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=rows[0].keys(), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        payload = output.getvalue().encode()
        self.client.put("/api/notas/2031-02-03", headers=other, json={"texto": "Existente"})
        conflict = self.client.post("/api/calendario/importar", headers=other, data=payload, content_type="text/csv")
        self.assertEqual(conflict.status_code, 409, conflict.json)
        self.assertFalse(any(p["nombre"] == "Importado" for p in self.client.get("/api/proyectos", headers=other).json))
        self.assertEqual(self.client.get("/api/calendario/2031", headers=other).json["asignaciones"], [])
        self.client.delete("/api/notas/2031-02-03", headers=other)
        result = self.client.post("/api/calendario/importar", headers=other, data=payload, content_type="text/csv")
        self.assertEqual(result.status_code, 201, result.json)
        created = next(p for p in self.client.get("/api/proyectos", headers=other).json if p["nombre"] == "Importado")
        self.assertEqual(created["restantes"], 4)
        for invalid in (b"no,csv\n", b"\xff", payload.replace(b"2031-02-03", b"2032-02-03")):
            with self.subTest(payload=invalid[:15]):
                response = self.client.post("/api/calendario/importar", headers=self.admin, data=invalid, content_type="text/csv")
                self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(self.client.post("/api/calendario/importar", data=payload, content_type="text/csv").status_code, 401)

    def test_calendar_csv_preserves_original_leap_day_for_future_repetition(self):
        self.create_user("other")
        other = self.login("other", "password123")
        self.assertEqual(self.client.post("/api/recordatorios", headers=self.admin, json={
            "fecha": "2024-02-29", "texto": "Bisiesto", "repetir": True,
        }).status_code, 201)
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2025}).status_code, 201)
        exported = self.client.get("/api/calendario/2025/exportar", headers=self.admin)
        imported = self.client.post("/api/calendario/importar", headers=other, data=exported.data, content_type="text/csv")
        self.assertEqual(imported.status_code, 201, imported.json)
        self.assertEqual(self.client.get("/api/recordatorios/2025-02-28", headers=other).json[0]["texto"], "Bisiesto")
        self.assertEqual(self.client.post("/api/new_year", headers=other, json={"year": 2028}).status_code, 201)
        self.assertEqual(self.client.get("/api/recordatorios/2028-02-29", headers=other).json[0]["texto"], "Bisiesto")

    def test_calendar_csv_preserves_long_text_and_time_precision(self):
        self.create_user("other")
        other = self.login("other", "password123")
        text = "'" + "x" * 140000
        self.assertEqual(self.client.put("/api/notas/2030-01-05", headers=self.admin, json={"texto": text}).status_code, 200)
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute(
                """INSERT INTO recordatorios (usuario_id, fecha, fecha_original, hora, texto, repetir)
                   VALUES (1, '2030-01-05', '2030-01-05', '10:30:15.123456', 'Cita', false)"""
            )
        exported = self.client.get("/api/calendario/2030/exportar", headers=self.admin)
        result = self.client.post("/api/calendario/importar", headers=other, data=exported.data, content_type="text/csv")
        self.assertEqual(result.status_code, 201, result.json)
        self.assertEqual(self.client.get("/api/calendario/2030", headers=other).json["notas"][0]["texto"], text)
        with psycopg.connect(self.url, autocommit=True) as db:
            self.assertEqual(db.execute(
                "SELECT hora::text FROM recordatorios WHERE usuario_id = 2 AND fecha = '2030-01-05'"
            ).fetchone()[0], "10:30:15.123456")

    def test_calendar_csv_rejects_insufficient_project_days_without_partial_changes(self):
        self.create_user("other")
        other = self.login("other", "password123")
        project_id = self.client.post("/api/proyectos", headers=self.admin, json={
            "nombre": "Limitado CSV", "restantes": 1, "activo": True,
        }).json["proyecto_id"]
        self.client.post("/api/asignaciones", headers=self.admin, json={
            "fecha": "2030-05-01", "proyecto_id": project_id, "es_prevision": False,
        })
        self.client.put("/api/notas/2030-05-01", headers=self.admin, json={"texto": "Nota"})
        exported = self.client.get("/api/calendario/2030/exportar", headers=self.admin)
        result = self.client.post("/api/calendario/importar", headers=other, data=exported.data, content_type="text/csv")
        self.assertEqual(result.status_code, 409, result.json)
        self.assertIn("días restantes", result.json["error"])
        calendar = self.client.get("/api/calendario/2030", headers=other).json
        self.assertEqual(calendar["asignaciones"], [])
        self.assertEqual(calendar["notas"], [])

    def test_confirm_forecast_and_merge_existing_assignment(self):
        project = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Proyecto", "activo": True})
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

    def test_remaining_days_for_confirmations_and_deletions(self):
        project_id = self.client.post(
            "/api/proyectos", headers=self.admin, json={"nombre": "Limitado", "restantes": 2, "activo": True}
        ).json["proyecto_id"]

        def remaining():
            return next(p["restantes"] for p in self.client.get("/api/proyectos", headers=self.admin).json
                        if p["proyecto_id"] == project_id)

        def assign(day, forecast):
            return self.client.post("/api/asignaciones", headers=self.admin, json={
                "fecha": day, "proyecto_id": project_id, "es_prevision": forecast
            })

        self.assertEqual(assign("2026-01-01", False).status_code, 201)
        self.assertEqual(remaining(), 1)
        self.assertEqual(assign("2026-01-01", False).status_code, 409)
        self.assertEqual(assign("2026-01-01", True).status_code, 201)
        self.assertEqual(self.client.post(f"/api/asignaciones/2026-01-01/{project_id}/confirmar", headers=self.admin).status_code, 200)
        self.assertEqual(remaining(), 1)
        self.assertEqual(assign("2026-01-02", True).status_code, 201)
        self.assertEqual(self.client.post(f"/api/asignaciones/2026-01-02/{project_id}/confirmar", headers=self.admin).status_code, 200)
        self.assertEqual(remaining(), 0)
        self.assertEqual(assign("2026-01-02", True).status_code, 201)
        self.assertEqual(self.client.post(f"/api/asignaciones/2026-01-02/{project_id}/confirmar", headers=self.admin).status_code, 200)
        self.assertEqual(remaining(), 0)
        self.assertEqual(assign("2026-01-03", True).status_code, 201)
        self.assertEqual(self.client.post(f"/api/asignaciones/2026-01-03/{project_id}/confirmar", headers=self.admin).status_code, 409)
        self.assertEqual(assign("2026-01-04", False).status_code, 409)
        assignments = self.client.get("/api/calendario/2026", headers=self.admin).json["asignaciones"]
        self.assertTrue(any(a["fecha"] == "2026-01-03" and a["es_prevision"] for a in assignments))
        self.assertFalse(any(a["fecha"] == "2026-01-04" for a in assignments))
        self.assertEqual(self.client.delete(f"/api/asignaciones/2026-01-03/{project_id}/true", headers=self.admin).status_code, 204)
        self.assertEqual(remaining(), 0)
        self.assertEqual(self.client.delete(f"/api/asignaciones/2026-01-01/{project_id}/false", headers=self.admin).status_code, 204)
        self.assertEqual(remaining(), 1)
        self.assertEqual(self.client.delete(f"/api/asignaciones/2026-01-01/{project_id}/false", headers=self.admin).status_code, 404)
        self.assertEqual(remaining(), 1)
        self.client.patch(f"/api/proyectos/{project_id}", headers=self.admin, json={"restantes": 880})
        self.assertEqual(self.client.delete(f"/api/asignaciones/2026-01-02/{project_id}/false", headers=self.admin).status_code, 409)
        self.assertEqual(remaining(), 880)
        self.assertTrue(any(a["fecha"] == "2026-01-02" for a in self.client.get(
            "/api/calendario/2026", headers=self.admin).json["asignaciones"]))

    def test_multiple_remaining_days_are_atomic(self):
        limited = self.client.post("/api/proyectos", headers=self.admin, json={"restantes": 1, "activo": True}).json["proyecto_id"]
        unlimited = self.client.post("/api/proyectos", headers=self.admin, json={"restantes": None, "activo": True}).json["proyecto_id"]
        type_id = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True, "activo": True}).json["tipo_id"]
        payload = {"fechas": ["2026-02-01", "2026-02-02"], "proyectos": [limited, unlimited],
                   "tipos": [type_id], "es_prevision": False}
        response = self.client.post("/api/asignaciones/multiples", headers=self.admin, json=payload)
        self.assertEqual(response.status_code, 409, response.json)
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual((calendar["asignaciones"], calendar["tipados"]), ([], []))
        projects = {p["proyecto_id"]: p["restantes"] for p in self.client.get("/api/proyectos", headers=self.admin).json}
        self.assertEqual(projects[limited], 1)
        self.assertIsNone(projects[unlimited])
        self.client.patch(f"/api/proyectos/{limited}", headers=self.admin, json={"restantes": 2})
        self.assertEqual(self.client.post("/api/asignaciones/multiples", headers=self.admin, json=payload).status_code, 201)
        projects = {p["proyecto_id"]: p["restantes"] for p in self.client.get("/api/proyectos", headers=self.admin).json}
        self.assertEqual(projects[limited], 0)
        self.assertIsNone(projects[unlimited])
        self.assertEqual(self.client.delete(f"/api/asignaciones/2026-02-01/{unlimited}/false", headers=self.admin).status_code, 204)
        projects = {p["proyecto_id"]: p["restantes"] for p in self.client.get("/api/proyectos", headers=self.admin).json}
        self.assertIsNone(projects[unlimited])

    def test_remaining_days_are_shared_and_safe_under_concurrency(self):
        project_id = self.client.post("/api/proyectos", headers=self.admin, json={"restantes": 1, "activo": True}).json["proyecto_id"]
        self.create_user("other")
        other = self.login("other", "password123")

        def assign(token):
            with self.app.test_client() as client:
                return client.post("/api/asignaciones", headers=token, json={
                    "fecha": "2026-01-01", "proyecto_id": project_id, "es_prevision": False
                }).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(assign, (self.admin, other))), [201, 409])
        project = next(p for p in self.client.get("/api/proyectos", headers=self.admin).json
                       if p["proyecto_id"] == project_id)
        self.assertEqual(project["restantes"], 0)

    def test_multiple_assignments(self):
        project_ids = [
            self.client.post("/api/proyectos", headers=self.admin, json={"nombre": name, "activo": True}).json["proyecto_id"]
            for name in ("Uno", "Dos")
        ]
        type_ids = [
            self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": border, "activo": True}).json["tipo_id"]
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
        calendar = self.client.get("/api/calendario/2026", headers=other).json
        self.assertEqual((calendar["asignaciones"], calendar["tipados"]), ([], []))
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
        project_id = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Proyecto", "restantes": 5, "activo": True}).json["proyecto_id"]
        type_id = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True, "activo": True}).json["tipo_id"]
        existing_type = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True, "activo": True}).json["tipo_id"]
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
        project = next(p for p in self.client.get("/api/proyectos", headers=self.admin).json if p["proyecto_id"] == project_id)
        self.assertEqual(project["restantes"], 4)

        self.assertEqual(self.client.delete(f"/api/asignaciones/2026-02-02/{project_id}/false", headers=self.admin).status_code, 204)
        self.assertEqual(self.client.post("/api/tipados", headers=self.admin, json={"fecha": "2026-02-02", "tipo_id": existing_type}).status_code, 201)
        conflict = self.client.post("/api/asignaciones/multiples", headers=self.admin, json=payload)
        self.assertEqual(conflict.status_code, 409, conflict.json)
        self.assertIn("2026-02-02", conflict.json["error"])
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual(calendar["asignaciones"], [])
        self.assertEqual(len(calendar["tipados"]), 1)
        project = next(p for p in self.client.get("/api/proyectos", headers=self.admin).json if p["proyecto_id"] == project_id)
        self.assertEqual(project["restantes"], 5)

    def test_multiple_assignments_serialize_with_single_typing(self):
        ids = [
            self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True, "activo": True}).json["tipo_id"]
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
                "/api/tipos-fecha", headers=self.admin, json={"en_borde": border, "color": "#aAbBcC", "activo": True}
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
            response = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True, "activo": True})
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
        created = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Trabajo", "activo": True})
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

    def test_inactive_catalogs_block_new_assignments_but_preserve_history(self):
        project = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Trabajo"}).json
        kind = self.client.post("/api/tipos-fecha", headers=self.admin, json={
            "nombre": "Especial", "en_borde": True,
        }).json
        project_id, type_id = project["proyecto_id"], kind["tipo_id"]
        self.assertIs(project["activo"], False)
        self.assertIs(kind["activo"], False)
        assignment = {"fecha": "2026-03-02", "proyecto_id": project_id, "es_prevision": True}
        typing = {"fecha": "2026-03-02", "tipo_id": type_id}
        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json=assignment).status_code, 409)
        self.assertEqual(self.client.post("/api/tipados", headers=self.admin, json=typing).status_code, 409)
        for path in (f"/api/proyectos/{project_id}", f"/api/tipos-fecha/{type_id}"):
            for value in (None, 0, "true"):
                self.assertEqual(self.client.patch(path, headers=self.admin, json={"activo": value}).status_code, 400)
            self.assertEqual(self.client.patch(path, headers=self.admin, json={"activo": True}).status_code, 200)
        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json=assignment).status_code, 201)
        self.assertEqual(self.client.post("/api/tipados", headers=self.admin, json=typing).status_code, 201)
        self.client.patch(f"/api/proyectos/{project_id}", headers=self.admin, json={"activo": False})
        self.client.patch(f"/api/tipos-fecha/{type_id}", headers=self.admin, json={"activo": False})
        bulk = {"fechas": ["2026-03-03", "2026-03-04"], "proyectos": [project_id],
                "tipos": [type_id], "es_prevision": False}
        project_conflict = self.client.post("/api/asignaciones/multiples", headers=self.admin, json={**bulk, "tipos": []})
        self.assertEqual(project_conflict.status_code, 409)
        self.assertIn("proyectos activos", project_conflict.json["error"])
        self.client.patch(f"/api/proyectos/{project_id}", headers=self.admin, json={"activo": True})
        type_conflict = self.client.post("/api/asignaciones/multiples", headers=self.admin, json=bulk)
        self.assertEqual(type_conflict.status_code, 409)
        self.assertIn("tipos de fecha activos", type_conflict.json["error"])
        calendar = self.client.get("/api/calendario/2026", headers=self.admin).json
        self.assertEqual(len(calendar["asignaciones"]), 1)
        self.assertEqual(len(calendar["tipados"]), 1)
        self.client.patch(f"/api/proyectos/{project_id}", headers=self.admin, json={"activo": False})
        self.assertEqual(self.client.post(
            f"/api/asignaciones/2026-03-02/{project_id}/confirmar", headers=self.admin
        ).status_code, 200)
        self.assertEqual(self.client.delete(
            f"/api/asignaciones/2026-03-02/{project_id}/false", headers=self.admin
        ).status_code, 204)
        self.assertEqual(self.client.delete(f"/api/tipados/2026-03-02/{type_id}", headers=self.admin).status_code, 204)

    def test_active_catalog_migration_preserves_existing_rows_as_inactive(self):
        with psycopg.connect(self.url, autocommit=True) as db:
            db.execute("ALTER TABLE proyectos DROP COLUMN activo")
            db.execute("ALTER TABLE tipos_fecha DROP COLUMN activo")
            db.execute((ROOT / "DB/07_activo_catalogos.sql").read_text())
            self.assertEqual(db.execute("SELECT activo FROM proyectos WHERE nombre = 'Vacaciones'").fetchone(), (False,))
            self.assertEqual(db.execute("SELECT activo FROM tipos_fecha WHERE nombre = 'Festivo'").fetchone(), (False,))
            self.assertEqual(db.execute("INSERT INTO proyectos DEFAULT VALUES RETURNING activo").fetchone(), (False,))
            self.assertEqual(db.execute("INSERT INTO tipos_fecha DEFAULT VALUES RETURNING activo").fetchone(), (False,))

    def test_csv_import_preserves_inactive_history_and_supports_legacy_files(self):
        self.create_user("other")
        self.create_user("legacy")
        other = self.login("other", "password123")
        legacy = self.login("legacy", "password123")
        project_id = self.client.post("/api/proyectos", headers=self.admin, json={
            "nombre": "Trabajo", "activo": True,
        }).json["proyecto_id"]
        type_id = self.client.post("/api/tipos-fecha", headers=self.admin, json={
            "nombre": "Especial", "en_borde": True, "activo": True,
        }).json["tipo_id"]
        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json={
            "fecha": "2026-04-03", "proyecto_id": project_id, "es_prevision": True,
        }).status_code, 201)
        self.assertEqual(self.client.post("/api/tipados", headers=self.admin, json={
            "fecha": "2026-04-03", "tipo_id": type_id,
        }).status_code, 201)
        exported = self.client.get("/api/calendario/2026/exportar", headers=self.admin)
        rows = list(csv.DictReader(io.StringIO(exported.data.decode(), newline="")))
        self.assertEqual([row["activo"] for row in rows if row["tipo"] in ("proyecto", "tipo_fecha")], ["true", "true"])
        self.client.patch(f"/api/proyectos/{project_id}", headers=self.admin, json={"activo": False})
        self.client.patch(f"/api/tipos-fecha/{type_id}", headers=self.admin, json={"activo": False})
        self.assertEqual(self.client.post("/api/calendario/importar", headers=other, data=exported.data).status_code, 201)
        self.assertFalse(next(p for p in self.client.get("/api/proyectos", headers=other).json
                              if p["proyecto_id"] == project_id)["activo"])
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=[key for key in rows[0] if key != "activo"],
                                extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        response = self.client.post("/api/calendario/importar", headers=legacy, data=output.getvalue().encode())
        self.assertEqual(response.status_code, 201, response.json)
        calendar = self.client.get("/api/calendario/2026", headers=legacy).json
        self.assertEqual((len(calendar["asignaciones"]), len(calendar["tipados"])), (1, 1))
        self.create_user("new-catalog")
        new_catalog = self.login("new-catalog", "password123")
        for row in rows:
            if row["tipo"] in ("proyecto", "tipo_fecha"):
                row["nombre"] += " importado"
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=rows[0].keys(), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        response = self.client.post("/api/calendario/importar", headers=new_catalog, data=output.getvalue().encode())
        self.assertEqual(response.status_code, 201, response.json)
        self.assertTrue(next(p for p in self.client.get("/api/proyectos", headers=new_catalog).json
                             if p["nombre"] == "Trabajo importado")["activo"])
        self.assertTrue(next(t for t in self.client.get("/api/tipos-fecha", headers=new_catalog).json
                             if t["nombre"] == "Especial importado")["activo"])

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
        self.assertFalse(next(kind for kind in self.client.get("/api/tipos-fecha", headers=self.admin).json
                              if kind["tipo_id"] == kind_id)["activo"])
        self.assertEqual(self.client.post("/api/new_year", json={"year": 2026}).status_code, 401)
        response = self.client.post("/api/new_year", headers=self.admin, json={"year": 2026})
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(response.json, {"usuario_id": 1, "fecha": "2026-01-01", "tipo_id": kind_id})
        dates = {item["fecha"] for item in self.client.get("/api/calendario/2026", headers=self.admin).json["tipados"]}
        first = date(2026, 1, 1)
        expected = {first.isoformat()}
        expected.update((first + timedelta(days=offset)).isoformat() for offset in range(365)
                        if (first + timedelta(days=offset)).weekday() >= 5)
        self.assertEqual(dates, expected)
        self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": 2026}).status_code, 409)
        for invalid in (0, 10000, True, "2026", 2026.5):
            with self.subTest(year=invalid):
                self.assertEqual(self.client.post("/api/new_year", headers=self.admin, json={"year": invalid}).status_code, 400)
        self.assertEqual(self.client.post("/api/tipos-fecha", headers=self.admin, json={"nombre": "Festivo", "en_borde": False}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/tipos-fecha/{kind_id}", headers=self.admin, json={"nombre": "Otro"}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/tipos-fecha/{kind_id}", headers=self.admin, json={"en_borde": True}).status_code, 409)

    def test_new_year_leap_year_and_weekend_conflict_are_atomic(self):
        response = self.client.post("/api/new_year", headers=self.admin, json={"year": 2028})
        self.assertEqual(response.status_code, 201, response.json)
        dates = [item["fecha"] for item in self.client.get("/api/calendario/2028", headers=self.admin).json["tipados"]]
        first = date(2028, 1, 1)
        expected = {(first + timedelta(days=offset)).isoformat() for offset in range(366)
                    if (first + timedelta(days=offset)).weekday() >= 5}
        self.assertEqual(set(dates), expected)
        self.assertEqual(len(dates), len(expected))
        inside = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": False, "activo": True}).json["tipo_id"]
        self.assertEqual(self.client.post("/api/tipados", headers=self.admin, json={
            "fecha": "2029-01-06", "tipo_id": inside
        }).status_code, 201)
        response = self.client.post("/api/new_year", headers=self.admin, json={"year": 2029})
        self.assertEqual(response.status_code, 409, response.json)
        self.assertIn("2029-01-06", response.json["error"])
        self.assertEqual([item["fecha"] for item in self.client.get(
            "/api/calendario/2029", headers=self.admin).json["tipados"]], ["2029-01-06"])

    def test_vacation_context_across_years_and_user_isolation(self):
        vacation_id = next(p["proyecto_id"] for p in self.client.get("/api/proyectos", headers=self.admin).json
                           if p["nombre"] == "Vacaciones")
        holiday_id = next(t["tipo_id"] for t in self.client.get("/api/tipos-fecha", headers=self.admin).json
                          if t["nombre"] == "Festivo")
        self.client.patch(f"/api/proyectos/{vacation_id}", headers=self.admin, json={"activo": True})
        self.client.patch(f"/api/tipos-fecha/{holiday_id}", headers=self.admin, json={"activo": True})
        for day in ("2025-12-31", "2027-01-01"):
            self.assertEqual(self.client.post("/api/tipados", headers=self.admin,
                                              json={"fecha": day, "tipo_id": holiday_id}).status_code, 201)
        for day, forecast in (("2025-12-30", True), ("2027-01-04", False), ("2027-01-05", True)):
            self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json={
                "fecha": day, "proyecto_id": vacation_id, "es_prevision": forecast
            }).status_code, 201)
        context = self.client.get("/api/calendario/2026", headers=self.admin).json["contexto_vacaciones"]
        self.assertEqual(context["anterior"], [{"color": "#FF7800", "es_prevision": True}])
        self.assertEqual(context["posterior"], [{"color": "#FF7800", "es_prevision": False}])
        self.assertEqual(self.client.post("/api/asignaciones", headers=self.admin, json={
            "fecha": "2027-01-02", "proyecto_id": vacation_id, "es_prevision": True
        }).status_code, 201)
        context = self.client.get("/api/calendario/2026", headers=self.admin).json["contexto_vacaciones"]
        self.assertCountEqual(context["posterior"], [
            {"color": "#FF7800", "es_prevision": False}, {"color": "#FF7800", "es_prevision": True}
        ])
        self.create_user("other")
        other = self.login("other", "password123")
        self.assertEqual(self.client.get("/api/calendario/2026", headers=other).json["contexto_vacaciones"],
                         {"anterior": [], "posterior": []})
        for year in (1, 9999):
            self.assertEqual(self.client.get(f"/api/calendario/{year}", headers=self.admin).status_code, 200)

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
        project = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Proyecto", "activo": True})
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
        border = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": True, "activo": True}).json["tipo_id"]
        inside = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": False, "activo": True}).json["tipo_id"]
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
        kind = self.client.post("/api/tipos-fecha", headers=self.admin, json={"en_borde": False, "activo": True}).json["tipo_id"]
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
        project = self.client.post("/api/proyectos", headers=self.admin, json={"nombre": "Trabajo", "color": "#123456", "activo": True}).json
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
        calendar = self.client.get("/api/calendario/2027", headers=other).json
        self.assertEqual((calendar["asignaciones"], calendar["tipados"]), ([], []))
        self.assertEqual(self.client.get("/api/calendario/10000", headers=other).status_code, 400)


if __name__ == "__main__":
    unittest.main()
