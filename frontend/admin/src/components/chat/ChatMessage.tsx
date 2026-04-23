import type { ActionRequest, ChatMessage as ChatMessageType, RetrievalResult } from "../../api";
import MarkdownPreview from "../MarkdownPreview";
import SourceChips from "./SourceChips";
import ActionRequestCard from "./ActionRequestCard";
import { renderWithRedactions } from "./redactedText";

type RenderableChatMessage = Pick<ChatMessageType, "role" | "content"> & {
  sources?: { knowledge: RetrievalResult[]; memory: RetrievalResult[] };
  action_requests?: ActionRequest[];
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
  onActionConfirmed,
  onActionCancelled,
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
  onActionConfirmed?: (request: ActionRequest) => void;
  onActionCancelled?: (request: ActionRequest) => void;
}) {
  const isUserMessage = message.role === "user";
  const isAssistantMessage = message.role === "assistant";
  const isPlaying = playingIndex === index;
  const isPrefetching = Boolean(ttsPrefetching && isLastMessage);
  const timestamp = formatMessageTime(createdAt);
  const shouldRenderMarkdown = renderMarkdown ?? isAssistantMessage;
  const shouldShowAssistantActions = Boolean(
    showAssistantActions
    && isAssistantMessage
    && message.content
    && onPlayTts
    && index !== undefined,
  );
  const messageCardClassName = isUserMessage
    ? "ml-auto bg-primary text-white rounded-tr-sm"
    : "bg-white dark:bg-slate-900/80 text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-slate-800/80 rounded-tl-sm backdrop-blur-sm";
  const messageMetaClassName = isUserMessage
    ? "text-primary-100 opacity-80"
    : "text-slate-500";
  const ttsButtonTitle = isPlaying ? "停止" : isPrefetching ? "語音準備中…" : "播放";
  const ttsButtonClassName = [
    "text-slate-500 hover:text-slate-900 dark:hover:text-white",
    isPlaying ? "!opacity-100 text-primary" : "",
    isPrefetching ? "animate-pulse text-primary/50" : "",
  ].filter(Boolean).join(" ");

  return (
    <article
      className={`max-w-[85%] lg:max-w-[75%] rounded-2xl px-5 py-4 shadow-sm group/msg ${messageCardClassName}`}
    >
      <div className={`mb-2 flex items-center gap-3 text-[10px] uppercase tracking-[0.2em] font-bold ${messageMetaClassName}`}>
        <span>{isUserMessage ? "You" : "Brain"}</span>
        {timestamp && <span>{timestamp}</span>}
        {shouldShowAssistantActions && (
          <div className="flex items-center gap-1 ml-auto opacity-0 group-hover/msg:opacity-100 transition-opacity">
            <button
              type="button"
              onClick={() => onPlayTts?.(message.content, index as number)}
              className={ttsButtonClassName}
              title={ttsButtonTitle}
            >
              <span className="material-symbols-outlined text-[14px]">
                {isPlaying ? "stop" : "volume_up"}
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
        <p className="whitespace-pre-wrap text-[15px] leading-relaxed relative z-10">{renderWithRedactions(message.content)}</p>
      )}
      {isAssistantMessage && message.sources && (
        <SourceChips sources={message.sources} />
      )}
      {isAssistantMessage && message.action_requests && message.action_requests.length > 0 && (
        <div className="mt-2 space-y-2">
          {message.action_requests.map((req, i) => (
            <ActionRequestCard
              key={`${req.action}-${i}`}
              request={req}
              onConfirmed={onActionConfirmed}
              onCancelled={onActionCancelled}
            />
          ))}
        </div>
      )}
    </article>
  );
}
