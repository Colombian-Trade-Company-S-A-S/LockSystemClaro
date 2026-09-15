import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, CircleAlert, Loader2, Pencil, Plus } from 'lucide-react'
import {
  useCreateTelevisor,
  useTelevisor,
  useUpdateTelevisor,
} from '@/features/televisores/api/televisores.queries'
import type { TelevisorInput } from '@/features/televisores/types'
import { ApiError } from '@/lib/http/errors'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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

const emptyForm: TelevisorInput = {
  mac_address: '',
  serial_number: '',
  numero_credito: '',
}

/** Extrae errores por campo y un mensaje general de un ApiError de DRF. */
function parseErrors(err: unknown): {
  fields: Record<string, string>
  general: string | null
} {
  if (err instanceof ApiError && err.data && typeof err.data === 'object') {
    const data = err.data as Record<string, unknown>
    const fields: Record<string, string> = {}
    let general: string | null = null
    for (const [key, val] of Object.entries(data)) {
      const msg = Array.isArray(val) ? String(val[0]) : String(val)
      if (key === 'detail' || key === 'non_field_errors') general = msg
      else fields[key] = msg
    }
    return { fields, general }
  }
  return { fields: {}, general: (err as Error)?.message ?? 'Error inesperado.' }
}

// Reglas espejo de `televisores/validadores.py` en el backend, que es el guardia
// real; aquí se filtra al teclear para que el usuario no llegue a escribir un
// carácter que luego le rechacen.
const SERIAL_MIN = 4
const SERIAL_MAX = 17

/** Quita lo que no sea letra o número y pasa a mayúsculas. */
function sanitizarSerial(valor: string): string {
  return valor
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '')
    .slice(0, SERIAL_MAX)
}

// Dirección MAC: seis pares hexadecimales con dos puntos (B4:04:29:7E:3A:AA).
const MAC_RE = /^[0-9A-F]{2}(:[0-9A-F]{2}){5}$/
const MAC_LARGO = 17
const MENSAJE_MAC =
  'La dirección MAC debe tener el formato XX:XX:XX:XX:XX:XX (por ejemplo B4:04:29:7E:3A:AA).'

/** Deja solo hexadecimales (máx. 12) y pone los dos puntos cada dos. Así una
 *  MAC pegada con guiones o sin separadores también queda bien. */
function formatearMac(valor: string): string {
  const hex = valor.toUpperCase().replace(/[^0-9A-F]/g, '').slice(0, 12)
  return hex.match(/.{1,2}/g)?.join(':') ?? ''
}

function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null
  return <p className="text-xs text-destructive">{msg}</p>
}

export function TelevisorFormPage() {
  const { id } = useParams()
  const isEdit = Boolean(id)
  const navigate = useNavigate()

  const [form, setForm] = useState<TelevisorInput>(emptyForm)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [general, setGeneral] = useState<string | null>(null)

  // Carga del televisor a editar (React Query: cacheada y compartida con la lista).
  const detailQuery = useTelevisor(isEdit ? id : undefined)
  const loading = isEdit && detailQuery.isLoading
  const createMut = useCreateTelevisor()
  const updateMut = useUpdateTelevisor(id ?? '')
  const saving = createMut.isPending || updateMut.isPending

  // Al llegar los datos del televisor, se siembran en el formulario editable.
  const tv = detailQuery.data
  useEffect(() => {
    if (tv) {
      setForm({
        mac_address: tv.mac_address,
        serial_number: tv.serial_number,
        numero_credito: tv.numero_credito,
      })
    }
  }, [tv])
  useEffect(() => {
    if (detailQuery.error) setGeneral((detailQuery.error as Error).message)
  }, [detailQuery.error])

  function set<K extends keyof TelevisorInput>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setFieldErrors({})
    setGeneral(null)

    // El backend valida lo mismo; esto solo evita el viaje.
    const errores: Record<string, string> = {}
    // El serial es opcional, pero si se escribe algo tiene que ser un serial
    // de verdad.
    const serial = form.serial_number.trim()
    if (serial && serial.length < SERIAL_MIN) {
      errores.serial_number = `El número de serie debe tener al menos ${SERIAL_MIN} caracteres.`
    } else if (serial.length > SERIAL_MAX) {
      // Solo pasa con un serial viejo cargado al editar: al teclear no se puede.
      errores.serial_number = `El número de serie no puede superar ${SERIAL_MAX} caracteres.`
    }
    const mac = form.mac_address.trim().toUpperCase()
    if (!mac) errores.mac_address = 'La dirección MAC es obligatoria.'
    else if (!MAC_RE.test(mac)) errores.mac_address = MENSAJE_MAC
    if (Object.keys(errores).length) {
      setFieldErrors(errores)
      return
    }

    try {
      const saved = isEdit
        ? await updateMut.mutateAsync(form)
        : await createMut.mutateAsync(form)
      navigate(`/televisores/${saved.id}`)
    } catch (err) {
      const { fields, general: g } = parseErrors(err)
      setFieldErrors(fields)
      setGeneral(g)
    }
  }

  const titulo = isEdit ? 'Editar televisor' : 'Nuevo televisor'

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-5">
      {/* Encabezado */}
      <div className="flex flex-col gap-3">
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 w-fit text-muted-foreground"
          render={<Link to="/televisores" />}
        >
          <ArrowLeft data-icon="inline-start" /> Volver a televisores
        </Button>
        <div className="flex items-center gap-3">
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
            {isEdit ? <Pencil className="size-5" /> : <Plus className="size-5" />}
          </span>
          <div className="flex flex-col gap-0.5">
            <h1 className="text-lg font-bold text-foreground">{titulo}</h1>
            <p className="text-sm text-muted-foreground">
              {isEdit
                ? 'Actualiza los datos de registro del televisor.'
                : 'Registra un nuevo televisor en el sistema.'}
            </p>
          </div>
        </div>
      </div>

      <Card>
        <CardHeader className="border-b pb-4">
          <CardTitle>Datos del dispositivo</CardTitle>
          <CardDescription>
            La dirección MAC es obligatoria; los demás campos son opcionales.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex flex-col gap-5">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="grid gap-2">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-9 w-full" />
                </div>
              ))}
            </div>
          ) : (
            <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
              {general && (
                <Alert variant="destructive">
                  <CircleAlert />
                  <AlertTitle>No se pudo guardar</AlertTitle>
                  <AlertDescription>{general}</AlertDescription>
                </Alert>
              )}

              <div className="grid gap-2">
                <Label htmlFor="serial">Número de serie</Label>
                <Input
                  id="serial"
                  className="font-mono"
                  inputMode="text"
                  autoCapitalize="characters"
                  autoComplete="off"
                  spellCheck={false}
                  maxLength={SERIAL_MAX}
                  value={form.serial_number}
                  onChange={(e) =>
                    set('serial_number', sanitizarSerial(e.target.value))
                  }
                  placeholder="ABC123456789"
                  aria-invalid={!!fieldErrors.serial_number}
                  aria-describedby="serial-ayuda"
                  autoFocus
                />
                {fieldErrors.serial_number ? (
                  <FieldError msg={fieldErrors.serial_number} />
                ) : (
                  <p id="serial-ayuda" className="text-xs text-muted-foreground">
                    Solo letras y números, máximo {SERIAL_MAX} caracteres, sin
                    espacios ni caracteres especiales. Opcional.
                  </p>
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="mac">
                  Dirección MAC <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="mac"
                  className="font-mono"
                  autoCapitalize="characters"
                  autoComplete="off"
                  spellCheck={false}
                  maxLength={MAC_LARGO}
                  value={form.mac_address}
                  onChange={(e) => set('mac_address', formatearMac(e.target.value))}
                  placeholder="B4:04:29:7E:3A:AA"
                  aria-invalid={!!fieldErrors.mac_address}
                  aria-describedby="mac-ayuda"
                />
                {fieldErrors.mac_address ? (
                  <FieldError msg={fieldErrors.mac_address} />
                ) : (
                  <p id="mac-ayuda" className="text-xs text-muted-foreground">
                    Formato XX:XX:XX:XX:XX:XX. Los dos puntos se ponen solos.
                  </p>
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="credito">Número de crédito</Label>
                <Input
                  id="credito"
                  value={form.numero_credito}
                  onChange={(e) =>
                    set('numero_credito', e.target.value.replace(/\D/g, '').slice(0, 60))
                  }
                  placeholder="1234567890"
                  inputMode="numeric"
                  aria-invalid={!!fieldErrors.numero_credito}
                />
                <FieldError msg={fieldErrors.numero_credito} />
              </div>

              <div className="flex gap-2 pt-1">
                <Button type="submit" disabled={saving}>
                  {saving && <Loader2 className="animate-spin" data-icon="inline-start" />}
                  {saving ? 'Guardando…' : 'Guardar'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => navigate('/televisores')}
                >
                  Cancelar
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
