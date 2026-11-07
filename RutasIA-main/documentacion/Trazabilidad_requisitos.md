# Trazabilidad de Flamia con los documentos del cliente

## Fuentes y criterio de alcance

Se revisaron `Entrega de Anteproyecto j.pdf` (26 páginas) y `#2 Entrega de Proyecto Final.pdf` (34 páginas), proporcionados por el usuario. Los números de página siguientes corresponden a las páginas físicas del PDF.

**Documento principal de requisitos: `Entrega de Anteproyecto j.pdf`.** Por indicación expresa del usuario, este documento prevalece al definir funciones, prioridades, exclusiones y criterios de aceptación. `#2 Entrega de Proyecto Final.pdf` es una referencia secundaria de implementación; no amplía por sí solo el alcance del anteproyecto ni sustituye sus requisitos.

El orden de prioridad es: instrucciones directas del usuario, anteproyecto y, únicamente como apoyo compatible, entrega final. El núcleo obligatorio es el de la página 19 del anteproyecto: usuarios y roles, clientes y direcciones, productos, pedidos, asignación de repartidores y rutas, visitas ordenadas, estados de entrega, cobros, abonos, saldos, historial del cliente, reportes básicos y operación offline con consulta y sincronización de pendientes. Los objetivos de la página 11 y el presupuesto técnico de las páginas 21–22 complementan esa definición.

Las propuestas futuras y las actividades de investigación no se convierten en módulos operativos. Las referencias a la entrega final en la matriz son evidencia complementaria, no nuevos requisitos del cliente. Se conserva el mapa actual con Google Maps y todas sus claves por instrucción directa del usuario, aunque la entrega final mencione MapLibre. No se modificaron los PDF.

## Funciones y evidencia de implementación

| ID | Requisito y fuente | Implementación verificable |
|---|---|---|
| R01 | Usuarios y roles: anteproyecto p. 19; entrega final pp. 11, 18–20 | Inicio/cierre de sesión; administrador, supervisor y operador; creación de usuarios y formulario para actualizar rol y acceso. Matriz de escritura centralizada en `presentation/permissions.py`. |
| R02 | Clientes, direcciones y ubicación: anteproyecto pp. 7, 19, 21; entrega final pp. 11, 26 | Registro de tienda, contacto, dirección, coordenadas y precisión. Se conservan la captura GPS real y el permiso nativo solicitados previamente por el usuario. |
| R03 | Productos de agua y gas: anteproyecto pp. 7, 19; entrega final pp. 11, 26 | Catálogo con presentación, precio y peso; validación de valores positivos. |
| R04 | Pedidos asociados al cliente y productos: anteproyecto pp. 11, 19, 21; entrega final pp. 11–12, 26 | Los nuevos pedidos requieren cliente y al menos un producto. Cantidades enteras positivas, precios válidos, carga calculada y estado de cobro visible. El operador puede registrar pedidos. |
| R05 | Vehículos y repartidores: anteproyecto pp. 5, 9, 21; entrega final pp. 11–12, 26 | Catálogos existentes conservados; capacidad y rendimiento validados; planificación rechaza un repartidor inactivo y utiliza el conductor del vehículo cuando no se indica otro. |
| R06 | Planificación y asignación diaria: anteproyecto pp. 11, 19, 21; entrega final pp. 12–13, 19, 21 | Selector Dijkstra/A*, pedidos pendientes, base común, control de capacidad y orden de paradas. Se evita asignar un pedido a dos rutas abiertas. La estrategia de varias paradas sigue siendo voraz, como documenta la entrega final. |
| R07 | Estados de pedidos, viajes y paradas: anteproyecto pp. 9, 16, 19; entrega final pp. 12, 19, 22–24 | Iniciar la ruta antes de registrar visitas o completarla; entregado/no entregado, observaciones y cancelación de pedidos pendientes o asignados. Las entregas confirmadas no se reabren por cancelación o inicio de viaje. Los pedidos cancelados no se reactivan. |
| R08 | Cobros al contado, abonos y crédito: anteproyecto pp. 15–16, 19, 21; entrega final pp. 11, 19, 22 | Crédito registra Q 0 recibido y conserva la deuda. Abono recibe un importe positivo; pago completo coincide con el saldo. Se rechazan importes negativos, sobrepagos y UUID reutilizado para otro movimiento. |
| R09 | Saldo e historial del cliente: anteproyecto pp. 6, 15–16, 19; entrega final pp. 11, 22, 26 | En Tiendas se consulta historial de pedidos, productos, resultados de visita, cobros, observaciones y saldo; disponible a partir de datos descargados y pendientes locales. |
| R10 | Responsable y fecha de cada movimiento: anteproyecto p. 16; entrega final pp. 19, 22, 24 | Los nuevos cobros guardan usuario autenticado, fecha de operación y repartidor cuando participa. Las visitas y eventos conservan usuario, fecha y parada. La fecha de campo se conserva al sincronizar. |
| R11 | Operación offline y sincronización: anteproyecto pp. 6, 11, 15, 18–21; entrega final pp. 12, 22, 27 | IndexedDB por cuenta, consultas locales, cola persistente, orden de dependencias, identificadores únicos, reenvíos sin duplicados y consulta de pendientes. Cancelar un pedido creado offline resuelve su identificador local antes de enviarlo. |
| R12 | Reportes básicos: anteproyecto pp. 7, 19, 21; entrega final pp. 11, 19 | Ventas, dinero recibido, saldos, entregas, viajes, distancia y combustible. El crédito se excluye del efectivo recibido. Los cobros se filtran por fecha de operación; las ventas por fecha del pedido. |
| R13 | Mapa y servicios complementarios con conexión: anteproyecto pp. 19, 21; entrega final pp. 11–13 | Se conserva íntegramente la implementación del mapa, su carga, claves, geometría y simulaciones. Las nuevas funciones comerciales están en un archivo separado, `business.js`. |
| R14 | Apoyo técnico existente al cálculo de rutas y costos: anteproyecto p. 5; detalle complementario en entrega final pp. 11–13 | Las estimaciones de combustible se conservan como apoyo existente a la planificación; no se consideran un módulo obligatorio nuevo exigido por el anteproyecto. Cuando el scraper usa GlobalPetrolPrices, la fuente y la estimación del precio súper se identifican; no se presentan como cotización oficial del MEM. |
| R15 | Acceso, confidencialidad, pruebas y despliegue: anteproyecto pp. 10, 18–19, 22; apoyo técnico en entrega final pp. 14–17, 30 | Transacciones incluso sin cabecera de idempotencia, comprobación de permisos antes de un reenvío, validación de datos y verificaciones de configuración productiva antes de iniciar Gunicorn. |

## Funciones retiradas o corregidas

- Se retiró de la creación operativa el pedido de paquetería sin cliente ni productos. No corresponde a la adaptación al reparto de agua y gas definida en el anteproyecto. No se borran pedidos históricos ni se alteran sus relaciones.
- Se eliminó la validación desactivada `True or ...`; una ruta debe salir de una sola base y puede contener varios destinos.
- Se corrigió el tratamiento del crédito como dinero cobrado. El registro de deuda no implica recepción de efectivo.
- Se corrigieron transiciones que podían reabrir entregas confirmadas o reactivar pedidos cancelados.
- No se retiraron vehículos, conductores, combustible, algoritmos, roles, estadísticas ni simulaciones del mapa: están descritos expresamente en la entrega final.

Los componentes internos de persistencia, comprobantes de reenvío y aplicación de pagos son soporte técnico de los requisitos; no son nuevas líneas de negocio. Los scripts de documentación y archivos históricos del repositorio no se convierten en pantallas ni se eliminan por no figurar como módulos.

## Reglas concretas para cubrir los requisitos

La documentación exige saldos por cliente y admite cobros con o sin pedido específico, pero no define cómo distribuir estos últimos. Se adoptó una regla explícita: un cobro al cliente sin pedido liquida las deudas más antiguas primero. `PaymentAllocation` conserva a qué pedidos se aplicó cada importe; un cobro directo mantiene su asociación original. No se permite crear un sobrepago ni un anticipo sin deuda, porque no se ha incluido gestión de anticipos.

Registrar crédito requiere seleccionar un pedido con saldo y declarar importe recibido Q 0. El pago completo debe corresponder al saldo seleccionado. Un pedido con dinero recibido no se cancela automáticamente: el alcance no incluye devoluciones bancarias ni notas contables.

Los registros anteriores a estas migraciones mantienen su fecha histórica conocida. No se inventa el usuario que los registró: el historial indica que no fue registrado. Los antiguos cobros generales que no tenían aplicación por pedido conservan sus importes y se consideran en el saldo del cliente; no se inventa retroactivamente su reparto entre pedidos.

La consulta histórica muestra por separado la persona que registró el cobro y el repartidor. Un cobro en caja no se atribuye a un repartidor ficticio. Cuando existe una ruta asociada se recupera su conductor; también puede seleccionarse un repartidor al cobrar.

## Exclusiones y límites conservados

No se incorporan facturación electrónica certificada, contabilidad formal, procesamiento bancario, telemetría vehicular en vivo, optimización dinámica con tráfico en vivo, predicción de demanda ni un optimizador global de flota. El anteproyecto los excluye de la primera versión o los menciona como ampliaciones. Registrar que se recibió una transferencia no conecta el sistema al banco.

El sistema utiliza rutas y datos precargados para trabajar offline. Planificar nuevas rutas y cargar servicios externos del mapa requiere conexión. La simulación ya existente del mapa se conserva por estar documentada y por la instrucción expresa del usuario; la captura real de ubicación y el registro operativo de entregas permanecen separados de ella.

Las entrevistas, evaluaciones con participantes, evidencias de campo, respaldos del proveedor y alertas externas necesitan ejecución real por parte del negocio o acceso a su infraestructura. No se declaran realizadas ni se fabrican resultados, testimonios, respaldos o capturas de dispositivos físicos.

## Despliegue y validación

Las migraciones nuevas `0010` y `0011` añaden responsable, fecha de operación, repartidor y aplicación de cobros, además del vínculo de eventos con paradas. Son aditivas y no eliminan datos históricos. Aplicarlas antes de utilizar esta versión.

El arranque de Render y Procfile ejecuta `check --deploy --fail-level ERROR`, seguido de las migraciones. Deben configurarse `DEBUG=False`, `SECRET_KEY` segura, `DATABASE_URL`, `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` explícitos. No se retiran ni sustituyen claves del mapa. Si el panel de hosting tiene un comando personalizado, debe actualizarse para usar estos pasos.

El build debe ejecutar `collectstatic`; el service worker incluye el nuevo módulo comercial y una nueva versión de caché. Abrir con conexión después de actualizar y confirmar que los datos necesarios se descargaron antes de salir a repartir.

Pruebas reproducibles, desde la carpeta de `manage.py`:

```powershell
python manage.py test logistics verification.test_browser --settings=verification.settings --verbosity 1
python manage.py check
python manage.py makemigrations --check --dry-run
node --check static/logistics/business.js
```

La configuración de pruebas utiliza una base temporal independiente de la empresa. Las pruebas de navegador cubren Chrome y WebKit con coordenadas y permisos controlados; no sustituyen la aceptación en teléfonos físicos ni certifican servicios externos. La fidelidad documental se verifica por requisitos, código y pruebas, no mediante una promesa de ausencia absoluta de fallos.

Resultado de la validación local del 6 de noviembre de 2026 (Guatemala): **50 pruebas aprobadas**, 32 de backend y 18 de navegador. También aprobaron `manage.py check`, la verificación de migraciones pendientes, la revisión sintáctica de JavaScript y `collectstatic`. El control de despliegue aceptó una configuración explícita de prueba, sin conectarse a servicios del cliente. Una comparación con Git confirmó que las funciones y la sección visual del mapa, su carga y sus claves originales permanecen sin cambios.
