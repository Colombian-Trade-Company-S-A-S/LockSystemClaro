// Definición central de rutas. Nuevas secciones se añaden aquí;
// las privadas cuelgan de <ProtectedRoute> (guarda de sesión) y del
// <DashboardLayout> (sidebar + chrome). El breadcrumb se define en `handle`.
//
// Autorización por rol: las rutas de escritura/gestión se agrupan bajo
// <RequireRole> (canOperate) y las de administración bajo <RequireRole> (isAdmin).
// La política real la impone el backend; esto solo evita navegar a lo que no aplica.

import { createBrowserRouter, Navigate } from 'react-router-dom'
import { ProtectedRoute } from '@/features/auth/components/ProtectedRoute'
import { RequireRole } from '@/features/auth/components/RequireRole'
import { canOperate, isAdmin } from '@/features/auth/permissions'
import { LoginPage } from '@/features/auth/pages/LoginPage'
import { ForgotPasswordPage } from '@/features/auth/pages/ForgotPasswordPage'
import { ResetPasswordPage } from '@/features/auth/pages/ResetPasswordPage'
import { TelevisoresPage } from '@/features/televisores/pages/TelevisoresPage'
import { TelevisorFormPage } from '@/features/televisores/pages/TelevisorFormPage'
import { TelevisorImportPage } from '@/features/televisores/pages/TelevisorImportPage'
import { TelevisorDetailPage } from '@/features/televisores/pages/TelevisorDetailPage'
import { TelevisorEstadoPage } from '@/features/televisores/pages/TelevisorEstadoPage'
import { JobsEnCursoPage } from '@/features/televisores/pages/JobsEnCursoPage'
import { TelevisorSincronizacionesPage } from '@/features/televisores/pages/TelevisorSincronizacionesPage'
import { TelevisorPincodesUsadosPage } from '@/features/televisores/pages/TelevisorPincodesUsadosPage'
import { EnrolarEstadoPage } from '@/features/televisores/pages/EnrolarEstadoPage'
import { SincronizacionesPage } from '@/features/sincronizaciones/pages/SincronizacionesPage'
import { HistorialPage } from '@/features/historial/pages/HistorialPage'
import { PincodesPage } from '@/features/pincodes/pages/PincodesPage'
import { UsuariosPage } from '@/features/usuarios/pages/UsuariosPage'
import { UsuarioFormPage } from '@/features/usuarios/pages/UsuarioFormPage'
import { SettingsPage } from '@/features/settings/pages/SettingsPage'
import { AuditoriaPage } from '@/features/auditoria/pages/AuditoriaPage'
import { DashboardLayout } from '@/shared/layout/DashboardLayout'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  // Recuperación de contraseña: públicas por definición (quien las usa no
  // puede iniciar sesión). La ruta de restablecimiento recibe el token del
  // correo en ?token= y lo valida contra el backend antes de pedir nada.
  { path: '/recuperar-password', element: <ForgotPasswordPage /> },
  { path: '/restablecer-password', element: <ResetPasswordPage /> },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <DashboardLayout />,
        children: [
          // --- Lectura: cualquier usuario autenticado (incluido Consulta) ---
          {
            // El dashboard es la página de inicio (raíz).
            // Carga diferida: recharts solo se descarga al entrar al dashboard.
            path: '/',
            lazy: async () => ({
              Component: (await import('@/features/dashboard/pages/DashboardPage'))
                .DashboardPage,
            }),
            handle: { breadcrumb: 'Dashboard' },
          },
          // Compatibilidad: la antigua URL /dashboard redirige a la raíz.
          { path: '/dashboard', element: <Navigate to="/" replace /> },
          {
            path: '/televisores',
            element: <TelevisoresPage />,
            handle: { breadcrumb: 'Televisores' },
          },
          {
            // Antes que '/televisores/:id' para que "en-curso" no se tome por
            // el id de un televisor.
            path: '/televisores/en-curso',
            element: <JobsEnCursoPage />,
            handle: { breadcrumb: 'Televisores / En curso' },
          },
          {
            path: '/televisores/:id',
            element: <TelevisorDetailPage />,
            handle: { breadcrumb: 'Televisores / Detalle' },
          },
          {
            path: '/televisores/:id/sincronizaciones',
            element: <TelevisorSincronizacionesPage />,
            handle: { breadcrumb: 'Televisores / Sincronizaciones' },
          },
          {
            path: '/televisores/:id/pincodes',
            element: <TelevisorPincodesUsadosPage />,
            handle: { breadcrumb: 'Televisores / Códigos Pin' },
          },
          {
            path: '/sincronizaciones',
            element: <SincronizacionesPage />,
            handle: { breadcrumb: 'Sincronizaciones' },
          },
          {
            path: '/pincodes',
            element: <PincodesPage />,
            handle: { breadcrumb: 'Códigos Pin' },
          },
          {
            // Auditoría de cambios en los datos del televisor (no de estado).
            path: '/historial',
            element: <HistorialPage />,
            handle: { breadcrumb: 'Historial' },
          },
          {
            // Carga diferida: recharts (la gráfica del modo agrupado) solo se
            // descarga al entrar a Reportes, igual que en el dashboard.
            path: '/reportes',
            lazy: async () => ({
              Component: (await import('@/features/reportes/pages/ReportesPage'))
                .ReportesPage,
            }),
            handle: { breadcrumb: 'Reportes' },
          },
          {
            path: '/configuracion',
            element: <SettingsPage />,
            handle: { breadcrumb: 'Configuración' },
          },

          // --- Gestión/escritura: Operador y Administrador ---
          {
            element: <RequireRole allow={canOperate} />,
            children: [
              {
                path: '/televisores/nuevo',
                element: <TelevisorFormPage />,
                handle: { breadcrumb: 'Televisores / Nuevo' },
              },
              {
                path: '/televisores/importar',
                element: <TelevisorImportPage />,
                handle: { breadcrumb: 'Televisores / Enrolar Televisores' },
              },
              {
                path: '/televisores/enrolar-estado',
                element: <EnrolarEstadoPage />,
                handle: { breadcrumb: 'Televisores / Enrolar Estado' },
              },
              {
                path: '/televisores/:id/editar',
                element: <TelevisorFormPage />,
                handle: { breadcrumb: 'Televisores / Editar' },
              },
              {
                path: '/televisores/:id/estado',
                element: <TelevisorEstadoPage />,
                handle: { breadcrumb: 'Televisores / Estado' },
              },
            ],
          },

          // --- Administración de usuarios: solo Administrador ---
          {
            element: <RequireRole allow={isAdmin} />,
            children: [
              {
                path: '/usuarios',
                element: <UsuariosPage />,
                handle: { breadcrumb: 'Usuarios' },
              },
              {
                path: '/usuarios/nuevo',
                element: <UsuarioFormPage />,
                handle: { breadcrumb: 'Usuarios / Nuevo' },
              },
              {
                path: '/usuarios/:id/editar',
                element: <UsuarioFormPage />,
                handle: { breadcrumb: 'Usuarios / Editar' },
              },
              {
                // Bitácora central (plan de trazabilidad). Solo Administrador:
                // decisión D-4 pendiente; el backend aplica la misma regla.
                path: '/auditoria',
                element: <AuditoriaPage />,
                handle: { breadcrumb: 'Auditoría' },
              },
            ],
          },
        ],
      },
    ],
  },
  // Cualquier ruta desconocida vuelve al inicio.
  { path: '*', element: <Navigate to="/" replace /> },
])
