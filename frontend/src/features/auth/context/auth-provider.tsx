// Provider que mantiene el estado de sesión y lo expone vía contexto.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { authApi } from '@/features/auth/api/auth.api'
import { AuthContext, type AuthContextValue } from '@/features/auth/context/auth-context'
import type { AuthStatus, User } from '@/features/auth/types'
import { actividad, avisoExpiracion, useInactividad } from '@/features/auth/useInactividad'
import { useVigilanciaSesion } from '@/features/auth/useVigilanciaSesion'
import { applyAccentKey } from '@/features/settings/accent'
import { config } from '@/lib/config'
import { alTerminarSesion, rearmarAvisoSesion } from '@/lib/http/session-events'
import { tokenStore } from '@/lib/http/tokens'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')
  // Ventana de inactividad. Arranca con el valor por defecto y se ajusta con lo
  // que diga el backend, que es la fuente de verdad (allí vive la variable de
  // entorno y allí se impone el corte).
  // `number` explícito: `config` es `as const`, así que el valor por defecto
  // se inferiría como el literal 15 y no admitiría el del backend.
  const [inactividadMin, setInactividadMin] = useState<number>(
    config.inactividadPorDefectoMin,
  )

  // Al montar: intenta restaurar la sesión a partir del refresh token guardado.
  useEffect(() => {
    let active = true
    authApi.restore().then((restored) => {
      if (!active) return
      setUser(restored)
      setStatus(restored ? 'authenticated' : 'unauthenticated')
      // Arranca con el acento guardado en la cuenta (fuente de verdad).
      if (restored) applyAccentKey(restored.accent)
    })
    return () => {
      active = false
    }
  }, [])

  // Configuración del backend. Si falla (backend caído, red), se queda con el
  // valor por defecto: preferimos una ventana razonable a no vigilar nada.
  useEffect(() => {
    let active = true
    authApi
      .config()
      .then((cfg) => {
        if (active && cfg.session_inactivity_minutes > 0) {
          setInactividadMin(cfg.session_inactivity_minutes)
        }
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const loggedIn = await authApi.login(email, password)
    // La ventana de inactividad empieza a contar desde el inicio de sesión.
    actividad.marcar()
    // Sesión nueva: vuelve a armarse el aviso de fin de sesión.
    rearmarAvisoSesion()
    setUser(loggedIn)
    setStatus('authenticated')
    // Al entrar, aplica el acento que el usuario dejó guardado en su cuenta.
    applyAccentKey(loggedIn.accent)
  }, [])

  const salir = useCallback((motivo?: 'inactividad') => {
    authApi.logout(motivo)
    actividad.limpiar()
    setUser(null)
    setStatus('unauthenticated')
  }, [])

  const logout = useCallback(() => salir(), [salir])

  /**
   * Cierre local, sin avisar al backend. Se usa cuando la sesión ya murió allí:
   * llamar a /logout con un token inválido solo daría otro 401.
   */
  const cerrarEnLocal = useCallback(() => {
    tokenStore.clear()
    actividad.limpiar()
    setUser(null)
    setStatus('unauthenticated')
  }, [])

  const refreshUser = useCallback(async () => {
    setUser(await authApi.me())
  }, [])

  // Cierre por inactividad: mismo camino que un logout normal, más el aviso que
  // la pantalla de login mostrará para que el usuario sepa qué pasó.
  const expirarPorInactividad = useCallback(() => {
    avisoExpiracion.poner(
      `Cerramos tu sesión tras ${inactividadMin} minutos sin actividad.`,
    )
    salir('inactividad')
  }, [salir, inactividadMin])

  useInactividad({
    minutos: inactividadMin,
    activo: status === 'authenticated',
    onExpirar: expirarPorInactividad,
  })

  // Sondeo periódico: detecta que la sesión murió en el servidor aunque el
  // usuario no esté tocando nada.
  useVigilanciaSesion(status === 'authenticated')

  // El cliente HTTP avisa cuando el servidor rechaza la sesión (cierre forzado
  // por un administrador, revocación, caducidad). Aquí se traduce en salir de
  // la aplicación al momento, sin esperar a que el usuario pulse algo ni a que
  // recargue la página.
  useEffect(
    () =>
      alTerminarSesion(() => {
        avisoExpiracion.poner(
          'Tu sesión se cerró: pudo cerrarla un administrador o caducar por seguridad.',
        )
        cerrarEnLocal()
      }),
    [cerrarEnLocal],
  )

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, login, logout, refreshUser, inactividadMin }),
    [user, status, login, logout, refreshUser, inactividadMin],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
