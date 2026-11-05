import { useLayoutEffect, useRef, type TextareaHTMLAttributes } from "react";

/** 高度跟著內容走：一行的問題就一行高，長答案才長高。 */
export default function AutoTextarea({
  value,
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { value: string }) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const fit = () => {
      element.style.height = "auto";
      const border = element.offsetHeight - element.clientHeight;
      element.style.height = `${element.scrollHeight + border}px`;
    };
    fit();
    // 寬度一變，換行數也跟著變。
    if (typeof ResizeObserver === "undefined") return;
    let lastWidth = element.offsetWidth;
    const observer = new ResizeObserver(() => {
      if (element.offsetWidth === lastWidth) return;
      lastWidth = element.offsetWidth;
      fit();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [value]);

  return (
    <textarea
      {...props}
      ref={ref}
      value={value}
      rows={1}
      className={`resize-none overflow-y-auto ${className}`}
    />
  );
}
