# API de Calendar

API JSON de Flask para PostgreSQL, independiente del lenguaje o framework del
cliente. El calendario es individual: las asignaciones, los tipados y las notas pertenecen
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

3. Desde `Backend`, crea el fichero de configuración privado:

   ```sh
   cp config.example.json config.json
   chmod 600 config.json
   ```

   Edita `config.json` y establece `DATABASE_URL` con una cadena de conexión
   PostgreSQL y `SECRET_KEY` con un secreto aleatorio privado de al menos 32
   caracteres. Por ejemplo, la conexión puede tener la forma
   `postgresql://usuario:contraseña@localhost:5432/calendar`; codifica los
   caracteres especiales de las credenciales para utilizarlos en una URL.
   Puedes generar una clave con `python -c "import secrets; print(secrets.token_hex(32))"`.
   Conserva la misma clave entre reinicios para no invalidar los tokens activos.
   El rol de la base de datos debe poder leer y modificar las tablas y usar las
   secuencias. Para navegadores en otro origen, configura `CORS_ORIGINS` como
   cadena de orígenes separados por comas, por ejemplo `https://app.example.com`.
   Una cadena vacía deshabilita CORS. `TEST_DATABASE_URL` solo se usa para las
   pruebas y puede dejarse vacío.

   `config.json` está excluido de Git; no compartas ni subas sus credenciales.
   El backend lee este fichero desde su propia carpeta, independientemente del
   directorio desde el que se arranque, y no utiliza variables de entorno para
   estas opciones.
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
caducan en diez horas; cambiar las credenciales los invalida y desactivar un
usuario impide su uso. No son tokens JWT.

| Método y ruta | Cuerpo o resultado |
| --- | --- |
| `POST /api/auth/login` | `nombre_usuario`, `password`; devuelve `access_token`, `token_type`, `expires_in` |
| `GET /api/me` | Datos y permisos del usuario autenticado |
| `GET /api/usuarios` | Lista de usuarios y nombres de acceso, solo para administradores |
| `POST /api/usuarios` | Campos de usuario, `nombre_usuario`, `password` |
| `PATCH /api/usuarios/{usuario_id}` | Campos de usuario, `nombre_usuario` y/o `password` |
| `POST /api/proyectos` | Campos de proyecto |
| `GET /api/proyectos` | Lista de proyectos compartidos |
| `PATCH /api/proyectos/{proyecto_id}` | Campos de proyecto a modificar |
| `POST /api/tipos-fecha` | Campos de tipo de fecha; `en_borde` es obligatorio |
| `GET /api/tipos-fecha` | Lista de tipos de fecha compartidos |
| `PATCH /api/tipos-fecha/{tipo_id}` | Campos de tipo de fecha a modificar |
| `POST /api/asignaciones` | `fecha`, `proyecto_id`, `es_prevision` |
| `POST /api/asignaciones/multiples` | `fechas` (lista de fechas), `proyectos` y `tipos` (listas de identificadores), `es_prevision` |
| `POST /api/asignaciones/{fecha}/{proyecto_id}/confirmar` | Confirma una previsión del usuario autenticado |
| `DELETE /api/asignaciones/{fecha}/{proyecto_id}/{es_prevision}` | `es_prevision` es `true` o `false` |
| `POST /api/tipados` | `fecha`, `tipo_id` |
| `DELETE /api/tipados/{fecha}/{tipo_id}` | Elimina el tipado del usuario autenticado |
| `PUT /api/notas/{fecha}` | `{"texto": "..."}`; crea o actualiza la nota del usuario para esa fecha |
| `DELETE /api/notas/{fecha}` | Elimina la nota del usuario para esa fecha |
| `POST /api/recordatorios` | `fecha`, `hora` opcional (`HH:MM` o `null`), `texto`, `repetir` |
| `GET /api/recordatorios/recurrentes` | Lista las series anuales del usuario, con `mes`, `dia`, `hora`, `texto` y `repetir` |
| `PATCH /api/recordatorios/{recordatorio_id}` | Actualiza una serie anual: `mes`, `dia`, `hora`, `texto` y `repetir` |
| `GET /api/recordatorios/{fecha}` | Lista los recordatorios del usuario para la fecha |
| `GET /api/get_years` | Devuelve `{"years": [2025, 2026]}` con los años del usuario autenticado, sin duplicados y ordenados |
| `GET /api/calendario/{year}` | Asignaciones, tipados, notas y recordatorios del usuario para el año, y `contexto_vacaciones` de los días adyacentes fuera del año |
| `GET /api/calendario/{year}/exportar` | Descarga el calendario del usuario y año en CSV UTF-8 |
| `GET /api/calendario/exportar` | Descarga todos los años del usuario en un único CSV UTF-8 |
| `POST /api/calendario/importar` | Recibe el CSV en el cuerpo y lo combina con el calendario del usuario |
| `POST /api/new_year` | `{"year": 2026}`; tipa como `Festivo` el 1 de enero y todos los sábados y domingos, y copia los recordatorios repetidos del usuario |

Solo los administradores pueden crear o modificar usuarios. Los demás cambios
puede hacerlos cualquier usuario activo. En las creaciones de usuario,
`nombre_usuario` y `password` son obligatorios; `activo` se establece en `true`
y `es_administrador` en `false` si se omiten. Las contraseñas deben tener entre
8 y 1024 caracteres y se almacenan como hashes.

Los proyectos tienen un campo booleano `laborable`, que por defecto es `true`.
También se incluye en las asignaciones devueltas por el calendario.
Los proyectos y tipos de fecha tienen `activo` booleano, `false` por defecto.
Solo los activos admiten nuevas asignaciones individuales o múltiples. Las
asignaciones existentes siguen visibles y se pueden eliminar; también se pueden
confirmar previsiones de proyectos inactivos. Crear un año sigue asignando
automáticamente `Festivo` aunque esté inactivo.
Las notas son privadas y hay como máximo una por usuario y fecha. Su texto debe
contener algún carácter distinto de espacios y no puede contener caracteres
nulos; se conserva el texto introducido. `PUT` devuelve la nota con código 200.
`DELETE` devuelve 404 si no existe. Los años con notas también aparecen en
`get_years`.

Los recordatorios son privados y se admiten varios por fecha. El texto debe
contener algún carácter distinto de espacios y no puede contener caracteres
nulos. Al crear un año se copian los recordatorios con `repetir=true` de todos
los años del usuario. No se crea una copia si ya existe en el año de destino
un recordatorio con la misma fecha, hora y texto. El 29 de febrero se copia al
28 en años no bisiestos, pero mantiene su fecha original para años posteriores.
Los años con recordatorios también aparecen en `get_years`.
La edición anual identifica una serie por usuario, día y mes originales, hora
y texto; las repeticiones idénticas se muestran agrupadas. Los cambios se aplican
a todas sus ocurrencias existentes y a las que se generen posteriormente, con
el ajuste del 29 de febrero. Desactivar `repetir` conserva las ocurrencias
existentes, pero deja de copiarlas. La API devuelve 409 si la serie editada
coincidiría con otra serie anual existente.

### Intercambio CSV

El CSV incluye únicamente las asignaciones, tipados, notas y recordatorios del
usuario y del año seleccionado o de todos sus años, junto con los datos de los
proyectos y tipos referenciados. No contiene usuarios ni credenciales. Al
importar se usan las fechas del archivo y siempre se escribe en el calendario
del usuario autenticado.
La respuesta de importación incluye `year` para un archivo anual o `years`
para uno de varios años, además de los totales importados.
La importación es atómica: las asignaciones y notas duplicadas, los
recordatorios existentes con la misma fecha, hora y texto, los tipos
incompatibles o los catálogos ambiguos o diferentes provocan un error sin
modificar datos. Se buscan proyectos y tipos por nombre, incluido `null`; si
hay varios con el mismo nombre no se puede resolver la referencia. Los
catálogos existentes no se modifican salvo por el descuento de los días
restantes de proyectos existentes por nuevas asignaciones confirmadas. Los
proyectos nuevos conservan los días restantes del archivo. Si no hay saldo
suficiente, se cancela toda la importación.
La importación permite restaurar asignaciones de catálogos inactivos. Para
catálogos existentes conserva su estado `activo`; para nuevos usa el del CSV,
o `false` si el archivo antiguo no contiene esa columna.

El archivo tiene cabecera `tipo,ref,fecha,fecha_original,nombre,descripcion,duracion,restantes,color,laborable,en_borde,es_prevision,hora,texto,repetir,version,anio,activo`.
También se aceptan los CSV anteriores sin la columna `activo`.
La primera fila, `calendario`, indica `version=1` y el año para una exportación
anual, o `version=2` y `anio=\N` para todos los años. Las demás filas
son `proyecto`, `tipo_fecha`, `asignacion`, `tipado`, `nota` o `recordatorio`;
`ref` enlaza asignaciones y tipados con sus catálogos dentro del archivo.
Se usa `\N` para `null`, y una barra invertida inicial se duplica para
distinguirla de ese marcador. Los valores booleanos son `true` o `false`.
Las cadenas que comienzan con apóstrofo o pueden interpretarse como fórmulas
se exportan con un apóstrofo adicional, que se retira al importar; evita editar
el archivo con herramientas que alteren este escape.

Las fechas usan `AAAA-MM-DD`; los colores, `#RRGGBB`. Cada usuario puede asignar
varios proyectos a una fecha, pero no repetir la misma combinación de fecha,
proyecto y previsión. Por fecha y usuario se admite un tipo con `en_borde=true`
y otro con `en_borde=false`. No se puede cambiar `en_borde` mientras el tipo
esté asignado. Los cambios de tipados deben hacerse a través de la API para
respetar esta regla.

Al confirmar una previsión se convierte en asignación confirmada. Si esta ya
existía para el mismo día y proyecto, se elimina la previsión y se conserva la
asignación confirmada. Si no existe la previsión, la API devuelve 404.
Una asignación confirmada nueva descuenta un día de `restantes` del proyecto
compartido, tanto si se crea directamente como si se confirma una previsión;
si ya estaba confirmada no se descuenta otra vez. Las previsiones no descuentan.
Si `restantes` es `null`, no cambia; si es cero o negativo, la confirmación
devuelve 409. Al eliminar una asignación confirmada se devuelve un día, salvo
que `restantes` sea `null`; si superaría 880, la eliminación devuelve 409.
Esto también se aplica a asignaciones existentes y no recalcula datos históricos.
La asignación múltiple acepta al menos dos fechas distintas del mismo año y uno
o más proyectos o tipos; `es_prevision` se aplica a todos los proyectos. Si
alguna asignación ya existe, faltan días restantes o un tipo entra en conflicto, devuelve 409 y no
guarda ninguna. Devuelve 201 con las cantidades de fechas, asignaciones y
tipados creados.

El tipo básico `Festivo` se crea con el script de datos de `DB`, con color
`#FF0000` y `en_borde=false`. Su nombre está reservado y no se puede cambiar
su nombre ni su valor de `en_borde` desde la API. `new_year` requiere un año
entero entre 1 y 9999 y devuelve el tipado del 1 de enero con código 201.
Cuando el 1 de enero cae en fin de semana se inserta una sola vez. Si el tipo
`Festivo` no está configurado correctamente o cualquiera de las fechas tiene
un tipado no de borde incompatible, devuelve 409 sin modificar los datos. Se
permite coexistir con un tipado de borde.

El calendario incluye `contexto_vacaciones`, con las listas `anterior` y
`posterior` de colores y estados de previsión de asignaciones de `Vacaciones`
del usuario que conectan con el límite del año a través de festivos y fines de
semana consecutivos. Este contexto es visual y no añade asignaciones al año.

Las creaciones devuelven 201, las modificaciones 200 y las eliminaciones 204.
Los errores devuelven un objeto `{"error": "..."}` con el código HTTP
correspondiente.

## Pruebas

Configura `TEST_DATABASE_URL` en `config.json` con la conexión a una base de
datos PostgreSQL **de pruebas** y un rol con permiso para crear esquemas. Las
pruebas crean y eliminan únicamente su propio esquema temporal. Si no se
configura, se omiten las pruebas de integración:

```sh
python -m unittest discover -s tests -v
```
