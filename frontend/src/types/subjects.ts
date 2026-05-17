export type SubjectType = 'human' | 'pet'
export type SubjectStatus = 'active' | 'archived'
export type AliasSource = 'user' | 'ai' | 'system'

export type CareSubjectAlias = {
  id: string
  alias: string
  normalized_alias: string
  source: AliasSource | string
  status: SubjectStatus | string
  created_at: string
}

export type CareSubject = {
  id: string
  owner_user_id: string
  subject_type: SubjectType
  display_name: string
  legal_name: string | null
  relation_type: string | null
  species: string | null
  breed: string | null
  gender: string | null
  birth_date: string | null
  status: SubjectStatus | string
  notes: string | null
  created_at: string
  updated_at: string
  aliases: CareSubjectAlias[]
}

export type CreateSubjectInput = {
  subject_type: SubjectType
  display_name: string
  alias?: string | null
  legal_name?: string | null
  relation_type?: string | null
  species?: string | null
  breed?: string | null
  gender?: string | null
  birth_date?: string | null
  notes?: string | null
}

export type UpdateSubjectInput = Partial<Omit<CreateSubjectInput, 'subject_type' | 'alias'>> & {
  status?: SubjectStatus
}

export type CreateAliasInput = {
  alias: string
  source?: AliasSource
}

export type UpdateAliasInput = {
  alias?: string
  status?: SubjectStatus
}
