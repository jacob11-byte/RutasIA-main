# Offline y ubicación de Flamia

La captura y sincronización funcionan sin utilizar la simulación del mapa. La implementación del mapa, su proveedor y sus claves se conservan.

## Trabajo del repartidor

1. Abrir Flamia con conexión, iniciar sesión y esperar a que aparezcan clientes, productos y rutas. Hacerlo en cada dispositivo y navegador que se usará durante el reparto.
2. Para registrar una tienda, estar frente al establecimiento y pulsar **Tomar ubicación actual de la tienda**. Permitir la ubicación en el aviso del navegador. Revisar coordenadas, precisión, municipio y dirección antes de guardar. La dirección escrita puede completarse manualmente sin internet; el GPS no depende del geocodificador del mapa.
3. Sin red se pueden guardar tiendas, pedidos de esas tiendas, cobros, resultados de paradas, acciones de rutas y registros de visita. Los nuevos clientes y pedidos aparecen en sus selectores con identificadores locales. Cada dispositivo conserva su propia cola; otro teléfono no tendrá esos cambios hasta sincronizarlos.
4. En **Rutas**, usar **Registrar entrega con ubicación del repartidor**. Seleccionar ruta y entrega, tomar la ubicación estando en el lugar y guardar. La captura debe tener menos de cinco minutos al enviar el formulario. Se guarda por separado de las coordenadas del cliente, incluyendo precisión y fecha de captura. Puede permanecer pendiente varios días: se conserva la fecha capturada, aunque el servidor la reciba después.
5. Al recuperar internet, mantener Flamia abierta. La sincronización se reintenta al recuperar red, volver a la aplicación y cada 30 segundos mientras esté abierta. También puede pulsarse **Sincronizar**. No depende de ejecución en segundo plano de iOS.
6. Revisar **Operaciones pendientes en este dispositivo**. Un error de permisos, validación o sesión detiene el envío en ese punto para conservar el orden y sus dependencias. Iniciar sesión con la misma cuenta para continuar. Descartar es una decisión manual: no deshace un registro que el servidor ya haya recibido.

Los saldos por tienda incluyen pedidos y cobros pendientes guardados en ese dispositivo. Los reportes y estadísticas corresponden a la última información del servidor; sincronizar antes de usarlos como cierre administrativo. La planificación de nuevas rutas requiere conexión y pedidos sincronizados. El mapa conserva sus dependencias externas y requiere internet para cargar cartografía o calcular nuevos recorridos.

## Ubicación y compatibilidad

La web pide el permiso nativo al pulsar el botón. Si ya fue concedido, el navegador puede no mostrar otro aviso. Si fue denegado, la web no puede activar la localización ni forzar que vuelva a aparecer el aviso.

- Usar HTTPS en el dominio de la empresa. HTTP por una IP de red local no habilita geolocalización ni service workers en teléfonos; localhost se utiliza exclusivamente para pruebas locales.
- En iPhone, permitir Localización al navegador y al sitio, y activar Ubicación precisa. Probar tanto Safari como la aplicación añadida a inicio, porque sus permisos pueden diferir.
- En Android, habilitar ubicación del dispositivo y permitirla al navegador y al sitio.
- En computadoras, la ubicación puede estar basada en redes y ser mucho menos precisa que en un teléfono. Siempre se muestra la precisión reportada. No se promete exactitud absoluta; las lecturas superiores a 100 m advierten de precisión baja y el registro de tienda solicita revisión.
- La aplicación distingue permiso bloqueado, tiempo agotado, ubicación no disponible y acceso sin HTTPS. No utiliza coordenadas simuladas como sustituto de una captura fallida.

Los datos pendientes se guardan en IndexedDB por cuenta. No borrar datos del sitio, desinstalar la aplicación ni cambiar de navegador con pendientes. La persistencia solicitada al navegador reduce el riesgo de limpieza automática, pero el navegador y el sistema operativo controlan el almacenamiento. Si guardar falla por espacio o permisos, el formulario conserva los datos y no anuncia un guardado exitoso.

La cola antigua de localStorage se conserva y puede descargarse desde el panel. No se asigna automáticamente a una cuenta porque la versión anterior no guardaba el propietario. Antes de actualizar dispositivos con pendientes antiguos, sincronizarlos en la versión anterior o respaldarlos y conciliarlos con los registros existentes; no reimportarlos a ciegas porque esas solicitudes no tenían protección general contra duplicados.

## Despliegue

La migración `0009` añade precisión y fecha de captura a clientes, coordenadas de entrega a paradas y comprobantes de operaciones para evitar duplicados. No altera coordenadas existentes. Los comandos de arranque de Render y Procfile aplican migraciones antes de arrancar Gunicorn. Si el servicio usa comandos personalizados en su panel, actualizarlo o ejecutar `python manage.py migrate --noinput` antes de arrancar esta versión.

El build debe ejecutar `python manage.py collectstatic --noinput` para incluir `offline.js`, `location.js` y el service worker actualizado. Recargar con conexión después del despliegue y comprobar que la nueva versión se ha instalado antes de salir a repartir. No borrar comprobantes de operaciones mientras existan dispositivos que puedan reenviar solicitudes antiguas.

No se ha publicado esta versión ni accedido a una base de datos de la empresa durante la implementación.

## Verificación reproducible

Desde la carpeta que contiene `manage.py`:

```powershell
python -m pip install -r requirements-test.txt
python -m playwright install chromium webkit
python manage.py test logistics verification.test_browser --settings=verification.settings --verbosity 1
python manage.py check
python manage.py makemigrations --check --dry-run
```

La configuración de pruebas usa una base SQLite temporal separada y no utiliza `DATABASE_URL`. Las pruebas de navegador usan Chrome instalado en Windows si está disponible; en otros equipos utilizan Chromium de Playwright. Puede indicarse `FLAMIA_CHROME_EXECUTABLE` para seleccionar otro Chrome. WebKit se prueba con pantalla y entrada táctil móvil. Los permisos y coordenadas se emulan de forma controlada; las llamadas externas del mapa se bloquean durante estas pruebas para no consumir claves.

La suite cubre 15 pruebas de backend y 10 de navegador: recarga offline, tienda → pedido → cobro, saldos, sincronización, ubicación de entrega, permiso denegado, pérdida de respuesta después del guardado, almacenamiento fallido, sesión vencida, cambio de cuenta y concurrencia con el bloqueo alternativo para Safari.

Antes de habilitarlo en la empresa, repetir el recorrido en los dispositivos físicos con el dominio HTTPS real: conceder y denegar permisos, capturar frente a una tienda, desconectar internet, registrar tienda/pedido/cobro/entrega, cerrar y reabrir la app, recuperar red y comprobar en otro equipo que cada operación aparece una sola vez. Las pruebas de WebKit no certifican el GPS ni los permisos del sistema operativo de un iPhone físico.
