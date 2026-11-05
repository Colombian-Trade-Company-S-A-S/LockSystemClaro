"""Gestión de API-keys desde el panel (solo Administrador).

Se monta bajo `/api/integracion/` (ver core/urls.py):
    GET/POST  /api/integracion/api-keys/
    GET       /api/integracion/api-keys/{id}/
    POST      /api/integracion/api-keys/{id}/revocar/

No hay DELETE: una clave se revoca, nunca se borra (ver ApiKeyViewSet).
"""
from rest_framework.routers import SimpleRouter

from .views import ApiKeyViewSet

# SimpleRouter (no DefaultRouter): comparte prefijo `/api/integracion/` con el
# router de televisores de integración; evitamos dos vistas raíz en conflicto.
router = SimpleRouter()
router.register(r'api-keys', ApiKeyViewSet, basename='api-key')

urlpatterns = router.urls
