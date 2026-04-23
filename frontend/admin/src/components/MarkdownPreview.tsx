import Markdown from "react-markdown";
import { transformChildren } from "./chat/redactedText";

interface MarkdownPreviewProps {
  content: string;
  className?: string;
}

export default function MarkdownPreview({ content, className = "" }: MarkdownPreviewProps) {
  return (
    <div className={className}>
    <Markdown
      components={{
        h1: ({ children }) => <h1 className="text-2xl font-bold text-slate-900 dark:text-white mb-4 mt-6 first:mt-0">{transformChildren(children)}</h1>,
        h2: ({ children }) => <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-3 mt-5 border-b border-slate-200 dark:border-slate-800 pb-2">{transformChildren(children)}</h2>,
        h3: ({ children }) => <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-2 mt-4">{transformChildren(children)}</h3>,
        p: ({ children }) => <p className="text-sm leading-7 text-slate-600 dark:text-slate-300 mb-4">{transformChildren(children)}</p>,
        ul: ({ children }) => <ul className="list-disc list-inside text-sm text-slate-600 dark:text-slate-300 mb-4 space-y-1.5 pl-2">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside text-sm text-slate-600 dark:text-slate-300 mb-4 space-y-1.5 pl-2">{children}</ol>,
        li: ({ children }) => <li className="text-sm text-slate-600 dark:text-slate-300">{transformChildren(children)}</li>,
        code: ({ children, className: codeClassName }) => {
          const isBlock = codeClassName?.includes("language-");
          if (isBlock) {
            return <code className="block rounded-lg bg-slate-50 dark:bg-slate-950 p-4 text-sm text-primary dark:text-primary/80 font-mono overflow-x-auto mb-4 border border-slate-200 dark:border-slate-800">{children}</code>;
          }
          return <code className="rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 text-sm text-primary dark:text-primary/80 font-mono">{children}</code>;
        },
        pre: ({ children }) => <pre className="mb-4">{children}</pre>,
        blockquote: ({ children }) => <blockquote className="border-l-4 border-primary/40 pl-4 italic text-slate-500 dark:text-slate-400 mb-4 bg-slate-50 dark:bg-primary/5 py-2 pr-4 rounded-r-lg">{transformChildren(children)}</blockquote>,
        a: ({ children, href }) => <a href={href} className="text-primary hover:text-primary/80 underline decoration-primary/30 underline-offset-2 transition-colors" target="_blank" rel="noopener noreferrer">{children}</a>,
        hr: () => <hr className="border-slate-200 dark:border-slate-800 my-6" />,
        strong: ({ children }) => <strong className="font-bold text-slate-900 dark:text-slate-200">{transformChildren(children)}</strong>,
        em: ({ children }) => <em>{transformChildren(children)}</em>,
        table: ({ children }) => <div className="overflow-x-auto mb-4"><table className="w-full text-sm text-slate-600 dark:text-slate-300 border-collapse">{children}</table></div>,
        th: ({ children }) => <th className="border border-slate-200 dark:border-slate-700 px-4 py-2.5 text-left font-semibold text-slate-900 dark:text-slate-200 bg-slate-50 dark:bg-slate-800/50">{transformChildren(children)}</th>,
        td: ({ children }) => <td className="border border-slate-200 dark:border-slate-700 px-4 py-2 bg-white dark:bg-slate-900/20 text-slate-700 dark:text-slate-300">{transformChildren(children)}</td>,
      }}
    >
      {content}
    </Markdown>
    </div>
  );
}
