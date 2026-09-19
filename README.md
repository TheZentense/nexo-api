# Nexo API

Backend para gestionar un catálogo de proyectos, hecho con FastAPI y PostgreSQL.
El código y los mensajes de la API están en inglés; esta guía y los comentarios están en español.

## Qué permite hacer

- Consultar categorías y proyectos publicados, con filtros y paginación.
- Iniciar sesión como administrador con JWT y cerrar la sesión.
- Crear y editar categorías y proyectos.
- Guardar borradores, publicar, archivar y volver a borrador.
- Evitar que una edición antigua sobrescriba cambios recientes.
- Crear cuentas, cambiar contraseñas y desactivarlas desde la terminal.

Esta etapa todavía no incluye archivos multimedia, formularios ni pagos.
Para publicar se piden los datos del proyecto; la portada se incorporará con multimedia.
No se incluyen cuentas, contraseñas ni datos reales.

## Cómo está organizado

Usamos un monolito modular con Vertical Slicing: cada funcionalidad tiene su propia
carpeta y reúne ahí sus rutas, modelos, esquemas y servicios. Todo corre en una sola
aplicación y usa una sola base de datos.

```text
app/
  core/                 # configuración y conexión a la base
  modules/
    auth/               # login, JWT y sesiones
    projects/           # categorías y proyectos
  main.py               # reúne las rutas y los controles de salud
migrations/             # cambios de la base, en orden
scripts/                # tareas locales de administración
tests/
  test_catalog.py       # consultas públicas y validaciones
  test_admin.py         # JWT y administración
  test_audit.py         # historial y permisos
  conftest.py           # prepara la base temporal de pruebas
  helpers.py            # pasos compartidos, como login y creación de proyectos
```

Angular consumirá la API por HTTP. Las credenciales de PostgreSQL se quedan en el backend.
No hace falta agregar microservicios para este alcance.

## Preparar el entorno

Requiere Python 3.12+, PostgreSQL y una base dedicada a este proyecto. Los comandos
siguientes se ejecutan desde la carpeta del repositorio, con PowerShell 7.1 o posterior:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
$env:DATABASE_URL = Read-Host 'Application PostgreSQL URL (postgresql+psycopg://...)' -MaskInput
$env:MIGRATION_DATABASE_URL = Read-Host 'Migration PostgreSQL URL (postgresql+psycopg://...)' -MaskInput
.venv/Scripts/python.exe -m scripts.local_key
$env:JWT_SECRET = Get-Content -Raw .local/jwt.key
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic current
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m scripts.admin create admin@example.com
.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Reemplaza el correo por el tuyo. La herramienta pide la contraseña dos veces sin
mostrarla. No hay registro público ni cuentas predeterminadas.

La clave JWT queda en `.local/jwt.key`, ignorada por Git. El comando conserva la clave
si ya existe. Cárgala otra vez en cada terminal nueva; cambiarla invalida los JWT anteriores.
No se carga ningún archivo `.env`. Las URLs se proporcionan por variables de entorno;
si tu terminal no admite `-MaskInput`, usa su configuración privada de variables.

En desarrollo puedes usar una cuenta local propia para ambas conexiones. Para un
entorno compartido usa roles separados: MIGRATION_DATABASE_URL para migraciones y
cuentas; DATABASE_URL para la API. La cuenta de la API necesita lectura de admin_users,
actualización de password_hash, lectura/inserción/borrado de admin_sessions,
lectura/inserción/actualización de auth_rate_limits y de categorías/proyectos.
No necesita crear tablas ni crear o desactivar administradores.

## Probar el acceso

1. Abre [Swagger](http://127.0.0.1:8000/docs).
2. Ejecuta `POST /api/v1/auth/login` con tu correo y contraseña.
3. Copia `access_token`, pulsa **Authorize** y pega solo el token.
4. Prueba `GET /api/v1/auth/me` y las rutas de Administration.
5. Ejecuta `POST /api/v1/auth/logout`: ese token deja de funcionar inmediatamente.

Cada petición privada usa `Authorization: Bearer <token>`. El JWT vence a los 30 minutos
por defecto. No hay cookies de autenticación ni refresh token; al vencer, inicia sesión
otra vez. En Angular se guardará en memoria y se agregará la cabecera solo para esta API.

La firma, el emisor, la audiencia y las fechas se validan en cada solicitud. Además,
se comprueba la sesión en PostgreSQL para poder revocarla. Las contraseñas se guardan
como hashes Argon2id. El login admite 5 intentos por correo y 30 por cliente cada
15 minutos, incluidos los accesos correctos. Si se supera el límite devuelve 429.

Puedes ajustar JWT_ACCESS_MINUTES (1 a 60), JWT_ISSUER y JWT_AUDIENCE. Los valores por
defecto de emisor y audiencia son `nexo-api` y `nexo-admin`. JWT_SECRET debe tener al
menos 43 caracteres aleatorios; el comando local ya genera una clave adecuada.
CORS permite `http://localhost:4200`; CORS_ORIGINS acepta una lista JSON de orígenes.

## Crear y publicar un proyecto

Primero crea una categoría con `POST /api/v1/admin/categories`:

```json
{"name": "Education", "slug": "education"}
```

Luego crea el proyecto con `POST /api/v1/admin/projects`, usando el ID recibido:

```json
{
  "title": "Community classes",
  "slug": "community-classes",
  "category_id": "REPLACE-WITH-CATEGORY-UUID",
  "project_date": "2026-09-01",
  "short_description": "Weekly learning activities.",
  "description": "Classes and practical activities for the community.",
  "location": "Community center",
  "beneficiaries_count": 30,
  "progress_percent": 0
}
```

Se crea como `draft`, con `version: 1`. Para editar, usa
`PATCH /api/v1/admin/projects/{id}`:

```json
{"version": 1, "progress_percent": 25}
```

La respuesta trae una versión nueva. Usa siempre esa versión en la siguiente operación.
Para publicar, archivar o volver a borrador, envía `{"version": 2}` (o la versión actual)
a `/api/v1/admin/projects/{id}/publish`, `/archive` o `/draft` mediante POST.
Publicar requiere categoría, fecha, resumen, descripción y ubicación, además del título y slug.
No hay borrado de proyectos: archivar conserva sus datos y los retira del catálogo público.
Una categoría se edita con PATCH `/api/v1/admin/categories/{id}`, enviando nombre y slug.

- 401: falta un JWT válido o la cuenta ya no está activa.
- 404: el proyecto no existe o no es público en esa ruta.
- 409: el slug/nombre ya existe o se intentó guardar una versión antigua.
- 422: algún dato no es válido o faltan campos para publicar.

Puedes consultar el [catálogo](http://127.0.0.1:8000/api/v1/projects),
la [salud de la API](http://127.0.0.1:8000/api/v1/health/live) y
la [conexión a la base](http://127.0.0.1:8000/api/v1/health/ready).
Una base nueva devuelve listas vacías hasta que crees y publiques un proyecto.

## Administrar cuentas

```powershell
.venv/Scripts/python.exe -m scripts.admin reset-password admin@example.com
.venv/Scripts/python.exe -m scripts.admin disable admin@example.com
```

Ambas acciones revocan los tokens de la cuenta. Cambiar contraseña no reactiva una
cuenta desactivada. Estas operaciones requieren MIGRATION_DATABASE_URL.

## Migraciones y pruebas

La primera migración crea categorías y proyectos. La segunda agrega autenticación;
la tercera añade la versión de edición. Las nuevas revisiones conservan las filas
existentes. No se usa `create_all` al iniciar la aplicación ni se reinicia la base.
El downgrade destructivo está bloqueado: un cambio se corrige con otra migración revisada.

Pruebas rápidas, sin PostgreSQL:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check app migrations scripts tests
```

Para probar también JWT, administración y migraciones en PostgreSQL:

```powershell
$env:TEST_DATABASE_URL = Read-Host 'Local PostgreSQL test URL (postgresql+psycopg://...)' -MaskInput
.venv/Scripts/python.exe -m pytest -q
```

Usa un servidor local de pruebas. La cuenta necesita crear bases: la suite crea una
base `nexo_test_*` con nombre aleatorio y la elimina al terminar, sin modificar las
bases existentes. Comprueba también que actualizar desde la primera migración conserva
los datos. Sin TEST_DATABASE_URL estas pruebas se muestran como omitidas.

Las pruebas rápidas usan SQLite en memoria para consultas y respuestas HTTP. Las de
PostgreSQL comprueban las migraciones, restricciones, versiones y autenticación reales.

## Pendiente

Multimedia y formularios se agregarán en otras entregas. Antes de producción
faltan HTTPS, límites del proxy, revisión de roles y respaldo con prueba de restauración.
Las guías privadas, archivos locales, credenciales y bases de datos quedan fuera de Git.


## Historial de cambios en PostgreSQL

La migración `0004_database_audit` agrega `audit.events`. Registra altas, cambios y
borrados en proyectos, categorías y cuentas. En los proyectos también distingue
publicar, archivar y volver a borrador. Los datos existentes no se modifican ni se
crean eventos retroactivos: el historial empieza al aplicar esta migración.

Cada evento incluye fecha, registro afectado, operación, valores anteriores y nuevos,
cuenta de base de datos y, para cambios desde la API, el administrador y un identificador
de la operación. El administrador viene del JWT validado, no de un campo enviado por
el cliente. Su identidad se limpia al terminar la transacción.

Los cambios y el evento se guardan juntos. Si falla la operación o se revierte la
transacción, tampoco queda el evento. Las consultas no generan historial.

En cuentas solo se guardan el ID y el estado activo. Un cambio de contraseña se marca
como `credentials_changed`, sin copiar contraseñas, hashes, correos ni tokens.
Las sesiones y los contadores de intentos no se auditan. Los textos de proyectos sí
forman parte del historial: no incluyas información privada en contenido público.

Para consultar desde pgAdmin con la cuenta propietaria de las migraciones:

```sql
SELECT occurred_at, actor_id, request_id, database_user,
       table_name, record_id, operation, action, before_data, after_data
FROM audit.events
ORDER BY id DESC
LIMIT 50;
```

No hay pantalla ni endpoint para consultar auditoría. El rol normal de la API no
debe ser propietario de las tablas, superusuario, miembro del rol de migraciones
ni tener permisos de escritura sobre el esquema audit. La migración no da acceso
a PUBLIC; los triggers escriben con una función de permisos controlados y rutas
SQL fijas. Si ya diste permisos especiales a otros roles, debes revisarlos aparte.

Las pruebas verifican que un rol limitado pueda cambiar contenido y generar su evento,
pero no leer, insertar, editar, borrar o vaciar el historial ni desactivar el trigger.
Para ejecutar esa prueba, TEST_DATABASE_URL debe usar una cuenta local de pruebas con
CREATEDB y CREATEROLE. El rol temporal se elimina al revertir la transacción de prueba.

Un cambio hecho directamente por SQL o por las herramientas de cuentas puede tener
actor_id vacío: se conserva database_user sin inventar quién estaba usando esa cuenta.
Esto no es un registro imposible de alterar: el propietario o un superusuario conserva
poder sobre la base. La separación de roles y los respaldos son necesarios en producción.
