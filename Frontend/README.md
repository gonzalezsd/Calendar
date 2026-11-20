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
El fondo de un día utiliza el color de su proyecto o `#2C813A` si tiene varios
proyectos distintos; las asignaciones ordinarias y de previsión del mismo
proyecto cuentan como uno solo. Si el proyecto no tiene color se usa gris. Los
tipos se representan con el color del número o del borde, sin etiquetas en el
calendario; los detalles siguen disponibles en el panel.
Los días con solo previsiones usan un fondo más claro; si hay alguna asignación
confirmada se usa el color normal. Las previsiones se pueden confirmar desde el
detalle del día; si ya existe la asignación confirmada, ambas se unifican.
Al pulsar varios días con Mayús se seleccionan sin abrir el panel. Una pulsación
sin Mayús sustituye la selección y abre el detalle. Al cerrar el panel se
deselecciona el día consultado; al cambiar de año se limpia toda la selección.
En la vista anual, al seleccionar varios días aparece «Asignar» para elegir
proyectos, tipos y si los proyectos son previsiones. La operación se cancela
completamente si alguna asignación ya existe o entra en conflicto.
En la vista anual, «Información anual» muestra los días laborables (todos los
días salvo los que tengan el tipo `Festivo` o el proyecto `Vacaciones`), los
días trabajados y los totales por tipo y proyecto. Las previsiones se incluyen;
cada día se cuenta una sola vez por proyecto, aunque también tenga asignación real.

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

La sesión se conserva en el almacenamiento local del navegador hasta que el
token caduque (una hora), se invalide o se cierre sesión. La contraseña no se
almacena. El token es accesible para JavaScript del mismo origen: utiliza HTTPS,
protección frente a XSS y solo dispositivos de confianza en producción.

## Producción y pruebas

`npm run build` genera la aplicación en `dist/calendar-frontend/browser`. Sirve
esos archivos estáticos y configura el servidor para reenviar `/api` al backend;
no uses el servidor de desarrollo en producción. Si el proxy de producción
atiende ambos bajo el mismo origen, no se necesita CORS.

Ejecuta `npm test -- --watch=false --browsers=ChromeHeadless` con Chrome
instalado. Las pruebas del backend se describen en su README.
