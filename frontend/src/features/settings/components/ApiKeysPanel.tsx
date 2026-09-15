import { useEffect, useState } from 'react'
import {
  CircleAlert,
  Copy,
  FileText,
  KeyRound,
  Loader2,
  Plus,
  ShieldAlert,
  Trash2,
} from 'lucide-react'
// Guía de integración: se importa como asset para que Vite genere la URL con
// hash y respete el `base` de despliegue (así la descarga no falla en la web).
import guiaIntegracionUrl from '@/assets/Guia_API_Integracion_Locking_System.docx'
import { type ApiKey, type ApiKeyCreada } from '@/features/settings/api/apiKeys.api'
import {
  useApiKeys,
  useCreateApiKey,
  useEliminarApiKey,
  useRevocarApiKey,
} from '@/features/settings/api/apiKeys.queries'
import { ApiError } from '@/lib/http/errors'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.data && typeof err.data === 'object') {
    const data = err.data as Record<string, unknown>
    const first = data.detail ?? data.nombre ?? Object.values(data)[0]
    if (first) return Array.isArray(first) ? String(first[0]) : String(first)
  }
  // `||` y no `??`: un 500 sin cuerpo trae el statusText vacío (HTTP/2 no lo
  // manda), y un mensaje vacío dejaba el diálogo sin ninguna respuesta.
  return (err as Error)?.message || fallback
}

// Límites espejo de integracion/api/serializers.py (el backend es el guardia).
const NOMBRE_MAX = 100
const IPS_MAX_ENTRADAS = 20
const IPS_MAX_CARACTERES = 1000

const OCTETO = '(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)'
const IPV4_RE = new RegExp(`^${OCTETO}(\\.${OCTETO}){3}$`)

function esIpv6(valor: string): boolean {
  if (!valor.includes(':') || !/^[0-9a-fA-F:.]+$/.test(valor)) return false
  try {
    // El parser de URL del navegador valida IPv6 completo (abreviaturas, ::).
    return Boolean(new URL(`http://[${valor}]/`))
  } catch {
    return false
  }
}

/** IP o rango CIDR, IPv4 o IPv6 (p. ej. 190.0.0.1 o 192.168.1.0/24). */
function esIpOCidr(entrada: string): boolean {
  const partes = entrada.split('/')
  if (partes.length > 2) return false
  const [ip, mascara] = partes
  const maxMascara = IPV4_RE.test(ip) ? 32 : esIpv6(ip) ? 128 : -1
  if (maxMascara < 0) return false
  if (mascara === undefined) return true
  return /^\d{1,3}$/.test(mascara) && Number(mascara) <= maxMascara
}

/** Mensaje de error de la lista de IPs, o null si es válida. */
function validarIps(texto: string): string | null {
  const entradas = texto
    .split(/[\n,]/)
    .map((e) => e.trim())
    .filter(Boolean)
  if (entradas.length > IPS_MAX_ENTRADAS) return `Máximo ${IPS_MAX_ENTRADAS} IPs o rangos.`
  const invalida = entradas.find((e) => !esIpOCidr(e))
  if (!invalida) return null
  const muestra = invalida.length > 40 ? `${invalida.slice(0, 40)}…` : invalida
  return `«${muestra}» no es una IP ni un rango CIDR válido (p. ej. 190.0.0.1 o 192.168.1.0/24).`
}

function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null
  return <p className="text-xs text-destructive [overflow-wrap:anywhere]">{msg}</p>
}

function fmtDate(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString('es-CO', { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Estado legible de la clave: revocada > expirada > activa. */
function EstadoBadge({ k }: { k: ApiKey }) {
  if (!k.activa)
    return (
      <Badge variant="outline" className="text-muted-foreground">
        Revocada
      </Badge>
    )
  if (k.expira && new Date(k.expira).getTime() <= Date.now())
    return (
      <Badge variant="outline" className="text-amber-600 dark:text-amber-400">
        Expirada
      </Badge>
    )
  return <Badge variant="secondary">Activa</Badge>
}

// ---------------------------------------------------------------------------
// Diálogo de creación (y muestra de la clave en claro, una sola vez)
// ---------------------------------------------------------------------------
function CrearDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const [nombre, setNombre] = useState('')
  const [ips, setIps] = useState('')
  const [expira, setExpira] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [campos, setCampos] = useState<Record<string, string>>({})
  const [creada, setCreada] = useState<ApiKeyCreada | null>(null)
  const [copiada, setCopiada] = useState(false)
  const createMut = useCreateApiKey()
  const saving = createMut.isPending

  // Al abrir/cerrar, se limpia todo (para no arrastrar una clave anterior).
  useEffect(() => {
    if (!open) {
      setNombre('')
      setIps('')
      setExpira('')
      setError(null)
      setCampos({})
      setCreada(null)
      setCopiada(false)
    }
  }, [open])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const errores: Record<string, string> = {}
    if (!nombre.trim()) errores.nombre = 'Ponle un nombre para identificar al integrador.'
    else if (nombre.trim().length > NOMBRE_MAX)
      errores.nombre = `El nombre no puede superar ${NOMBRE_MAX} caracteres.`
    const errorIps = validarIps(ips)
    if (errorIps) errores.ips_permitidas = errorIps
    setCampos(errores)
    if (Object.keys(errores).length) return

    try {
      // La mutación invalida la lista por detrás; aquí solo mostramos la clave.
      const key = await createMut.mutateAsync({
        nombre: nombre.trim(),
        ips_permitidas: ips,
        expira: expira || null,
      })
      setCreada(key)
    } catch (err) {
      // Lo que el backend rechaza por campo va debajo de ese campo; cualquier
      // otra cosa (500, red caída) va arriba, pero SIEMPRE con un mensaje.
      const data =
        err instanceof ApiError && err.data && typeof err.data === 'object'
          ? (err.data as Record<string, unknown>)
          : null
      const porCampo: Record<string, string> = {}
      for (const campo of ['nombre', 'ips_permitidas', 'expira']) {
        const v = data?.[campo]
        if (v) porCampo[campo] = Array.isArray(v) ? String(v[0]) : String(v)
      }
      setCampos(porCampo)
      if (!Object.keys(porCampo).length)
        setError(apiErrorMessage(err, 'No se pudo crear la API key. Intenta de nuevo.'))
    }
  }

  async function copiar() {
    if (!creada) return
    try {
      await navigator.clipboard.writeText(creada.clave)
      setCopiada(true)
    } catch {
      setCopiada(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {creada ? (
          // --- Vista "clave creada": el secreto se muestra AQUÍ y solo aquí ---
          <>
            <DialogHeader>
              <DialogTitle>Copia la clave ahora</DialogTitle>
              <DialogDescription>
                Esta clave no se puede volver a consultar: en la base solo queda su
                hash. Cópiala y entrégasela de forma segura al integrador.
              </DialogDescription>
            </DialogHeader>

            {/* El nombre y la clave se parten donde haga falta: un nombre largo
                sin espacios desbordaba la ventana, y la clave recortada con
                "…" no se podía leer completa (hallazgo EXUS_36). */}
            <div className="grid min-w-0 gap-2">
              <p className="text-sm font-medium [overflow-wrap:anywhere]">
                Clave de «{creada.nombre}»
              </p>
              <code className="block rounded-lg border bg-muted px-2.5 py-2 font-mono text-xs break-all select-all">
                {creada.clave}
              </code>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="justify-self-end"
                onClick={copiar}
              >
                <Copy />
                {copiada ? 'Copiada' : 'Copiar'}
              </Button>
            </div>

            <Alert>
              <ShieldAlert />
              <AlertDescription>
                Guárdala en un gestor de secretos. Si se pierde, revócala y genera otra.
              </AlertDescription>
            </Alert>

            <DialogFooter>
              <Button type="button" onClick={() => onOpenChange(false)}>
                Ya la copié
              </Button>
            </DialogFooter>
          </>
        ) : (
          // --- Vista formulario ---
          <form onSubmit={onSubmit} noValidate>
            <DialogHeader>
              <DialogTitle>Nueva API key</DialogTitle>
              <DialogDescription>
                Credencial para que un integrador opere la API por serial.
              </DialogDescription>
            </DialogHeader>

            <div className="grid gap-4 py-4">
              {error && (
                <Alert variant="destructive">
                  <CircleAlert />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              <div className="grid gap-2">
                <Label htmlFor="ak_nombre">Nombre</Label>
                <Input
                  id="ak_nombre"
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                  maxLength={NOMBRE_MAX}
                  placeholder="ERP de Google"
                  aria-invalid={!!campos.nombre}
                  autoFocus
                />
                {campos.nombre ? (
                  <FieldError msg={campos.nombre} />
                ) : (
                  <p className="flex justify-between gap-2 text-xs text-muted-foreground">
                    <span>Para identificar al integrador.</span>
                    <span className="tabular-nums">
                      {nombre.length}/{NOMBRE_MAX}
                    </span>
                  </p>
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="ak_ips">IPs permitidas (opcional)</Label>
                <textarea
                  id="ak_ips"
                  value={ips}
                  onChange={(e) => setIps(e.target.value)}
                  rows={3}
                  maxLength={IPS_MAX_CARACTERES}
                  placeholder={'190.0.0.1\n192.168.1.0/24'}
                  aria-invalid={!!campos.ips_permitidas}
                  className={cn(
                    'max-h-40 w-full resize-y rounded-lg border border-input bg-transparent px-2.5 py-1.5 font-mono text-sm break-all outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:bg-input/30',
                  )}
                />
                {campos.ips_permitidas ? (
                  <FieldError msg={campos.ips_permitidas} />
                ) : (
                  <p className="text-xs text-muted-foreground">
                    IPs (190.0.0.1) o rangos CIDR (192.168.1.0/24), uno por línea,
                    máximo {IPS_MAX_ENTRADAS}. Vacío = cualquier IP.
                  </p>
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="ak_expira">Caduca el (opcional)</Label>
                <Input
                  id="ak_expira"
                  type="date"
                  value={expira}
                  onChange={(e) => setExpira(e.target.value)}
                  aria-invalid={!!campos.expira}
                  className="w-fit"
                />
                {campos.expira ? (
                  <FieldError msg={campos.expira} />
                ) : (
                  <p className="text-xs text-muted-foreground">Vacío = no expira.</p>
                )}
              </div>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Cancelar
              </Button>
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="animate-spin" />}
                {saving ? 'Creando…' : 'Crear API key'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Diálogo de confirmación (revocar / eliminar)
// ---------------------------------------------------------------------------
function ConfirmDialog({
  target,
  onOpenChange,
}: {
  target: { key: ApiKey; accion: 'revocar' | 'eliminar' } | null
  onOpenChange: (v: boolean) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const esEliminar = target?.accion === 'eliminar'
  const revocarMut = useRevocarApiKey()
  const eliminarMut = useEliminarApiKey()
  const working = revocarMut.isPending || eliminarMut.isPending

  useEffect(() => {
    if (target) setError(null)
  }, [target])

  async function confirmar() {
    if (!target) return
    setError(null)
    try {
      // Cada mutación invalida la lista; no hay que refrescar a mano.
      if (esEliminar) await eliminarMut.mutateAsync(target.key.id)
      else await revocarMut.mutateAsync(target.key.id)
      onOpenChange(false)
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo completar la acción.'))
    }
  }

  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {esEliminar ? 'Eliminar API key' : 'Revocar API key'}
          </DialogTitle>
          <DialogDescription className="[overflow-wrap:anywhere]">
            {esEliminar ? (
              <>
                Se elimina «{target?.key.nombre}» de forma definitiva. Esta acción no
                se puede deshacer.
              </>
            ) : (
              <>
                «{target?.key.nombre}» dejará de funcionar de inmediato. El registro
                queda como bitácora (no se borra).
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button
            type="button"
            variant={esEliminar ? 'destructive' : 'default'}
            onClick={confirmar}
            disabled={working}
          >
            {working && <Loader2 className="animate-spin" />}
            {esEliminar ? 'Eliminar' : 'Revocar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Panel principal
// ---------------------------------------------------------------------------
export function ApiKeysPanel() {
  const [crearAbierto, setCrearAbierto] = useState(false)
  const [confirm, setConfirm] = useState<
    { key: ApiKey; accion: 'revocar' | 'eliminar' } | null
  >(null)

  const listQuery = useApiKeys()
  const keys = listQuery.data ?? []
  const loading = listQuery.isLoading
  const error = listQuery.error
    ? apiErrorMessage(listQuery.error, 'No se pudieron cargar las API keys.')
    : null

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 border-b pb-4">
        <div>
          <CardTitle>API keys de integración</CardTitle>
          <CardDescription>
            Credenciales para que integradores operen la API por serial. La clave se
            muestra una sola vez, al crearla.
          </CardDescription>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            variant="outline"
            render={
              <a
                href={guiaIntegracionUrl}
                download="Guia_API_Integracion_Locking_System.docx"
              />
            }
          >
            <FileText />
            Guía de integración
          </Button>
          <Button onClick={() => setCrearAbierto(true)}>
            <Plus />
            Nueva
          </Button>
        </div>
      </CardHeader>

      <CardContent>
        {error && (
          <Alert variant="destructive" className="mb-4">
            <CircleAlert />
            <AlertTitle>No se pudo cargar</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nombre</TableHead>
                <TableHead>Prefijo</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Caduca</TableHead>
                <TableHead>Último uso</TableHead>
                <TableHead className="text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 6 }).map((__, j) => (
                      <TableCell key={j}>
                        <Skeleton className="h-4 w-full max-w-24" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : keys.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="h-24 text-center text-muted-foreground"
                  >
                    <KeyRound className="mx-auto mb-2 size-5 opacity-50" />
                    Aún no hay API keys. Crea la primera para un integrador.
                  </TableCell>
                </TableRow>
              ) : (
                keys.map((k) => (
                  <TableRow key={k.id}>
                    <TableCell className="font-medium">
                      <span className="block max-w-56 truncate" title={k.nombre}>
                        {k.nombre}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {k.prefijo}…
                    </TableCell>
                    <TableCell>
                      <EstadoBadge k={k} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {fmtDate(k.expira)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {fmtDate(k.ultimo_uso)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        {k.activa && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setConfirm({ key: k, accion: 'revocar' })}
                          >
                            Revocar
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="Eliminar"
                          onClick={() => setConfirm({ key: k, accion: 'eliminar' })}
                        >
                          <Trash2 className="text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>

      <CrearDialog open={crearAbierto} onOpenChange={setCrearAbierto} />
      <ConfirmDialog
        target={confirm}
        onOpenChange={(v) => !v && setConfirm(null)}
      />
    </Card>
  )
}
