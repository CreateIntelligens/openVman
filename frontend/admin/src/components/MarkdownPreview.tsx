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
        h1: ({ children }) => <h1 className="text-2xl font-bold text-content mb-4 mt-6 first:mt-0">{transformChildren(children)}</h1>,
        h2: ({ children }) => <h2 className="text-xl font-bold text-content mb-3 mt-5 border-b border-border pb-2">{transformChildren(children)}</h2>,
        h3: ({ children }) => <h3 className="text-lg font-semibold text-content mb-2 mt-4">{transformChildren(children)}</h3>,
        p: ({ children }) => <p className="text-sm leading-7 text-content-muted mb-4">{transformChildren(children)}</p>,
        ul: ({ children }) => <ul className="list-disc list-inside text-sm text-content-muted mb-4 space-y-1.5 pl-2">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside text-sm text-content-muted mb-4 space-y-1.5 pl-2">{children}</ol>,
        li: ({ children }) => <li className="text-sm text-content-muted">{transformChildren(children)}</li>,
        code: ({ children, className: codeClassName }) => {
          const isBlock = codeClassName?.includes("language-");
          if (isBlock) {
            return <code className="block rounded-lg bg-surface p-4 text-sm text-primary dark:text-primary/80 font-mono overflow-x-auto mb-4 border border-border">{children}</code>;
          }
          return <code className="rounded bg-surface-sunken px-1.5 py-0.5 text-sm text-primary dark:text-primary/80 font-mono">{children}</code>;
        },
        pre: ({ children }) => <pre className="mb-4">{children}</pre>,
        blockquote: ({ children }) => <blockquote className="border-l-4 border-primary/40 pl-4 italic text-content-muted mb-4 bg-surface dark:bg-primary/5 py-2 pr-4 rounded-r-lg">{transformChildren(children)}</blockquote>,
        a: ({ children, href }) => <a href={href} className="text-primary hover:text-primary/80 underline decoration-primary/30 underline-offset-2 transition-colors" target="_blank" rel="noopener noreferrer">{children}</a>,
        hr: () => <hr className="border-border my-6" />,
        strong: ({ children }) => <strong className="font-bold text-content">{transformChildren(children)}</strong>,
        em: ({ children }) => <em>{transformChildren(children)}</em>,
        table: ({ children }) => <div className="overflow-x-auto mb-4"><table className="w-full text-sm text-content-muted border-collapse">{children}</table></div>,
        th: ({ children }) => <th className="border border-border px-4 py-2.5 text-left font-semibold text-content bg-surface dark:bg-surface-overlay/50">{transformChildren(children)}</th>,
        td: ({ children }) => <td className="border border-border px-4 py-2 bg-surface-raised dark:bg-surface-sunken/20 text-content-muted">{transformChildren(children)}</td>,
      }}
    >
      {content}
    </Markdown>
    </div>
  );
}
