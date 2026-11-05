// Capa de acceso a la bitácora de auditoría (solo Administrador).
// El backend vive en `/api/auditoria/` (ver backend/auditoria/api/urls.py).

import { apiDownload, apiFetch } from '@/lib/http/client'
import type { Paginated } from '@/shared/types'
import type {
  CatalogoAuditoria,
  Evento,
  FiltroEventos,
} from '@/features/auditoria/types'

export const EVENTOS_POR_PAGINA = 25

function query(filtro: FiltroEventos, page = 1): string {
  const p = new URLSearchParams()
  if (page > 1) p.set('page', String(page))
  for (const [clave, valor] of Object.entries(filtro)) {
    if (valor) p.set(clave, valor)
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const auditoriaApi = {
  eventos: (page = 1, filtro: FiltroEventos = {}) =>
    apiFetch<Paginated<Evento>>(`/api/auditoria/eventos/${query(filtro, page)}`),

  catalogo: () => apiFetch<CatalogoAuditoria>('/api/auditoria/catalogo/'),

  /** Excel con los mismos filtros. La descarga también queda en la bitácora. */
  exportar: (filtro: FiltroEventos = {}) =>
    apiDownload(
      `/api/auditoria/eventos/exportar/${query(filtro)}`,
      `auditoria_${filtro.desde || 'inicio'}_a_${filtro.hasta || 'hoy'}.xlsx`,
    ),
}
