import { createContext, useContext, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'

const STORAGE_KEY = 'hmi.dataTypeId'

type WorkspaceValue = {
  dataTypeId: string
}

const Ctx = createContext<WorkspaceValue>({ dataTypeId: 'oms_cabin' })

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

export function DataTypeWorkspaceProvider({ children }: { children: ReactNode }) {
  const { dataTypeId } = useParams()
  const id = (dataTypeId || readRememberedDataTypeId() || 'oms_cabin').trim()
  if (dataTypeId) rememberDataTypeId(dataTypeId)
  return <Ctx.Provider value={{ dataTypeId: id }}>{children}</Ctx.Provider>
}

export function useDataTypeWorkspace(): WorkspaceValue {
  return useContext(Ctx)
}
