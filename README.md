# SuiteLocal

Sistema de ventas, inventario y facturación para pequeños y medianos negocios del Ecuador
(tiendas, minimarkets, cafeterías, restaurantes, ferreterías, barberías y similares).
Funciona sin internet en una sola computadora con Windows.

## Qué incluye

- **Caja** con lector de códigos, teclas rápidas, cobro en efectivo, transferencia o tarjeta,
  pago dividido y cálculo de cambio.
- **IVA ecuatoriano** (15 %, 5 % y 0 %) incluido en el precio de cada producto.
- **Inventario** con categorías, costo, margen y aviso de stock bajo.
- **Importación de productos** desde Excel (`.xlsx`) o CSV, con vista previa y todo o nada. Columnas: código, nombre, precio y stock (obligatorias); categoría, costo e IVA (opcionales). El formato `.xls` antiguo no se lee: guardalo como `.xlsx` o CSV.
- **Clientes**: búsqueda por cédula al cobrar, historial de compras y lista de quienes aceptan ofertas.
- **Mesas y comandas** para cafeterías y restaurantes (módulo opcional).
- **Apertura y cierre de caja** con arqueo, y **reportes** exportables a CSV (Excel).
- **Ticket interno** imprimible en impresoras térmicas de 58 u 80 mm o en PDF.
- **Factura electrónica del SRI** (esquema offline) para RIMPE emprendedor y régimen general,
  con envío automático cuando hay conexión.
- **Modo claro y oscuro**, usuarios con roles de dueño y cajero, y respaldos de la base de datos.

## Requisitos

- Windows 10 u 11.
- Python 3.12 (marcar "Add python.exe to PATH" al instalarlo).

## Instalación

En PowerShell, desde la carpeta del proyecto:

```powershell
python -m pip install -e .
```

## Instalador para Windows

El dueño del negocio no necesita instalar Python: recibe un instalador o un zip y lo abre con doble clic.

Guía completa (generar, subir a Google Drive e instalar en cada empresa): [`docs/INSTALL-GUIDE.md`](docs/INSTALL-GUIDE.md).

**Generarlo** (en PowerShell, desde la carpeta del proyecto, con `python -m pip install -e ".[dev]"` hecho antes):

```powershell
.\packaging\build.ps1
```

El script limpia `build\` y `dist\`, ejecuta PyInstaller y verifica que exista `dist\SuiteLocal\SuiteLocal.exe`.
Después:

- Si [Inno Setup 6](https://jrsoftware.org/isinfo.php) está instalado, compila `dist\SuiteLocal-Setup.exe`.
- Si no, deja `dist\SuiteLocal.zip` como alternativa.

**Instalarlo** (el dueño):

1. Doble clic en `SuiteLocal-Setup.exe` (no pide permisos de administrador; se instala en `%LOCALAPPDATA%\Programs\SuiteLocal`) y seguir el asistente. Crea accesos directos en el menú Inicio y, si se marca, en el escritorio.
   Con el zip: descomprimirlo y abrir `SuiteLocal\SuiteLocal.exe`.
2. Abrir SuiteLocal desde el acceso directo.

Los datos (base, respaldos y certificados) viven en `%LOCALAPPDATA%\SuiteLocal`; desinstalar la aplicación **no** los borra.

**Comprobar un build**: `.\dist\SuiteLocal\SuiteLocal.exe --smoke-test` arranca sin ventanas, con una base temporal, y termina con código 0.

## Uso

```powershell
python -m suitelocal.main
```

La primera vez, un asistente pide el nombre del negocio, el tipo de negocio, el régimen
tributario y el usuario dueño. El tipo de negocio activa una plantilla con módulos y
categorías sugeridas; todo se puede cambiar después en **Ajustes**.

Los datos se guardan en `%LOCALAPPDATA%\SuiteLocal\suitelocal.db`. Para usar otra base:

```powershell
python -m suitelocal.main --database C:\ruta\mi-negocio.db
```

## Adaptar el sistema al negocio

Todo se configura desde **Ajustes**, sin tocar código:

| Ajuste | Para qué sirve |
|---|---|
| Tipo de negocio | Aplica una plantilla con módulos y categorías de ejemplo |
| Módulos | Activa o desactiva Mesas, códigos de barras y categorías |
| Régimen tributario | Define si se emite ticket interno o factura electrónica |
| Cobro | Formas de pago, IVA por defecto, separador decimal y aviso de stock |
| Ticket | Impresora, ancho de papel y mensaje al pie |

## Factura electrónica

1. En **Ajustes > Datos del negocio**, elegir el régimen y cargar el RUC.
2. En **Ajustes > Facturación electrónica**, cargar el certificado `.p12` y su contraseña.
   Se guardan cifrados con la protección de usuario de Windows.
3. Probar primero en el ambiente **Pruebas** del SRI, que no tiene validez tributaria.
4. Cambiar a **Producción** cuando las pruebas salgan autorizadas.

Las facturas se envían al SRI cada 2 minutos. Sin internet quedan pendientes y se envían
al volver la conexión (el SRI admite hasta 72 horas).

## Respaldos

En **Ajustes > Respaldo y recuperación** se crea una copia de seguridad de la base.
Conviene guardarla fuera de la computadora (pendrive o nube) al menos una vez por semana.

## Desarrollo

Comandos, estructura y reglas del proyecto: ver `AGENTS.md`.
Arquitectura: `docs/ARCHITECTURE.md`.
