/**
 * Smoke asserts for pickBoundTaxonomyVersion (no vitest in frontend package).
 * Run from hmi/frontend:
 *   node --experimental-strip-types scripts/taxonomyTree.assert.mts
 */
import { pickBoundTaxonomyVersion } from '../src/utils/boundTaxonomy.ts'
import type { TaxonomyVersion } from '../src/api/types.ts'

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg)
}

function ver(partial: Partial<TaxonomyVersion> & Pick<TaxonomyVersion, 'id' | 'version_code' | 'status'>): TaxonomyVersion {
  return {
    published_at: null,
    created_by: null,
    source_import: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    node_count: 1,
    ...partial,
  }
}

const oms = ver({ id: 'oms', version_code: 'v2', status: 'published' })
const defect = ver({ id: 'ad', version_code: 'audio_defect', status: 'draft' })
const versions = [oms, defect]

assert(pickBoundTaxonomyVersion(versions, { taxonomyId: 'audio_defect' })?.id === 'ad', 'bind by taxonomy_id')
assert(
  pickBoundTaxonomyVersion(versions, { versionCode: 'missing', taxonomyId: 'audio_defect' })?.id === 'ad',
  'missing version_code falls through to taxonomy_id',
)
assert(
  pickBoundTaxonomyVersion(versions, { taxonomyId: 'oms_cabin' }) == null,
  'unknown taxonomy_id must not use published OMS on clip page',
)
assert(
  pickBoundTaxonomyVersion(versions, { versionCode: 'v2' })?.id === 'oms',
  'explicit version_code still wins',
)

console.log('taxonomyTree.assert.mts ok')
