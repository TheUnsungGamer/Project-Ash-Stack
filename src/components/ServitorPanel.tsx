/**
 * Project Ash - Servitor Tactical Panel
 * 
 * A sliding augmetic readout panel that displays Servitor audit results.
 * Styled after Warhammer 40K Mechanicus cogitator interfaces.
 */

import React from 'react';

// =============================================================================
// TYPES
// =============================================================================

interface ServitorResult {
  status: 'OPTIMAL' | 'REVIEW' | 'CRITICAL';
  confidence: number | null;
  mortality_estimate: number | null;
  risk_category: string | null;
  deficiency: string | null;
  amendment: string | null;
  recommended_action: string | null;
}

interface ServitorPanelProps {
  result: ServitorResult | null;
  isVisible: boolean;
  isPending: boolean;
  onDismiss: () => void;
  onPlayVoice?: () => void;
}

// =============================================================================
// STYLES
// =============================================================================

const styles = `
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&display=swap');

  .servitor-panel {
    position: fixed;
    top: 0;
    right: 0;
    height: 100vh;
    width: 420px;
    max-width: 90vw;
    background: linear-gradient(
      135deg,
      rgba(15, 15, 20, 0.98) 0%,
      rgba(25, 20, 30, 0.98) 50%,
      rgba(20, 15, 25, 0.98) 100%
    );
    border-left: 2px solid #8b0000;
    box-shadow: 
      -10px 0 40px rgba(139, 0, 0, 0.3),
      inset 0 0 100px rgba(139, 0, 0, 0.05);
    transform: translateX(100%);
    transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
    z-index: 9999;
    overflow: hidden;
    font-family: 'Share Tech Mono', monospace;
  }

  .servitor-panel.visible {
    transform: translateX(0);
  }

  .servitor-panel.critical {
    animation: critical-pulse 1s ease-in-out infinite;
  }

  @keyframes critical-pulse {
    0%, 100% { 
      border-color: #8b0000;
      box-shadow: -10px 0 40px rgba(139, 0, 0, 0.3);
    }
    50% { 
      border-color: #ff0000;
      box-shadow: -10px 0 60px rgba(255, 0, 0, 0.5);
    }
  }

  .servitor-scanlines {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0, 0, 0, 0.1) 2px,
      rgba(0, 0, 0, 0.1) 4px
    );
    pointer-events: none;
    z-index: 1;
  }

  .servitor-content {
    position: relative;
    z-index: 2;
    height: 100%;
    padding: 24px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .servitor-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: 16px;
    border-bottom: 1px solid rgba(139, 0, 0, 0.5);
  }

  .servitor-title {
    font-family: 'Orbitron', sans-serif;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 3px;
    color: #8b0000;
    text-transform: uppercase;
  }

  .servitor-dismiss {
    background: transparent;
    border: 1px solid rgba(139, 0, 0, 0.5);
    color: #666;
    width: 32px;
    height: 32px;
    cursor: pointer;
    font-family: 'Share Tech Mono', monospace;
    font-size: 18px;
    transition: all 0.2s;
  }

  .servitor-dismiss:hover {
    border-color: #8b0000;
    color: #8b0000;
  }

  .servitor-status {
    text-align: center;
    padding: 20px;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(139, 0, 0, 0.3);
  }

  .status-label {
    font-family: 'Orbitron', sans-serif;
    font-size: 12px;
    color: #555;
    letter-spacing: 2px;
    margin-bottom: 8px;
  }

  .status-value {
    font-family: 'Orbitron', sans-serif;
    font-size: 28px;
    font-weight: 900;
    letter-spacing: 4px;
  }

  .status-value.optimal {
    color: #00ff88;
    text-shadow: 0 0 20px rgba(0, 255, 136, 0.5);
  }

  .status-value.review {
    color: #ffa500;
    text-shadow: 0 0 20px rgba(255, 165, 0, 0.5);
  }

  .status-value.critical {
    color: #ff0000;
    text-shadow: 0 0 20px rgba(255, 0, 0, 0.5);
    animation: text-flicker 0.5s ease-in-out infinite;
  }

  @keyframes text-flicker {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.8; }
  }

  .servitor-metrics {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }

  .metric-box {
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(139, 0, 0, 0.3);
    padding: 16px;
  }

  .metric-label {
    font-size: 10px;
    color: #555;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 8px;
  }

  .metric-value {
    font-family: 'Orbitron', sans-serif;
    font-size: 24px;
    font-weight: 700;
  }

  .metric-value.confidence {
    color: #00ff88;
  }

  .metric-value.mortality {
    color: #ff4444;
  }

  .metric-bar {
    height: 4px;
    background: rgba(255, 255, 255, 0.1);
    margin-top: 8px;
    overflow: hidden;
  }

  .metric-bar-fill {
    height: 100%;
    transition: width 0.8s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .metric-bar-fill.confidence {
    background: linear-gradient(90deg, #00ff88, #00aa55);
  }

  .metric-bar-fill.mortality {
    background: linear-gradient(90deg, #ff4444, #ff0000);
  }

  .servitor-section {
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(139, 0, 0, 0.3);
    padding: 16px;
  }

  .section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }

  .section-icon {
    width: 16px;
    height: 16px;
    border: 1px solid #8b0000;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    color: #8b0000;
  }

  .section-title {
    font-size: 11px;
    color: #8b0000;
    letter-spacing: 2px;
    text-transform: uppercase;
  }

  .section-content {
    font-size: 13px;
    color: #aaa;
    line-height: 1.6;
  }

  .section-content.amendment {
    color: #ffa500;
  }

  .section-content.action {
    color: #ff4444;
    font-weight: 600;
  }

  .servitor-footer {
    margin-top: auto;
    padding-top: 16px;
    border-top: 1px solid rgba(139, 0, 0, 0.3);
    text-align: center;
  }

  .cogitator-text {
    font-size: 10px;
    color: #444;
    letter-spacing: 1px;
  }

  .servitor-pending {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    gap: 24px;
  }

  .pending-spinner {
    width: 60px;
    height: 60px;
    border: 2px solid rgba(139, 0, 0, 0.3);
    border-top-color: #8b0000;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .pending-text {
    font-family: 'Orbitron', sans-serif;
    font-size: 12px;
    color: #8b0000;
    letter-spacing: 2px;
    animation: pending-blink 1s ease-in-out infinite;
  }

  @keyframes pending-blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }

  .voice-button {
    background: transparent;
    border: 1px solid #8b0000;
    color: #8b0000;
    padding: 8px 16px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    letter-spacing: 1px;
    cursor: pointer;
    transition: all 0.2s;
    margin-top: 12px;
  }

  .voice-button:hover {
    background: rgba(139, 0, 0, 0.2);
  }

  .risk-category {
    display: inline-block;
    padding: 4px 8px;
    background: rgba(139, 0, 0, 0.2);
    border: 1px solid rgba(139, 0, 0, 0.5);
    font-size: 10px;
    color: #8b0000;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-top: 8px;
  }
`;

// =============================================================================
// COMPONENT
// =============================================================================

const ServitorPanel: React.FC<ServitorPanelProps> = ({
  result,
  isVisible,
  isPending,
  onDismiss,
  onPlayVoice
}) => {
  const isCritical = result?.status === 'CRITICAL';

  return (
    <>
      <style>{styles}</style>
      <div 
        className={`servitor-panel ${isVisible ? 'visible' : ''} ${isCritical ? 'critical' : ''}`}
      >
        <div className="servitor-scanlines" />
        
        <div className="servitor-content">
          <div className="servitor-header">
            <div className="servitor-title">++Servitor Audit++</div>
            <button className="servitor-dismiss" onClick={onDismiss}>×</button>
          </div>

          {isPending && !result ? (
            <div className="servitor-pending">
              <div className="pending-spinner" />
              <div className="pending-text">COGITATING...</div>
              <div className="cogitator-text">++Processing tactical assessment++</div>
            </div>
          ) : result ? (
            <>
              {/* Status Display */}
              <div className="servitor-status">
                <div className="status-label">Audit Status</div>
                <div className={`status-value ${result.status.toLowerCase()}`}>
                  {result.status}
                </div>
                {result.risk_category && (
                  <div className="risk-category">{result.risk_category.replace('_', ' ')}</div>
                )}
              </div>

              {/* Metrics */}
              <div className="servitor-metrics">
                {result.confidence !== null && (
                  <div className="metric-box">
                    <div className="metric-label">Confidence</div>
                    <div className="metric-value confidence">{result.confidence}%</div>
                    <div className="metric-bar">
                      <div 
                        className="metric-bar-fill confidence"
                        style={{ width: `${result.confidence}%` }}
                      />
                    </div>
                  </div>
                )}
                
                {result.mortality_estimate !== null && (
                  <div className="metric-box">
                    <div className="metric-label">Mortality Est.</div>
                    <div className="metric-value mortality">{result.mortality_estimate}%</div>
                    <div className="metric-bar">
                      <div 
                        className="metric-bar-fill mortality"
                        style={{ width: `${result.mortality_estimate}%` }}
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Deficiency */}
              {result.deficiency && (
                <div className="servitor-section">
                  <div className="section-header">
                    <div className="section-icon">!</div>
                    <div className="section-title">Deficiency Detected</div>
                  </div>
                  <div className="section-content">{result.deficiency}</div>
                </div>
              )}

              {/* Amendment */}
              {result.amendment && (
                <div className="servitor-section">
                  <div className="section-header">
                    <div className="section-icon">→</div>
                    <div className="section-title">Amendment</div>
                  </div>
                  <div className="section-content amendment">{result.amendment}</div>
                </div>
              )}

              {/* Recommended Action */}
              {result.recommended_action && (
                <div className="servitor-section">
                  <div className="section-header">
                    <div className="section-icon">⚠</div>
                    <div className="section-title">Recommended Action</div>
                  </div>
                  <div className="section-content action">{result.recommended_action}</div>
                </div>
              )}

              {/* Voice Playback */}
              {onPlayVoice && (
                <button className="voice-button" onClick={onPlayVoice}>
                  ▶ VOCALIZE ASSESSMENT
                </button>
              )}
            </>
          ) : null}

          <div className="servitor-footer">
            <div className="cogitator-text">++THE OMNISSIAH PROTECTS++</div>
          </div>
        </div>
      </div>
    </>
  );
};

export default ServitorPanel;