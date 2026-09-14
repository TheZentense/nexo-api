# Nexo API

Base de un backend de catálogo de proyectos con FastAPI y PostgreSQL.

## Alcance inicial

- Categorías y proyectos: modelos con UUID, relaciones, restricciones e índices.
- Listado público paginado, filtro por categoría/año y detalle por slug.
- Solo los proyectos publicados son visibles; borradores y archivados devuelven 404.
- Endpoints de salud y primera migración Alembic.
- Pruebas de consultas, privacidad, validaciones y configuración.

Esta entrega es de solo lectura. Administración con JWT, auditoría, multimedia y
formularios se incorporarán en etapas posteriores, antes de habilitar escrituras.

## Arquitectura

Monolito modular organizado por funcionalidad (Vertical Slicing):

```text
app/
  core/                 # configuración y conexión compartidas
  modules/projects/
    models.py           # persistencia
    schemas.py          # contrato HTTP
    service.py          # consultas y reglas del catálogo
    router.py           # transporte HTTP
  main.py               # composición y salud
migrations/             # historial de cambios del esquema
tests/                  # pruebas de la entrega
```

Cada funcionalidad reúne sus modelos, contratos y servicios. Se mantiene un solo
proceso y una sola base, sin microservicios ni repositorios genéricos innecesarios.
Angular consumirá JSON por HTTP; nunca accederá directamente a PostgreSQL.

## Configuración local

Requiere Python 3.12+ y una base PostgreSQL vacía dedicada a este proyecto.
Desde PowerShell, dentro de esta carpeta:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
$env:DATABASE_URL = Read-Host 'URL PostgreSQL local (postgresql+psycopg://...)' -MaskInput
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic current
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-proxy-headers
```

`-MaskInput` requiere PowerShell 7.1+. En otros entornos configura DATABASE_URL mediante
el mecanismo privado de variables de entorno de tu terminal. No hay archivos .env
incluidos ni cargados automáticamente. No guardar credenciales en Git o comandos compartidos.

- [Swagger](http://127.0.0.1:8000/docs)
- [Salud](http://127.0.0.1:8000/api/v1/health/ready)
- [Catálogo](http://127.0.0.1:8000/api/v1/projects)

Una base nueva devuelve listas vacías; esta entrega no contiene datos reales ni
endpoints de alta. Los tests generan sus propios datos sintéticos.
CORS permite http://localhost:4200; CORS_ORIGINS acepta una lista JSON de orígenes explícitos.

## Modelos y migraciones

La migración inicial crea únicamente categorías, proyectos y el trigger de updated_at.
Las siguientes modificaciones deben tener revisiones nuevas y revisadas; no editar
una migración ya aplicada. La reversión destructiva está bloqueada. Antes de aplicar
cambios futuros sobre datos existentes, comprobar respaldo y restauración en pruebas.
Para producción se separarán el rol de migraciones y el rol de ejecución de la API.

## Pruebas

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check app migrations tests
```

La suite rápida usa SQLite en memoria para consultas y contratos; no sustituye la
verificación de migraciones y triggers en PostgreSQL. No se conecta a bases existentes.
No es todavía una configuración de producción.
