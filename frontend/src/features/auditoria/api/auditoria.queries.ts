// Hooks de datos de la auditoría sobre TanStack Query. El listado usa
// `usePaginatedList` (ver AuditoriaPage); aquí solo el catálogo, que no cambia
// mientras la app está abierta.

import { useQuery } from '@tanstack/react-query'
import { auditoriaApi } from '@/features/auditoria/api/auditoria.api'

export function useCatalogoAuditoria() {
  return useQuery({
    queryKey: ['auditoria', 'catalogo'],
    queryFn: () => auditoriaApi.catalogo(),
    staleTime: Infinity,
  })
}
