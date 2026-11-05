// Capa de acceso a las API-keys de integración (solo Administrador).
// El backend vive en `/api/integracion/api-keys/` (ver integracion/api/urls.py).

import { apiFetch } from '@/lib/http/client'
import type { Paginated } from '@/shared/types'

/** API-key tal como se lista: metadatos, nunca el secreto. */
export interface ApiKey {
  id: string
  nombre: string
  prefijo: string
  activa: boolean
  ips_permitidas: string
  expira: string | null
  creada: string
  ultimo_uso: string | null
}

/** Respuesta de creación: la clave en claro viaja SOLO aquí, una única vez. */
export interface ApiKeyCreada {
  id: string
  nombre: string
  prefijo: string
  clave: string
}

export interface ApiKeyCreateInput {
  nombre: string
  /** IPs o rangos CIDR (uno por línea). Vacío = cualquier IP. */
  ips_permitidas?: string
  /** Fecha ISO de caducidad. Vacío/null = no expira. */
  expira?: string | null
}

export const apiKeysApi = {
  /** Lista las claves (metadatos). El backend pagina; devolvemos los resultados. */
  async list(): Promise<ApiKey[]> {
    const data = await apiFetch<Paginated<ApiKey>>('/api/integracion/api-keys/')
    return data.results
  },

  /** Crea una clave nueva y devuelve la clave en claro (mostrar una sola vez). */
  create: (data: ApiKeyCreateInput) =>
    apiFetch<ApiKeyCreada>('/api/integracion/api-keys/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** Revoca (desactiva) la clave: deja de funcionar, queda de bitácora. Es la
   *  única forma de retirarla: el backend no permite borrarlas. */
  revocar: (id: string) =>
    apiFetch<ApiKey>(`/api/integracion/api-keys/${id}/revocar/`, {
      method: 'POST',
    }),
}
