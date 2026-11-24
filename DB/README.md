# Base de datos PostgreSQL

Ejecuta los scripts en este orden desde la carpeta raíz del proyecto:

```sh
psql -v ON_ERROR_STOP=1 -d postgres -f DB/01_crear_base_datos.sql
psql -v ON_ERROR_STOP=1 -d calendar -f DB/02_crear_tablas.sql
psql -v ON_ERROR_STOP=1 -d calendar -f DB/03_crear_tipo_festivo.sql
psql -v ON_ERROR_STOP=1 -d calendar -f DB/04_crear_proyecto_vacaciones.sql
```

Configura la conexión de `psql` según tu servidor. El usuario debe tener permiso
para crear bases de datos. El primer script crea la base de datos `calendar` y
falla si ya existe; en ese caso, ejecuta el segundo script sobre la base de
datos deseada. El segundo script también falla si las tablas ya existen.
El script de tablas crea también las credenciales y las relaciones por usuario
necesarias para el backend; no actualiza tablas creadas con versiones anteriores.
Para una instalación existente que todavía no tenga la tabla `notas`, ejecuta
`psql -v ON_ERROR_STOP=1 -d calendar -f DB/05_crear_notas.sql`. Este script no
es necesario en instalaciones nuevas y falla si la tabla ya existe.
Para una instalación existente sin recordatorios, ejecuta
`psql -v ON_ERROR_STOP=1 -d calendar -f DB/06_crear_recordatorios.sql`.
Este script tampoco es necesario en instalaciones nuevas y falla si la tabla ya existe.
Para una instalación existente sin las columnas `activo`, ejecuta
`psql -v ON_ERROR_STOP=1 -d calendar -f DB/07_activo_catalogos.sql`. Los proyectos
y tipos existentes quedan inactivos; activa los que quieras poder asignar desde
la aplicación. El script no es necesario en instalaciones nuevas.
El tercer script crea el tipo básico `Festivo` y su índice de unicidad; puede
ejecutarse también sobre una instalación existente. El cuarto script crea el
proyecto básico `Vacaciones` y su índice de unicidad; puede ejecutarse también
sobre una instalación existente. Si ya existe un `Festivo` o `Vacaciones`
distinto o hay duplicados, falla sin modificar los datos para que se revisen.

Las notas contienen fecha y texto y se asocian a un único usuario; la clave
primaria impide que un usuario tenga más de una nota en la misma fecha.
Los recordatorios contienen fecha, hora opcional, texto y repetición, y pertenecen
a un usuario. La fecha original permite conservar el 29 de febrero al copiar
recordatorios a años no bisiestos.

Los identificadores primarios se generan automáticamente, aunque se pueden
proporcionar explícitamente. Los campos sin restricciones explícitas admiten
valores nulos. `duracion` y `restantes` son `smallint` con un máximo de 880;
no se ha definido un mínimo. `laborable` es booleano, no admite nulos y vale
`true` por defecto. Los colores se almacenan como texto sin límite
de longitud ni formato impuesto.
`activo` en proyectos y tipos de fecha es booleano, no admite nulos y vale
`false` por defecto, también para los datos básicos `Festivo` y `Vacaciones`.
