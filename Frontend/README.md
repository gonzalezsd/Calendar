# Frontend de Calendar

Aplicación Angular de página única. Consulta y selecciona años, crea años y
permite crear o modificar usuarios, proyectos y tipos de fecha. La gestión de
usuarios solo está disponible para administradores. La vista anual muestra las
asignaciones y los tipados del usuario autenticado; no permite editarlos.

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
