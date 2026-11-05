// Auditoría: la bitácora central de eventos (solo Administrador).
//
// Responde «¿qué pasó con esto?» en un solo lugar: quién entró, quién dio
// permisos, qué se cambió, qué información salió. Las pantallas de cada módulo
// (Sincronizaciones, Historial, Códigos Pin) siguen existiendo; esta las junta
// con un formato común y añade lo que antes no dejaba rastro.
//
// Desde el detalle de un televisor se llega con ?objeto_tipo=televisor&
// objeto_id=… para ver «todo lo que pasó con este televisor».

import { Fragment, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowRight,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  Download,
  Search,
  ShieldBan,
  X,
} from 'lucide-react'
import {
  auditoriaApi,
  EVENTOS_POR_PAGINA,
} from '@/features/auditoria/api/auditoria.api'
import { useCatalogoAuditoria } from '@/features/auditoria/api/auditoria.queries'
import type { Evento, FiltroEventos, ResultadoEvento } from '@/features/auditoria/types'
import { ROLE_LABELS } from '@/features/auth/permissions'
import type { Role } from '@/features/auth/types'
import { usePaginatedList } from '@/shared/hooks/usePaginatedList'
import { RangoFechas } from '@/shared/components/RangoFechas'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const TODAS = 'todas'
const DIAS_POR_DEFECTO = 7
const COLUMNAS = 6

/** 'YYYY-MM-DD' de hace `dias` días, en hora local. */
function haceDias(dias: number): string {
  const d = new Date()
  d.setDate(d.getDate() - dias)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

function fecha(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString('es-CO', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
}

// --- Presentación del detalle ----------------------------------------------

/** Nombres legibles de los campos que aparecen en antes/después. */
const CAMPOS: Record<string, string> = {
  mac_address: 'MAC',
  serial_number: 'Serial',
  numero_credito: 'Crédito',
  eui64: 'EUI-64',
  inhabilitado: 'Inhabilitado',
  created_at: 'Registrado',
  email: 'Correo',
  first_name: 'Nombres',
  last_name: 'Apellidos',
  role: 'Rol',
  is_active: 'Activo',
  is_staff: 'Acceso al admin',
  is_superuser: 'Superusuario',
  nombre: 'Nombre',
  prefijo: 'Prefijo',
  activa: 'Activa',
  ips_permitidas: 'IPs permitidas',
  expira: 'Expira',
}

/** Nombres legibles de las demás claves del detalle. */
const CLAVES: Record<string, string> = {
  motivo: 'Motivo',
  origen: 'Origen',
  operacion: 'Operación',
  job: 'Sincronización #',
  lote: 'Lote #',
  registro: 'Registro de pin #',
  archivo: 'Archivo',
  filas: 'Filas',
  filtros: 'Filtros',
  parametros: 'Parámetros',
  tipo: 'Tipo',
  ruta: 'Ruta',
  metodo: 'Método',
  dispositivo: 'Dispositivo',
  sesion: 'Sesión',
  ip_sesion: 'IP de la sesión',
  detectada_por: 'Detectada por',
  iniciada: 'Sesión iniciada',
  ultima_actividad: 'Última actividad',
  cuenta_ocupante: 'Cuenta que ocupaba el navegador',
  estado: 'Estado del lote',
  forma: 'Forma',
  total: 'Total',
  procesados: 'Procesados',
  ok: 'Correctos',
  errores: 'Errores',
  errores_archivo: 'Errores en el archivo',
  creados: 'Creados',
  actualizados: 'Actualizados',
  grupos: 'Grupos de pines',
  historial_conservado: 'Historial conservado',
  error: 'Error',
}

function valor(campo: string, v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Sí' : 'No'
  if (campo === 'role' && typeof v === 'string') return ROLE_LABELS[v as Role] ?? v
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return fecha(v)
  if (typeof v === 'object') {
    const pares = Object.entries(v as Record<string, unknown>)
    return pares.length ? pares.map(([k, x]) => `${k}: ${String(x)}`).join(' · ') : '—'
  }
  return String(v)
}

function ResultadoBadge({ resultado, texto }: { resultado: ResultadoEvento; texto: string }) {
  if (resultado === 'exito')
    return (
      <Badge
        variant="outline"
        className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
      >
        <CircleCheck /> {texto}
      </Badge>
    )
  if (resultado === 'denegado')
    return (
      <Badge
        variant="outline"
        className="border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
      >
        <ShieldBan /> {texto}
      </Badge>
    )
  return (
    <Badge variant="destructive">
      <CircleX /> {texto}
    </Badge>
  )
}

/** Cuerpo desplegable de un evento: antes → después y el resto del detalle. */
function DetalleEvento({ e }: { e: Evento }) {
  const { antes, despues, ...resto } = e.detalle as {
    antes?: Record<string, unknown>
    despues?: Record<string, unknown>
  } & Record<string, unknown>
  const campos = [...new Set([...Object.keys(antes ?? {}), ...Object.keys(despues ?? {})])]

  return (
    <div className="grid gap-4 bg-muted/30 px-4 py-3 text-sm md:grid-cols-2">
      {campos.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">
            {antes && despues ? 'Cambios' : antes ? 'Estado antes' : 'Datos registrados'}
          </p>
          <table className="w-full text-xs">
            <tbody>
              {campos.map((campo) => (
                <tr key={campo} className="border-b border-border/50 last:border-0">
                  <td className="py-1 pr-3 text-muted-foreground">{CAMPOS[campo] ?? campo}</td>
                  <td className="py-1 font-mono">
                    {antes && despues ? (
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-muted-foreground line-through">
                          {valor(campo, antes[campo])}
                        </span>
                        <ArrowRight className="size-3 shrink-0 text-muted-foreground" />
                        <span className="font-medium text-foreground">
                          {valor(campo, despues[campo])}
                        </span>
                      </span>
                    ) : (
                      valor(campo, (despues ?? antes ?? {})[campo])
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {Object.entries(resto).map(([clave, v]) => (
          <Fragment key={clave}>
            <dt className="text-muted-foreground">{CLAVES[clave] ?? clave}</dt>
            <dd className="[overflow-wrap:anywhere]">{valor(clave, v)}</dd>
          </Fragment>
        ))}
        <dt className="text-muted-foreground">IP</dt>
        <dd className="font-mono">{e.ip || '—'}</dd>
        {e.navegador && (
          <>
            <dt className="text-muted-foreground">Navegador</dt>
            <dd className="[overflow-wrap:anywhere] text-muted-foreground">{e.navegador}</dd>
          </>
        )}
        {e.objeto_id && (
          <>
            <dt className="text-muted-foreground">Id del objeto</dt>
            <dd className="font-mono [overflow-wrap:anywhere]">{e.objeto_id}</dd>
          </>
        )}
      </dl>
    </div>
  )
}

// --- Página ------------------------------------------------------------------

export function AuditoriaPage() {
  const [params, setParams] = useSearchParams()
  // Objeto fijado desde otra pantalla (p. ej. el detalle de un televisor).
  const objetoTipo = params.get('objeto_tipo') ?? ''
  const objetoId = params.get('objeto_id') ?? ''
  const objetoEtiqueta = params.get('etiqueta') ?? objetoId

  // Rango acotado por defecto: la bitácora crece sin parar. Si se viene a ver
  // un objeto concreto, interesa su historia entera.
  const [desde, setDesde] = useState(objetoId ? '' : haceDias(DIAS_POR_DEFECTO))
  const [hasta, setHasta] = useState('')
  const [categoria, setCategoria] = useState(TODAS)
  const [resultado, setResultado] = useState(TODAS)
  // Lo que se escribe vs. lo que se consulta: una petición por búsqueda, no por tecla.
  const [actorInput, setActorInput] = useState('')
  const [objetoInput, setObjetoInput] = useState('')
  const [actor, setActor] = useState('')
  const [objeto, setObjeto] = useState('')
  const [abierto, setAbierto] = useState<number | null>(null)

  const filtro: FiltroEventos = {
    desde,
    hasta,
    categoria: categoria === TODAS ? '' : categoria,
    resultado: resultado === TODAS ? '' : resultado,
    actor,
    objeto,
    objeto_tipo: objetoTipo,
    objeto_id: objetoId,
  }

  const catalogo = useCatalogoAuditoria().data
  const { items, count, page, setPage, loading, error } = usePaginatedList(
    ['auditoria', 'eventos', filtro],
    (p) => auditoriaApi.eventos(p, filtro),
  )

  const [exportando, setExportando] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const totalPages = Math.max(1, Math.ceil(count / EVENTOS_POR_PAGINA))
  const pageError = error ?? exportError
  const hayFiltro = Boolean(
    desde !== haceDias(DIAS_POR_DEFECTO) ||
      hasta ||
      categoria !== TODAS ||
      resultado !== TODAS ||
      actor ||
      objeto ||
      objetoId,
  )

  // Con otros filtros cambia el número de páginas: quedarse en la 5 de un
  // resultado que ahora tiene 2 mostraría una tabla vacía.
  useEffect(() => {
    setPage(1)
    setAbierto(null)
  }, [desde, hasta, categoria, resultado, actor, objeto, objetoTipo, objetoId, setPage])

  function quitarObjeto() {
    setParams({})
    // Sin un objeto fijado vuelve el rango acotado.
    setDesde(haceDias(DIAS_POR_DEFECTO))
  }

  function limpiar() {
    setHasta('')
    setCategoria(TODAS)
    setResultado(TODAS)
    setActorInput('')
    setObjetoInput('')
    setActor('')
    setObjeto('')
    quitarObjeto()
  }

  async function exportar() {
    setExportError(null)
    setExportando(true)
    try {
      await auditoriaApi.exportar(filtro)
    } catch (e) {
      setExportError((e as Error).message)
    } finally {
      setExportando(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Auditoría</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Quién entró, quién cambió permisos, qué se modificó y qué información salió.
            Solo lectura.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RangoFechas desde={desde} hasta={hasta} setDesde={setDesde} setHasta={setHasta} />
          {hayFiltro && (
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={limpiar}>
              <X data-icon="inline-start" />
              Limpiar
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={exportar} disabled={exportando}>
            <Download data-icon="inline-start" />
            {exportando ? 'Exportando...' : 'Exportar'}
          </Button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <form
          onSubmit={(ev) => {
            ev.preventDefault()
            setActor(actorInput.trim())
            setObjeto(objetoInput.trim())
          }}
          className="flex min-w-0 flex-1 flex-wrap gap-2"
        >
          <div className="relative min-w-48 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={actorInput}
              onChange={(ev) => setActorInput(ev.target.value)}
              placeholder="Quién: correo o API key…"
              aria-label="Filtrar por actor"
              className="pl-9"
            />
          </div>
          <div className="relative min-w-48 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={objetoInput}
              onChange={(ev) => setObjetoInput(ev.target.value)}
              placeholder="Sobre qué: serial, MAC, correo…"
              aria-label="Filtrar por objeto"
              className="pl-9"
            />
          </div>
          <Button type="submit" variant="outline">
            Buscar
          </Button>
        </form>

        <Select value={categoria} onValueChange={(v) => setCategoria(String(v))}>
          <SelectTrigger className="w-52" aria-label="Categoría">
            <SelectValue>
              {(v: string) =>
                v === TODAS
                  ? 'Todas las categorías'
                  : (catalogo?.categorias.find((c) => c.valor === v)?.etiqueta ?? v)
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={TODAS}>Todas las categorías</SelectItem>
            {catalogo?.categorias.map((c) => (
              <SelectItem key={c.valor} value={c.valor}>
                {c.etiqueta}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={resultado} onValueChange={(v) => setResultado(String(v))}>
          <SelectTrigger className="w-40" aria-label="Resultado">
            <SelectValue>
              {(v: string) =>
                v === TODAS
                  ? 'Todo resultado'
                  : (catalogo?.resultados.find((r) => r.valor === v)?.etiqueta ?? v)
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={TODAS}>Todo resultado</SelectItem>
            {catalogo?.resultados.map((r) => (
              <SelectItem key={r.valor} value={r.valor}>
                {r.etiqueta}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {objetoId && (
        <div className="mb-4 flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Mostrando todo lo de</span>
          <Badge variant="secondary" className="gap-1.5">
            {objetoTipo === 'televisor' ? 'Televisor' : objetoTipo} · {objetoEtiqueta}
            <button
              type="button"
              aria-label="Quitar este filtro"
              className="rounded-sm opacity-70 hover:opacity-100"
              onClick={quitarObjeto}
            >
              <X className="size-3" />
            </button>
          </Badge>
        </div>
      )}

      {pageError && (
        <Alert variant="destructive" className="mb-4">
          <CircleAlert />
          <AlertTitle>Ocurrió un problema</AlertTitle>
          <AlertDescription>{pageError}</AlertDescription>
        </Alert>
      )}

      {!loading && (
        <p className="mb-3 text-xs text-muted-foreground">
          {count === 0 ? 'Sin eventos' : `${count} evento${count === 1 ? '' : 's'}`}
          {desde && !hasta && ` desde el ${desde.split('-').reverse().join('/')}`}
          {' '}· la exportación incluye lo mismo que ves (y queda registrada)
        </p>
      )}

      <Card className="gap-0 overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Fecha</TableHead>
              <TableHead>Evento</TableHead>
              <TableHead>Resultado</TableHead>
              <TableHead>Quién</TableHead>
              <TableHead>Sobre qué</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">Detalle</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: COLUMNAS }).map((__, j) => (
                    <TableCell key={j}>
                      <Skeleton className="h-4 w-full max-w-32" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={COLUMNAS} className="h-24 text-center text-muted-foreground">
                  No hay eventos que coincidan con los filtros.
                </TableCell>
              </TableRow>
            ) : (
              items.map((e) => {
                const expandido = abierto === e.id
                return (
                  <Fragment key={e.id}>
                    <TableRow
                      className="cursor-pointer"
                      onClick={() => setAbierto(expandido ? null : e.id)}
                      aria-expanded={expandido}
                    >
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {fecha(e.momento)}
                      </TableCell>
                      <TableCell>
                        <span className="block font-medium text-foreground">
                          {e.accion_display}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {e.categoria_display}
                        </span>
                      </TableCell>
                      <TableCell>
                        <ResultadoBadge resultado={e.resultado} texto={e.resultado_display} />
                      </TableCell>
                      <TableCell className="max-w-56">
                        <span className="block truncate" title={e.actor_nombre}>
                          {e.actor_nombre || '—'}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {e.actor_tipo_display}
                          {e.ip && ` · ${e.ip}`}
                        </span>
                      </TableCell>
                      <TableCell className="max-w-64">
                        <span className="block truncate font-mono text-xs" title={e.objeto_etiqueta}>
                          {e.objeto_etiqueta || '—'}
                        </span>
                      </TableCell>
                      <TableCell>
                        <ChevronDown
                          className={`size-4 text-muted-foreground transition-transform ${
                            expandido ? 'rotate-180' : ''
                          }`}
                        />
                      </TableCell>
                    </TableRow>
                    {expandido && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={COLUMNAS} className="p-0 whitespace-normal">
                          <DetalleEvento e={e} />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                )
              })
            )}
          </TableBody>
        </Table>
      </Card>

      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-end gap-2 text-sm text-muted-foreground">
          <span>
            Página {page} de {totalPages}
          </span>
          <Button
            variant="outline"
            size="icon-sm"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            aria-label="Anterior"
          >
            <ChevronLeft />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            disabled={page >= totalPages}
            onClick={() => setPage(page + 1)}
            aria-label="Siguiente"
          >
            <ChevronRight />
          </Button>
        </div>
      )}
    </div>
  )
}
