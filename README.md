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

Esta etapa incluye imágenes y videos. Todavía no incluye formularios ni pagos.
Para publicar se piden los datos del proyecto; la portada es opcional.
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
    media/              # imágenes, videos, almacenamiento y conversión
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
lectura/inserción/actualización de auth_rate_limits, categorías/proyectos, project_videos y project_images.
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


## Buscar proyectos desde la administración

En Swagger, usa GET `/api/v1/admin/projects` con el campo opcional `q`:

```text
/api/v1/admin/projects?q=community&status=draft&year=2026&page=1&page_size=12
```

Busca una parte del título, sin distinguir mayúsculas y minúsculas. Puedes combinarlo
con estado, categoría (`category_id`), año y paginación. `total` cuenta todas las
coincidencias, aunque la página muestre solo algunas.

Los espacios al principio y al final se ignoran; dejar q vacío conserva el listado
habitual. Se admiten hasta 200 caracteres. Los símbolos `%` y `_` se buscan como texto,
no como comodines. No se busca dentro de la descripción ni se eliminan las tildes.

Esta búsqueda requiere JWT y solo se agrega al listado administrativo. El catálogo
público conserva sus filtros y muestra únicamente proyectos publicados. Buscar no
modifica datos ni genera eventos de auditoría. Las pruebas están en `tests/test_project_search.py`.


## Resumen del panel administrativo

Después del login y de usar Authorize en Swagger, consulta
GET `/api/v1/admin/dashboard`. Devuelve el total de proyectos, las cantidades por
estado (`draft`, `published`, `archived`) y `recent`, con hasta cinco proyectos
ordenados por su última modificación. Si dos fechas coinciden, desempata por ID.

Sin proyectos, los contadores son cero y `recent` es una lista vacía. El resumen
incluye todos los proyectos, no solo los de la página actual del listado. Requiere
JWT, no se guarda en caché y consultarlo no genera eventos de auditoría.

No necesita una migración ni agrega una pantalla. Angular podrá usar esta respuesta
para las tarjetas de totales y la lista de actividad reciente. Las pruebas están en
`tests/test_dashboard.py`.


## Videos de los proyectos

La migración `0005_project_videos` agrega una tabla y su auditoría, sin borrar ni
actualizar los proyectos existentes. El original se conserva; la conversión genera
un MP4 H.264/AAC y una portada JPEG. Los archivos nunca se montan como carpeta pública.

Aceptamos MP4, MOV y WebM compatibles con FFmpeg, hasta 100 MiB y dos minutos.
Se comprueba el contenido; cambiar la extensión no convierte un archivo en video.
La subida revisa tamaño y cabecera. El worker comprueba duración, resolución y
que se pueda decodificar; si falla, deja el registro en `failed` y conserva el original.
Se admiten hasta dos videos por proyecto, incluidos los pendientes y fallidos.
Esta etapa no incluye eliminación ni reemplazo de originales.

La salida llega hasta 1280 × 720, conserva proporciones y no amplía videos pequeños.
Usa 30 fps, compresión con pérdida y `faststart`; no garantiza que todo archivo sea
más pequeño que su original. La entrada admite hasta 3840 × 2160 píxeles, también
verticales. Las opciones de protocolos y reproducción se describen en la
[documentación de FFmpeg](https://ffmpeg.org/ffmpeg-protocols.html) y sus
[formatos](https://ffmpeg.org/ffmpeg-formats.html).

### Probar la subida

Después de instalar las dependencias y ejecutar `alembic upgrade head`, inicia la API
como se indica arriba. En otra terminal, con las mismas variables de conexión,
JWT y almacenamiento, inicia el worker desde la raíz del repositorio:

```powershell
.venv/Scripts/python.exe -m app.modules.media.worker
```

Para procesar solo un trabajo pendiente y terminar:

```powershell
.venv/Scripts/python.exe -m app.modules.media.worker --once
```

`STORAGE_ROOT` puede indicar una carpeta absoluta privada. Su valor predeterminado es
`storage`, relativo al directorio de trabajo e ignorado por Git. API y worker deben
usar la misma carpeta. `VIDEO_MAX_BYTES` y `VIDEO_MAX_SECONDS` permiten bajar los
límites. El worker convierte en un subproceso que no recibe las credenciales de la
base, JWT ni bucket. Los límites de tiempo y protocolos no reemplazan el aislamiento
del proceso con permisos y recursos restringidos al desplegar en producción.

En Swagger, autoriza con JWT y utiliza `POST /api/v1/admin/projects/{id}/videos`.
El cuerpo es el archivo binario (`application/octet-stream`), no JSON ni multipart.
También puedes subirlo desde PowerShell, con la API en el puerto 8000:

```powershell
$videoToken = Read-Host 'Access token' -MaskInput
$videoProject = Read-Host 'Project UUID'
$videoFile = Read-Host 'Video path'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/admin/projects/$videoProject/videos" -Headers @{Authorization="Bearer $videoToken"} -ContentType 'application/octet-stream' -InFile $videoFile
```

La respuesta es `202` con `status: pending`; significa recibido, no convertido.
Consulta `GET /api/v1/admin/projects/{id}/videos` para ver el avance.
Los estados guardados son `pending`, `processing`, `ready` y `failed`.
Si un archivo listo falta o el almacenamiento no responde, se devuelve `unavailable`
sin cambiar la base. Los errores técnicos y las claves privadas no salen en el listado.

- `GET /api/v1/admin/videos/{id}/content`: MP4 optimizado, requiere JWT.
- `GET /api/v1/admin/videos/{id}/poster`: portada, requiere JWT.
- `GET /api/v1/admin/videos/{id}/original`: descarga privada del original.
- `POST /api/v1/admin/videos/{id}/retry`: reintenta un fallo o un proceso detenido
  durante más de diez minutos. No reemplaza el original; un archivo corrupto volverá
  a fallar. Los procesos activos rechazan reintentos para evitar duplicados.
- `GET /api/v1/projects/{slug}/videos`: consulta pública de un proyecto publicado.

El listado devuelve `video_url` y `poster_url` relativas a la API. Los visitantes
solo pueden descargar las variantes de proyectos publicados; al archivar o volver
a borrador, las rutas públicas dejan de entregarlas. Las respuestas no se guardan
en caché. Esto no puede retirar una copia que alguien haya descargado antes.

### Mensaje de video no disponible

Angular debe usar `status` antes de crear el reproductor:

- `pending` o `processing`: mostrar “Video en preparación”.
- `ready`: usar `video_url` y, si existe, `poster_url`.
- `failed` o `unavailable`: mostrar “Video no disponible por el momento”.

También debe manejar el evento `error` del reproductor, porque la red puede fallar
después de consultar la API. El backend no puede cambiar el mensaje nativo del navegador.
Las rutas de archivos mantienen códigos HTTP 404/503 con un mensaje genérico; Angular
los transforma en ese aviso visual. La vista administrativa debe obtener los archivos
con la cabecera Bearer y crear una URL de objeto para previsualizarlos, liberándola
al cerrar. Nunca colocar el JWT en la URL.

### Cambio posterior a un bucket

`media/storage.py` concentra `put`, `download`, `exists`, `delete` y `response`.
Hoy se usa `LocalStorage`; PostgreSQL guarda claves de objetos, nunca rutas del equipo
ni URLs firmadas. Un adaptador de bucket implementará esas operaciones y se inyectará
en la API y el worker, manteniendo las mismas rutas y permisos.

Los originales y las variantes seguirán privados en el bucket. Para entregar una
variante, la API comprobará primero el estado del proyecto. Se podrá transmitir el
archivo o generar una URL firmada corta; esta última puede seguir funcionando hasta
su vencimiento aunque se archive el proyecto. El proveedor, la caducidad y la caché
se decidirán al integrar el bucket. No hay SDK ni credenciales de almacenamiento
externo en esta etapa.

Las pruebas generan clips pequeños y usan carpetas y bases temporales. Cubren
formatos, conservación de originales, fallos, reintentos, auditoría, permisos,
lectura parcial de video y conservación de los datos al migrar.


## Imágenes, portada y galería

La migración `0006_project_images` agrega las imágenes y su auditoría. No modifica
los proyectos, videos ni eventos existentes. Después de migrar, el rol de la API
y del worker necesita SELECT, INSERT y UPDATE sobre `project_images`.

Se usa el mismo worker y almacenamiento privado de los videos. No hay un segundo
servicio ni una cola externa. El worker alterna videos e imágenes; `--once` procesa
como máximo un archivo, dando prioridad a un video pendiente si existe.

### Subir y consultar

- `POST /api/v1/admin/projects/{id}/images`: archivo binario con JWT, devuelve 202.
  Acepta `application/octet-stream`, `image/jpeg`, `image/png` o `image/webp`.
  El parámetro opcional `alt_text` describe la imagen (hasta 250 caracteres).
- `GET /api/v1/admin/projects/{id}/images`: orden, portada, `project_version` y estado
  de las imágenes, con variantes disponibles para previsualización autenticada.
- `GET /api/v1/projects/{slug}/images`: galería pública solo de proyectos publicados.
- `GET /api/v1/admin/images/{id}/original`: original privado descargable con JWT.
- `GET /api/v1/admin/images/{id}/{variant}` y `/api/v1/images/{id}/{variant}`:
  variantes privadas y públicas, respectivamente. `variant` es w480, w960 o w1600.
- `POST /api/v1/admin/images/{id}/retry`: reintento de un fallo o un proceso que lleva
  más de diez minutos detenido, con la misma regla que los videos.

Se aceptan JPEG, PNG y WebP estáticos. El límite inicial es 15 MiB, 25 millones de
píxeles y diez imágenes activas por proyecto, incluyendo pendientes y fallidas. Se pueden
reducir los límites con `IMAGE_MAX_BYTES` e `IMAGE_MAX_PIXELS`. No se aceptan SVG,
GIF ni imágenes animadas. La cabecera se comprueba al subir; la decodificación y
los límites de píxeles se verifican después, fuera de la petición web.

El original no cambia. Se corrige la orientación de la copia y se generan WebP
con ancho máximo de 480, 960 y 1600, conservando proporciones y limitando la altura
a 1600. Las imágenes pequeñas no se amplían y no se guardan tamaños duplicados.
Los nombres de variante indican el ancho máximo: usa `width` y `height` de la
respuesta para conocer las dimensiones reales. Cada variante incluye URL y peso.

La copia web conserva transparencia y excluye EXIF, XMP y perfil ICC del original.
La compresión y la eliminación del perfil pueden cambiar ligeramente la apariencia;
se preserva el original para otros usos. Las medidas de decodificación siguen la
[documentación de seguridad de Pillow](https://pillow.readthedocs.io/en/stable/handbook/security.html).

### Elegir portada y ordenar

Usa `PATCH /api/v1/admin/projects/{id}/images`, tomando la versión del último listado:

```json
{
  "version": 3,
  "image_ids": ["SECOND-IMAGE-UUID", "FIRST-IMAGE-UUID"],
  "cover_image_id": "FIRST-IMAGE-UUID"
}
```

La lista debe incluir todas las imágenes activas del proyecto exactamente una vez. La portada
puede ser null, o una imagen disponible del mismo proyecto. Solo puede haber una
portada por proyecto, también protegido por un índice único en PostgreSQL.
Una versión antigua devuelve 409; vuelve a cargar la galería antes de guardar.

Subir una imagen, ordenar, elegir portada o editar su texto actualiza la versión del
proyecto y su fecha de modificación. Usa la versión nueva también al editar o publicar
el proyecto. La conversión automática no cambia esa versión ni elige portada por ti.
Para editar el texto usa `PATCH /api/v1/admin/images/{id}`:

```json
{"version": 4, "alt_text": "Personas participando en el taller comunitario"}
```

El catálogo y el detalle públicos incluyen `cover_url`, o null cuando no hay una
portada disponible. Las portadas del listado se consultan juntas en la base. Si falta
una variante, se puede usar otra disponible; si no queda ninguna, la imagen responde
`unavailable`, sin URLs de archivos rotos. Angular debe manejar además los errores de
red y mostrar una imagen alternativa o un mensaje. No se entregan rutas internas ni
claves de almacenamiento. Archivar el proyecto cierra el acceso público a sus imágenes.

### Retirar una imagen

Envía `POST /api/v1/admin/images/{id}/archive` con JWT y la versión actual:

```json
{"version": 5}
```

La respuesta contiene la galería activa y la nueva `project_version`. La imagen deja
el catálogo y sus rutas públicas devuelven 404. Si era portada, el proyecto queda sin
portada hasta elegir otra. Las demás imágenes mantienen su orden y se libera un cupo.
El original y las variantes terminadas se conservan en privado.

Consulta `GET /api/v1/admin/projects/{id}/images?archived=true` para ver solo las
retiradas, con `status: "archived"` y `archived_at`. Sus originales siguen disponibles
con JWT. No se pueden editar, reintentar ni incluir en el orden de la galería.
Repetir el retiro con la versión actual no crea otro evento ni cambia la versión;
una versión antigua devuelve 409.

La migración `0007_archive_project_images` agrega la fecha de retiro sin borrar datos.
La auditoría registra quién retiró la imagen y cuándo. Si estaba convirtiéndose,
el worker descarta el resultado y conserva el original. Esta etapa no incluye restaurar
imágenes, reemplazarlas ni retirar videos. Tampoco puede revocar una copia descargada.

El adaptador de bucket queda pendiente, manteniendo la interfaz de almacenamiento
sin introducir URLs permanentes en la base.
