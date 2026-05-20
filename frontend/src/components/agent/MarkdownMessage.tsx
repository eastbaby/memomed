import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSanitize]}
      components={{
        a: ({ children, ...props }) => (
          <a
            {...props}
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-teal-700 underline decoration-teal-300 underline-offset-4 transition hover:text-teal-900"
          >
            {children}
          </a>
        ),
        code: ({ children, className, ...props }) => {
          const isInline = !className
          if (isInline) {
            return (
              <code {...props} className="rounded-md bg-stone-100 px-1.5 py-0.5 font-mono text-[0.9em] text-stone-800">
                {children}
              </code>
            )
          }
          return (
            <code {...props} className={`${className} block overflow-x-auto whitespace-pre rounded-2xl bg-stone-950 p-4 font-mono text-sm text-stone-50`}>
              {children}
            </code>
          )
        },
        h1: ({ children }) => <h1 className="mb-3 mt-1 text-xl font-black text-stone-950">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-2 mt-4 text-lg font-black text-stone-950">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-2 mt-3 text-base font-black text-stone-950">{children}</h3>,
        li: ({ children }) => <li className="pl-1">{children}</li>,
        ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
        p: ({ children }) => <p className="my-1 leading-7">{children}</p>,
        pre: ({ children }) => <pre className="my-3 overflow-x-auto">{children}</pre>,
        table: ({ children }) => (
          <div className="my-3 overflow-x-auto rounded-2xl border border-stone-200">
            <table className="min-w-full border-collapse text-left text-sm">{children}</table>
          </div>
        ),
        tbody: ({ children }) => <tbody className="divide-y divide-stone-100">{children}</tbody>,
        td: ({ children }) => <td className="px-3 py-2 align-top text-stone-700">{children}</td>,
        th: ({ children }) => <th className="bg-stone-50 px-3 py-2 font-black text-stone-800">{children}</th>,
        ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
