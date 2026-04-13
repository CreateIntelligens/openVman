import type { ChatMessage as ChatMessageType, RetrievalResult } from "../../api";
import MarkdownPreview from "../MarkdownPreview";
import SourceChips from "./SourceChips";

type RenderableChatMessage = Pick<ChatMessageType, "role" | "content"> & {
  sources?: { knowledge: RetrievalResult[]; memory: RetrievalResult[] };
};

function formatMessageTime(value: string | number | undefined): string | null {
  if (value == null || value === "") {
    return null;
  }

  const date = typeof value === "number" ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function ChatMessage({
  message,
  createdAt,
  index,
  playingIndex,
  ttsPrefetching,
  isLastMessage,
  onPlayTts,
  renderMarkdown,
  showAssistantActions,
}: {
  message: RenderableChatMessage;
  createdAt?: string | number;
  index?: number;
  playingIndex?: number | null;
  ttsPrefetching?: boolean;
  isLastMessage?: boolean;
  onPlayTts?: (text: string, index: number) => void;
  renderMarkdown?: boolean;
  showAssistantActions?: boolean;
}) {
  const timestamp = formatMessageTime(createdAt);
  const shouldRenderMarkdown = renderMarkdown ?? message.role === "assistant";
  const shouldShowAssistantActions = Boolean(
    showAssistantActions
    && message.role === "assistant"
    && message.content
    && onPlayTts
    && index !== undefined,
  );

  return (
    <article
      className={`max-w-[85%] lg:max-w-[75%] rounded-2xl px-5 py-4 shadow-sm group/msg ${message.role === "user"
        ? "ml-auto bg-primary text-white rounded-tr-sm"
        : "bg-white dark:bg-slate-900/80 text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-slate-800/80 rounded-tl-sm backdrop-blur-sm"
        }`}
    >
      <div className={`mb-2 flex items-center gap-3 text-[10px] uppercase tracking-[0.2em] font-bold ${message.role === "user" ? "text-primary-100 opacity-80" : "text-slate-500"
        }`}>
        <span>{message.role === "user" ? "You" : "Brain"}</span>
        {timestamp && <span>{timestamp}</span>}
        {shouldShowAssistantActions && (
          <div className="flex items-center gap-1 ml-auto opacity-0 group-hover/msg:opacity-100 transition-opacity">
            <button
              type="button"
              onClick={() => onPlayTts?.(message.content, index as number)}
              className={`text-slate-500 hover:text-slate-900 dark:hover:text-white ${playingIndex === index ? "!opacity-100 text-primary" : ""} ${ttsPrefetching && isLastMessage ? "animate-pulse text-primary/50" : ""}`}
              title={playingIndex === index ? "停止" : ttsPrefetching && isLastMessage ? "語音準備中…" : "播放"}
            >
              <span className="material-symbols-outlined text-[14px]">
                {playingIndex === index ? "stop" : "volume_up"}
              </span>
            </button>
            <button
              type="button"
              onClick={() => navigator.clipboard.writeText(message.content)}
              className="text-slate-500 hover:text-slate-900 dark:hover:text-white"
              title="Copy"
            >
              <span className="material-symbols-outlined text-[14px]">content_copy</span>
            </button>
          </div>
        )}
      </div>
      {shouldRenderMarkdown ? (
        <div className="text-[15px] leading-relaxed relative z-10">
          <MarkdownPreview content={message.content} />
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-[15px] leading-relaxed relative z-10">{message.content}</p>
      )}
      {message.role === "assistant" && message.sources && (
        <SourceChips sources={message.sources} />
      )}
    </article>
  );
}
