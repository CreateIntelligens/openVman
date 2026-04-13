

interface AsrButtonProps {
       supported: boolean;
       listening: boolean;
       speaking: boolean;
       onToggle: () => void;
}

export const AsrButton: React.FC<AsrButtonProps> = ({
       supported,
       listening,
       speaking,
       onToggle,
}) => {
       if (!supported) return null;

       const getButtonStyles = () => {
              if (!listening) {
                     return "w-10 border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700";
              }
              return speaking
                     ? "bg-red-500 text-white hover:bg-red-600 px-3 gap-1.5"
                     : "bg-amber-500 text-white animate-pulse hover:bg-amber-600 px-3 gap-1.5";
       };

       return (
              <button
                     onClick={onToggle}
                     className={`h-8 flex items-center justify-center rounded-lg transition-colors shadow-sm ${getButtonStyles()}`}
                     title={listening ? "停止語音輸入" : "語音輸入"}
              >
                     <span className="material-symbols-outlined text-[18px]">mic</span>
                     {listening && (
                            <span className="text-[11px] font-bold whitespace-nowrap">
                                   {speaking ? "聆聽中..." : "等待語音"}
                            </span>
                     )}
              </button>
       );
};
