import type { ComponentType } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  ChevronsUpDown,
  History,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Monitor,
  RefreshCw,
  ScrollText,
  Settings2,
  Users,
} from 'lucide-react'
import { useAuth } from '@/features/auth/context/auth-context'
import { usePermissions } from '@/features/auth/usePermissions'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar'

interface NavItem {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
  /** Si es true, solo lo ve el Administrador. */
  adminOnly?: boolean
}

const navItems: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/televisores', label: 'Televisores', icon: Monitor },
  { to: '/sincronizaciones', label: 'Sincronizaciones', icon: RefreshCw },
  { to: '/historial', label: 'Historial', icon: History },
  { to: '/pincodes', label: 'Códigos Pin', icon: KeyRound },
  { to: '/usuarios', label: 'Usuarios', icon: Users, adminOnly: true },
  { to: '/auditoria', label: 'Auditoría', icon: ScrollText, adminOnly: true },
]

// Logo de marca.
function BrandLogo({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M3 7a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4c2.5.4 4 2.3 4 5 0 3-2.2 5-6 5-1.6 0-2.9-.4-3.9-1.2-.7.8-1.8 1.2-3.1 1.2H7a4 4 0 0 1-4-4V7Zm5 3a1.2 1.2 0 1 0 0 2.4A1.2 1.2 0 0 0 8 10Z" />
    </svg>
  )
}

export function AppSidebar() {
  const { user, logout } = useAuth()
  const { isAdmin } = usePermissions()
  const { isMobile } = useSidebar()
  const { pathname } = useLocation()

  const nombre = user?.full_name?.trim() || user?.first_name || user?.email || ''
  const inicial = (nombre[0] ?? '?').toUpperCase()
  const items = navItems.filter((item) => !item.adminOnly || isAdmin)
  const isActive = (to: string) =>
    to === '/' ? pathname === '/' : pathname.startsWith(to)

  return (
    <Sidebar collapsible="icon">
      {/* Encabezado: logo */}
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<NavLink to="/" />}>
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-gradient-to-br from-whale-light to-whale-dark text-white shadow-sm shadow-whale/30">
                <BrandLogo className="size-5" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-semibold">Locking System</span>
                <span className="truncate text-xs text-muted-foreground">
                  Panel de gestión
                </span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      {/* Navegación */}
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Gestión</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton
                    isActive={isActive(item.to)}
                    tooltip={item.label}
                    render={<NavLink to={item.to} />}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      {/* Usuario + dropdown */}
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <SidebarMenuButton
                    size="lg"
                    className="data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground"
                  >
                    <Avatar className="size-8 rounded-lg">
                      <AvatarFallback className="rounded-lg bg-gradient-to-br from-whale-light to-whale-dark text-white">
                        {inicial}
                      </AvatarFallback>
                    </Avatar>
                    <div className="grid flex-1 text-left text-sm leading-tight">
                      <span className="truncate font-semibold">{nombre}</span>
                      {user?.role_display && (
                        <span className="truncate text-xs text-muted-foreground">
                          {user.role_display}
                        </span>
                      )}
                    </div>
                    <ChevronsUpDown className="ml-auto size-4" />
                  </SidebarMenuButton>
                }
              />
              <DropdownMenuContent
                className="w-56 rounded-lg"
                side={isMobile ? 'bottom' : 'right'}
                align="end"
                sideOffset={4}
              >
                <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                  <Avatar className="size-8 rounded-lg">
                    <AvatarFallback className="rounded-lg bg-gradient-to-br from-whale-light to-whale-dark text-white">
                      {inicial}
                    </AvatarFallback>
                  </Avatar>
                  <div className="grid flex-1 leading-tight">
                    <span className="truncate font-semibold">{nombre}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      {user?.email}
                    </span>
                  </div>
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem render={<NavLink to="/configuracion" />}>
                  <Settings2 />
                  Configuración
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={logout}>
                  <LogOut />
                  Cerrar sesión
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}
