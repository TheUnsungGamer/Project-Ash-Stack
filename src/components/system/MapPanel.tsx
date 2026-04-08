import { Panel } from "../layout/Panel";

export function MapPanel() {
  return (
    <Panel title="Map">
      <section
        aria-label="Map panel"
        className="map-panel"
        style={{ position: "relative", overflow: "hidden" }}
      >
        {/* 🔥 MAP IFRAME */}
        <iframe
          src="http://localhost:8081/map.html"
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            border: "none",
            zIndex: 1,
          }}
        />

        {/* 🔥 UI OVERLAY (kept on top of map) */}
        <div className="map-panel__glow" style={{ zIndex: 2 }} />

        <div className="map-crosshair" style={{ zIndex: 3 }}>
          <div className="map-crosshair__vertical-top" />
          <div className="map-crosshair__vertical-bottom" />
          <div className="map-crosshair__horizontal-left" />
          <div className="map-crosshair__horizontal-right" />
        </div>

        <div className="map-panel__label" style={{ zIndex: 4 }}>
          <div>TACTICAL MAP ONLINE</div>
          <div className="map-panel__sublabel">
            PMTILES LINK ESTABLISHED
          </div>
        </div>
      </section>
    </Panel>
  );
}