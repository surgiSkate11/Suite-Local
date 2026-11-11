# SuiteLocal — Progreso

## Estado actual

- Fase: 5 — Implementación
- Estado: Completada
- Piloto: Tienda de barrio

## Decisiones

- Usuarios iniciales: dueño y cajero.
- Límite inicial: hasta 5 usuarios por negocio.
- MVP: caja/POS, inventario, login y roles.
- Formas de pago: efectivo, transferencia y tarjeta registrada manualmente.
- Funcionamiento sin internet: ilimitado.
- Reportes, respaldos automáticos y licenciamiento: pendientes, fuera del MVP actual.
- Arquitectura documentada en `docs/ARCHITECTURE.md`.
- Roles definidos: dueño administra; cajero vende y opera caja.
- Modelo de datos preparado para pagos divididos y futura separación por negocio.
- Dinero almacenado como enteros en centavos.
- Diseño documentado en `docs/DESIGN.md`.
- Login, navegación, pagos divididos e inventario definidos.
- Contratos de aplicación definidos sin dependencia de Qt.
- Dependencias de desarrollo y configuración de Ruff/Pyright agregadas.
- `.env.example` documenta que el MVP offline no requiere variables de entorno.
- Validación completada: 6 pruebas, Ruff y Pyright sin errores.
- Smoke test de arranque PySide6 completado en modo offline.
- Autenticación local con hash scrypt y sesión implementada.
- Configuración inicial del negocio y usuario dueño implementada.
- Inventario conectado a UI para crear, listar y desactivar productos.
- Inventario restringido al rol dueño.
- Validación completada: 10 pruebas y smoke test autenticado.
- Shell visual tipo dashboard implementado con barra lateral, encabezado y tarjetas.
- Indicadores del panel se actualizan inmediatamente después de registrar una venta.
- Dashboard autenticado validado con 3 vistas para dueño: panel, caja e inventario.
- Validación final: 10 pruebas, Ruff, Pyright y smoke test visual sin errores.
- Pago con tarjeta definido como integración opcional de datáfono por negocio/proveedor.
- Transferencia definida como flujo nativo con referencia y confirmación del cajero.
- Diseño desacoplado mediante adaptador de terminal, sin asumir un proveedor.
- Pagos divididos implementados para efectivo y transferencia.
- Referencia obligatoria para transferencias.
- Pagos individuales persistidos en `sale_payments`.
- Datáfono preparado mediante `PaymentTerminalPort`, sin habilitar tarjeta hasta configurar proveedor.
- Validación final de pagos: 13 pruebas, Ruff y Pyright sin errores.
- Autorización de inventario aplicada en la capa de aplicación, no solo en la UI.
- Cajero bloqueado por política de dominio al intentar administrar productos.
- Inventario permite editar y desactivar productos desde la interfaz con confirmación.
- Validación final de inventario: 14 pruebas, Ruff, Pyright y smoke test sin errores.
- Configuración por negocio implementada: nombre, moneda, umbral de stock y métodos de pago.
- Pantalla Configuración agregada al dashboard del dueño.
- Tarjeta permanece bloqueada hasta integrar un proveedor real de datáfono.
- Personalización por empresa validada con nombre propio, moneda, umbral y métodos configurables.
- Dashboard del dueño incorpora la vista Configuración.
- Validación final de personalización: 16 pruebas, Ruff, Pyright y smoke test sin errores.
- Gestión de usuarios agregada: creación y desactivación de cajeros por negocio.
- Límite de cinco usuarios activos aplicado.
- Vista Usuarios agregada al dashboard del dueño.
- Validación final de usuarios: 18 pruebas, Ruff y Pyright sin errores.
- Registro extensible de módulos creado para evitar limitar el software a un solo tipo de empresa.
- Módulos base y futuras extensiones definidos mediante manifiestos y permisos.
- Validación final de extensibilidad: 20 pruebas, Ruff y Pyright sin errores.
- Validación final de consola y demo: 21 pruebas, Ruff y Pyright sin errores.
- Login y configuración inicial rediseñados con contraste, jerarquía visual y campos legibles.
- Smoke test de login rediseñado confirmado: tamaño, campos y contraseña verificados.
- Dashboard visual alineado con referencia SaaS: fondo claro, topbar, sidebar, tarjetas y tabla.
- Tema visual forzado para no depender del modo oscuro del sistema.
- Validación final visual: 21 pruebas, Ruff y Pyright sin errores.
- Corregidos valores métricos que mostraban HTML literal.
- Tabla del dashboard sin columna numérica técnica y navegación lateral sin recortes.
- Validación de corrección visual con datos demo completada.
- Renovación profunda del lenguaje visual: sidebar jerárquico, estado offline, bienvenida, acción rápida, métricas informativas y tabla contenida.
- Navegación protegida contra separadores visuales sin alterar los índices reales de las páginas.
- Acción "Registrar una venta" conectada directamente con Caja.
- Caja refinada con resumen de total, separación de catálogo/carrito/cobro y acción primaria destacada.
- Inventario, Configuración y Usuarios refinados con encabezados de página, subtítulos y superficies consistentes.
- Validación de vistas secundarias: 21 pruebas, Ruff, Pyright y smoke test de todas las vistas del dueño.
- Fase 1 iniciada y completada: tokens visuales, generador QSS, fuente con fallback, iconos SVG, elevación y galería de componentes.
- Galería validada en modo offscreen; las pantallas existentes aún no fueron migradas al nuevo tema.
- Fase 2 completada: componentes reutilizables para acciones, campos, tarjetas, KPI, badges, tablas, feedback, overlays y navegación.
- Catálogo actualizado con estados de botones, búsqueda, KPI, badge, toast, estado vacío, skeleton y tabla.
- Validación de componentes: 21 pruebas, Ruff, Pyright y smoke test de galería correctos.
- Fase 3 completada: login dividido, estados de error inline, envío con Enter, Shell con iconos SVG y sidebar colapsable.
- Navegación mantiene índices explícitos y conserva las restricciones dueño/cajero.
- El stylesheet central generado desde tokens queda conectado al arranque de la aplicación.
- Smoke test de login, roles y colapso del sidebar correcto; 21 pruebas, Ruff y Pyright sin errores.
- Fase 4 iniciada con Panel principal migrado a KpiCard, DataTable, StatusBadge y EmptyState.
- Dashboard muestra saludo contextual, productos por reponer y estado vacío sin inventar historial de ventas.
- Validación del Panel principal: 21 pruebas, Ruff, Pyright y smoke test de estados KPI/vacío correctos.
- Caja migrada con SearchField, DataTable, estado vacío, foco inicial, Enter para agregar y Ctrl+Enter para cobrar.
- El botón de confirmar venta permanece deshabilitado sin carrito y se habilita al agregar una línea.
- Inventario migrado a búsqueda, DataTable, estado vacío y drawer de producto.
- Usuarios migrado a DataTable, estado vacío y drawer de creación de cajero.
- Validación final de Fase 4 UI: 21 pruebas, Ruff, Pyright y smoke tests de Caja, Inventario y Usuarios.
- Atajos globales de Shell agregados: Ctrl+K enfoca búsqueda y Escape la limpia.
- Halo de foco centralizado aplicado a campos, selects y controles numéricos.
- Fase 5 de pulido iniciada: atajos Ctrl+K/Escape, foco de Caja al entrar y estados visuales de búsqueda/carrito.
- Validación final acumulada: 21 pruebas, Ruff, Pyright y smoke tests de Shell, Login, Dashboard, Caja, Inventario y Usuarios.
- IVA configurable por negocio implementado con validación de 0% a 100%, precisión de dos decimales y persistencia fiscal por venta.
- Caja muestra subtotal, IVA, total, faltante, pago recibido y vuelto calculados en centavos.
- Confirmación bloqueada hasta cubrir el total; pagos cero o negativos rechazados.
- Edición de cantidad con F2 implementada con validación de stock y resumen detallado de venta completada.
- Flujo de escáner USB/Bluetooth HID preparado: código terminado en Enter, foco continuo, limpieza tras lectura válida y mensajes de código inexistente o stock insuficiente.
- Seguridad de contraseñas endurecida: hashes scrypt con formato Base64 estricto, digest de longitud fija y rechazo seguro de valores corruptos.
- Validación final de seguridad: 34 pruebas, Ruff, Pyright y compilación Python sin errores.
- Respaldo y restauración SQLite implementados con `Connection.backup()`, soporte para WAL, comprobación de integridad y manejo compatible con Windows.
- Validación final de recuperación: 37 pruebas, Ruff, Pyright y compilación Python sin errores.
- Configuración incorpora acciones de crear y restaurar respaldos con selector de archivos, confirmación explícita y mensajes de resultado.
- Smoke test de la pantalla de Configuración con acciones de respaldo completado correctamente.
- La restauración genera automáticamente una copia de seguridad previa con marca de tiempo antes de reemplazar la base activa.
- Validación final de recuperación reforzada: 38 pruebas, Ruff, Pyright y compilación Python sin errores.
- Pulido visual responsive completado: estados de foco, tablas compactas, scroll suave, controles consistentes, KPI adaptables y paneles apilables.
- La aplicación validada en 1024 × 600 y 1440 × 900; conserva el tamaño, colapsa la barra lateral y desplaza verticalmente el contenido cuando es necesario.
- Textos genéricos eliminados del shell y pantallas: el feedback ahora identifica la configuración, producto, usuario o respaldo afectado, y la barra superior evita estados redundantes.
- Validación final de pulido: 38 pruebas, Ruff, Pyright y smoke test responsive sin errores.
- Flujo de demo eliminado: queda un único arranque oficial mediante `suitelocal`, con base real por instalación y configuración inicial del negocio.
- La base persistente de demostración fue eliminada de `%LOCALAPPDATA%`; el producto ya no crea ni utiliza datos demo.
- Corregido el Dashboard real: el título tenía política de ancho ignorada y se deformaba a una columna; ahora conserva ancho flexible y jerarquía visual.
- Validación final del arranque real: 37 pruebas, Ruff, Pyright, ayuda del comando oficial y captura de instalación real sin demo.
- Usuarios reforzados: los nombres no aceptan espacios, las contraseñas requieren confirmación y la regla se aplica también en el servicio de autenticación.
- Corregido el fondo del viewport de las páginas: el contenido ya no hereda el fondo oscuro del sistema operativo.
- Corrección profunda del Dashboard: cada página recibe un fondo estilizado explícito y protegido contra la paleta oscura del sistema; el smoke test confirmó el fondo `#F5F7FB`.
- Corregida la inicialización visual del sidebar: Administración vuelve a mostrar y abrir Inventario, Configuración y Usuarios para cuentas de dueño.
- Smoke test de navegación administrativa completado en las tres vistas.
- Centrado de iconos corregido en navegación expandida/colapsada y tarjetas KPI, con alineación explícita y padding responsive.
- Smoke test de iconos centrados completado para sidebar y métricas.
- Acabado final de interacción: botones de estados vacíos conectados a sus drawers, mensaje de cajero conserva el nombre creado y botones/tablas tienen alineación visual consistente.
- Validación final de pulido: 38 pruebas, Ruff, Pyright y smoke test de acciones contextuales sin errores.

## Pendientes

- Agregar pruebas de autorización y migración de base de datos.
- Convertir la migración compatible actual en migraciones versionadas para instalaciones futuras.
- Validar visualmente el dashboard renovado con usuarios piloto en Windows.
- Implementar proveedores reales de datáfono cuando se defina el primero.
- Validar gestión de usuarios con el piloto.
- Conectar el registro de módulos con licencias y configuración por negocio.
- Validar las vistas con datos reales de empresas piloto.

## Próximo paso

Fase 5 — Pulido: atajos, foco, toasts, transiciones, contraste y capturas visuales.

## Fase 5 — Pulido de UI (rama `feat/ui-polish`)

- Corregidos los atajos de Caja que se duplicaban al cruzar el breakpoint responsive; `Ctrl+Enter` acepta también el Enter principal.
- "Cerrar sesión" vuelve al login en vez de cerrar la aplicación.
- Tokens con contraste WCAG AA (`text-500`, `success`, nuevo `border-input`); un test verifica los pares de color y que `ui/` no tenga colores fijos.
- Toasts abajo a la derecha (4 s, con cierre manual), errores de formulario en línea en rojo y confirmaciones "Sí"/"No" con "No" por defecto; sin `QMessageBox` para el feedback rutinario.
- Teclado: `Esc` cierra paneles, `Enter` guarda formularios, flechas en la búsqueda de Caja, `Ctrl+K` según la pantalla, `Ctrl+1..5` para navegar y foco inicial en cada panel.
- Variantes de botón (primario, secundario, peligro, fantasma) con un solo primario por vista; iconos SVG en lugar de glifos de texto.
- Animaciones cortas: colapso del sidebar (180 ms) y aparición/salida de toasts (160 ms).
- Capturas reales a 1100 y 1440 px revisadas; detectaron el botón de cierre del panel sin estilo (corregido).
- Validación: 90 pruebas, Ruff y Pyright sin errores.
- Pendientes detectados en las capturas: sidebar colapsado recorta la marca y la tarjeta de usuario; la lista de Caja muestra solo el nombre del producto; el toast tapa el botón de confirmar venta durante 4 s; la casilla marcada no muestra el check.

## Fase 6 — Multinegocio Ecuador (rama `feat/multinegocio`)

- Estado: completa en `feat/multinegocio` (1612 tests). Detalle completo en `odd/tasks/rediseno-multinegocio.md`.
- Hecho: caja Atelier + Grafito con modo claro/oscuro, perfil de negocio ecuatoriano (IVA 15/5/0 % incluido en el precio, RUC, régimen, plantillas por tipo de negocio, módulos, categorías, costo y margen), mesas y comandas (sin propinas, decisión del usuario), apertura y cierre de caja, reportes CSV, ticket interno imprimible, factura electrónica del SRI (XML 1.1.0 validado con XSD, firma XAdES-BES idéntica a una referencia autorizada, cola offline, envío automático, RIDE con Code 128), clientes con búsqueda por cédula, IVA según régimen (sin registro y RIMPE popular no cobran IVA), impresión opcional al cobrar, fiado con abonos, respaldo automático diario, importación de productos desde CSV e instalador SuiteLocal-Setup.exe.
- Decisiones: un solo programa con módulos activables; comprobante según régimen (ticket interno o factura electrónica); el certificado .p12 se guarda cifrado con DPAPI; nunca se muestran botones de funciones que no existen.
- Pendiente: avisos menores de la revisión de T14 (límites del CSV, acumulación de respaldos si falla el registro); probar la factura contra el SRI de pruebas con un certificado real; venta por peso (cantidades decimales); integrar `feat/multinegocio` en `main`.
