import Image from "next/image";

export default function Home() {
  return (
    <>
      {/* Premium Header */}
      <header className="header">
        <div className="app-container header-inner">
          <div className="logo">
            🛡️ Financial <span>Life Copilot</span>
          </div>
          <nav style={{ display: 'flex', gap: '24px', alignItems: 'center' }}>
            <a href="#features" style={{ fontWeight: 500, fontSize: '15px', color: 'var(--text-secondary)' }}>Agents</a>
            <a href="#demo" style={{ fontWeight: 500, fontSize: '15px', color: 'var(--text-secondary)' }}>Interface</a>
            <button className="btn btn-secondary" style={{ padding: '8px 18px', fontSize: '14px' }}>
              Connect Wallet
            </button>
          </nav>
        </div>
      </header>

      {/* Hero Section */}
      <main className="app-container" style={{ padding: '60px 24px', flex: 1, display: 'flex', flexDirection: 'column', gap: '80px' }}>
        <section style={{ textAlign: 'center', maxWidth: '800px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div style={{ display: 'inline-flex', padding: '6px 16px', background: 'var(--primary-glow)', borderRadius: 'var(--radius-full)', border: '1px solid var(--border-glow)', alignSelf: 'center', fontSize: '13px', fontWeight: 600, color: 'var(--primary)', letterSpacing: '0.05em' }}>
            GOOGLE ADK & GEMINI 2.5 POWERED
          </div>
          <h1 style={{ fontSize: '48px', lineHeight: 1.1, color: 'var(--text-primary)' }}>
            Your Intelligent Multi-Agent <span style={{ color: 'var(--primary)' }}>Wealth Architect</span>
          </h1>
          <p style={{ fontSize: '18px', color: 'var(--text-secondary)', maxWidth: '640px', margin: '0 auto' }}>
            Securely upload financial files, simulate retirement scenarios, check tax compliance, and execute automated action plans under fiduciary guidelines.
          </p>
          <div style={{ display: 'flex', gap: '16px', justifyContent: 'center', marginTop: '12px' }}>
            <a href="#demo" className="btn btn-primary">Launch Copilot</a>
            <a href="#features" className="btn btn-secondary">Meet the Agents</a>
          </div>
        </section>

        {/* Dynamic Multi-Agent Cards Section */}
        <section id="features" style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
          <div style={{ textAlign: 'center' }}>
            <h2 style={{ fontSize: '32px', marginBottom: '8px' }}>Six Specialized Financial Agents</h2>
            <p style={{ color: 'var(--text-secondary)' }}>Collaboratively processing documents, calculations, risks, and compliance checks.</p>
          </div>
          
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '24px' }}>
            <div className="card">
              <div style={{ fontSize: '32px', marginBottom: '16px' }}>📄</div>
              <h3 style={{ fontSize: '20px', marginBottom: '8px' }}>1. Document Agent</h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                Ingests statements, payroll documents, and tax filings via Model Context Protocol (MCP) toolsets, converting them into structured database entities.
              </p>
            </div>

            <div className="card">
              <div style={{ fontSize: '32px', marginBottom: '16px' }}>📈</div>
              <h3 style={{ fontSize: '20px', marginBottom: '8px' }}>2. Financial Health Agent</h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                Calculates vital health metrics, including debt-to-income (DTI), net worth growth trajectories, and emergency liquidity scores.
              </p>
            </div>

            <div className="card">
              <div style={{ fontSize: '32px', marginBottom: '16px' }}>🏖️</div>
              <h3 style={{ fontSize: '20px', marginBottom: '8px' }}>3. Retirement Agent</h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                Runs Monte Carlo simulations and compounding growth projections in an isolated Vertex AI Python execution sandbox.
              </p>
            </div>

            <div className="card">
              <div style={{ fontSize: '32px', marginBottom: '16px' }}>🛡️</div>
              <h3 style={{ fontSize: '20px', marginBottom: '8px' }}>4. Insurance Agent</h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                Assesses coverage adequacy for life, disability, and liability protection relative to aggregate assets and family dependents.
              </p>
            </div>

            <div className="card">
              <div style={{ fontSize: '32px', marginBottom: '16px' }}>⚖️</div>
              <h3 style={{ fontSize: '20px', marginBottom: '8px' }}>5. Compliance Agent</h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                Acts as a fiduciary guardrail, auditing action recommendations against current IRS contribution caps and advisory guidelines.
              </p>
            </div>

            <div className="card">
              <div style={{ fontSize: '32px', marginBottom: '16px' }}>📋</div>
              <h3 style={{ fontSize: '20px', marginBottom: '8px' }}>6. Action Plan Agent</h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                Compiles advice into a prioritized, chronological roadmap. Initiates approval gates for any transactional recommendations.
              </p>
            </div>
          </div>
        </section>

        {/* Copilot Interface Demo */}
        <section id="demo" style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
          <div style={{ textAlign: 'center' }}>
            <h2 style={{ fontSize: '32px', marginBottom: '8px' }}>Interactive Copilot Console</h2>
            <p style={{ color: 'var(--text-secondary)' }}>Chat with the Root Coordinator, upload statements, and see agent execution logs live.</p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '32px', alignItems: 'start' }}>
            
            {/* Left Column: Chat Window */}
            <div className="chat-window" style={{ boxShadow: 'var(--shadow-premium)' }}>
              <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600 }}>Active Thread</span>
                <span style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--accent-success)' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'currentColor' }}></span>
                  Connected to ADK app
                </span>
              </div>
              
              <div className="chat-history">
                <div className="chat-message chat-message-copilot">
                  Hello! I am your <strong>Financial Life Copilot Coordinator</strong>. Upload your financial statements, or let me know what financial planning goals you would like to tackle today.
                </div>
                <div className="chat-message chat-message-user">
                  Can you inspect my W2 tax file and calculate my current debt-to-income ratio?
                </div>
                <div className="chat-message chat-message-copilot">
                  I will route this request:
                  <div style={{ marginTop: '8px', padding: '10px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)', fontSize: '13px' }}>
                    ⚙️ <strong>[Routing]</strong> Ingesting W2 via <code>document_agent</code>...<br />
                    ⚙️ <strong>[Calculation]</strong> Executing <code>financial_health_agent</code> ratios...
                  </div>
                </div>
              </div>

              <div className="chat-input-area">
                <input className="chat-input" placeholder="Type a request, or drag a statement file here..." disabled />
                <button className="btn btn-primary" style={{ padding: '0 24px', height: '42px', fontSize: '14px' }}>Send</button>
              </div>
            </div>

            {/* Right Column: Execution Log / Workspace State */}
            <div className="card-premium" style={{ height: '600px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <h3 style={{ fontSize: '20px' }}>Agent Collaboration Workspace</h3>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', flex: 1, overflowY: 'auto' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '12px', background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                  <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--primary)' }}>SESSION CONTEXT</span>
                  <div style={{ fontSize: '13px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <div><strong>Session ID:</strong> <code>copilot-session-xyz</code></div>
                    <div><strong>User ID:</strong> <code>client_john_doe</code></div>
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '12px', background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                  <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--primary)' }}>PII REDACTION LOG (DLP PLUGIN)</span>
                  <div style={{ fontSize: '13px', color: 'var(--accent-info)' }}>
                    ✓ Masked US_SOCIAL_SECURITY_NUMBER in prompt.<br />
                    ✓ Redacted BANK_ACCOUNT_NUMBER in response payload.
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '12px', background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                  <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--primary)' }}>COMPLIANCE BOUNDARIES</span>
                  <div style={{ fontSize: '13px', color: 'var(--accent-success)' }}>
                    ✓ Tax bracket contributions checked (IRS Sec 401k).<br />
                    ✓ Fiduciary compliance checks complete.
                  </div>
                </div>
              </div>

              <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '16px', display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
                <span>Backend Port: <code>8000</code></span>
                <span>Target: <code>Cloud Run</code></span>
              </div>
            </div>

          </div>
        </section>
      </main>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--border-color)', padding: '32px 24px', backgroundColor: 'var(--bg-secondary)', marginTop: '80px', fontSize: '14px', color: 'var(--text-secondary)' }}>
        <div className="app-container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>© 2026 Financial Life Copilot. All rights reserved.</div>
          <div style={{ display: 'flex', gap: '20px' }}>
            <a href="https://adk.dev" target="_blank" rel="noreferrer">Google ADK Docs</a>
            <a href="https://nextjs.org" target="_blank" rel="noreferrer">Next.js</a>
            <a href="https://fastapi.tiangolo.com" target="_blank" rel="noreferrer">FastAPI</a>
          </div>
        </div>
      </footer>
    </>
  );
}
