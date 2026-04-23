export default function Monitoring() {
  return (
    <div className="flex h-full w-full flex-col">
      <iframe
        src="/grafana/d/vman-overview/vman-overview?kiosk=tv&refresh=10s"
        title="Grafana Monitoring"
        className="h-full w-full flex-1 border-0"
        allow="fullscreen"
      />
    </div>
  );
}
