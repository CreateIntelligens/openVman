export default function Monitoring() {
  return (
    <div className="flex h-full w-full flex-col">
      {/* Grafana kiosk 模式全螢幕顯示，頁名僅供 a11y 使用 */}
      <h1 className="page-title sr-only">系統監控</h1>
      <iframe
        src="/grafana/d/vman-overview/vman-overview?kiosk=tv&refresh=10s"
        title="Grafana Monitoring"
        className="h-full w-full flex-1 border-0"
        allow="fullscreen"
      />
    </div>
  );
}
