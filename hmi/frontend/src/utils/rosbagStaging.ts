/**
 * 管线暂存：收集 .bag 与原始 video / audio / text。
 *
 * 浏览器限制：
 * - `<input directory>` / 拖文件夹时，可通过 `webkitRelativePath` 或 FileSystemEntry
 *   拿到相对路径（如 `0804caiji/时间戳/output.bag`）。
 * - 仅多选文件时通常只有 basename；后端用内容哈希分目录避免同名覆盖。
 *
 * 上传时用 `fileForUpload` 把相对路径写进 `File.name`，后端
 * `collection_dir_from_filename` 才能取到时间戳父目录名做展示。
 */

export type SourceModality = 'bag' | 'video' | 'audio' | 'text'

const VIDEO_EXTS = ['.mp4', '.webm', '.mov', '.mkv', '.avi']
const AUDIO_EXTS = ['.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac', '.dat']
const TEXT_EXTS = ['.txt', '.json', '.md', '.csv']

export function isBagFileName(name: string): boolean {
  return name.toLowerCase().endsWith('.bag')
}

export function classifySourceFileName(name: string): SourceModality | null {
  const lower = name.toLowerCase().replace(/\\/g, '/')
  const base = lower.includes('/') ? lower.slice(lower.lastIndexOf('/') + 1) : lower
  if (base.endsWith('.bag')) return 'bag'
  if (VIDEO_EXTS.some((ext) => base.endsWith(ext))) return 'video'
  if (AUDIO_EXTS.some((ext) => base.endsWith(ext))) return 'audio'
  if (TEXT_EXTS.some((ext) => base.endsWith(ext))) return 'text'
  return null
}

export function isPipelineSourceFileName(name: string): boolean {
  return classifySourceFileName(name) != null
}

/** Unify Windows/Unix separators; strip leading slashes. */
export function normalizeRelativePath(path: string): string {
  return path.replace(/\\/g, '/').replace(/^\/+/, '')
}

export type StagedBagFile = {
  file: File
  /** 上传/列表展示路径；文件夹选择时含父目录。 */
  relativePath: string
  modality?: SourceModality
}

function fileRelativePath(file: File): string {
  const withWebkit = file as File & { webkitRelativePath?: string }
  const rel = (withWebkit.webkitRelativePath || '').trim()
  return normalizeRelativePath(rel || file.name)
}

export function toStagedBag(file: File, relativePath?: string): StagedBagFile {
  const rel = normalizeRelativePath(relativePath || fileRelativePath(file))
  return {
    file,
    relativePath: rel,
    modality: classifySourceFileName(rel) || undefined,
  }
}

/**
 * Build a File whose `name` carries the relative path for multipart upload.
 * FastAPI `UploadFile.filename` 会读到该路径字符串。
 */
export function fileForUpload(staged: StagedBagFile): File {
  const uploadName = staged.relativePath || staged.file.name
  if (uploadName === staged.file.name) return staged.file
  return new File([staged.file], uploadName, {
    type: staged.file.type,
    lastModified: staged.file.lastModified,
  })
}

/** `readEntries` 按批返回，需循环直到空数组。 */
function readAllDirectoryEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const all: FileSystemEntry[] = []
    const readBatch = () => {
      reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(all)
          return
        }
        all.push(...batch)
        readBatch()
      }, reject)
    }
    readBatch()
  })
}

function entryFile(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => {
    entry.file(resolve, reject)
  })
}

/** DFS：收集 bag + 原始媒体，relativePath = 自拖入根起的路径。 */
async function walkEntry(entry: FileSystemEntry, parentPath: string, out: StagedBagFile[]): Promise<void> {
  if (entry.isFile) {
    const file = await entryFile(entry as FileSystemFileEntry)
    if (!isPipelineSourceFileName(file.name)) return
    const rel = parentPath ? `${parentPath}/${file.name}` : file.name
    out.push(toStagedBag(file, rel))
    return
  }
  if (!entry.isDirectory) return
  const dir = entry as FileSystemDirectoryEntry
  const nextParent = parentPath ? `${parentPath}/${dir.name}` : dir.name
  const children = await readAllDirectoryEntries(dir.createReader())
  for (const child of children) {
    await walkEntry(child, nextParent, out)
  }
}

/** 拖放：优先走 FileSystemEntry（可进文件夹）；否则退回 files 列表。 */
export async function collectBagsFromDataTransfer(dt: DataTransfer): Promise<StagedBagFile[]> {
  return collectSourcesFromDataTransfer(dt)
}

export async function collectSourcesFromDataTransfer(dt: DataTransfer): Promise<StagedBagFile[]> {
  const out: StagedBagFile[] = []
  const items = dt.items
  if (items && items.length > 0) {
    const entries: FileSystemEntry[] = []
    for (let i = 0; i < items.length; i += 1) {
      const entry = items[i]?.webkitGetAsEntry?.()
      if (entry) entries.push(entry)
    }
    if (entries.length > 0) {
      for (const entry of entries) {
        await walkEntry(entry, '', out)
      }
      return out
    }
  }
  for (let i = 0; i < dt.files.length; i += 1) {
    const file = dt.files.item(i)
    if (file && isPipelineSourceFileName(file.name)) {
      out.push(toStagedBag(file))
    }
  }
  return out
}

/** `<input type=file directory>` / 普通多选：依赖 webkitRelativePath。 */
export function collectBagsFromFileList(fileList: FileList | File[]): StagedBagFile[] {
  return collectSourcesFromFileList(fileList)
}

export function collectSourcesFromFileList(fileList: FileList | File[]): StagedBagFile[] {
  const files = Array.from(fileList)
  return files.filter((f) => isPipelineSourceFileName(f.name)).map((f) => toStagedBag(f))
}

export function modalityLabel(m: SourceModality | undefined): string {
  switch (m) {
    case 'bag':
      return 'Rosbag'
    case 'video':
      return '视频'
    case 'audio':
      return '音频'
    case 'text':
      return '文本'
    default:
      return '文件'
  }
}
