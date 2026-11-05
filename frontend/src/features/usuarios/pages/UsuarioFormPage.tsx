import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { CircleAlert, Loader2 } from 'lucide-react'
import {
  useCreateUsuario,
  useUpdateUsuario,
  useUsuario,
} from '@/features/usuarios/api/usuarios.queries'
import { ROLE_LABELS } from '@/features/auth/permissions'
import { usePermissions } from '@/features/auth/usePermissions'
import type { Role } from '@/features/auth/types'
import { ApiError } from '@/lib/http/errors'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PasswordInput } from '@/components/ui/password-input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

const ROLES: Role[] = ['admin', 'operador', 'consulta']

/** Descripción corta de cada rol (ayuda contextual en el formulario). */
const ROLE_HINT: Record<Role, string> = {
  admin: 'Todos los módulos + gestión de usuarios y parametrizaciones.',
  operador:
    'Habilitaciones, inhabilitaciones, enrolamiento/desenrolamiento, pines y reportes.',
  // No decir "solo lectura": entregar un Código Pin habilita el televisor.
  consulta:
    'Validar estado (individual o masivo), entregar Códigos Pin (habilitan el televisor) y descargar reportes. No edita televisores ni cambia estados.',
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

function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null
  return <p className="text-xs text-destructive">{msg}</p>
}

export function UsuarioFormPage() {
  const { id } = useParams()
  const isEdit = Boolean(id)
  const navigate = useNavigate()
  const { user: current } = usePermissions()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [role, setRole] = useState<Role>('consulta')
  const [isActive, setIsActive] = useState(true)

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [general, setGeneral] = useState<string | null>(null)

  const isSelf = isEdit && current?.id === id

  const detailQuery = useUsuario(isEdit ? id : undefined)
  const loading = isEdit && detailQuery.isLoading
  const createMut = useCreateUsuario()
  const updateMut = useUpdateUsuario(id ?? '')
  const saving = createMut.isPending || updateMut.isPending

  // Siembra el formulario cuando llegan los datos del usuario a editar.
  const u = detailQuery.data
  useEffect(() => {
    if (u) {
      setEmail(u.email)
      setFirstName(u.first_name)
      setLastName(u.last_name)
      setRole(u.role)
      setIsActive(u.is_active)
    }
  }, [u])
  useEffect(() => {
    if (detailQuery.error) setGeneral((detailQuery.error as Error).message)
  }, [detailQuery.error])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setFieldErrors({})
    setGeneral(null)

    // Nombres y apellidos son obligatorios, igual que en el perfil propio: una
    // cuenta sin nombre queda a medio identificar en la tabla y en la auditoría.
    const faltan: Record<string, string> = {}
    if (!firstName.trim()) faltan.first_name = 'Los nombres son obligatorios.'
    if (!lastName.trim()) faltan.last_name = 'Los apellidos son obligatorios.'
    if (Object.keys(faltan).length > 0) {
      setFieldErrors(faltan)
      return
    }

    try {
      if (isEdit) {
        await updateMut.mutateAsync({
          first_name: firstName.trim(),
          last_name: lastName.trim(),
          role,
          is_active: isActive,
        })
      } else {
        await createMut.mutateAsync({
          email,
          password,
          first_name: firstName.trim(),
          last_name: lastName.trim(),
          role,
        })
      }
      navigate('/usuarios')
    } catch (err) {
      const { fields, general: g } = parseErrors(err)
      setFieldErrors(fields)
      setGeneral(g)
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-xl">
        <Card>
          <CardContent className="space-y-4 py-6">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-xl">
      <Card>
        <CardHeader className="border-b pb-4">
          <CardTitle>{isEdit ? 'Editar usuario' : 'Nuevo usuario'}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} noValidate className="space-y-5">
            {general && (
              <Alert variant="destructive">
                <CircleAlert />
                <AlertTitle>No se pudo guardar</AlertTitle>
                <AlertDescription>{general}</AlertDescription>
              </Alert>
            )}

            <div className="grid gap-2">
              <Label htmlFor="email">Correo electrónico</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="usuario@claro.com"
                autoFocus={!isEdit}
                required={!isEdit}
                disabled={isEdit}
              />
              {isEdit && (
                <p className="text-xs text-muted-foreground">
                  El correo no se puede cambiar.
                </p>
              )}
              <FieldError msg={fieldErrors.email} />
            </div>

            {!isEdit && (
              <div className="grid gap-2">
                <Label htmlFor="password">Contraseña</Label>
                <PasswordInput
                  id="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Mínimo 10 caracteres"
                  autoComplete="new-password"
                  required
                />
                <FieldError msg={fieldErrors.password} />
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="first_name">Nombres</Label>
                <Input
                  id="first_name"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  required
                  aria-invalid={Boolean(fieldErrors.first_name)}
                />
                <FieldError msg={fieldErrors.first_name} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="last_name">Apellidos</Label>
                <Input
                  id="last_name"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  required
                  aria-invalid={Boolean(fieldErrors.last_name)}
                />
                <FieldError msg={fieldErrors.last_name} />
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="role">Rol</Label>
              <Select
                value={role}
                onValueChange={(v) => setRole(v as Role)}
                disabled={isSelf}
              >
                <SelectTrigger id="role" className="w-full">
                  <SelectValue>{(v: string) => ROLE_LABELS[v as Role]}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((r) => (
                    <SelectItem key={r} value={r}>
                      {ROLE_LABELS[r]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">{ROLE_HINT[role]}</p>
              {isSelf && (
                <p className="text-xs text-muted-foreground">
                  No puedes cambiar tu propio rol.
                </p>
              )}
              <FieldError msg={fieldErrors.role} />
            </div>

            {isEdit && (
              <div className="grid gap-2">
                <div className="flex items-center gap-2.5">
                  <Switch
                    id="is_active"
                    checked={isActive}
                    onCheckedChange={setIsActive}
                    disabled={isSelf}
                  />
                  <Label htmlFor="is_active">Cuenta activa</Label>
                </div>
                {isSelf && (
                  <p className="text-xs text-muted-foreground">
                    No puedes desactivar tu propia cuenta.
                  </p>
                )}
                <FieldError msg={fieldErrors.is_active} />
              </div>
            )}

            <div className="flex gap-2 pt-1">
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="animate-spin" />}
                {saving ? 'Guardando…' : 'Guardar'}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate('/usuarios')}
              >
                Cancelar
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
