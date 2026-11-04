# SuiteLocal — Documento de requisitos

> **En una frase:** un solo programa de escritorio que el dueño de una miniempresa en Ecuador instala en su PC para vender, controlar inventario, cuadrar caja y respaldar su información, **sin pagar hosting ni depender de internet**.
>
> **Promesa al cliente:** *"Lo compras una vez, funciona sin internet, tus datos quedan en tu PC."*

| Campo | Valor |
|-------|-------|
| Estado | Borrador v0.1 — para revisión |
| Fecha | 2026-10-30 |
| Rama | `docs/requisitos` |
| Autor | Daniel (producto) |

---

## Ruta rápida de lectura

1. **Qué y para quién** → [1. Visión](#1-visión) y [2. Cliente objetivo](#2-cliente-objetivo).
2. **Qué se construye primero** → [3. Módulos y prioridad](#3-módulos-y-prioridad) y [10. Plan por etapas](#10-plan-por-etapas).
3. **Qué debe cumplir** → [4. Funcionales](#4-requisitos-funcionales-rf), [5. No funcionales](#5-requisitos-no-funcionales-rnf), [6. Seguridad](#6-requisitos-de-seguridad-rs).
4. **Cómo se cobra y cómo se construye** → [7. Licenciamiento](#7-licenciamiento-y-modelo-de-cobro) y [8. Arquitectura](#8-arquitectura-propuesta).
5. **Cuándo seguir o parar** → [11. Riesgos](#11-riesgos) y [12. Métricas de decisión](#12-métricas-para-decidir-si-seguir).

**Fuera de alcance de este documento:** diseño visual detallado, precios definitivos, contratos legales y código.

---

## 1. Visión

Muchas miniempresas llevan sus ventas en cuaderno o en Excel. Las soluciones en la nube cobran mensualidad y fallan cuando se va el internet. SuiteLocal ofrece las herramientas esenciales de un negocio pequeño en **un único instalador**, que funciona sin conexión y guarda los datos en la propia PC del cliente.

**Principios de producto:**

| Principio | Qué significa en la práctica |
|-----------|------------------------------|
| Offline primero | Todo el trabajo diario funciona sin internet. Internet solo se usa para licencia, actualizaciones y sincronización opcional. |
| Pago único | El cliente compra la licencia una vez; el mantenimiento anual es opcional. |
| Datos del cliente | La información vive en la PC del cliente y en sus propios respaldos. |
| Simple de usar | Pensado para personas sin experiencia técnica: pocos clics, lenguaje claro, español. |
| Modular | Cada módulo se activa con la licencia; el cliente paga solo lo que usa. |

## 2. Cliente objetivo

| Segmento | Necesidad principal | Módulos más probables |
|----------|---------------------|-----------------------|
| Tiendas de barrio | Vender rápido, controlar stock, registrar fiado | Caja, inventario, fiado, reportes |
| Panaderías | Ventas de mostrador, cuadre diario | Caja, inventario, cuadre de caja |
| Ferreterías | Muchos productos, precios cambiantes | Inventario, caja, exportar a Excel |
| Academias | Control de asistencia y pagos | Asistencia QR, clientes y fiado |
| Consultorios | Registro de pacientes/clientes y cobros | Clientes, reportes, IA local (documentos) |
| Contadores pequeños | Procesar facturas electrónicas de sus clientes | Lector XML del SRI, exportar a Excel |

**Perfil del usuario final:** dueño o cajero, con PC de gama baja (Windows 10/11, 4 GB de RAM como referencia), conexión a internet intermitente y poca experiencia técnica.

---

## 3. Módulos y prioridad

**Leyenda:** **Debe** = entra en el MVP · **Diferencia** = razón para elegirnos frente a la competencia · **Después** = cuando el producto esté validado.

| ID | Módulo | Prioridad | Activable por licencia |
|----|--------|-----------|------------------------|
| M01 | Caja (POS) sin internet | Debe | Sí (base) |
| M02 | Inventario | Debe | Sí (base) |
| M03 | Reportes y cuadre de caja | Debe | Sí (base) |
| M04 | Clientes y fiado (crédito) | Diferencia | Sí |
| M05 | Exportar a Excel | Diferencia | Sí |
| M06 | Respaldos automáticos (USB o carpeta en la nube del cliente) | Diferencia | Sí (incluido en paquete base, ver RNF-06) |
| M07 | Lector de XML de facturas del SRI | Diferencia | Sí |
| M08 | Asistencia con QR | Después | Sí |
| M09 | IA local opcional con Ollama para consultar documentos | Después | Sí |
| M10 | Sincronización con DanStore | Después | Sí |

> **Decisión:** caja, inventario y reportes forman el "paquete base" porque son los que resuelven el dolor diario de casi todos los segmentos. Los demás se venden como complementos.

---

## 4. Requisitos funcionales (RF)

Cada requisito tiene criterios de aceptación en formato **Dado / Cuando / Entonces**.

### M01 — Caja (POS)

**RF-01 — Registrar una venta**
El cajero registra una venta buscando productos por nombre, código o lector de código de barras.

- **Dado** que hay productos con stock, **cuando** el cajero agrega productos y confirma el cobro en efectivo, **entonces** se guarda la venta, se descuenta el stock y se muestra el vuelto.
- **Dado** que no hay internet, **cuando** se registra una venta, **entonces** la venta se completa igual, sin mensajes de error.

**RF-02 — Formas de pago**
La venta admite efectivo, transferencia, tarjeta (registro manual) y fiado.

- **Dado** una venta de USD 10, **cuando** el cliente paga USD 6 en efectivo y USD 4 por transferencia, **entonces** la venta queda pagada y cada monto se registra con su forma de pago.

**RF-03 — Imprimir o guardar comprobante de venta**
El sistema genera una nota de venta imprimible (impresora térmica de 58/80 mm o A4) o en PDF.

- **Dado** una venta confirmada, **cuando** el cajero pulsa "Imprimir", **entonces** se imprime el comprobante con fecha, productos, total y nombre del negocio.
- **Nota:** este comprobante es interno. La facturación electrónica ante el SRI queda fuera del MVP (ver [11. Riesgos](#11-riesgos)).

**RF-04 — Anular una venta**
Solo un usuario con permiso puede anular una venta, indicando un motivo.

- **Dado** una venta registrada, **cuando** el dueño la anula escribiendo un motivo, **entonces** la venta queda marcada como anulada, el stock se devuelve y la acción queda en el registro de auditoría (RS-04).
- **Dado** un cajero sin permiso, **cuando** intenta anular, **entonces** el sistema pide la contraseña del dueño.

### M02 — Inventario

**RF-05 — Gestionar productos**
Crear, editar y desactivar productos con nombre, código, categoría, precio de costo, precio de venta, stock y stock mínimo.

- **Dado** el formulario de producto, **cuando** se guarda un código que ya existe, **entonces** el sistema lo rechaza con el mensaje "Ya existe un producto con ese código".

**RF-06 — Ingresar mercadería**
Registrar compras o ingresos de stock con proveedor, cantidad y costo.

- **Dado** un producto con stock 5, **cuando** se registra un ingreso de 20 unidades, **entonces** el stock queda en 25 y el movimiento aparece en el historial del producto.

**RF-07 — Alertas de stock bajo**

- **Dado** un producto con stock mínimo 3, **cuando** su stock llega a 3 o menos, **entonces** aparece en la lista "Productos por reponer" de la pantalla de inicio.

**RF-08 — Importar productos desde Excel**

- **Dado** un archivo `.xlsx` con la plantilla oficial, **cuando** el dueño lo importa, **entonces** se crean los productos válidos y se muestra la lista de filas con errores y su motivo.

### M03 — Reportes y cuadre de caja

**RF-09 — Apertura y cierre de caja**

- **Dado** el inicio del día, **cuando** el cajero abre caja con un monto inicial, **entonces** el sistema permite registrar ventas en ese turno.
- **Dado** un turno abierto, **cuando** el cajero cierra caja e ingresa el efectivo contado, **entonces** el sistema muestra lo esperado, lo contado y la diferencia (sobrante o faltante), y guarda el cierre.

**RF-10 — Reportes básicos**
Ventas por día, por rango de fechas, por producto y por cajero; productos más vendidos; utilidad estimada (precio de venta menos costo).

- **Dado** ventas registradas en la semana, **cuando** el dueño elige "Esta semana", **entonces** ve el total vendido, número de ventas y los 10 productos más vendidos.

### M04 — Clientes y fiado

**RF-11 — Registrar clientes**
Nombre, cédula o RUC (opcional), teléfono y límite de crédito.

**RF-12 — Vender a crédito (fiado)**

- **Dado** un cliente con límite de USD 50 y deuda de USD 45, **cuando** se intenta fiar USD 10, **entonces** el sistema avisa que supera el límite y solo el dueño puede autorizarlo.

**RF-13 — Registrar abonos y estado de cuenta**

- **Dado** un cliente con deuda de USD 30, **cuando** abona USD 10, **entonces** su saldo queda en USD 20 y el estado de cuenta muestra el abono con fecha.

### M05 — Exportar a Excel

**RF-14 — Exportar reportes y listas**

- **Dado** cualquier reporte o lista (ventas, productos, clientes, deudas), **cuando** el usuario pulsa "Exportar a Excel", **entonces** se genera un `.xlsx` con las mismas columnas que se ven en pantalla.

### M06 — Respaldos

**RF-15 — Respaldo automático diario**

- **Dado** que el respaldo está configurado en una carpeta (USB o carpeta sincronizada de Google Drive/OneDrive del cliente), **cuando** se cierra el programa o pasa la hora programada, **entonces** se crea un respaldo con fecha en esa carpeta y se conservan los últimos 30.

**RF-16 — Restaurar un respaldo**

- **Dado** un respaldo válido, **cuando** el dueño elige "Restaurar" e ingresa su contraseña, **entonces** el sistema guarda primero una copia de los datos actuales y luego restaura el respaldo elegido.

### M07 — Lector de XML de facturas del SRI

**RF-17 — Leer comprobantes electrónicos**
Leer archivos XML de facturas autorizadas por el SRI (uno o una carpeta completa) y extraer: emisor, RUC, fecha, número de comprobante, clave de acceso, subtotales por tarifa de IVA, IVA y total.

- **Dado** una carpeta con 100 XML de facturas, **cuando** el contador la selecciona, **entonces** el sistema muestra una tabla con los 100 comprobantes y marca los que no pudo leer con su motivo.
- **Dado** dos XML con la misma clave de acceso, **cuando** se importan, **entonces** el sistema registra solo uno y avisa del duplicado.

**RF-18 — Exportar comprobantes a Excel**

- **Dado** comprobantes leídos, **cuando** el contador exporta, **entonces** obtiene un `.xlsx` con una fila por comprobante y totales al final.

### M08 — Asistencia con QR

**RF-19 — Generar QR por persona**

- **Dado** un estudiante o empleado registrado, **cuando** se pulsa "Generar QR", **entonces** se crea un código QR imprimible con su identificador.

**RF-20 — Marcar asistencia con cámara web**

- **Dado** la pantalla de asistencia abierta, **cuando** una persona muestra su QR a la cámara, **entonces** se registra su entrada con fecha y hora, y se confirma con su nombre en pantalla.
- **Dado** que la persona ya marcó entrada hace menos de 5 minutos, **cuando** vuelve a escanear, **entonces** el sistema no duplica el registro.

### M09 — IA local opcional (Ollama)

**RF-21 — Consultar documentos propios**
El usuario carga documentos (PDF, Word, texto) y hace preguntas en lenguaje natural. El procesamiento ocurre en la PC con Ollama; nada se envía a internet.

- **Dado** que Ollama está instalado y hay documentos cargados, **cuando** el usuario pregunta algo, **entonces** el sistema responde citando el documento de donde sacó la información.
- **Dado** que Ollama no está instalado, **cuando** el usuario abre el módulo, **entonces** ve instrucciones claras para instalarlo y el resto del programa sigue funcionando.
- **Nota:** requiere una PC con más recursos que el resto de módulos; se debe informar al cliente antes de vender este módulo.

### M10 — Sincronización con DanStore (Después)

**RF-22 — Sincronizar con DanStore**
Cuando hay internet, la caja local puede enviar ventas y recibir el catálogo de productos desde DanStore (el SaaS Django del mismo autor).

- **Dado** ventas registradas sin conexión, **cuando** vuelve el internet, **entonces** se envían a DanStore sin duplicarse, aunque la sincronización se interrumpa y se reintente.
- **Dado** un conflicto de precio entre local y DanStore, **cuando** se sincroniza, **entonces** se aplica la regla definida (por defecto, gana el último cambio) y el conflicto queda registrado.
- **Nota:** la definición de la API y las reglas de conflicto se diseñarán en un documento aparte cuando este módulo pase a "Debe".

### Transversales

**RF-23 — Activar módulos con la licencia**

- **Dado** una licencia que incluye solo el paquete base, **cuando** el usuario abre el menú, **entonces** los demás módulos aparecen como "No incluido — ver cómo activarlo", sin errores.

**RF-24 — Asistente de primera configuración**

- **Dado** una instalación nueva, **cuando** se abre por primera vez, **entonces** un asistente pide nombre del negocio, contraseña del dueño, carpeta de respaldo y clave de licencia, en no más de 5 pasos.

---

## 5. Requisitos no funcionales (RNF)

| ID | Requisito | Criterio medible |
|----|-----------|------------------|
| RNF-01 | Funciona 100% sin internet | Todos los módulos excepto licencia, actualizaciones y M10 operan sin conexión. Prueba: desconectar la red y completar un día de ventas. |
| RNF-02 | Arranque rápido | Menos de 5 s desde el doble clic hasta la pantalla de inicio en una PC de gama baja de referencia (Windows 10/11, 4 GB RAM, disco HDD). |
| RNF-03 | Respuesta en caja | Buscar un producto y agregarlo a la venta tarda menos de 0,5 s con 10 000 productos. |
| RNF-04 | Instalador único | Un solo archivo `.exe` que instala, crea accesos directos y no requiere instalar Python ni otras dependencias. |
| RNF-05 | Datos locales protegidos | Base de datos SQLite cifrada o protegida (ver RS-05). |
| RNF-06 | Respaldo diario | Al menos un respaldo automático por día cuando el programa se usa; aviso visible si el último respaldo tiene más de 2 días. |
| RNF-07 | Actualizaciones descargables | El programa avisa cuando hay una versión nueva; el usuario la instala con un clic y sus datos se conservan. Las actualizaciones van firmadas para evitar instaladores falsos. |
| RNF-08 | Interfaz en español para no técnicos | Textos en español sin jerga técnica, botones grandes, atajos de teclado en caja y mensajes de error que dicen qué hacer. Prueba: un usuario nuevo registra su primera venta en menos de 10 minutos sin ayuda. |
| RNF-09 | Cumplimiento LOPDP (Ecuador) | Cumplir la Ley Orgánica de Protección de Datos Personales: guardar solo los datos necesarios de clientes, permitir corregirlos y eliminarlos, y documentar que el dueño del negocio es el responsable del tratamiento. Requiere revisión legal antes de vender. |
| RNF-10 | Compatibilidad | Windows 10 y 11 de 64 bits. Impresoras térmicas comunes vía controlador de Windows. |
| RNF-11 | Integridad ante cortes de luz | Una venta se guarda completa o no se guarda (transacciones). Tras un apagón, el programa abre sin datos corruptos. |
| RNF-12 | Mantenibilidad | Cada módulo se puede desarrollar y probar por separado; el dominio tiene pruebas automatizadas. |

## 6. Requisitos de seguridad (RS)

| ID | Requisito | Criterio de aceptación |
|----|-----------|------------------------|
| RS-01 | Acceso con contraseña | **Dado** el programa cerrado, **cuando** se abre, **entonces** pide usuario y contraseña. Las contraseñas se guardan con hash seguro (por ejemplo, Argon2 o bcrypt), nunca en texto plano. |
| RS-02 | Roles | Al menos dos roles: **Dueño** (todo) y **Cajero** (vender, abrir y cerrar caja). **Dado** un cajero, **cuando** intenta cambiar un precio, **entonces** el sistema lo bloquea o pide autorización del dueño. |
| RS-03 | Bloqueo por intentos fallidos | Tras 5 intentos fallidos, el inicio de sesión se bloquea por 5 minutos. El dueño puede recuperar el acceso con un código de recuperación generado en la instalación. |
| RS-04 | Registro de auditoría | Se registran anulaciones, cambios de precio, ajustes de stock, descuentos y restauraciones: quién, cuándo, valor anterior, valor nuevo y motivo. El registro no se puede editar desde la interfaz. |
| RS-05 | Protección de la base de datos | La base de datos está cifrada (opción a evaluar: SQLCipher) o, como mínimo, protegida con permisos de archivo y respaldos cifrados. Copiar el archivo a otra PC no debe permitir leer los datos sin la clave. |
| RS-06 | Licencia difícil de piratear | La licencia queda ligada a la PC (huella del equipo) y firmada digitalmente por el servidor de licencias; el programa verifica la firma con una clave pública incluida. Ver sección 7. |
| RS-07 | Respaldos protegidos | Los archivos de respaldo se cifran con una clave derivada de la contraseña del dueño. |
| RS-08 | Actualizaciones seguras | El actualizador solo instala paquetes firmados por el autor y descargados por HTTPS. |

> **Aclaración honesta:** ninguna protección local es imposible de romper. El objetivo es que piratear cueste más esfuerzo que comprar, no la protección perfecta.

---

## 7. Licenciamiento y modelo de cobro

### Cómo funciona

1. El cliente compra un paquete o módulos y recibe una **clave de licencia**.
2. En la primera activación (con internet), el programa envía la clave y la huella de la PC al servidor de licencias.
3. El servidor responde con un **archivo de licencia firmado** que indica módulos, PC y fecha de vencimiento del mantenimiento.
4. Cada **30 días** el programa intenta revalidar la licencia en línea.
5. Si no hay internet, el programa **sigue funcionando** durante un periodo de gracia (propuesta: 60 días adicionales) y muestra avisos amables. Pasado ese periodo, queda en **modo solo lectura** (consultar y exportar, no vender) hasta que se conecte.

> **Decisión:** el modo solo lectura protege al cliente honesto (nunca pierde acceso a sus datos) y a la vez desincentiva copias no autorizadas.

### Modelo de cobro

| Concepto | Descripción | Precio |
|----------|-------------|--------|
| Paquete base | Caja + inventario + reportes + respaldos | **Hipótesis a validar** (rango inicial de referencia: USD 80–200) |
| Módulo adicional | Fiado, Excel, lector XML, asistencia QR, IA local | **Hipótesis a validar** |
| Mantenimiento anual (opcional) | Actualizaciones, soporte remoto y revalidación | **Hipótesis a validar** |
| Cambio de PC | Transferir licencia a otro equipo | **Hipótesis a validar** (propuesta: 1 cambio gratis por año) |
| Soporte presencial | Instalación o visita | **Hipótesis a validar** (cobro aparte) |

**Sin mantenimiento:** el programa sigue funcionando con la última versión que tenía; solo deja de recibir actualizaciones y soporte.

**Pendiente:** validar precios con al menos 10 entrevistas a dueños de negocio antes de fijarlos (ver [12. Métricas](#12-métricas-para-decidir-si-seguir)). Este documento no asume datos de mercado.

**Servidor de licencias:** es el único componente en línea. Debe ser mínimo y barato (por ejemplo, un endpoint dentro de DanStore o un servicio ligero aparte); su caída no debe afectar a clientes ya activados.

---

## 8. Arquitectura propuesta

### Stack

| Capa | Elección | Por qué (una línea) |
|------|----------|---------------------|
| Lenguaje | Python 3.12+ | Es el lenguaje que el equipo ya domina y comparte con DanStore. |
| Interfaz | **PySide6** (recomendado) | Ver comparación abajo. |
| Base de datos | SQLite (con opción de cifrado SQLCipher) | Un solo archivo local, sin servidor, transaccional y probado. |
| Empaquetado | PyInstaller para el MVP; evaluar Nuitka | PyInstaller es más simple; Nuitka compila a C, puede arrancar más rápido y dificulta la ingeniería inversa. |
| Instalador | Inno Setup (o similar) sobre el ejecutable | Genera el `.exe` único con accesos directos y desinstalador. |
| Actualizador | Descarga de paquete firmado + reemplazo al reiniciar | Mantiene los datos fuera de la carpeta del programa para no perderlos. |
| Excel | openpyxl | Lee y escribe `.xlsx` sin necesitar Office instalado. |
| IA local | Ollama vía su API HTTP local | Corre modelos en la PC del cliente; nada sale a internet. |

### PySide6 vs Flet

| Criterio | PySide6 (Qt) | Flet (Flutter) |
|----------|--------------|----------------|
| Madurez | Muy alta; Qt tiene décadas en producción | Más joven; su API cambia con frecuencia entre versiones |
| Aspecto visual | Nativo/clásico; verse moderno requiere estilos (QSS) | Moderno (Material) desde el inicio, con poco esfuerzo |
| Curva de aprendizaje | Más alta (señales, slots, layouts) | Más baja; parecido a escribir componentes |
| Impresión de tickets | Soporte integrado (`QtPrintSupport`) | Sin soporte directo; requiere librerías externas |
| Cámara para QR | Disponible (`QtMultimedia`) o con OpenCV | Depende de librerías externas |
| Rendimiento en PC de gama baja | Bueno; widgets nativos | Aceptable; ejecuta un cliente Flutter aparte |
| Tamaño del instalador | Grande (Qt pesa), se reduce excluyendo módulos | Moderado |
| Licencia | LGPL (uso comercial permitido enlazando dinámicamente) | Apache 2.0 |
| Documentación y comunidad | Extensa | Creciente, menor |

**Recomendación: PySide6.** Para un producto que se vende y debe durar años, importan más la estabilidad, la impresión de tickets y la cámara integradas que la facilidad inicial de Flet.
**Validación obligatoria:** en la semana 1 se construye una prueba mínima (pantalla de caja + SQLite + empaquetado) y se mide RNF-02 en una PC de gama baja real. Si no cumple, se reevalúa.

### Estructura de carpetas (hexagonal ligera)

```text
suitelocal/
├── core/                    # Núcleo compartido
│   ├── domain/              # Entidades y reglas sin dependencias externas
│   ├── ports/               # Interfaces (repositorios, impresora, reloj, licencia)
│   └── plugins.py           # Registro y carga de módulos
├── modules/                 # Un módulo = un plugin
│   ├── pos/
│   │   ├── domain/          # Venta, LíneaDeVenta, reglas de cobro
│   │   ├── application/     # Casos de uso: RegistrarVenta, AnularVenta
│   │   ├── adapters/        # SQLite, impresora térmica
│   │   └── ui/              # Pantallas PySide6 del módulo
│   ├── inventory/
│   ├── reports/
│   ├── credit/              # Clientes y fiado
│   ├── excel_export/
│   ├── sri_xml/
│   ├── attendance_qr/
│   ├── local_ai/
│   └── danstore_sync/
├── infrastructure/          # SQLite, cifrado, respaldos, licencias, actualizador
├── ui/                      # Ventana principal, menú, login, tema
├── tests/
└── main.py                  # Punto de entrada: arma dependencias y abre la UI
```

**Reglas de dependencia:**

- `domain` no importa nada de `adapters`, `ui` ni `infrastructure`.
- Los casos de uso (`application`) dependen solo de `domain` y de `ports`.
- Cada módulo declara un manifiesto (nombre, versión, permisos, ítems de menú, clave de licencia requerida). `plugins.py` carga solo los módulos que la licencia habilita.
- Los datos del cliente viven en `%LOCALAPPDATA%\SuiteLocal\` (o la carpeta que elija), nunca en la carpeta de instalación, para que actualizar no los borre.

> **Decisión:** hexagonal *ligera* porque permite probar las reglas de negocio sin interfaz y cambiar PySide6 por otra UI si hiciera falta, sin la ceremonia de una arquitectura completa.

---

## 9. Integración opcional con DanStore (Después)

| Aspecto | Requisito |
|---------|-----------|
| Prioridad | **Después** — no entra en el MVP |
| Dirección | Productos: DanStore → local. Ventas: local → DanStore. |
| Cuándo | Solo cuando hay internet; nunca bloquea la caja. |
| Garantías | Sin duplicados (identificadores únicos por venta), reintentos seguros, registro de conflictos. |
| Diseño | La API y el contrato se definirán en un documento aparte. Este documento no analiza el código de DanStore. |

---

## 10. Plan por etapas

| Etapa | Duración estimada | Entregable | Criterio para pasar a la siguiente |
|-------|-------------------|------------|------------------------------------|
| 0. Prueba técnica | Semana 1 | Caja mínima + SQLite + `.exe` | RNF-02 cumplido en PC de gama baja real |
| 1. MVP | Semanas 2–6 | M01 Caja, M02 Inventario, M03 Reportes y cuadre, login con roles, respaldo básico, licencia | 3 negocios piloto lo usan 2 semanas seguidas |
| 2. Diferenciadores | +4–6 semanas | M04 Fiado, M05 Excel, M06 Respaldos completos, actualizador | Al menos 1 venta pagada |
| 3. Nichos | +4–8 semanas | M07 Lector XML del SRI (contadores), M08 Asistencia QR (academias) | Demanda confirmada por segmento |
| 4. Avanzado | Por definir | M09 IA local, M10 Sincronización DanStore | Clientes existentes lo piden |

> **MVP en 4–6 semanas** contando la etapa 0 y la etapa 1. Es una estimación para un desarrollador a tiempo parcial y debe revisarse al terminar la etapa 0.

---

## 11. Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Soporte presencial costoso | Alto: visitas consumen tiempo y no escalan | Asistente de configuración (RF-24), soporte remoto (por ejemplo, AnyDesk), videos cortos, cobrar visitas aparte |
| Piratería | Medio: menos ingresos | Licencia firmada y ligada a la PC (RS-06), revalidación cada 30 días, precio accesible |
| Actualizaciones difíciles de distribuir | Medio: clientes con versiones viejas y errores | Actualizador con un clic (RNF-07), datos separados del programa, migraciones automáticas de base de datos |
| Pérdida de datos (PC dañada o robada) | Alto: el cliente pierde su negocio | Respaldos automáticos fuera de la PC (RF-15), aviso de respaldo vencido (RNF-06) |
| Confusión con facturación electrónica | Alto: el cliente cree que el comprobante es factura válida | Etiquetar como "Nota de venta interna"; evaluar emisión electrónica ante el SRI como etapa futura con análisis legal propio |
| Hardware muy limitado | Medio: lentitud, mala reputación | Prueba técnica en semana 1; PC de referencia documentada; IA local solo para equipos que la soporten |
| Cumplimiento LOPDP | Medio: riesgo legal | Revisión legal antes del lanzamiento; minimizar datos personales |
| Precio mal calculado | Medio: no cubre soporte | Entrevistas y pilotos antes de fijar precios |

## 12. Métricas para decidir si seguir

| Momento | Métrica | Umbral para seguir (propuesta) |
|---------|---------|--------------------------------|
| Antes de construir el MVP | Entrevistas a dueños de negocio que confirman el problema | ≥ 7 de 10 |
| Fin de la etapa 1 | Negocios piloto usando la caja a diario | ≥ 3 durante 2 semanas |
| Fin de la etapa 1 | Tiempo para que un usuario nuevo registre su primera venta | < 10 minutos |
| Fin de la etapa 2 | Pilotos dispuestos a pagar el precio hipotético | ≥ 1 venta pagada |
| Continuo | Horas de soporte por cliente al mes | < 1 hora |
| Continuo | Clientes que renuevan el mantenimiento anual | Medir desde el primer año; umbral por definir |

**Regla de decisión:** si al terminar la etapa 2 no hay ninguna venta pagada, se pausa el desarrollo de nuevos módulos y se revisa el segmento o el precio.

---

## Checklist de revisión

- [ ] La visión y la promesa se entienden en menos de un minuto.
- [ ] Cada módulo tiene prioridad y es activable por licencia.
- [ ] Cada RF tiene criterios Dado/Cuando/Entonces verificables.
- [ ] Los RNF y RS tienen criterios medibles.
- [ ] Los precios están marcados como hipótesis.
- [ ] La recomendación de UI tiene una prueba técnica que la valida.
- [ ] La integración con DanStore está marcada como "Después".

## Próximo paso

Revisar este documento, ajustar prioridades y precios hipotéticos, y arrancar la **etapa 0 (prueba técnica)** para validar PySide6 + SQLite + empaquetado en una PC de gama baja real.
