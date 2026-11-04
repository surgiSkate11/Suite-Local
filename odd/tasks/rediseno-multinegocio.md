# Rediseño y funciones multinegocio

Mejora profunda del diseño, funciones de valor agregado y personalización por tipo de negocio.
Rama de trabajo: `feat/multinegocio` (parte de `fix/hallazgos-revision`).

## Specs

- S1: "hay q realizar una mejora profunda en el diseño" — diseño: "Ver propuestas primero (Recomendado)": armar 2 o 3 direcciones visuales en el canvas, elegir una e implementarla.
- S2: "agregar muchas funciones interesantes de valor agregado" — primero: "Reportes y exportación" (ventas por día, productos top, ganancias, exportar a CSV o Excel).
- S3: "Caja: apertura y cierre" (arqueo, faltantes y sobrantes por cajero).
- S4: "Tickets e impresión" (comprobante imprimible con el logo y los datos del negocio).
- S5: "y q todo sea personalizable para cualquiern negocio" — primero para "Tienda / minimarket" (códigos de barra, categorías, venta rápida) y "Cafetería / restaurante" (mesas, comandas y propinas).
- S6: "sobreb todo usa la skill de find para buscar skills".
- S7: corregir los hallazgos de la revisión de seguridad (respaldo, stock, conexiones, login, permisos, tests de usuarios).

## Tasks

- [x] T1 (S7) Corregir hallazgos de revisión — inline — e186b1f (revisión nativa aprobada)
- [x] T2 (S6) Buscar skills con find-skills — inline — sin commit
- [x] T3 (S1) Propuestas de diseño de la caja en `design/caja-multinegocio/` — inline — (commit siguiente)
- [ ] T4 (S5) Perfil de negocio, categorías y código de barras — inline
- [ ] T5 (S3) Apertura y cierre de caja con arqueo — inline
- [ ] T6 (S2) Reportes y exportación CSV — inline
- [ ] T7 (S4) Tickets imprimibles — inline
- [ ] T8 (S5) Mesas, comandas y propinas (cafetería) — inline
- [ ] T9 (S1) Implementar la dirección de diseño elegida — inline

## Log

- L1: "hazlo y sobreb todo usa la skill de find para buscar skills y hay q realizar una mejora profunda en el diseño y agregar muchas funciones interesantes de valor agregado, y q todo sea personalizable para cualquiern negocio"
- L2: Respuestas: negocios = "Tienda / minimarket", "Cafetería / restaurante"; funciones = "Reportes y exportación", "Caja: apertura y cierre", "Tickets e impresión"; diseño = "Ver propuestas primero (Recomendado)".
- L3: find-skills: búsquedas "pyside6", "desktop ui design" y "point of sale" solo devolvieron skills con 1–71 instalaciones y autores desconocidos; no se instaló ninguna (umbral de calidad: 1K+).
- L4: T1 revisión nativa aprobada (review-717b8b3e494b72c3) con 6 avisos no bloqueantes; pendientes: test de concurrencia real en ventas y verificación del update de producto.
- L5: T3 propuestas en `design/caja-multinegocio/`: 01-grid-tactil, 02-escaner-primero, 03-salon-y-mostrador. Pendiente que el usuario elija.
- L6: Usuario: "continua con la q te parezca mejor?". Decisión: base 01-grid-tactil + de 02 el campo de escáner siempre activo, la calculadora de vuelto y la barra de estado; 03 se muestra solo con el perfil cafetería. Alternativas: 02 y 03.
- L7: Usuario: "por cierto los diseños q me proporcionaste me parecieron muy básicos y no es lo q se espera de un elegante software profesional". Segunda ronda en `design/caja-premium/`: 01-noir-ejecutivo, 02-porcelana-cobro. T9 espera nueva elección.
- L8: Revisión nativa de 3a79f68 (review-dc272c1bfe55ce1e) detenida con manual_intervention_required tras timeout de captura; pendiente decisión del usuario.
