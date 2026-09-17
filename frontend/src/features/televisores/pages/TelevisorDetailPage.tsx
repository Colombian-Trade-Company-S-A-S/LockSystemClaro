import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Ban,
  Check,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Copy,
  KeyRound,
  ListChecks,
  Loader2,
  Pencil,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Tv,
} from 'lucide-react'
import { televisoresApi } from '@/features/televisores/api/televisores.api'
import {
  televisorKeys,
  useDeleteTelevisor,
  useTelevisor,
  useTelevisorRegistros,
} from '@/features/televisores/api/televisores.queries'
import { usePermissions } from '@/features/auth/usePermissions'
import { ApiError } from '@/lib/http/errors'
import type {
  PinCodeGroup,
  Televisor,
  ValidarResult,
} from '@/features/televisores/types'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

function formatearFecha(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString('es-CO', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
}

function EstadoBadge({ inhabilitado }: { inhabilitado: boolean }) {
  return inhabilitado ? (
    <Badge variant="destructive">
      <Ban /> Inhabilitado
    </Badge>
  ) : (
    <Badge
      variant="outline"
      className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
    >
      <CircleCheck /> Habilitado
    </Badge>
  )
}

function Campo({
  label,
  value,
  mono,
  children,
}: {
  label: string
  value?: string
  mono?: boolean
  children?: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </span>
      {children ?? (
        <span
          className={cn(
            'text-sm font-medium text-foreground',
            mono && 'font-mono break-all',
          )}
        >
          {value || '—'}
        </span>
      )}
    </div>
  )
}

function RegistroRow({
  to,
  icon: Icon,
  label,
  count,
}: {
  to: string
  icon: React.ComponentType<{ className?: string }>
  label: string
  count?: number
}) {
  return (
    <Link
      to={to}
      className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2.5 transition-colors hover:bg-muted/50"
    >
      <span className="flex items-center gap-3 text-sm font-medium text-foreground">
        <span className="flex size-9 items-center justify-center rounded-md bg-muted text-muted-foreground">
          <Icon className="size-4" />
        </span>
        {label}
      </span>
      <span className="flex items-center gap-2">
        <Badge variant="secondary">{count ?? '…'}</Badge>
        <ChevronRight className="size-4 text-muted-foreground" />
      </span>
    </Link>
  )
}

export function TelevisorDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { canOperate } = usePermissions()

  // Lecturas cacheadas (React Query). El televisor lo comparte con la lista y
  // el formulario: volver aquí es instantáneo mientras revalida por detrás.
  const detailQuery = useTelevisor(id)
  const tv = detailQuery.data ?? null
  const loading = detailQuery.isLoading
  const registros = useTelevisorRegistros(id).data ?? null
  const deleteMut = useDeleteTelevisor()
  const [actionError, setActionError] = useState<string | null>(null)
  const error =
    actionError ?? (detailQuery.error ? (detailQuery.error as Error).message : null)
  const setError = setActionError

  // Validación
  const [validando, setValidando] = useState(false)
  const [validacion, setValidacion] = useState<ValidarResult | null>(null)

  // Código Pin
  const [codigosError, setCodigosError] = useState<string | null>(null)
  const [passInput, setPassInput] = useState('')
  const [pinResult, setPinResult] = useState<PinCodeGroup | null>(null)
  const [obteniendo, setObteniendo] = useState(false)
  const [noEncontrado, setNoEncontrado] = useState(false)
  const [copiado, setCopiado] = useState(false)

  // Sincronización con el portal que dispara el uso del pin.
  const qc = useQueryClient()
  const [pinSync, setPinSync] = useState<
    { fase: 'corriendo' } | { fase: 'ok' } | { fase: 'error'; error: string } | null
  >(null)
  const pinPollRef = useRef<number | null>(null)
  useEffect(
    () => () => {
      if (pinPollRef.current) window.clearInterval(pinPollRef.current)
    },
    [],
  )

  function refrescarTelevisor() {
    qc.invalidateQueries({ queryKey: televisorKeys.lists() })
    qc.invalidateQueries({ queryKey: televisorKeys.registros(id!) })
  }

  function seguirSyncPin(jobId: number) {
    if (pinPollRef.current) window.clearInterval(pinPollRef.current)
    setPinSync({ fase: 'corriendo' })
    pinPollRef.current = window.setInterval(async () => {
      try {
        const s = await televisoresApi.syncStatus(id!, jobId)
        if (!s.finalizado) return
        if (pinPollRef.current) window.clearInterval(pinPollRef.current)
        setPinSync(
          s.estado === 'terminado'
            ? { fase: 'ok' }
            : { fase: 'error', error: s.error || 'No se pudo aplicar en el portal.' },
        )
        refrescarTelevisor()
      } catch {
        // Un fallo puntual del polling no corta el seguimiento.
      }
    }, 2000)
  }

  async function obtenerPin(e: React.FormEvent) {
    e.preventDefault()
    setPinResult(null)
    setPinSync(null)
    setNoEncontrado(false)
    setCodigosError(null)
    setObteniendo(true)
    try {
      const r = await televisoresApi.usarPincode(id!, passInput.trim())
      setPinResult({ codeId: '', passCode: r.passcode, pinCode: r.pin_code })
      // El pin desbloquea el televisor: la consola lo muestra Habilitado ya,
      // sin esperar a que termine la sincronización con el portal.
      qc.setQueryData<Televisor>(televisorKeys.detail(id!), (prev) =>
        prev ? { ...prev, inhabilitado: r.inhabilitado } : prev,
      )
      refrescarTelevisor()
      seguirSyncPin(r.job)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNoEncontrado(true)
      else setCodigosError((err as Error).message)
    } finally {
      setObteniendo(false)
    }
  }

  function copiar(texto: string) {
    navigator.clipboard?.writeText(texto)
    setCopiado(true)
    window.setTimeout(() => setCopiado(false), 1500)
  }

  async function validar() {
    if (!id) return
    setValidando(true)
    setValidacion(null)
    try {
      setValidacion(await televisoresApi.validar(id))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setValidando(false)
    }
  }

  async function eliminar() {
    if (!tv || !confirm(`¿Eliminar el televisor ${tv.mac_address}?`)) return
    try {
      await deleteMut.mutateAsync(tv.id)
      navigate('/televisores')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (loading) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-5">
        <Skeleton className="h-8 w-44" />
        <Card>
          <CardHeader className="border-b pb-4">
            <Skeleton className="h-5 w-56" />
          </CardHeader>
          <CardContent>
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (error || !tv) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-4">
        <Alert variant="destructive">
          <CircleAlert />
          <AlertTitle>No se pudo cargar</AlertTitle>
          <AlertDescription>{error ?? 'Televisor no encontrado.'}</AlertDescription>
        </Alert>
        <Button
          variant="outline"
          size="sm"
          className="w-fit"
          render={<Link to="/televisores" />}
        >
          <ArrowLeft data-icon="inline-start" /> Volver
        </Button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5">
      {/* Encabezado + acciones */}
      <div className="flex flex-col gap-3">
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 w-fit text-muted-foreground"
          render={<Link to="/televisores" />}
        >
          <ArrowLeft data-icon="inline-start" /> Volver a televisores
        </Button>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Tv className="size-5" />
            </span>
            <div className="flex flex-col gap-1">
              <h1 className="font-mono text-lg font-bold text-foreground">
                {tv.mac_address}
              </h1>
              <EstadoBadge inhabilitado={tv.inhabilitado} />
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={validar} disabled={validando}>
              {validando ? (
                <Loader2 className="animate-spin" data-icon="inline-start" />
              ) : (
                <ShieldCheck data-icon="inline-start" />
              )}
              {validando ? 'Validando…' : 'Validar'}
            </Button>
            {canOperate && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  render={<Link to={`/televisores/${tv.id}/estado`} />}
                >
                  <SlidersHorizontal data-icon="inline-start" /> Estado
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  render={<Link to={`/televisores/${tv.id}/editar`} />}
                >
                  <Pencil data-icon="inline-start" /> Editar
                </Button>
                <Button variant="destructive" size="sm" onClick={eliminar}>
                  <Trash2 data-icon="inline-start" /> Eliminar
                </Button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Información del dispositivo */}
      <Card>
        <CardHeader className="border-b pb-4">
          <CardTitle>Información del dispositivo</CardTitle>
          <CardDescription>Datos de registro del televisor.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {validacion && (
            <Alert
              className={cn(
                validacion.coincide
                  ? 'border-emerald-500/30 text-emerald-600 dark:text-emerald-400'
                  : 'border-amber-500/30 text-amber-600 dark:text-amber-400',
              )}
            >
              {validacion.coincide ? <CircleCheck /> : <CircleAlert />}
              <AlertTitle>
                {validacion.coincide ? 'Estados sincronizados' : 'Diferencia detectada'}
              </AlertTitle>
              <AlertDescription
                className={
                  validacion.coincide
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-amber-600 dark:text-amber-400'
                }
              >
                {validacion.mensaje}
              </AlertDescription>
            </Alert>
          )}

          <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
            <Campo label="Dirección MAC" value={tv.mac_address} mono />
            <Campo label="Número de serie" value={tv.serial_number} />
            <Campo label="N° Crédito" value={tv.numero_credito} mono />
            <Campo label="Estado">
              <EstadoBadge inhabilitado={tv.inhabilitado} />
            </Campo>
            <Campo label="Registrado" value={formatearFecha(tv.created_at)} />
            <Campo label="EUI64" value={tv.eui64} mono />
          </div>
        </CardContent>
      </Card>

      {/* Registros */}
      <Card>
        <CardHeader className="border-b pb-4">
          <CardTitle>Registros</CardTitle>
          <CardDescription>Historial asociado a este dispositivo.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <RegistroRow
            to={`/televisores/${tv.id}/sincronizaciones`}
            icon={RefreshCw}
            label="Sincronizaciones"
            count={registros?.sincronizaciones}
          />
          <RegistroRow
            to={`/televisores/${tv.id}/pincodes`}
            icon={ListChecks}
            label="Códigos Pin"
            count={registros?.pincodes}
          />
        </CardContent>
      </Card>

      {/* Código Pin (Habilitación manual) */}
      <Card>
        <CardHeader className="border-b pb-4">
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="size-4 text-muted-foreground" /> Código Pin
          </CardTitle>
          <CardDescription>
            Ingresa el <b>Código de Acceso</b> que muestra el televisor para obtener su{' '}
            <b>Código Pin</b> de desbloqueo.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form onSubmit={obtenerPin} className="flex flex-wrap items-end gap-3">
            <div className="grid gap-2">
              <Label htmlFor="passcode">Código de Acceso (Passcode)</Label>
              <Input
                id="passcode"
                className="w-48"
                value={passInput}
                onChange={(e) => setPassInput(e.target.value)}
                placeholder="Ej. 0323"
                inputMode="numeric"
                autoComplete="off"
              />
            </div>
            <Button type="submit" disabled={obteniendo || !passInput.trim()}>
              {obteniendo ? (
                <Loader2 className="animate-spin" data-icon="inline-start" />
              ) : (
                <KeyRound data-icon="inline-start" />
              )}
              {obteniendo ? 'Obteniendo…' : 'Obtener Código Pin'}
            </Button>
          </form>

          {codigosError && (
            <Alert variant="destructive">
              <CircleAlert />
              <AlertDescription>{codigosError}</AlertDescription>
            </Alert>
          )}

          {noEncontrado && (
            <Alert className="border-amber-500/30 text-amber-600 dark:text-amber-400">
              <CircleAlert />
              <AlertDescription className="text-amber-600 dark:text-amber-400">
                No hay un Código Pin disponible para ese Código de Acceso.
              </AlertDescription>
            </Alert>
          )}

          {pinResult && (
            <div className="rounded-xl border border-primary/20 bg-primary/5 p-6 text-center">
              <p className="text-sm text-muted-foreground">
                Código Pin para el acceso{' '}
                <b className="text-foreground">{pinResult.passCode}</b>
              </p>
              <div className="my-3 font-mono text-4xl font-extrabold tracking-[0.3em] text-primary tabular-nums">
                {pinResult.pinCode}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => copiar(pinResult.pinCode)}
              >
                {copiado ? (
                  <Check data-icon="inline-start" />
                ) : (
                  <Copy data-icon="inline-start" />
                )}
                {copiado ? 'Copiado' : 'Copiar'}
              </Button>
              {pinSync && (
                <p
                  className={cn(
                    'mt-4 flex items-center justify-center gap-2 text-sm [overflow-wrap:anywhere]',
                    pinSync.fase === 'error'
                      ? 'text-destructive'
                      : 'text-muted-foreground',
                  )}
                >
                  {pinSync.fase === 'corriendo' && (
                    <>
                      <Loader2 className="size-4 shrink-0 animate-spin" />
                      El televisor quedó Habilitado. Sincronizando con el portal…
                    </>
                  )}
                  {pinSync.fase === 'ok' && (
                    <>
                      <CircleCheck className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                      El televisor quedó Habilitado y sincronizado con el portal.
                    </>
                  )}
                  {pinSync.fase === 'error' && (
                    <>
                      <CircleAlert className="size-4 shrink-0" />
                      El televisor quedó Habilitado, pero no se pudo sincronizar con el
                      portal: {pinSync.error}
                    </>
                  )}
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
