import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import type { DataTypeRecipe } from '../api/types'

const STORAGE_KEY = 'hmi.dataTypeId'

type WorkspaceValue = {
  dataTypeId: string
  recipe: DataTypeRecipe | null
}

const Ctx = createContext<WorkspaceValue>({ dataTypeId: 'oms_cabin', recipe: null })

export function rememberDataTypeId(id: string): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, id)
  } catch {
    /* ignore */
  }
}

export function readRememberedDataTypeId(): string {
  try {
    return sessionStorage.getItem(STORAGE_KEY) || 'oms_cabin'
  } catch {
    return 'oms_cabin'
  }
}

export function DataTypeWorkspaceProvider({
  children,
  recipe: recipeProp,
}: {
  children: ReactNode
  recipe?: DataTypeRecipe | null
}) {
  const { dataTypeId } = useParams()
  const id = (dataTypeId || readRememberedDataTypeId() || 'oms_cabin').trim()
  if (dataTypeId) rememberDataTypeId(dataTypeId)
  return <Ctx.Provider value={{ dataTypeId: id, recipe: recipeProp ?? null }}>{children}</Ctx.Provider>
}

export function useDataTypeWorkspace(): WorkspaceValue {
  return useContext(Ctx)
}

/** Recipe from workspace layout, or fetched by remembered DataType (Explorer / 校核). */
export function useDataTypeRecipe(): DataTypeRecipe | null {
  const { dataTypeId, recipe } = useDataTypeWorkspace()
  const [loaded, setLoaded] = useState<DataTypeRecipe | null>(recipe)
  const id = dataTypeId || readRememberedDataTypeId()

  useEffect(() => {
    if (recipe) {
      setLoaded(recipe)
      return
    }
    let cancelled = false
    void api
      .getDataType(id)
      .then((rec) => {
        if (!cancelled) setLoaded(rec)
      })
      .catch(() => {
        if (!cancelled) setLoaded(null)
      })
    return () => {
      cancelled = true
    }
  }, [id, recipe])

  return loaded
}
