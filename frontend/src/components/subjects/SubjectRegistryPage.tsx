import { Cat, Dog, HeartPulse, Loader2, Pencil, Plus, RefreshCw, Save, UserRound, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import {
  createSubject,
  createSubjectAlias,
  listSubjects,
  updateSubject,
  updateSubjectAlias,
} from '@/api/memomedAgentClient'
import type { CareSubject, CreateSubjectInput, SubjectType, UpdateSubjectInput } from '@/types/subjects'

type SubjectDraft = {
  display_name: string
  legal_name: string
  relation_type: string
  species: string
  breed: string
  gender: string
  birth_date: string
  notes: string
}

const emptyDraft: SubjectDraft = {
  display_name: '',
  legal_name: '',
  relation_type: '',
  species: '',
  breed: '',
  gender: '',
  birth_date: '',
  notes: '',
}

const relationOptions = [
  { label: '自己', value: 'self' },
  { label: '妈妈', value: 'mother' },
  { label: '爸爸', value: 'father' },
  { label: '伴侣', value: 'spouse' },
  { label: '孩子', value: 'child' },
  { label: '宠物', value: 'pet' },
  { label: '其他', value: 'other' },
]

const speciesOptions = [
  { label: '猫', value: 'cat' },
  { label: '狗', value: 'dog' },
  { label: '其他', value: 'other' },
]

export function SubjectRegistryPage() {
  const [subjects, setSubjects] = useState<CareSubject[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [createType, setCreateType] = useState<SubjectType>('human')
  const [createName, setCreateName] = useState('')
  const [createLegalName, setCreateLegalName] = useState('')
  const [createAliasText, setCreateAliasText] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState<SubjectDraft>(emptyDraft)
  const [aliasDrafts, setAliasDrafts] = useState<Record<string, string>>({})

  useEffect(() => {
    void load()
  }, [])

  async function load() {
    setIsLoading(true)
    setError(null)
    try {
      setSubjects(await listSubjects())
    } catch (err) {
      setError(readableError(err, '成员列表加载失败'))
    } finally {
      setIsLoading(false)
    }
  }

  async function handleCreateSubject() {
    const displayName = createName.trim()
    if (!displayName) return
    setIsSaving(true)
    setError(null)
    try {
      const input: CreateSubjectInput = {
        subject_type: createType,
        display_name: displayName,
        alias: createAliasText.trim() || displayName,
        legal_name: nullableText(createLegalName),
        relation_type: createType === 'pet' ? 'pet' : null,
        species: createType === 'pet' ? 'cat' : null,
      }
      const created = await createSubject(input)
      setSubjects((current) => sortSubjects([...current, created]))
      setCreateName('')
      setCreateLegalName('')
      setCreateAliasText('')
    } catch (err) {
      setError(readableError(err, '新增失败'))
    } finally {
      setIsSaving(false)
    }
  }

  function startEdit(subject: CareSubject) {
    setEditingId(subject.id)
    setDraft({
      display_name: subject.display_name,
      legal_name: subject.legal_name ?? '',
      relation_type: subject.relation_type ?? '',
      species: subject.species ?? '',
      breed: subject.breed ?? '',
      gender: subject.gender ?? '',
      birth_date: subject.birth_date ?? '',
      notes: subject.notes ?? '',
    })
  }

  async function saveSubject(subject: CareSubject, patch?: UpdateSubjectInput) {
    setIsSaving(true)
    setError(null)
    try {
      const input =
        patch ??
        ({
          display_name: draft.display_name.trim(),
          legal_name: nullableText(draft.legal_name),
          relation_type: nullableText(draft.relation_type),
          species: subject.subject_type === 'pet' ? nullableText(draft.species) : null,
          breed: subject.subject_type === 'pet' ? nullableText(draft.breed) : null,
          gender: nullableText(draft.gender),
          birth_date: nullableText(draft.birth_date),
          notes: nullableText(draft.notes),
        } satisfies UpdateSubjectInput)
      const updated = await updateSubject(subject.id, input)
      replaceSubject(updated)
      setEditingId(null)
    } catch (err) {
      setError(readableError(err, '保存失败'))
    } finally {
      setIsSaving(false)
    }
  }

  async function addAlias(subject: CareSubject) {
    const alias = aliasDrafts[subject.id]?.trim()
    if (!alias) return
    setIsSaving(true)
    setError(null)
    try {
      const updated = await createSubjectAlias(subject.id, { alias, source: 'user' })
      replaceSubject(updated)
      setAliasDrafts((current) => ({ ...current, [subject.id]: '' }))
    } catch (err) {
      setError(readableError(err, '别名保存失败'))
    } finally {
      setIsSaving(false)
    }
  }

  async function archiveAlias(subject: CareSubject, aliasId: string) {
    setIsSaving(true)
    setError(null)
    try {
      const updated = await updateSubjectAlias(subject.id, aliasId, { status: 'archived' })
      replaceSubject(updated)
    } catch (err) {
      setError(readableError(err, '别名归档失败'))
    } finally {
      setIsSaving(false)
    }
  }

  function replaceSubject(updated: CareSubject) {
    setSubjects((current) => sortSubjects(current.map((subject) => (subject.id === updated.id ? updated : subject))))
  }

  const humans = subjects.filter((subject) => subject.subject_type === 'human')
  const pets = subjects.filter((subject) => subject.subject_type === 'pet')

  return (
    <section className="relative overflow-hidden rounded-[2rem] border border-white/70 bg-[#fffaf0]/80 p-5 shadow-2xl shadow-stone-300/40 backdrop-blur">
      <div className="pointer-events-none absolute right-0 top-0 h-56 w-56 rounded-full bg-lime-200/50 blur-3xl" />
      <div className="pointer-events-none absolute bottom-6 left-6 h-32 w-32 rounded-full bg-teal-200/40 blur-2xl" />

      <div className="relative flex flex-col gap-5">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.28em] text-teal-800">Subject Registry</p>
            <h2 className="mt-2 text-3xl font-black tracking-tight text-stone-950">家庭成员与宠物档案</h2>
            <p className="mt-2 max-w-2xl text-sm text-stone-600">
              这里是 Agent 识别“这次要管理谁”的事实源。AI 判断不确定时，优先让你在这里修正名字和别名。
            </p>
          </div>
          <button
            onClick={() => void load()}
            disabled={isLoading}
            className="inline-flex items-center justify-center gap-2 rounded-2xl border border-stone-200 bg-white px-4 py-3 text-sm font-bold text-stone-800 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md disabled:opacity-60"
          >
            {isLoading ? <Loader2 className="animate-spin" size={16} /> : <RefreshCw size={16} />}
            刷新
          </button>
        </div>

        <div className="grid gap-3 rounded-3xl border border-stone-200 bg-white/80 p-3 md:grid-cols-[12rem_1fr_1fr] xl:grid-cols-[12rem_1fr_1fr_1fr_auto]">
          <div className="grid grid-cols-2 gap-2 rounded-2xl bg-stone-100 p-1">
            <button
              onClick={() => setCreateType('human')}
              className={`rounded-xl px-3 py-2 text-sm font-bold transition ${createType === 'human' ? 'bg-stone-950 text-white' : 'text-stone-600 hover:bg-white'}`}
            >
              人物
            </button>
            <button
              onClick={() => setCreateType('pet')}
              className={`rounded-xl px-3 py-2 text-sm font-bold transition ${createType === 'pet' ? 'bg-teal-700 text-white' : 'text-stone-600 hover:bg-white'}`}
            >
              宠物
            </button>
          </div>
          <input
            value={createName}
            onChange={(event) => setCreateName(event.target.value)}
            placeholder={createType === 'pet' ? '宠物展示名，如：小橘' : '成员展示名，如：妈妈'}
            className="rounded-2xl border border-stone-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-teal-500"
          />
          <input
            value={createLegalName}
            onChange={(event) => setCreateLegalName(event.target.value)}
            placeholder={createType === 'pet' ? '登记名/正式名，可不填' : '法定名字/真实姓名，可不填'}
            className="rounded-2xl border border-stone-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-teal-500"
          />
          <input
            value={createAliasText}
            onChange={(event) => setCreateAliasText(event.target.value)}
            placeholder="默认别名，可不填"
            className="rounded-2xl border border-stone-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-teal-500"
          />
          <button
            onClick={() => void handleCreateSubject()}
            disabled={isSaving || !createName.trim()}
            className="inline-flex items-center justify-center gap-2 rounded-2xl bg-stone-950 px-5 py-3 text-sm font-bold text-white transition hover:bg-stone-800 disabled:bg-stone-300"
          >
            <Plus size={16} />
            新增
          </button>
        </div>

        {error ? <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

        {isLoading ? (
          <div className="flex min-h-60 items-center justify-center rounded-3xl border border-dashed border-stone-300 bg-white/60 text-stone-500">
            <Loader2 className="mr-2 animate-spin" size={18} />
            正在读取成员档案...
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-2">
            <SubjectColumn
              title="人类成员"
              icon={<UserRound size={20} />}
              emptyText="还没有人类成员。先新增“自己”或“妈妈”都可以。"
              subjects={humans}
              editingId={editingId}
              draft={draft}
              aliasDrafts={aliasDrafts}
              isSaving={isSaving}
              onDraftChange={setDraft}
              onAliasDraftChange={setAliasDrafts}
              onEdit={startEdit}
              onCancelEdit={() => setEditingId(null)}
              onSave={saveSubject}
              onArchive={(subject) => void saveSubject(subject, { status: 'archived' })}
              onAddAlias={addAlias}
              onArchiveAlias={archiveAlias}
            />
            <SubjectColumn
              title="宠物"
              icon={<HeartPulse size={20} />}
              emptyText="还没有宠物档案。你可以先新增猫咪或狗狗。"
              subjects={pets}
              editingId={editingId}
              draft={draft}
              aliasDrafts={aliasDrafts}
              isSaving={isSaving}
              onDraftChange={setDraft}
              onAliasDraftChange={setAliasDrafts}
              onEdit={startEdit}
              onCancelEdit={() => setEditingId(null)}
              onSave={saveSubject}
              onArchive={(subject) => void saveSubject(subject, { status: 'archived' })}
              onAddAlias={addAlias}
              onArchiveAlias={archiveAlias}
            />
          </div>
        )}
      </div>
    </section>
  )
}

function SubjectColumn({
  title,
  icon,
  emptyText,
  subjects,
  editingId,
  draft,
  aliasDrafts,
  isSaving,
  onDraftChange,
  onAliasDraftChange,
  onEdit,
  onCancelEdit,
  onSave,
  onArchive,
  onAddAlias,
  onArchiveAlias,
}: {
  title: string
  icon: ReactNode
  emptyText: string
  subjects: CareSubject[]
  editingId: string | null
  draft: SubjectDraft
  aliasDrafts: Record<string, string>
  isSaving: boolean
  onDraftChange: (draft: SubjectDraft) => void
  onAliasDraftChange: (drafts: Record<string, string>) => void
  onEdit: (subject: CareSubject) => void
  onCancelEdit: () => void
  onSave: (subject: CareSubject) => Promise<void>
  onArchive: (subject: CareSubject) => void
  onAddAlias: (subject: CareSubject) => Promise<void>
  onArchiveAlias: (subject: CareSubject, aliasId: string) => Promise<void>
}) {
  return (
    <div className="rounded-3xl border border-stone-200 bg-white/70 p-4">
      <div className="mb-4 flex items-center gap-2 text-stone-900">
        <span className="rounded-2xl bg-teal-50 p-2 text-teal-700">{icon}</span>
        <h3 className="text-lg font-black">{title}</h3>
        <span className="ml-auto rounded-full bg-stone-100 px-3 py-1 text-xs font-bold text-stone-500">{subjects.length}</span>
      </div>
      {subjects.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-stone-300 bg-stone-50 px-4 py-8 text-center text-sm text-stone-500">{emptyText}</p>
      ) : (
        <div className="space-y-4">
          {subjects.map((subject) => (
            <SubjectCard
              key={subject.id}
              subject={subject}
              isEditing={editingId === subject.id}
              draft={draft}
              aliasValue={aliasDrafts[subject.id] ?? ''}
              isSaving={isSaving}
              onDraftChange={onDraftChange}
              onAliasChange={(value) => onAliasDraftChange({ ...aliasDrafts, [subject.id]: value })}
              onEdit={() => onEdit(subject)}
              onCancelEdit={onCancelEdit}
              onSave={() => onSave(subject)}
              onArchive={() => onArchive(subject)}
              onAddAlias={() => onAddAlias(subject)}
              onArchiveAlias={(aliasId) => onArchiveAlias(subject, aliasId)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SubjectCard({
  subject,
  isEditing,
  draft,
  aliasValue,
  isSaving,
  onDraftChange,
  onAliasChange,
  onEdit,
  onCancelEdit,
  onSave,
  onArchive,
  onAddAlias,
  onArchiveAlias,
}: {
  subject: CareSubject
  isEditing: boolean
  draft: SubjectDraft
  aliasValue: string
  isSaving: boolean
  onDraftChange: (draft: SubjectDraft) => void
  onAliasChange: (value: string) => void
  onEdit: () => void
  onCancelEdit: () => void
  onSave: () => Promise<void>
  onArchive: () => void
  onAddAlias: () => Promise<void>
  onArchiveAlias: (aliasId: string) => Promise<void>
}) {
  const activeAliases = subject.aliases.filter((alias) => alias.status === 'active')
  const Icon = subject.subject_type === 'pet' ? (subject.species === 'dog' ? Dog : Cat) : UserRound

  return (
    <article className={`rounded-3xl border p-4 transition ${subject.status === 'archived' ? 'border-stone-200 bg-stone-100/70 opacity-70' : 'border-stone-200 bg-white shadow-sm'}`}>
      <div className="flex items-start gap-3">
        <div className="rounded-2xl bg-lime-100 p-3 text-teal-800">
          <Icon size={20} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-xl font-black text-stone-950">{subject.display_name}</h4>
            <span className="rounded-full bg-stone-100 px-2.5 py-1 text-xs font-bold text-stone-500">
              {subject.subject_type === 'pet' ? petTypeLabel(subject.species) : relationLabel(subject.relation_type)}
            </span>
            {subject.status === 'archived' ? <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-bold text-amber-700">已归档</span> : null}
          </div>
          <p className="mt-1 text-xs text-stone-500">ID: {subject.id}</p>
        </div>
        <button
          onClick={isEditing ? onCancelEdit : onEdit}
          className="rounded-xl border border-stone-200 p-2 text-stone-600 transition hover:bg-stone-50"
          title={isEditing ? '取消编辑' : '编辑'}
        >
          {isEditing ? <X size={16} /> : <Pencil size={16} />}
        </button>
      </div>

      {isEditing ? (
        <div className="mt-4 rounded-3xl border border-teal-100 bg-teal-50/50 p-3">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-black uppercase tracking-[0.18em] text-teal-700">编辑主体资料</p>
            <div className="flex gap-2">
              <button
                onClick={() => void onSave()}
                disabled={isSaving || !draft.display_name.trim()}
                className="inline-flex items-center gap-2 rounded-2xl bg-teal-700 px-4 py-2 text-sm font-bold text-white transition hover:bg-teal-600 disabled:bg-stone-300"
              >
                <Save size={15} />
                保存
              </button>
              <button onClick={onCancelEdit} disabled={isSaving} className="rounded-2xl border border-stone-200 bg-white px-4 py-2 text-sm font-bold text-stone-600 transition hover:bg-stone-50">
                取消
              </button>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <LabeledInput label="展示名" value={draft.display_name} onChange={(value) => onDraftChange({ ...draft, display_name: value })} />
            <LabeledInput
              label={subject.subject_type === 'pet' ? '登记名/正式名' : '法定名字/真实姓名'}
              value={draft.legal_name}
              onChange={(value) => onDraftChange({ ...draft, legal_name: value })}
            />
            <LabeledSelect
              label="关系"
              value={draft.relation_type}
              options={relationOptions}
              onChange={(value) => onDraftChange({ ...draft, relation_type: value })}
            />
            {subject.subject_type === 'pet' ? (
              <LabeledSelect
                label="物种"
                value={draft.species}
                options={speciesOptions}
                onChange={(value) => onDraftChange({ ...draft, species: value })}
              />
            ) : (
              <LabeledInput label="性别" value={draft.gender} onChange={(value) => onDraftChange({ ...draft, gender: value })} />
            )}
            {subject.subject_type === 'pet' ? (
              <>
                <LabeledInput label="品种" value={draft.breed} onChange={(value) => onDraftChange({ ...draft, breed: value })} />
                <LabeledInput label="性别" value={draft.gender} onChange={(value) => onDraftChange({ ...draft, gender: value })} />
              </>
            ) : null}
            <LabeledInput label="出生日期" type="date" value={draft.birth_date} onChange={(value) => onDraftChange({ ...draft, birth_date: value })} />
            <label className="grid gap-1 text-xs font-bold text-stone-500 md:col-span-2">
              备注
              <textarea
                value={draft.notes}
                onChange={(event) => onDraftChange({ ...draft, notes: event.target.value })}
                className="min-h-20 rounded-2xl border border-stone-200 bg-white px-3 py-2 text-sm font-normal text-stone-900 outline-none focus:border-teal-500"
              />
            </label>
          </div>
          <button onClick={onArchive} disabled={isSaving} className="mt-3 rounded-2xl border border-stone-200 bg-white px-4 py-2.5 text-sm font-bold text-stone-600 transition hover:bg-stone-50">
            归档主体
          </button>
        </div>
      ) : (
        <div className="mt-4 grid gap-2 rounded-3xl border border-stone-100 bg-stone-50/80 p-3 sm:grid-cols-2">
          <FieldBadge label="主体类型" value={subjectTypeLabel(subject.subject_type)} />
          <FieldBadge label={subject.subject_type === 'pet' ? '登记名/正式名' : '法定名字/真实姓名'} value={subject.legal_name} />
          <FieldBadge label="关系" value={relationLabel(subject.relation_type)} />
          <FieldBadge label="状态" value={subject.status === 'active' ? 'active（使用中）' : 'archived（已归档）'} />
          <FieldBadge label="物种" value={subject.subject_type === 'pet' ? petTypeLabel(subject.species) : null} />
          <FieldBadge label="品种" value={subject.breed} />
          <FieldBadge label="性别" value={subject.gender} />
          <FieldBadge label="出生日期" value={subject.birth_date} />
          <FieldBadge label="创建时间" value={formatDateTime(subject.created_at)} />
          <FieldBadge label="更新时间" value={formatDateTime(subject.updated_at)} />
          <FieldBadge label="备注" value={subject.notes} wide />
        </div>
      )}

      <div className="mt-4">
        <p className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-stone-400">Aliases</p>
        <div className="flex flex-wrap gap-2">
          {activeAliases.length > 0 ? (
            activeAliases.map((alias) => (
              <span key={alias.id} className="inline-flex items-center gap-1 rounded-2xl bg-stone-100 px-3 py-1.5 text-xs font-bold text-stone-700">
                <span>{alias.alias}</span>
                <span className="font-medium text-stone-400">norm: {alias.normalized_alias}</span>
                <span className="font-medium text-stone-400">{alias.source}/{alias.status}</span>
                <button onClick={() => void onArchiveAlias(alias.id)} className="text-stone-400 hover:text-red-600" title="归档别名">
                  <X size={13} />
                </button>
              </span>
            ))
          ) : (
            <span className="text-sm text-stone-400">暂无 active 别名</span>
          )}
        </div>
        <div className="mt-3 flex gap-2">
          <input
            value={aliasValue}
            onChange={(event) => onAliasChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void onAddAlias()
            }}
            placeholder="添加别名，如：老妈、橘猫"
            className="min-w-0 flex-1 rounded-2xl border border-stone-200 bg-white px-3 py-2 text-sm outline-none focus:border-teal-500"
          />
          <button
            onClick={() => void onAddAlias()}
            disabled={isSaving || !aliasValue.trim()}
            className="rounded-2xl bg-stone-950 px-3 py-2 text-sm font-bold text-white transition hover:bg-stone-800 disabled:bg-stone-300"
          >
            添加
          </button>
        </div>
      </div>
    </article>
  )
}

function LabeledInput({
  label,
  value,
  type = 'text',
  onChange,
}: {
  label: string
  value: string
  type?: string
  onChange: (value: string) => void
}) {
  return (
    <label className="grid gap-1 text-xs font-bold text-stone-500">
      {label}
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-2xl border border-stone-200 bg-white px-3 py-2 text-sm font-normal text-stone-900 outline-none focus:border-teal-500"
      />
    </label>
  )
}

function FieldBadge({ label, value, wide }: { label: string; value: string | null | undefined; wide?: boolean }) {
  return (
    <div className={`rounded-2xl bg-white px-3 py-2 shadow-sm ${wide ? 'sm:col-span-2' : ''}`}>
      <p className="text-[0.65rem] font-black uppercase tracking-[0.16em] text-stone-400">{label}</p>
      <p className="mt-1 break-words text-sm font-bold text-stone-800">{displayValue(value)}</p>
    </div>
  )
}

function LabeledSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { label: string; value: string }[]
  onChange: (value: string) => void
}) {
  return (
    <label className="grid gap-1 text-xs font-bold text-stone-500">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-2xl border border-stone-200 bg-white px-3 py-2 text-sm font-normal text-stone-900 outline-none focus:border-teal-500"
      >
        <option value="">未设置</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function nullableText(value: string) {
  const trimmed = value.trim()
  return trimmed || null
}

function sortSubjects(subjects: CareSubject[]) {
  return [...subjects].sort((left, right) => {
    if (left.status !== right.status) return left.status === 'active' ? -1 : 1
    if (left.subject_type !== right.subject_type) return left.subject_type === 'human' ? -1 : 1
    return left.display_name.localeCompare(right.display_name, 'zh-Hans-CN')
  })
}

function relationLabel(value: string | null) {
  return relationOptions.find((option) => option.value === value)?.label ?? value ?? '-'
}

function petTypeLabel(value: string | null) {
  return speciesOptions.find((option) => option.value === value)?.label ?? value ?? '-'
}

function subjectTypeLabel(value: SubjectType) {
  return value === 'pet' ? 'pet（宠物）' : 'human（人物）'
}

function displayValue(value: string | null | undefined) {
  return value?.trim() ? value : '-'
}

function formatDateTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function readableError(err: unknown, fallback: string) {
  if (!(err instanceof Error)) return fallback
  try {
    const parsed = JSON.parse(err.message) as { detail?: string }
    return parsed.detail || fallback
  } catch {
    return err.message || fallback
  }
}
