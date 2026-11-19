# API de Calendar

API JSON de Flask para PostgreSQL, independiente del lenguaje o framework del
cliente. El calendario es individual: las asignaciones y los tipados pertenecen
al usuario autenticado. Los proyectos y tipos de fecha son compartidos.

## Preparación

1. Crea la base de datos y las tablas siguiendo las instrucciones de
   [DB](../DB/README.md). El script de creación incluye todo el esquema que
   necesita el backend. Una base creada con una versión anterior no se
   actualiza automáticamente y debe adaptarse antes de usarla.
2. Desde `Backend`, crea un entorno virtual e instala las dependencias:

   ```sh
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Configura `DATABASE_URL` con una cadena de conexión PostgreSQL y `SECRET_KEY`
   con un secreto aleatorio privado de al menos 32 caracteres. El rol de la base
   de datos debe poder leer y modificar las tablas y usar las secuencias. Para
   navegadores en otro origen, configura `CORS_ORIGINS` con los orígenes
   permitidos separados por comas, por ejemplo `https://app.example.com`.
   Sin esta variable no se habilita CORS; los clientes no sujetos a la política
   de mismo origen del navegador no la necesitan.
4. Crea el primer administrador de forma interactiva y arranca la aplicación:

   ```sh
   flask --app app:create_app crear-administrador --nombre-usuario admin --nombre "Administrador"
   flask --app app:create_app run
   ```

   El comando solo funciona mientras no existan credenciales. Un administrador
   puede asociar credenciales a un usuario previo mediante la API, proporcionando
   `nombre_usuario` y `password` juntos. Los usuarios existentes deben tener
   `activo = true` para poder iniciar sesión.

El servidor de desarrollo de Flask no debe usarse en producción. En producción
usa un servidor WSGI, HTTPS y protección contra intentos repetidos de acceso en
el proxy o infraestructura. Mantén secretos y cadenas de conexión fuera del
repositorio.

## Contrato de la API

Las peticiones y respuestas usan JSON. Salvo el inicio de sesión, todas las
operaciones requieren `Authorization: Bearer <access_token>`. Los tokens firmados
caducan en una hora; cambiar las credenciales los invalida y desactivar un
usuario impide su uso. No son tokens JWT.

| Método y ruta | Cuerpo o resultado |
| --- | --- |
| `POST /api/auth/login` | `nombre_usuario`, `password`; devuelve `access_token`, `token_type`, `expires_in` |
| `POST /api/usuarios` | Campos de usuario, `nombre_usuario`, `password` |
| `PATCH /api/usuarios/{usuario_id}` | Campos de usuario, `nombre_usuario` y/o `password` |
| `POST /api/proyectos` | Campos de proyecto |
| `PATCH /api/proyectos/{proyecto_id}` | Campos de proyecto a modificar |
| `POST /api/tipos-fecha` | Campos de tipo de fecha; `en_borde` es obligatorio |
| `PATCH /api/tipos-fecha/{tipo_id}` | Campos de tipo de fecha a modificar |
| `POST /api/asignaciones` | `fecha`, `proyecto_id`, `es_prevision` |
| `DELETE /api/asignaciones/{fecha}/{proyecto_id}/{es_prevision}` | `es_prevision` es `true` o `false` |
| `POST /api/tipados` | `fecha`, `tipo_id` |
| `DELETE /api/tipados/{fecha}/{tipo_id}` | Elimina el tipado del usuario autenticado |
| `GET /api/get_years` | Devuelve `{"years": [2025, 2026]}` con los años del usuario autenticado, sin duplicados y ordenados |
| `POST /api/new_year` | `{"year": 2026}`; crea un tipado `Festivo` para el 1 de enero del usuario autenticado |

Solo los administradores pueden crear o modificar usuarios. Los demás cambios
puede hacerlos cualquier usuario activo. En las creaciones de usuario,
`nombre_usuario` y `password` son obligatorios; `activo` se establece en `true`
y `es_administrador` en `false` si se omiten. Las contraseñas deben tener entre
8 y 1024 caracteres y se almacenan como hashes.

Las fechas usan `AAAA-MM-DD`; los colores, `#RRGGBB`. Cada usuario puede asignar
varios proyectos a una fecha, pero no repetir la misma combinación de fecha,
proyecto y previsión. Por fecha y usuario se admite un tipo con `en_borde=true`
y otro con `en_borde=false`. No se puede cambiar `en_borde` mientras el tipo
esté asignado. Los cambios de tipados deben hacerse a través de la API para
respetar esta regla.

El tipo básico `Festivo` se crea con el script de datos de `DB`, con color
`#FF0000` y `en_borde=false`. Su nombre está reservado y no se puede cambiar
su nombre ni su valor de `en_borde` desde la API. `new_year` requiere un año
entero entre 1 y 9999 y devuelve el tipado creado con código 201. Si el tipo
`Festivo` no está configurado correctamente o ya existe un tipado no de borde
para ese día, devuelve 409 sin modificar los datos. Se permite coexistir con un
tipado de borde.

Las creaciones devuelven 201, las modificaciones 200 y las eliminaciones 204.
Los errores devuelven un objeto `{"error": "..."}` con el código HTTP
correspondiente.

## Pruebas

Usa una base de datos PostgreSQL **de pruebas** y un rol con permiso para crear
esquemas. Las pruebas crean y eliminan únicamente su propio esquema temporal:

```sh
export TEST_DATABASE_URL='postgresql://usuario:contraseña@localhost/base_de_pruebas'
python -m unittest discover -s tests -v
```
