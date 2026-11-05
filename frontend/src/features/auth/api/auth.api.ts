// Capa de acceso a la API de autenticación. Encapsula los endpoints y el
// almacenamiento de tokens para que el resto de la app no conozca esos detalles.

import { config } from '@/lib/config'
import { apiFetch, refreshSession } from '@/lib/http/client'
import { tokenStore } from '@/lib/http/tokens'
import type { AuthTokens, User } from '@/features/auth/types'

/** Parámetros que define el backend (ver /api/config/). */
export interface AppConfig {
  session_inactivity_minutes: number
  password_reset_minutes: number
}

/** Respuesta de la validación del enlace de recuperación. */
export interface ResetTokenInfo {
  valido: true
  /** Correo parcialmente oculto (`da*****@gmail.com`), para confirmar la cuenta. */
  email: string
  expira_en: string
  /**
   * Segundos que le quedan al enlace, medidos por el servidor. La cuenta atrás
   * usa esto y no `expira_en`: comparar una fecha absoluta contra el reloj del
   * equipo daba el enlace por vencido si ese reloj iba adelantado.
   */
  segundos_restantes: number
}

/** Por qué un enlace de recuperación no sirve. */
export type ResetTokenMotivo = 'invalido' | 'vencido' | 'usado'

export const authApi = {
  /** Parámetros de configuración del backend. Público, no requiere sesión. */
  config: (): Promise<AppConfig> =>
    apiFetch<AppConfig>(config.endpoints.config, { auth: false }),

  /**
   * Inicia sesión con email + contraseña y devuelve el perfil del usuario.
   *
   * Puede fallar con 409: la cuenta ya tiene sesión en otro sitio
   * (`sesion_activa`) o este navegador ya tiene abierta otra cuenta
   * (`navegador_ocupado`). Al navegador lo identifica el servidor por IP +
   * navegador, sin nada que el cliente tenga que enviar.
   */
  async login(email: string, password: string): Promise<User> {
    const tokens = await apiFetch<AuthTokens>(config.endpoints.login, {
      method: 'POST',
      auth: false,
      body: JSON.stringify({ email, password }),
    })
    tokenStore.setAccess(tokens.access)
    tokenStore.setRefresh(tokens.refresh)
    return authApi.me()
  },

  /** Perfil del usuario autenticado. */
  me: (): Promise<User> => apiFetch<User>(config.endpoints.me),

  /**
   * Restaura la sesión al arrancar la app: si hay refresh token guardado,
   * obtiene un access nuevo y devuelve el perfil. Null si no hay sesión válida.
   */
  async restore(): Promise<User | null> {
    if (!tokenStore.getRefresh()) return null
    const ok = await refreshSession()
    if (!ok) return null
    try {
      return await authApi.me()
    } catch {
      tokenStore.clear()
      return null
    }
  },

  /**
   * Cierra la sesión. Best-effort: pide al backend revocar los tokens del
   * usuario (logout real server-side) y, pase lo que pase, los descarta
   * localmente. No lanza: el cierre local nunca debe fallar por la red.
   *
   * `motivo: 'inactividad'` cuando lo decide el navegador y no la persona: la
   * bitácora lo registra como sesión expirada en vez de cierre voluntario.
   */
  async logout(motivo?: 'inactividad'): Promise<void> {
    try {
      await apiFetch<void>(config.endpoints.logout, {
        method: 'POST',
        body: motivo ? JSON.stringify({ motivo }) : undefined,
      })
    } catch {
      // El servidor pudo estar caído o el token vencido: da igual, limpiamos.
    } finally {
      tokenStore.clear()
    }
  },

  // --- Recuperación de contraseña (sin sesión) -----------------------------

  /**
   * Pide el enlace de recuperación. El backend responde igual exista o no la
   * cuenta, así que esto nunca revela si un correo está registrado.
   */
  requestPasswordReset: (email: string): Promise<{ detail: string; expira_minutos: number }> =>
    apiFetch(config.endpoints.passwordReset, {
      method: 'POST',
      auth: false,
      body: JSON.stringify({ email }),
    }),

  /** Comprueba el token del enlace antes de mostrar el formulario. */
  validateResetToken: (token: string): Promise<ResetTokenInfo> =>
    apiFetch(
      `${config.endpoints.passwordResetValidate}?token=${encodeURIComponent(token)}`,
      { auth: false },
    ),

  /** Fija la nueva contraseña y consume el enlace. */
  confirmPasswordReset: (token: string, newPassword: string): Promise<{ detail: string }> =>
    apiFetch(config.endpoints.passwordResetConfirm, {
      method: 'POST',
      auth: false,
      body: JSON.stringify({ token, new_password: newPassword }),
    }),
}
