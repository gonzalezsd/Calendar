# Frontend de Calendar

Aplicación Angular de página única. Consulta y selecciona años, crea años y
permite crear o modificar usuarios, proyectos y tipos de fecha. La gestión de
usuarios solo está disponible para administradores. El calendario muestra el
año completo; al pulsar el nombre de un mes se abre su vista mensual y el
elemento «Calendario» de navegación vuelve a la vista anual. Al seleccionar un
día en cualquiera de las vistas se abre un panel para consultar, añadir o
eliminar sus asignaciones de proyectos y tipos de fecha. Desde el panel se puede abrir la edición del
proyecto o tipo correspondiente. Se admite un tipo con borde y otro sin borde
por día; para sustituir uno hay que eliminarlo primero.
Los proyectos y tipos se crean inactivos y se pueden activar desde Configuración;
solo los activos aparecen como opciones para nuevas asignaciones individuales o
múltiples. Las asignaciones existentes siguen visibles al desactivarlos.
Cada día puede tener una nota privada, indicada mediante una etiqueta «Nota»
en el calendario. Al pasar el ratón o enfocar el día se muestra su texto.
En el detalle se puede leer y editar; al guardar el texto
vacío se elimina. Se pide confirmación antes de descartar cambios sin guardar.
La cabecera de cada mes muestra entre paréntesis el número de fechas con algún
proyecto laborable confirmado, contando cada fecha una sola vez. Los días
anteriores a hoy sin asignación de proyecto se muestran sombreados, incluso si
tienen un tipo de fecha; la comparación usa la fecha local.
El fondo de un día utiliza el color de su proyecto o `#2C813A` si tiene varios
proyectos distintos; las asignaciones ordinarias y de previsión del mismo
proyecto cuentan como uno solo. Si el proyecto no tiene color se usa gris. Los
tipos se representan con el color del número o del borde, sin etiquetas en el
calendario; los detalles siguen disponibles en el panel.
Los días con solo previsiones usan un fondo más claro; si hay alguna asignación
confirmada se usa el color normal. Las previsiones se pueden confirmar desde el
detalle del día; si ya existe la asignación confirmada, ambas se unifican.
Las cadenas de sábados, domingos y festivos contiguas a `Vacaciones` usan su
color, incluso entre meses o años; si hay vacaciones confirmadas y en
previsión junto a la misma cadena, se usa el color confirmado. Se conservan
los colores de los días que ya tienen proyectos asignados. El sombreado no
crea asignaciones ni modifica los totales.
Al pulsar varios días con Mayús se seleccionan sin abrir el panel. Una pulsación
sin Mayús sustituye la selección y abre el detalle. Al cerrar el panel se
deselecciona el día consultado; al cambiar de año se limpia toda la selección.
En la vista anual, al seleccionar varios días aparece «Asignar» para elegir
proyectos, tipos y si los proyectos son previsiones. La operación se cancela
completamente si alguna asignación ya existe o entra en conflicto.
En la vista anual, «Información anual» muestra los días laborables (fechas con
algún proyecto laborable asignado, incluidas las previsiones, contadas una sola
vez), los días trabajados y los totales por tipo y proyecto. Los días trabajados generales
cuentan fechas con algún proyecto laborable confirmado; por proyecto se cuentan
sus fechas confirmadas. Los días asignados incluyen previsiones y cada fecha se
cuenta una sola vez por proyecto, aunque también tenga asignación confirmada.
En la vista mensual, «Información mensual» muestra los mismos recuentos limitados
al mes consultado. Los desgloses solo incluyen proyectos y tipos asignados al
periodo, aunque estén inactivos. La duración inicial y los días restantes son valores globales
del proyecto, no del mes.
En el detalle de cada día se pueden consultar y crear recordatorios privados,
con hora opcional y repetición anual. Los días con recordatorios muestran una
etiqueta; al pasar el ratón se leen los recordatorios sin hora. Al iniciar sesión
aparece un diálogo con todos los recordatorios de ese día. Crear un año copia
los recordatorios repetidos sin duplicados; los del 29 de febrero pasan al 28
en años no bisiestos.
En Configuración, «Recordatorios anuales» permite editar el día, mes, hora, texto
y repetición de cada serie. Los cambios afectan a todas sus ocurrencias; al
desactivar la repetición se conservan las existentes, pero no se crean nuevas.
En Configuración, «Importar/exportar calendario» descarga el año elegido o
todos los años como un CSV, o importa un archivo al calendario del usuario actual.
El archivo determina los años de destino. La importación combina los datos y se cancela por completo
ante cualquier conflicto; consulta el contrato CSV en el README del backend.

El código de `src/app` está organizado en componentes independientes para acceso,
calendario, usuarios, proyectos y tipos de fecha. `core` contiene los modelos y
el estado compartido de la sesión y el calendario.

## Desarrollo

1. Prepara la base de datos y arranca Flask como se explica en
   [Backend](../Backend/README.md), incluyendo el tipo básico `Festivo`.
2. Usa una versión de Node compatible con Angular 20 (20.19+, 22.12+ o 24).
   Desde esta carpeta:

   ```sh
   npm install
   npm start
   ```

3. Abre `http://localhost:4200`. El proxy de desarrollo envía `/api` a
   `http://127.0.0.1:5000`; modifica `proxy.conf.json` si Flask usa otra
   dirección. No es necesario habilitar CORS cuando se usa este proxy.

Al iniciar sesión se selecciona el año actual si está disponible; en caso
contrario, se muestra el año disponible más reciente.

La sesión se conserva en el almacenamiento local del navegador hasta que el
token caduque (diez horas), se invalide o se cierre sesión. La contraseña no se
almacena. El token es accesible para JavaScript del mismo origen: utiliza HTTPS,
protección frente a XSS y solo dispositivos de confianza en producción.

## Producción y pruebas

`npm run build` genera la aplicación en `dist/calendar-frontend/browser`. Sirve
esos archivos estáticos y configura el servidor para reenviar `/api` al backend;
no uses el servidor de desarrollo en producción. Si el proxy de producción
atiende ambos bajo el mismo origen, no se necesita CORS.

Ejecuta `npm test -- --watch=false --browsers=ChromeHeadless` con Chrome
instalado. Las pruebas del backend se describen en su README.
