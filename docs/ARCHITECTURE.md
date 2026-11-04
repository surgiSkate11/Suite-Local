# SuiteLocal — Arquitectura

## Alcance de esta versión

La arquitectura cubre el MVP offline para una tienda de barrio:

- Caja/POS.
- Inventario.
- Usuarios, autenticación y roles.
- Efectivo, transferencia y tarjeta registrada manualmente.

Reportes, respaldos automáticos programados, licenciamiento y sincronización quedan fuera de
esta fase.

## Decisiones técnicas

| Área | Decisión | Motivo |
|---|---|---|
| Runtime | Python 3.12+ | Compatible con el equipo y el requisito del proyecto. |
| UI | PySide6 | Aplicación Windows nativa, impresión y soporte maduro. |
| Persistencia | SQLite | Offline, transaccional y sin servidor local. |
| Respaldo | SQLite `Connection.backup()` | Incluye correctamente el estado WAL y valida integridad. |
| Arquitectura | Hexagonal ligera | Pruebas de negocio sin UI y adaptadores reemplazables. |
| Dinero | Enteros en centavos | Evita errores de precisión con valores monetarios. |
| Identidad | Usuarios locales con contraseña derivada | El MVP no depende de internet. |
| Instalación | PyInstaller + Inno Setup | Ejecutable e instalador para Windows. |
| Datáfono | Puerto/adaptador por proveedor | Cada negocio puede tener proveedor, modelo y conexión distintos. |

## Módulos

```text
suitelocal/
├── domain/
│   ├── models.py              # Entidades y reglas puras
│   ├── errors.py              # Errores de negocio
│   └── policies.py            # Reglas de permisos
├── application/
│   ├── cart.py                # Carrito de venta
│   ├── pos.py                 # Casos de uso de caja
│   ├── inventory.py           # Casos de uso de inventario
│   └── auth.py                # Casos de uso de acceso
├── infrastructure/
│   ├── database.py            # Conexión, esquema y transacciones
│   ├── repositories.py        # Persistencia SQLite
│   ├── security.py            # Hash y verificación de contraseñas
│   └── backups.py             # Respaldo y restauración segura de SQLite
├── ui/
│   ├── pos.py                 # Pantalla de caja
│   ├── inventory.py           # Pantalla de inventario
│   └── login.py               # Inicio de sesión
└── main.py                    # Composición de dependencias
```

`core/plugins.py` registra módulos mediante manifiestos. Cada módulo declara una
clave, nombre visible, descripción y permiso requerido. Caja e Inventario son
módulos base; Clientes y crédito, Reportes, XML del SRI, Asistencia e IA local
pueden activarse como extensiones sin modificar las reglas del núcleo.

La personalización se hace por configuración y módulos, no creando una versión
distinta del programa para cada empresa. Un negocio puede vender solo Caja,
otro añadir Inventario y Reportes, y otro activar módulos especializados.

### Reglas de dependencia

- `domain` no importa `ui`, `infrastructure` ni PySide6.
- `application` depende de `domain` y de puertos/interfaces.
- `infrastructure` implementa persistencia y seguridad.
- `ui` coordina eventos visuales y muestra errores explícitos.
- `main.py` arma las dependencias; los módulos no crean conexiones globales.

## Roles del MVP

| Acción | Dueño | Cajero |
|---|---:|---:|
| Registrar ventas | Sí | Sí |
| Abrir y cerrar caja | Sí | Sí |
| Crear y editar productos | Sí | No |
| Ajustar stock | Sí | No |
| Anular ventas | Sí | No |
| Gestionar usuarios | Sí | No |

El límite de cinco usuarios se valida en la aplicación y en la base de datos mediante una regla de dominio.

## Modelo de datos inicial

### `business`

- `id`
- `name`
- `created_at`

El MVP se instala para un negocio local. La tabla permite preparar una futura separación multiempresa sin mezclar datos.

### `users`

- `id`
- `business_id`
- `username` único por negocio
- `password_hash`
- `role` (`owner` o `cashier`)
- `active`
- `created_at`

Nunca se almacena la contraseña original.

### `products`

- `id`
- `business_id`
- `code` único por negocio
- `name`
- `price_cents`
- `stock`
- `active`

### `sales`

- `id`
- `business_id`
- `user_id`
- `created_at`
- `total_cents`
- `status`

### `sale_items`

- `id`
- `sale_id`
- `product_id`
- `product_name`
- `quantity`
- `unit_price_cents`

Se conserva `product_name` y `unit_price_cents` como fotografía histórica de la venta.

### `sale_payments`

- `id`
- `sale_id`
- `method` (`cash`, `transfer` o `card`)
- `amount_cents`
- `reference`
- `status`

Separar pagos permite admitir combinaciones de formas de pago sin alterar la venta.

### Configuración de pagos

La configuración local del negocio determina si transferencia y tarjeta están disponibles. Las credenciales de un proveedor de datáfono no pertenecen al dominio; viven en infraestructura protegida y nunca se guardan en la venta.

El dominio depende de un puerto `PaymentTerminalPort`, mientras que cada proveedor implementa su propio adaptador. La ausencia de adaptador o terminal configurado deshabilita tarjeta sin afectar efectivo ni transferencia.

## Flujo crítico de una venta

1. El usuario inicia sesión.
2. La UI busca productos activos.
3. El carrito valida cantidades contra el stock visible.
4. El caso de uso vuelve a consultar stock dentro de una transacción.
5. Se valida que los pagos sumen el total.
6. Se insertan venta, líneas y pagos.
7. Se descuenta el stock.
8. La transacción se confirma; ante error se revierte completa.

La validación final siempre ocurre en la transacción para evitar vender stock desactualizado.

## Respaldos y recuperación

`infrastructure.backups` expone `create_backup` y `restore_backup`. Ambas operaciones:

- usan la API nativa de SQLite, no una copia directa del archivo principal;
- funcionan con la base en modo WAL;
- ejecutan `PRAGMA integrity_check` antes de aceptar los datos;
- rechazan rutas inexistentes o el intento de respaldar sobre la misma base;
- escriben el respaldo mediante un archivo temporal y reemplazo atómico;
- restauran sobre la conexión destino para tolerar archivos abiertos en Windows.
- pueden crear una copia de seguridad de seguridad previa antes de restaurar, conservando el
  estado que estaba activo.

La restauración debe ofrecerse desde una acción explícita de administración y acompañarse de una
confirmación visible, porque reemplaza los datos actuales del negocio.
