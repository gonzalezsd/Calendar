# Base de datos PostgreSQL

Ejecuta los scripts en este orden desde la carpeta raíz del proyecto:

```sh
psql -v ON_ERROR_STOP=1 -d postgres -f DB/01_crear_base_datos.sql
psql -v ON_ERROR_STOP=1 -d calendar -f DB/02_crear_tablas.sql
```

Configura la conexión de `psql` según tu servidor. El usuario debe tener permiso
para crear bases de datos. El primer script crea la base de datos `calendar` y
falla si ya existe; en ese caso, ejecuta el segundo script sobre la base de
datos deseada. El segundo script también falla si las tablas ya existen.

Los identificadores primarios se generan automáticamente, aunque se pueden
proporcionar explícitamente. Los campos sin restricciones explícitas admiten
valores nulos. `duracion` y `restantes` son `smallint` con un máximo de 880;
no se ha definido un mínimo. Los colores se almacenan como texto sin límite
de longitud ni formato impuesto.
