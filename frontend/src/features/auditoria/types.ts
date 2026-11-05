// Tipos de la bitácora central de auditoría (backend: app `auditoria`).

export type ResultadoEvento = 'exito' | 'fallo' | 'denegado'

/** Un evento tal como lo devuelve /api/auditoria/eventos/. */
export interface Evento {
  id: number
  momento: string
  categoria: string
  categoria_display: string
  accion: string
  accion_display: string
  resultado: ResultadoEvento
  resultado_display: string
  actor_tipo: 'usuario' | 'api_key' | 'anonimo' | 'sistema'
  actor_tipo_display: string
  /** Congelado: sigue diciendo quién fue aunque la cuenta cambie o se borre. */
  actor_nombre: string
  ip: string | null
  /** User-Agent completo. */
  navegador: string
  /** 'Chrome en Windows'. */
  dispositivo: string
  objeto_tipo: string
  objeto_id: string
  objeto_etiqueta: string
  /** Antes/después y lo propio de cada acción (motivo, filtros, filas...). */
  detalle: Record<string, unknown>
}

export interface Opcion {
  valor: string
  etiqueta: string
}

/** Catálogo de eventos: la única lista de categorías y acciones. */
export interface CatalogoAuditoria {
  categorias: Opcion[]
  acciones: (Opcion & { categoria: string })[]
  resultados: Opcion[]
  actor_tipos: Opcion[]
}

/** Filtros de la bitácora. Los vacíos no se envían. */
export interface FiltroEventos {
  desde?: string
  hasta?: string
  categoria?: string
  resultado?: string
  /** Texto dentro del actor (correo o nombre de la API key). */
  actor?: string
  /** Texto dentro del objeto (serial, MAC, correo...). */
  objeto?: string
  /** Un objeto concreto: «todo lo que pasó con este televisor». */
  objeto_tipo?: string
  objeto_id?: string
}
