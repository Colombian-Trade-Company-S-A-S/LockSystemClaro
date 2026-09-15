import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  CircleAlert,
  CircleCheck,
  CircleX,
  Download,
  FileSpreadsheet,
  Loader2,
  RefreshCw,
  UploadCloud,
} from 'lucide-react'
import { televisoresApi } from '@/features/televisores/api/televisores.api'
import type { ImportResult } from '@/features/televisores/types'
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

const COLUMNAS = [
  { columna: 'mac_address', ejemplo: 'B4:04:29:7E:3A:AA', obligatoria: true },
  { columna: 'serial_number', ejemplo: 'CLR23275', obligatoria: false },
  { columna: 'numero_credito', ejemplo: '1234567890', obligatoria: false, nota: 'solo dígitos' },
]

function Stat({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string
  value: number
  icon: React.ComponentType<{ className?: string }>
  tone: 'emerald' | 'primary' | 'destructive' | 'muted'
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-muted/30 p-4">
      <span
        className={cn(
          'flex size-10 items-center justify-center rounded-lg',
          tone === 'emerald' && 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
          tone === 'primary' && 'bg-primary/10 text-primary',
          tone === 'destructive' && 'bg-destructive/10 text-destructive',
          tone === 'muted' && 'bg-muted text-muted-foreground',
        )}
      >
        <Icon className="size-5" />
      </span>
      <div className="flex flex-col">
        <span className="text-2xl font-bold tabular-nums text-foreground">{value}</span>
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
    </div>
  )
}

export function TelevisorImportPage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState<string | null>(null)
  const [resultado, setResultado] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [subiendo, setSubiendo] = useState(false)
  const [descargando, setDescargando] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const file = inputRef.current?.files?.[0]
    if (!file) {
      setError('Selecciona un archivo.')
      return
    }
    setError(null)
    setResultado(null)
    setSubiendo(true)
    try {
      setResultado(await televisoresApi.import(file))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubiendo(false)
    }
  }

  async function descargarPlantilla() {
    setError(null)
    setDescargando(true)
    try {
      await televisoresApi.plantillaTelevisores()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setDescargando(false)
    }
  }

  const conError = resultado ? resultado.errores.length : 0

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-5">
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
            <UploadCloud className="size-5" />
          </span>
          <div className="flex flex-col gap-0.5">
            <h1 className="text-lg font-bold text-foreground">Enrolar televisores</h1>
            <p className="text-sm text-muted-foreground">
              Importación masiva desde Excel o CSV.
            </p>
          </div>
        </div>
      </div>

      {/* Resultado de la importación */}
      {resultado && (
        <Card>
          <CardHeader className="border-b pb-4">
            <CardTitle>Resultado de la importación</CardTitle>
            <CardDescription>Resumen del último archivo procesado.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Creados" value={resultado.creados} icon={CircleCheck} tone="emerald" />
              <Stat
                label="Actualizados"
                value={resultado.actualizados}
                icon={RefreshCw}
                tone="primary"
              />
              <Stat
                label="Con error"
                value={conError}
                icon={CircleX}
                tone={conError > 0 ? 'destructive' : 'muted'}
              />
            </div>

            {conError > 0 && (
              <div className="overflow-hidden rounded-lg border border-destructive/30 bg-destructive/5">
                <div className="flex items-center gap-2 border-b border-destructive/20 px-4 py-2 text-sm font-medium text-destructive">
                  <CircleAlert className="size-4" /> {conError} fila(s) con error
                </div>
                <div className="max-h-56 divide-y divide-destructive/10 overflow-auto">
                  {resultado.errores.map((e, i) => (
                    <div key={i} className="px-4 py-1.5 text-sm text-destructive/90">
                      {e}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Formulario de importación */}
      <Card>
        <CardHeader className="border-b pb-4">
          <CardTitle>Subir archivo</CardTitle>
          <CardDescription>
            Sube un archivo <b>Excel (.xlsx)</b> o <b>CSV</b>. Si el televisor ya existe
            (misma <b>MAC</b>) se actualiza; si no, se crea.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {/* Especificación de columnas */}
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Columna</TableHead>
                  <TableHead>Ejemplo</TableHead>
                  <TableHead>Obligatoria</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {COLUMNAS.map((c) => (
                  <TableRow key={c.columna}>
                    <TableCell className="font-mono text-foreground">{c.columna}</TableCell>
                    <TableCell className="text-muted-foreground">{c.ejemplo}</TableCell>
                    <TableCell>
                      {c.obligatoria ? (
                        <Badge
                          variant="outline"
                          className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                        >
                          Sí
                        </Badge>
                      ) : (
                        <span className="text-sm text-muted-foreground">
                          No{c.nota ? ` · ${c.nota}` : ''}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {error && (
            <Alert variant="destructive">
              <CircleAlert />
              <AlertTitle>No se pudo importar</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            {/* Zona de carga */}
            <label
              htmlFor="archivo"
              className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border bg-muted/20 px-6 py-8 text-center transition-colors hover:border-primary/50 hover:bg-muted/40"
            >
              <span className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                {fileName ? (
                  <FileSpreadsheet className="size-6" />
                ) : (
                  <UploadCloud className="size-6" />
                )}
              </span>
              {fileName ? (
                <>
                  <span className="text-sm font-medium text-foreground">{fileName}</span>
                  <span className="text-xs text-muted-foreground">
                    Haz clic para cambiar el archivo
                  </span>
                </>
              ) : (
                <>
                  <span className="text-sm font-medium text-foreground">
                    Haz clic para seleccionar un archivo
                  </span>
                  <span className="text-xs text-muted-foreground">
                    Excel (.xlsx) o CSV
                  </span>
                </>
              )}
              <input
                id="archivo"
                ref={inputRef}
                type="file"
                name="archivo"
                accept=".csv,.xlsx,.xls"
                className="sr-only"
                onChange={(e) => setFileName(e.target.files?.[0]?.name ?? null)}
              />
            </label>

            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={subiendo}>
                {subiendo ? (
                  <Loader2 className="animate-spin" data-icon="inline-start" />
                ) : (
                  <UploadCloud data-icon="inline-start" />
                )}
                {subiendo ? 'Importando…' : 'Importar'}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={descargarPlantilla}
                disabled={descargando}
              >
                {descargando ? (
                  <Loader2 className="animate-spin" data-icon="inline-start" />
                ) : (
                  <Download data-icon="inline-start" />
                )}
                {descargando ? 'Descargando…' : 'Descargar plantilla Excel'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
