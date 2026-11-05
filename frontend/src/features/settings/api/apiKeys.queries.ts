// Hooks de datos de las API-keys sobre TanStack Query. Crear/revocar invalidan
// la lista para que el cambio se refleje al instante.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiKeysApi, type ApiKeyCreateInput } from '@/features/settings/api/apiKeys.api'

export const apiKeyKeys = {
  all: ['api-keys'] as const,
  list: () => [...apiKeyKeys.all, 'list'] as const,
}

export function useApiKeys() {
  return useQuery({
    queryKey: apiKeyKeys.list(),
    queryFn: () => apiKeysApi.list(),
  })
}

export function useCreateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ApiKeyCreateInput) => apiKeysApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: apiKeyKeys.list() }),
  })
}

export function useRevocarApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiKeysApi.revocar(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: apiKeyKeys.list() }),
  })
}
