// Paleta de comandos global (Ctrl/⌘ + K).
//
// Es un buscador-navegador rápido, autocontenido: no toca el backend salvo para
// buscar televisores por serial/MAC/crédito reutilizando el endpoint de lista.
// Muestra secciones (Ir a / Acciones) filtradas por rol y, si hay texto, los
// televisores que coinciden. Enter navega; ↑/↓ mueven; Esc cierra.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  CornerDownLeft,
  FileSpreadsheet,
  KeyRound,
  LayoutDashboard,
  Loader2,
  Monitor,
  Plus,
  RefreshCw,
  ScrollText,
  Search,
  Settings2,
  Upload,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { usePermissions } from '@/features/auth/usePermissions'
import { televisoresApi } from '@/features/televisores/api/televisores.api'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

// --- Utilidades -----------------------------------------------------------

/** Normaliza para comparar sin tildes ni mayúsculas. */
function norm(s: string): string {
  return s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .trim()
}

/** Un elemento seleccionable de la paleta. */
interface CommandItem {
  id: string
  label: string
  sublabel?: string
  icon: LucideIcon
  keywords?: string
  run: () => void
}

interface CommandGroup {
  heading: string
  items: CommandItem[]
}

// --- Componente -----------------------------------------------------------

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const navigate = useNavigate()
  const { isAdmin, canOperate } = usePermissions()
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [active, setActive] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)

  // Al cerrar se limpia el texto para volver a abrir "en limpio".
  useEffect(() => {
    if (!open) setQuery('')
  }, [open])

  // Debounce del texto para no pegarle a la API en cada tecla.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 200)
    return () => clearTimeout(t)
  }, [query])

  const q = norm(query)

  // Busca televisores solo si hay algo escrito (mín. 2 caracteres) y está abierta.
  const tvSearch = useQuery({
    queryKey: ['command-palette-tv', debounced],
    queryFn: () => televisoresApi.list(debounced, 1),
    enabled: open && norm(debounced).length >= 2,
    placeholderData: keepPreviousData,
  })

  const go = (to: string) => {
    onOpenChange(false)
    navigate(to)
  }

  // Acciones estáticas (navegación), filtradas por rol.
  const navItems = useMemo<CommandItem[]>(() => {
    const base: (CommandItem & { show: boolean })[] = [
      {
        id: 'nav-dashboard',
        label: 'Dashboard',
        icon: LayoutDashboard,
        keywords: 'inicio home reportes graficas',
        show: true,
        run: () => go('/'),
      },
      {
        id: 'nav-televisores',
        label: 'Televisores',
        icon: Monitor,
        keywords: 'tv equipos dispositivos',
        show: true,
        run: () => go('/televisores'),
      },
      {
        id: 'nav-sincronizaciones',
        label: 'Sincronizaciones',
        icon: RefreshCw,
        keywords: 'sync historial',
        show: true,
        run: () => go('/sincronizaciones'),
      },
      {
        id: 'nav-pincodes',
        label: 'Códigos Pin',
        icon: KeyRound,
        keywords: 'pin passcode',
        show: true,
        run: () => go('/pincodes'),
      },
      {
        id: 'nav-reportes',
        label: 'Reportes',
        icon: FileSpreadsheet,
        keywords: 'constructor reportes exportar excel consultas',
        show: true,
        run: () => go('/reportes'),
      },
      {
        id: 'nav-usuarios',
        label: 'Usuarios',
        icon: Users,
        keywords: 'cuentas roles administrar',
        show: isAdmin,
        run: () => go('/usuarios'),
      },
      {
        id: 'nav-auditoria',
        label: 'Auditoría',
        icon: ScrollText,
        keywords: 'bitacora trazabilidad eventos quien accesos log',
        show: isAdmin,
        run: () => go('/auditoria'),
      },
      {
        id: 'nav-configuracion',
        label: 'Configuración',
        icon: Settings2,
        keywords: 'ajustes perfil contraseña api keys apariencia',
        show: true,
        run: () => go('/configuracion'),
      },
    ]
    return base.filter((i) => i.show)
  }, [isAdmin]) // eslint-disable-line react-hooks/exhaustive-deps

  // Acciones rápidas (escritura), solo para quien puede operar.
  const actionItems = useMemo<CommandItem[]>(() => {
    if (!canOperate) return []
    return [
      {
        id: 'act-nuevo-tv',
        label: 'Nuevo televisor',
        icon: Plus,
        keywords: 'crear agregar registrar televisor',
        run: () => go('/televisores/nuevo'),
      },
      {
        id: 'act-enrolar-tv',
        label: 'Enrolar televisores',
        icon: Upload,
        keywords: 'importar carga masiva excel',
        run: () => go('/televisores/importar'),
      },
      {
        id: 'act-enrolar-estado',
        label: 'Enrolar estado',
        icon: RefreshCw,
        keywords: 'estado masivo bloquear inhabilitar excel',
        run: () => go('/televisores/enrolar-estado'),
      },
    ]
  }, [canOperate]) // eslint-disable-line react-hooks/exhaustive-deps

  // Televisores que coinciden con el texto.
  const tvItems = useMemo<CommandItem[]>(() => {
    if (norm(debounced).length < 2) return []
    return (tvSearch.data?.results ?? []).slice(0, 6).map((tv) => ({
      id: `tv-${tv.id}`,
      label: tv.serial_number || tv.mac_address,
      sublabel: [tv.mac_address, tv.numero_credito && `Crédito ${tv.numero_credito}`]
        .filter(Boolean)
        .join(' · '),
      icon: Monitor,
      run: () => go(`/televisores/${tv.id}`),
    }))
  }, [tvSearch.data, debounced]) // eslint-disable-line react-hooks/exhaustive-deps

  // Filtra las secciones estáticas por el texto (nombre + palabras clave).
  const groups = useMemo<CommandGroup[]>(() => {
    const match = (i: CommandItem) =>
      !q || norm(`${i.label} ${i.keywords ?? ''}`).includes(q)
    const g: CommandGroup[] = [
      { heading: 'Ir a', items: navItems.filter(match) },
      { heading: 'Acciones', items: actionItems.filter(match) },
    ]
    if (tvItems.length > 0) g.push({ heading: 'Televisores', items: tvItems })
    return g.filter((s) => s.items.length > 0)
  }, [q, navItems, actionItems, tvItems])

  // Lista plana (en orden de render) para navegar con el teclado.
  const flat = useMemo(() => groups.flatMap((s) => s.items), [groups])

  // Al cambiar los resultados, la selección vuelve al primero.
  useEffect(() => {
    setActive(0)
  }, [debounced, q, flat.length])

  // Mantiene visible el elemento activo.
  useEffect(() => {
    listRef.current
      ?.querySelector(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [active])

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, Math.max(flat.length - 1, 0)))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      flat[active]?.run()
    }
  }

  const buscandoTv = tvSearch.isFetching && norm(debounced).length >= 2
  const sinResultados = flat.length === 0 && !buscandoTv

  // Índice global corrido para poder resaltar/activar a través de las secciones.
  let runningIndex = -1

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="top-[15%] max-w-lg translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-lg"
      >
        <DialogTitle className="sr-only">Buscar</DialogTitle>

        {/* Caja de búsqueda */}
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Buscar televisor o ir a una sección…"
            className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          {buscandoTv && (
            <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
          )}
        </div>

        {/* Resultados */}
        <div ref={listRef} className="max-h-80 overflow-y-auto p-2">
          {sinResultados ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              Sin resultados para «{query}».
            </div>
          ) : (
            groups.map((group) => (
              <div key={group.heading} className="mb-1">
                <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                  {group.heading}
                </div>
                {group.items.map((item) => {
                  runningIndex += 1
                  const index = runningIndex
                  const isActive = index === active
                  const Icon = item.icon
                  return (
                    <button
                      key={item.id}
                      type="button"
                      data-index={index}
                      onClick={item.run}
                      onMouseMove={() => setActive(index)}
                      className={cn(
                        'flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm outline-none',
                        isActive
                          ? 'bg-muted text-foreground'
                          : 'text-foreground/90',
                      )}
                    >
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{item.label}</span>
                        {item.sublabel && (
                          <span className="block truncate text-xs text-muted-foreground">
                            {item.sublabel}
                          </span>
                        )}
                      </span>
                      {isActive && (
                        <CornerDownLeft className="size-3.5 shrink-0 text-muted-foreground" />
                      )}
                    </button>
                  )
                })}
              </div>
            ))
          )}
        </div>

        {/* Pie con ayudas de teclado */}
        <div className="flex items-center gap-3 border-t px-3 py-2 text-xs text-muted-foreground">
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd>
          <span>navegar</span>
          <Kbd>↵</Kbd>
          <span>abrir</span>
          <Kbd>esc</Kbd>
          <span>cerrar</span>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border bg-muted px-1 font-sans text-[10px] font-medium">
      {children}
    </kbd>
  )
}
