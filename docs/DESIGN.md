# SuiteLocal — Diseño del MVP (v2: Sistema de diseño)

> Aplicación de escritorio para tiendas, instalada localmente. Todo el texto de la UI está en español.
> La referencia visual inspira la *estructura* (barra lateral, tarjetas, tablas), pero no se copia su marca ni su contenido. SuiteLocal tiene identidad propia.

---

## 1. Principios de diseño

1. **Calma y claridad.** Mucho espacio en blanco, una sola acción primaria por pantalla, color solo con significado.
2. **Velocidad de mostrador.** La Caja se usa 200 veces al día: teclado primero, objetivos grandes, cero clics innecesarios.
3. **Jerarquía evidente.** Primero el estado (qué pasa), después la acción (qué hago). Número grande, etiqueta pequeña, dato secundario en gris.
4. **Consistencia absoluta.** Mismos radios, mismas sombras, mismos espacios, mismos componentes en todas las pantallas. Todo sale de tokens, nunca de valores sueltos.
5. **Errores humanos.** Mensajes en español claro, junto al campo, con acción sugerida. Nunca se pierde lo que el usuario escribió.
6. **Elegancia sobria.** Sin degradados chillones, sin sombras pesadas, sin bordes gruesos. Detalles sutiles: halo de foco, transiciones cortas, estados vacíos cuidados.

---

## 2. Tokens de diseño

Todos los valores viven en un único módulo (`ui/theme/tokens.py`). Ninguna pantalla define colores, tamaños o sombras por su cuenta.

### 2.1 Color

**Marca (azul)**

| Token | Hex | Uso |
|---|---|---|
| `brand-950` | `#091438` | Fondo inferior de la barra lateral |
| `brand-900` | `#0E1E5B` | Fondo superior de la barra lateral |
| `brand-800` | `#162C80` | Hover en barra lateral, tarjeta promocional |
| `brand-600` | `#2B54D6` | Botón primario (hover/pressed) |
| `brand-500` | `#3B6BF0` | **Acción primaria**, enlaces, ítem activo |
| `brand-400` | `#6B93F5` | Anillo de foco, acentos sobre fondo oscuro |
| `brand-100` | `#E6EDFE` | Fondo de cabecera de tabla, chips activos |
| `brand-50`  | `#F2F5FF` | Hover de filas, fondos suaves |

> El azul primario pasa de `#527FF1` a `#3B6BF0` para que el texto blanco sobre botones cumpla contraste AA (≥ 4.5:1).

**Neutros**

| Token | Hex | Uso |
|---|---|---|
| `bg` | `#F5F7FB` | Fondo de trabajo |
| `surface` | `#FFFFFF` | Tarjetas, tablas, paneles |
| `border` | `#E5E9F2` | Bordes de tarjetas y separadores |
| `border-strong` | `#D3DAE8` | Bordes de inputs |
| `text-900` | `#0F1B3D` | Títulos y cifras |
| `text-700` | `#36456B` | Texto de cuerpo |
| `text-500` | `#6B7899` | Texto secundario, placeholders |
| `text-400` | `#94A0BD` | Texto deshabilitado, iconos inactivos |

**Semánticos (cada uno con fondo, texto y borde)**

| Estado | Texto/icono | Fondo | Borde |
|---|---|---|---|
| Éxito | `#0E8A45` | `#E7F7EE` | `#BFE8D0` |
| Advertencia | `#9A6200` | `#FFF4D6` | `#F6DC9A` |
| Peligro | `#C92A45` | `#FDEBEE` | `#F6C4CC` |
| Información | `#2B54D6` | `#E6EDFE` | `#C5D3FB` |

Acentos pastel para iconos de tarjetas KPI (fondo del icono → icono): azul `#E6EDFE → #3B6BF0`, verde `#E7F7EE → #0E8A45`, ámbar `#FFF4D6 → #B7791F`, violeta `#EFE9FE → #6D44D9`.

### 2.2 Tipografía

- **Fuente:** Inter, incluida dentro del instalador (carpeta `assets/fonts`) para que se vea idéntica en cualquier equipo. Respaldo: Segoe UI, system-ui.
- Cifras con **números tabulares** (alineación perfecta en tablas y totales).

| Rol | Tamaño | Peso | Uso |
|---|---|---|---|
| `display` | 32 px | 700 | Total de la venta, cifra grande de Caja |
| `kpi` | 28 px | 700 | Números de tarjetas KPI |
| `h1` | 24 px | 700 | Título de página |
| `h2` | 17 px | 600 | Título de tarjeta o panel |
| `body` | 13 px | 400 | Texto general |
| `body-strong` | 13 px | 600 | Nombres, valores destacados |
| `label` | 12 px | 600 | Etiquetas de formulario, cabeceras de tabla |
| `caption` | 11 px | 500 | Notas, metadatos, badges |

Interlineado: 1.4 para texto, 1.2 para títulos y cifras.

### 2.3 Espaciado, radios y elevación

- **Espaciado (base 4):** 4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 · 56.
- **Radios:** controles 10 px · tarjetas 14 px · paneles/diálogos 18 px · badges y chips 999 px (píldora).
- **Elevación** (sombras suaves, tono azul-gris, nunca negro puro):
  - `e1` tarjetas: desplazamiento y 1, desfoque 3, `rgba(15,27,61,0.06)`.
  - `e2` elementos flotantes (dropdowns, toasts): y 6, desfoque 20, `rgba(15,27,61,0.10)`.
  - `e3` diálogos y paneles laterales: y 16, desfoque 40, `rgba(15,27,61,0.16)`.

### 2.4 Iconografía

- Set único de iconos **SVG de trazo lineal** (estilo Lucide), grosor 1.75 px, tamaños 16/18/20/24.
- Se colorean por código con el color del texto del contexto, sin PNG sueltos.
- Prohibido mezclar emojis o iconos de otros sets.

### 2.5 Movimiento

- Duraciones: 120 ms (hover), 180 ms (cambios de estado), 260 ms (paneles que entran/salen).
- Curva: ease-out cúbica.
- Se animan: opacidad, desplazamiento corto (≤ 16 px), ancho de la barra lateral. Nunca se bloquea la entrada del usuario durante una animación.

---

## 3. Componentes base

| Componente | Especificación |
|---|---|
| **Botón primario** | Alto 40 px, fondo `brand-500`, texto blanco 600, radio 10. Hover `brand-600`. Pressed 1 tono más oscuro. Deshabilitado: fondo `border`, texto `text-400`. |
| **Botón secundario** | Alto 40 px, fondo blanco, borde `border-strong`, texto `text-700`. Hover fondo `brand-50`. |
| **Botón fantasma** | Sin borde ni fondo, texto `brand-500`. Para acciones terciarias. |
| **Botón peligro** | Mismo formato; fondo `danger`; solo para acciones destructivas. |
| **Botón grande (Caja)** | Alto 52 px, texto 15 px 700. Solo "Cobrar" y "Confirmar venta". |
| **Input** | Alto 40 px, fondo blanco, borde `border-strong`, radio 10, padding 12. Foco: borde `brand-500` + halo de 3 px `brand-400` al 30 %. Error: borde `danger` + mensaje 11 px debajo con icono. |
| **Búsqueda** | Input con icono de lupa a la izquierda y chip de atajo (`Ctrl K`) a la derecha. |
| **Select** | Igual que input, con chevron. |
| **Tarjeta** | Fondo `surface`, borde `border` 1 px, radio 14, sombra `e1`, padding 20–24. |
| **Tarjeta KPI** | Icono 40×40 en cuadrado pastel (radio 12), etiqueta `caption`, cifra `kpi`, línea inferior con tendencia opcional (flecha + % + "vs ayer"). |
| **Badge de estado** | Píldora, alto 22, punto de 6 px + texto 11 px 600, fondo y borde semánticos. |
| **Tabla** | Cabecera en `brand-100` con texto `label` en `text-700`, esquinas superiores redondeadas. Filas de 52 px, separador `border`, hover `brand-50`. Números a la derecha con cifras tabulares. Sin cebras. |
| **Paginación** | Cuadrados de 32 px, radio 8. Activo en `brand-500` con texto blanco. |
| **Chip de método de pago** | Tarjeta pequeña seleccionable con icono + nombre; seleccionado: borde `brand-500`, fondo `brand-50`. |
| **Toast** | Esquina inferior derecha, ancho 360, sombra `e2`, barra de color semántico a la izquierda, se cierra solo a los 4 s (los errores de persistencia no se cierran solos). |
| **Diálogo** | Centrado, ancho 440, radio 18, sombra `e3`, fondo oscuro translúcido detrás. Acciones a la derecha: secundaria + primaria. |
| **Panel lateral (drawer)** | Entra desde la derecha, ancho 440, sombra `e3`. Se usa para formularios de Inventario y Usuarios. |
| **Estado vacío** | Ilustración lineal simple (96 px), título `h2`, texto `text-500`, un botón de acción. |
| **Skeleton** | Bloques `border` con pulso suave, para cargas mayores a 200 ms. |

---

## 4. Estructura general (shell)

```text
┌──────────────┬──────────────────────────────────────────────┐
│              │  Topbar (64 px): búsqueda · fecha · estado   │
│  Sidebar     ├──────────────────────────────────────────────┤
│  248 px      │                                              │
│              │   Contenido (padding 32, ancho máx. 1280)    │
│  Usuario     │                                              │
└──────────────┴──────────────────────────────────────────────┘
```

- **Adaptación:** la ventana puede operar desde 1024 × 600. Por debajo de 1200 px de ancho, la
  barra lateral colapsa a 72 px (solo iconos con tooltip), la topbar prioriza la búsqueda y el
  contenido usa desplazamiento vertical cuando una pantalla supera la altura disponible.
- **Composición responsive:** los KPI pasan a una cuadrícula 2 × 2 y los paneles de Caja se
  apilan en ventanas estrechas; en espacios amplios recuperan la composición horizontal.
- **Barra lateral:** degradado vertical muy sutil `brand-900 → brand-950`. Arriba: logo de SuiteLocal (marca de texto + símbolo simple). Menú con icono + texto blanco al 80 %. Ítem activo: bloque redondeado (radio 12) `brand-500` con texto blanco 100 % y una barra de 3 px a la izquierda. Hover: blanco al 8 %. Abajo: tarjeta de usuario (avatar con iniciales, nombre, rol, botón de cerrar sesión).
- **Topbar:** fondo blanco, borde inferior `border` (sin sombra pesada). Izquierda: búsqueda global. Derecha: fecha, indicador "Datos locales · guardado" (punto verde) y avatar.
- **Separadores de menú:** no son páginas. La UI conserva un índice explícito de pantallas para que la navegación funcione aunque cambie la estructura visual.
- **Autorización:** el menú de Inventario, Configuración y Usuarios se **oculta** para el cajero; además la autorización se valida en el caso de uso, no solo en la UI.

### Navegación

```text
Inicio de sesión
└── Aplicación principal
    ├── Panel principal
    ├── Caja
    ├── Inventario (dueño)
    ├── Usuarios (dueño)
    ├── Configuración (dueño)
    └── Cerrar sesión
```

---

## 5. Pantallas

### 5.1 Inicio de sesión

Pantalla dividida en dos mitades.

- **Izquierda (55 %), panel de marca:** degradado `brand-900 → brand-950`, con formas geométricas muy sutiles (círculos y líneas al 6 % de blanco). Logo, frase corta de valor ("Tu tienda, siempre en orden.") y tres puntos de beneficio con icono (rápido, local, seguro).
- **Derecha (45 %), formulario:** fondo blanco, formulario centrado de 380 px de ancho.
  - Título `h1` "Bienvenido", subtítulo en `text-500`.
  - Campos: Usuario y Contraseña (con botón de mostrar/ocultar). Aviso discreto si el bloqueo de mayúsculas está activo.
  - Botón primario "Iniciar sesión" de ancho completo, alto 44.
  - Error inline sobre el botón (caja `danger` con icono): `Usuario o contraseña incorrectos`.
  - Al enviar, el botón muestra un spinner y se deshabilita para evitar doble envío.
  - Pie: nombre del negocio local, versión de la app.
- Foco inicial en Usuario. `Enter` envía.

**Flujo:**

1. El usuario escribe usuario y contraseña.
2. El sistema verifica que el usuario exista, esté activo y pertenezca al negocio local.
3. Si es válido, crea una sesión con `user_id`, `business_id` y `role`.
4. Si falla, muestra `Usuario o contraseña incorrectos`.
5. No se informa si falló el usuario o la contraseña.

El límite de intentos y la recuperación se implementarán junto con seguridad, fuera del primer slice de UI. La aplicación inicia siempre en login.

### 5.2 Panel principal

- **Cabecera:** saludo contextual ("Buenos días, {nombre}") como `h1`, subtítulo con la fecha larga. A la derecha, botón primario **"Nueva venta"** (acción rápida, abre Caja).
- **Fila de 4 tarjetas KPI** (se actualizan tras cada venta):
  1. Productos activos (azul).
  2. Por reponer (ámbar; si es > 0, la tarjeta es clicable y lleva a Inventario filtrado).
  3. Ventas del día (verde).
  4. Total vendido hoy (violeta, con símbolo monetario del negocio).
- **Debajo, dos paneles:**
  - "Productos por reponer": tabla compacta con nombre, stock y badge (Agotado / Stock bajo).
  - "Últimas ventas": lista con número de venta, hora, método(s) y total.
- Estado vacío amable si todavía no hay ventas.

### 5.3 Caja

Diseñada para trabajar con teclado y pantalla táctil. Dos columnas.

**Columna izquierda (flexible): búsqueda y productos**

- Búsqueda grande (alto 48) con foco inicial. Busca por código o nombre; los resultados aparecen debajo como lista de filas grandes (nombre, código, stock, precio). Teclas ↑/↓ para moverse, `Enter` agrega.
- Producto sin stock: fila atenuada con badge "Agotado", no se puede agregar.
- Estado vacío: "Escribe o escanea un código para empezar".

**Columna derecha (400 px fija): carrito y cobro**

- Tarjeta con título "Venta actual" y contador de ítems.
- Líneas del carrito: nombre, precio unitario, selector de cantidad (− n +), subtotal y botón quitar. Alto cómodo, cantidad editable.
- Pie fijo: subtotal, total en `display` y botón grande **"Cobrar"** (`Ctrl+Enter`). Deshabilitado con carrito vacío.

**Paso de cobro (panel que se desliza sobre el carrito, o diálogo de 520 px):**

- Resumen: Total a pagar en grande.
- Chips de método de pago: Efectivo, Transferencia, Tarjeta (esta solo si hay datáfono configurado).
- Cada método elegido añade una fila con su monto. Indicador de progreso: "Pagado $X de $Y" y "Falta $Z" en tiempo real. Si sobra en efectivo, "Vuelto $W" resaltado en verde.
- Transferencia: monto, banco (opcional), número de referencia y casilla de confirmación del cajero.
- Tarjeta: botón "Enviar al datáfono" con estados visibles (esperando, aprobado, rechazado, cancelado, no disponible).
- Botón **"Confirmar venta"** (alto 52) solo se activa cuando la suma de pagos es exactamente igual al total.

**Éxito:** pantalla/diálogo con check animado, "Venta N° 000123", vuelto en grande si hubo efectivo, y botón "Nueva venta" con foco. Luego se limpia el carrito y se actualizan existencias.

**Flujo funcional:**

1. Buscar por código o nombre.
2. Seleccionar producto.
3. Agregar al carrito.
4. Ajustar cantidad o quitar línea.
5. Elegir una o más formas de pago.
6. Confirmar cuando la suma de pagos sea igual al total.
7. Mostrar número de venta y vuelto únicamente si existe pago en efectivo.
8. Limpiar carrito y actualizar existencias.

#### Pago dividido

```text
PaymentInput:
    method: cash | transfer | card
    amount_cents: int
```

Reglas:

- No se aceptan montos cero o negativos.
- No se aceptan métodos repetidos en la misma venta; se edita el existente.
- La suma debe ser exactamente igual al total.
- El vuelto solo aplica al excedente de efectivo.
- Transferencia y tarjeta no generan vuelto.

#### Métodos configurables por negocio

- **Efectivo:** siempre disponible.
- **Transferencia:** flujo nativo con monto, banco opcional y número de referencia.
- **Tarjeta:** solo disponible si el negocio tiene un datáfono configurado.

La transferencia se registra de forma fluida en la caja y requiere confirmación del cajero. SuiteLocal no afirma que una transferencia bancaria fue validada automáticamente mientras no exista una integración bancaria real.

La tarjeta se procesa en el datáfono y SuiteLocal recibe un resultado mediante un adaptador:

```text
PaymentTerminalPort
    charge(amount_cents) -> ApprovedPayment | DeclinedPayment
```

El proveedor, modelo, credenciales y modo de conexión se configuran por negocio. No se acoplará la caja a un banco específico. Si el negocio no tiene datáfono configurado, la opción tarjeta no aparece.

Estados mínimos de una operación con datáfono: `approved`, `declined`, `cancelled` y `unavailable`. Una venta no se confirma como pagada si el datáfono no devuelve `approved`.

### 5.4 Inventario (solo dueño)

- **Cabecera:** `h1` "Inventario", subtítulo con total de productos. A la derecha, botón primario "Nuevo producto".
- **Barra de herramientas** sobre la tabla: búsqueda, filtro de estado (Todos / Activos / Inactivos / Por reponer) y contador de resultados.
- **Tabla** dentro de una tarjeta:

  | Código | Nombre | Precio de venta | Stock | Estado | Acciones |
  |---|---|---|---|---|---|

  - Código en `brand-500` 600. Nombre en `body-strong`. Precio y stock alineados a la derecha con cifras tabulares.
  - Estado: badge verde "Activo", gris "Inactivo", ámbar "Stock bajo", rojo "Agotado".
  - Acciones: menú de tres puntos (Editar, Ajustar stock, Desactivar).
  - Pie: "Mostrando 1 a 10 de N", paginación y filas por página.
- **Formulario en panel lateral** (drawer de 440 px), no en diálogo, para ver la tabla detrás:
  - Código (obligatorio, único), Nombre (obligatorio), Precio de venta (≥ 0), Stock (entero ≥ 0).
  - Botones "Guardar" (primario) y "Cancelar".
  - Los errores se muestran junto a cada campo **sin perder los valores escritos**.
- Desactivar pide confirmación (diálogo con botón de peligro).
- Estado vacío: "Aún no tienes productos" con botón "Crear el primero".

Solo el dueño puede crear, editar, desactivar o ajustar productos.

### 5.5 Configuración (solo dueño)

Tarjetas por secciones, cada una con título y descripción corta:

- **Negocio:** nombre, símbolo monetario, umbral de stock bajo.
- **Métodos de pago:** interruptores (toggle) para transferencia y tarjeta; si se activa tarjeta, aparece la configuración del datáfono (proveedor, modelo, modo de conexión).
- Botón "Guardar cambios" fijo al pie de la tarjeta; aviso toast "Cambios guardados". Las opciones se guardan por negocio y se aplican sin cambiar código.

### 5.6 Usuarios (solo dueño)

Misma estructura que Inventario: tabla (usuario, nombre, rol con badge, estado) y drawer para crear/editar. Roles: Dueño y Cajero.

---

## 6. Estados y mensajes

| Situación | Tratamiento |
|---|---|
| Carga mayor a 200 ms | Skeleton en la zona afectada |
| Lista sin datos | Estado vacío con acción |
| Éxito | Toast verde de 4 s |
| Error de validación | Mensaje bajo el campo, valores conservados |
| Error de negocio (stock, autorización) | Diálogo breve con acción sugerida |
| Error de persistencia | Toast rojo persistente + detalle; nunca se silencia |
| Acción destructiva | Diálogo de confirmación con botón de peligro |

Textos siempre en español, directos y sin tecnicismos ("No hay stock suficiente de *Arroz 1 kg*. Quedan 3.").

---

## 7. Atajos de teclado

| Atajo | Acción |
|---|---|
| `Ctrl+K` | Enfocar búsqueda |
| `Enter` | Agregar producto seleccionado (Caja) / enviar formulario |
| `Ctrl+Enter` | Cobrar / confirmar una venta válida |
| `↑` `↓` | Moverse en resultados |
| `Esc` | Cerrar diálogo, drawer o limpiar búsqueda |
| `F2` | Editar cantidad de la línea seleccionada |
| `Supr` | Quitar línea del carrito |

El foco inicial de Caja queda en búsqueda. El orden de tabulación sigue el orden visual.

---

## 8. Accesibilidad y escalado

- Contraste mínimo AA (4.5:1 texto, 3:1 componentes).
- Anillo de foco visible en **todos** los elementos interactivos.
- Objetivos táctiles ≥ 40 px (≥ 52 px en acciones de cobro).
- El estado nunca depende solo del color: siempre icono o texto además (badge con texto, error con icono).
- Soporte de escalado de pantalla (DPI) 100 %–200 % sin recortes.
- Montos visibles con dos decimales; persistencia en centavos.
- El IVA se configura por negocio, se aplica a todos los productos y se guarda
  junto con cada venta. Inventario usa precios base antes de IVA; Caja muestra
  subtotal, impuesto, total y vuelto calculados en centavos.
- Los escáneres USB o Bluetooth compatibles con HID funcionan como teclado:
  Caja mantiene el foco en la búsqueda, acepta el código terminado en Enter y
  agrega el producto sin depender de una marca concreta. Cada negocio puede
  personalizar sus códigos desde Inventario.

---

## 9. Notas técnicas de implementación (Qt / QSS)

QSS es un subconjunto limitado de CSS. Decisiones para lograr el resultado elegante:

- **Tokens → QSS:** una función genera la hoja de estilos desde `tokens.py`. Cero colores escritos a mano en pantallas.
- **Sombras:** QSS no soporta `box-shadow`. Se aplican con `QGraphicsDropShadowEffect` mediante un helper reutilizable (`apply_elevation(widget, "e1")`). No aplicar a listas largas o filas de tabla (rendimiento).
- **Degradados:** `qlineargradient` en QSS para sidebar y panel de login.
- **Iconos:** SVG con `QtSvg`, recoloreados por código.
- **Fuentes:** cargar Inter con `QFontDatabase.addApplicationFont`.
- **Animaciones:** `QPropertyAnimation` (opacidad, posición, ancho). No usar transiciones inexistentes en QSS.
- **Componentes propios** (en `ui/components/`): `PrimaryButton`, `SecondaryButton`, `TextField`, `SearchField`, `Card`, `KpiCard`, `StatusBadge`, `DataTable`, `Drawer`, `Dialog`, `Toast`, `EmptyState`, `Skeleton`, `Sidebar`, `Topbar`.
- **Propiedades dinámicas** (`variant="primary"`, `state="error"`) para variar estilos desde QSS sin duplicar código.
- Los casos de uso no conocen widgets Qt: la UI solo llama contratos y recibe resultados tipados.

La Fase 1 incorpora estos fundamentos en `suitelocal/ui/theme/`: tokens tipados,
generador QSS, carga de Inter con respaldo Segoe UI, iconos SVG lineales y elevación
mediante `QGraphicsDropShadowEffect`. La galería ejecutable está en
`python -m suitelocal.ui.dev.gallery`.

La Fase 2 incorpora la librería reutilizable en `suitelocal/ui/components/`:
botones, campos, tarjetas, KPI, badges, tablas, overlays, drawers, toasts,
estados vacíos, skeletons y componentes base de navegación.

La Fase 3 conecta el Shell y Login con el tema central: login dividido en panel
de marca y formulario, sidebar con iconos SVG, navegación por índices explícitos,
colapso visual a 72 px y menú condicionado por rol.

La Fase 4 comienza migrando el Panel principal a componentes reutilizables:
saludo contextual, cuatro KPI, reposición con badges y estado vacío cuando no
existen ventas. Los datos de historial aún no disponibles en los contratos no
se inventan.

La migración continúa en Caja e Inventario con búsqueda orientada a teclado,
estados vacíos, tablas reutilizables y drawers. Usuarios utiliza el mismo patrón
de drawer; Configuración conserva sus controles existentes dentro de la jerarquía
visual compartida.

El pulido transversal añade `Ctrl+K` para búsqueda global, `Escape` para limpiar
la búsqueda, foco inicial en Caja y estados de carrito que impiden cobrar cuando
no hay productos.

---

## 10. Contratos de aplicación

Los casos de uso recibirán datos simples y devolverán resultados tipados; no recibirán widgets Qt.

```text
AuthenticateUser(username, password) -> Session
CreateProduct(session, code, name, price_cents, stock) -> Product
SearchProducts(session, query) -> list[Product]
RegisterSale(session, items, payments) -> SaleReceipt
```

Los casos de uso lanzan errores de dominio explícitos para autorización, validación y conflictos de stock.

---

## 11. Convenciones de UI

- Textos en español.
- Montos visibles con dos decimales; persistencia en centavos.
- Acciones destructivas requieren confirmación.
- El foco inicial de Caja queda en búsqueda.
- Enter agrega el producto seleccionado; `Ctrl+Enter` confirma una venta válida.
- No se silencian errores de persistencia o de negocio.

---

## 12. Criterios de aceptación visual

- [ ] Ninguna pantalla usa colores, radios, sombras o tamaños fuera de los tokens.
- [ ] Login, Panel, Caja, Inventario, Configuración y Usuarios comparten cabeceras, tarjetas y componentes.
- [ ] Todos los elementos interactivos tienen estados: normal, hover, foco, pressed, deshabilitado.
- [ ] Todas las listas tienen estado vacío; las cargas largas tienen skeleton.
- [ ] Se puede completar una venta completa solo con teclado.
- [ ] La app se ve nítida a 100 %, 125 %, 150 % y 200 % de escala.
- [ ] Se capturan imágenes de cada pantalla (ancho 1100 y 1440) y se revisan contra este documento.
</document_content>