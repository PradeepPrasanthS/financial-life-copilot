'use client';

import React, { useState } from 'react';

// --- Types & Interfaces ---
interface DocumentFile {
  id: string;
  name: string;
  size: string;
  type: string;
  uploadedAt: string;
  status: 'analyzed' | 'pending' | 'failed';
}

interface ActionItem {
  id: string;
  title: string;
  agent: string;
  priority: 'high' | 'medium' | 'low';
  timeframe: 'Immediate' | '30-Day' | '90-Day' | '1-Year';
  description: string;
  status: 'pending' | 'approved' | 'rejected' | 'completed';
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'upload' | 'results' | 'roadmap'>('dashboard');
  const [sessionToken, setSessionToken] = useState<string>('session_demo_9845x');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(0);

  // Mock initial state
  const [uploadedFiles, setUploadedFiles] = useState<DocumentFile[]>([
    { id: 'doc-1', name: 'W2_Tax_Statement_2025.pdf', size: '2.4 MB', type: 'PDF', uploadedAt: '2026-06-22 10:14', status: 'analyzed' },
    { id: 'doc-2', name: 'Chase_Savings_Statement.csv', size: '482 KB', type: 'CSV', uploadedAt: '2026-06-22 11:32', status: 'analyzed' },
  ]);

  const [actionItems, setActionItems] = useState<ActionItem[]>([
    {
      id: 'act-1',
      title: 'Maximize 401(k) Catch-Up Contributions',
      agent: 'Retirement Agent',
      priority: 'high',
      timeframe: 'Immediate',
      description: 'Increase pre-tax contributions to reach the IRS annual limit of $23,000 plus catch-up if eligible. Compliant with current IRS Sec 401k guidelines.',
      status: 'pending',
    },
    {
      id: 'act-2',
      title: 'Review Term Life Policy Coverage',
      agent: 'Insurance Agent',
      priority: 'high',
      timeframe: '30-Day',
      description: 'Address the detected $250,000 coverage gap in critical illness and primary life protection based on outstanding liabilities.',
      status: 'pending',
    },
    {
      id: 'act-3',
      title: 'Build 6-Month Emergency Cash Reserves',
      agent: 'Financial Health Agent',
      priority: 'medium',
      timeframe: '90-Day',
      description: 'Reallocate $1,200 monthly from excess cash-flow into the high-yield savings vault to boost emergency index from 3.2 months to 6.0 months.',
      status: 'approved',
    },
    {
      id: 'act-4',
      title: 'Establish Roth IRA Backdoor Pipeline',
      agent: 'Compliance Agent',
      priority: 'low',
      timeframe: '1-Year',
      description: 'Implement a tax-efficient conversion process matching current income thresholds and state tax limits.',
      status: 'pending',
    },
  ]);

  // Upload handler simulation
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    const newDoc: DocumentFile = {
      id: `doc-${Date.now()}`,
      name: file.name,
      size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
      type: file.name.split('.').pop()?.toUpperCase() || 'UNKNOWN',
      uploadedAt: new Date().toISOString().replace('T', ' ').slice(0, 16),
      status: 'pending',
    };
    setUploadedFiles(prev => [newDoc, ...prev]);
  };

  // Trigger analysis simulation
  const startAnalysis = () => {
    setIsAnalyzing(true);
    setAnalysisProgress(0);
    const interval = setInterval(() => {
      setAnalysisProgress(p => {
        if (p >= 100) {
          clearInterval(interval);
          setIsAnalyzing(false);
          // Mark all files as analyzed
          setUploadedFiles(files => files.map(f => ({ ...f, status: 'analyzed' })));
          setActiveTab('results');
          return 100;
        }
        return p + 20;
      });
    }, 400);
  };

  // Decide action plan items (approval gates)
  const handleDecision = (id: string, decision: 'approved' | 'rejected') => {
    setActionItems(items =>
      items.map(item => (item.id === id ? { ...item, status: decision } : item))
    );
  };

  return (
    <>
      {/* Header */}
      <header className="header">
        <div className="app-container header-inner">
          <div className="logo">
            🛡️ Financial <span>Life Copilot</span>
          </div>
          <nav style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              className={`nav-tab ${activeTab === 'dashboard' ? 'nav-tab-active' : ''}`}
              onClick={() => setActiveTab('dashboard')}
            >
              Dashboard
            </button>
            <button
              className={`nav-tab ${activeTab === 'upload' ? 'nav-tab-active' : ''}`}
              onClick={() => setActiveTab('upload')}
            >
              Upload Documents
            </button>
            <button
              className={`nav-tab ${activeTab === 'results' ? 'nav-tab-active' : ''}`}
              onClick={() => setActiveTab('results')}
            >
              Analysis Results
            </button>
            <button
              className={`nav-tab ${activeTab === 'roadmap' ? 'nav-tab-active' : ''}`}
              onClick={() => setActiveTab('roadmap')}
            >
              Financial Roadmap
            </button>
          </nav>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>Token Session Active</span>
            <span style={{ height: '8px', width: '8px', borderRadius: '50%', backgroundColor: 'var(--accent-success)' }} />
          </div>
        </div>
      </header>

      {/* Main Workspace Area */}
      <main className="app-container" style={{ padding: '40px 24px', flex: 1, display: 'flex', flexDirection: 'column', gap: '32px' }}>
        
        {/* --- 1. DASHBOARD PAGE --- */}
        {activeTab === 'dashboard' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
            <section style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h1 style={{ fontSize: '32px', marginBottom: '8px' }}>Copilot Dashboard</h1>
                <p style={{ color: 'var(--text-secondary)' }}>Welcome back. Monitor health index metrics, secure assets, and trigger agent pipelines.</p>
              </div>
              <button className="btn btn-primary" onClick={() => setActiveTab('upload')}>
                Upload New Files 🚀
              </button>
            </section>

            {/* Metric Overview Grid */}
            <div className="grid-cols-4">
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px', fontWeight: 500 }}>Overall Health Index</span>
                <span style={{ fontSize: '36px', fontWeight: 700, color: 'var(--primary-light)' }}>78%</span>
                <span style={{ color: 'var(--accent-success)', fontSize: '12px' }}>↑ 4.2% from W2 uploads</span>
              </div>
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px', fontWeight: 500 }}>Emergency Cash Index</span>
                <span style={{ fontSize: '36px', fontWeight: 700, color: 'var(--accent-warning)' }}>3.2 mo</span>
                <span style={{ color: 'var(--text-tertiary)', fontSize: '12px' }}>Target: 6.0 months</span>
              </div>
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px', fontWeight: 500 }}>Debt-to-Income (DTI)</span>
                <span style={{ fontSize: '36px', fontWeight: 700, color: 'var(--text-primary)' }}>28.4%</span>
                <span style={{ color: 'var(--accent-success)', fontSize: '12px' }}>Within healthy boundaries</span>
              </div>
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px', fontWeight: 500 }}>Active Risks Flagged</span>
                <span style={{ fontSize: '36px', fontWeight: 700, color: 'var(--accent-error)' }}>2 Issues</span>
                <span style={{ color: 'var(--accent-error)', fontSize: '12px' }}>Insurance gap identified</span>
              </div>
            </div>

            {/* Pipeline and Activity Layout */}
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '32px', alignItems: 'start' }}>
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <h3 style={{ fontSize: '18px', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>Recent Documents & Pipeline Status</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {uploadedFiles.map(doc => (
                    <div key={doc.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px', background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <span style={{ fontSize: '20px' }}>{doc.type === 'PDF' ? '📄' : '📊'}</span>
                        <div>
                          <p style={{ fontSize: '14px', fontWeight: 600 }}>{doc.name}</p>
                          <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>{doc.size} • Uploaded {doc.uploadedAt}</span>
                        </div>
                      </div>
                      <span
                        style={{
                          fontSize: '11px',
                          padding: '4px 10px',
                          borderRadius: 'var(--radius-full)',
                          background: doc.status === 'analyzed' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
                          color: doc.status === 'analyzed' ? 'var(--accent-success)' : 'var(--accent-warning)',
                          border: `1px solid ${doc.status === 'analyzed' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)'}`,
                        }}
                      >
                        {doc.status.toUpperCase()}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Dynamic Status Sidebar */}
              <div className="card-premium" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <h3>Pipeline Engine</h3>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Trigger a full multi-agent compliance run across all structured uploads.</p>
                {isAnalyzing ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                      <span>Compiling Graph edges...</span>
                      <span>{analysisProgress}%</span>
                    </div>
                    <div style={{ width: '100%', height: '6px', background: 'var(--bg-primary)', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ width: `${analysisProgress}%`, height: '100%', background: 'var(--primary)', transition: 'width 0.3s ease' }} />
                    </div>
                  </div>
                ) : (
                  <button className="btn btn-primary" onClick={startAnalysis} style={{ width: '100%' }}>
                    Start Multi-Agent Analysis ⚡
                  </button>
                )}
                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', borderTop: '1px solid var(--border-color)', paddingTop: '12px', display: 'flex', justifyContent: 'space-between' }}>
                  <span>Google ADK Framework</span>
                  <span>v2.0.0</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* --- 2. UPLOAD DOCUMENTS PAGE --- */}
        {activeTab === 'upload' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
            <div>
              <h1 style={{ fontSize: '32px', marginBottom: '8px' }}>Secure Document Portal</h1>
              <p style={{ color: 'var(--text-secondary)' }}>Upload W2 statements, paystubs, and asset statements. PII data is automatically redacted client-side.</p>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '32px', alignItems: 'start' }}>
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '24px', textAlign: 'center', padding: '48px 32px' }}>
                <div style={{ fontSize: '48px' }}>📁</div>
                <div>
                  <h3 style={{ fontSize: '18px', marginBottom: '8px' }}>Drag and drop statement files</h3>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>Supports PDF and CSV format up to 10MB per file</p>
                </div>
                <div style={{ position: 'relative', display: 'inline-block', margin: '0 auto' }}>
                  <input
                    type="file"
                    accept=".pdf,.csv"
                    onChange={handleFileUpload}
                    style={{ position: 'absolute', opacity: 0, width: '100%', height: '100%', cursor: 'pointer' }}
                  />
                  <button className="btn btn-secondary">Choose File</button>
                </div>
              </div>

              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <h3 style={{ fontSize: '18px' }}>Safety & Cryptographic Standards</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', fontSize: '13px' }}>
                  <div style={{ display: 'flex', gap: '12px' }}>
                    <span>🔒</span>
                    <p><strong>PII Redaction:</strong> SSN, Account Numbers, and addresses are masked immediately using localized session keys before files reach the analysis engine.</p>
                  </div>
                  <div style={{ display: 'flex', gap: '12px' }}>
                    <span>🛡️</span>
                    <p><strong>Auditable Trail:</strong> Secure hashes of all ingested files are stored on GCP for immutability validation and compliance auditing.</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* --- 3. ANALYSIS RESULTS PAGE --- */}
        {activeTab === 'results' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
            <div>
              <h1 style={{ fontSize: '32px', marginBottom: '8px' }}>Multi-Agent Findings</h1>
              <p style={{ color: 'var(--text-secondary)' }}>Detailed reports and simulated gaps generated by specialist agents.</p>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '24px' }}>
              
              {/* Card 1: Insurance */}
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontSize: '18px' }}>🛡️ Insurance Gap Analysis</h3>
                  <span style={{ fontSize: '10px', background: 'rgba(239, 68, 68, 0.1)', color: 'var(--accent-error)', padding: '2px 8px', borderRadius: '4px' }}>Critical</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
                  <p><strong>Life Insurance:</strong> Recommended coverage $750k. Existing coverage $500k. <strong>Gap: $250k.</strong></p>
                  <p><strong>Health & Critical Protection:</strong> Recommended coverage $100k. Existing coverage $0. <strong>Gap: $100k.</strong></p>
                </div>
                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
                  Audited by Insurance Agent
                </span>
              </div>

              {/* Card 2: Health */}
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontSize: '18px' }}>📊 Net Worth & Cashflow</h3>
                  <span style={{ fontSize: '10px', background: 'rgba(16, 185, 129, 0.1)', color: 'var(--accent-success)', padding: '2px 8px', borderRadius: '4px' }}>Pass</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
                  <p><strong>DTI Ratio:</strong> 28.4% (Favorable). Savings rate sits comfortably at 18.2% of post-tax payroll.</p>
                  <p><strong>Compound Index:</strong> Projected Net Worth path reaches $1.4M by retirement age 62.</p>
                </div>
                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
                  Audited by Financial Health Agent
                </span>
              </div>

              {/* Card 3: Compliance */}
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontSize: '18px' }}>⚖️ Compliance & Fiduciary</h3>
                  <span style={{ fontSize: '10px', background: 'rgba(59, 130, 246, 0.1)', color: 'var(--accent-info)', padding: '2px 8px', borderRadius: '4px' }}>Secure</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
                  <p><strong>Advisory Compliance:</strong> Zero product recommendations generated. No hallucinations or unsupported advisory statements detected.</p>
                  <p><strong>Limits Checked:</strong> Max 401(k) and IRA limits reconciled matching current tax-year guidelines.</p>
                </div>
                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
                  Audited by Compliance Agent
                </span>
              </div>
            </div>
          </div>
        )}

        {/* --- 4. FINANCIAL ROADMAP PAGE --- */}
        {activeTab === 'roadmap' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
            <div>
              <h1 style={{ fontSize: '32px', marginBottom: '8px' }}>Fiduciary Action Roadmap</h1>
              <p style={{ color: 'var(--text-secondary)' }}>Prioritized tasks generated by the Action Plan Agent. Secure approval gates for executing high-impact items.</p>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {actionItems.map(item => (
                <div key={item.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <span
                        style={{
                          fontSize: '11px',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          fontWeight: 600,
                          background: item.priority === 'high' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                          color: item.priority === 'high' ? 'var(--accent-error)' : 'var(--accent-warning)',
                        }}
                      >
                        {item.priority.toUpperCase()}
                      </span>
                      <h3 style={{ fontSize: '16px' }}>{item.title}</h3>
                    </div>
                    <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{item.timeframe}</span>
                  </div>

                  <p style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>{item.description}</p>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-color)', paddingTop: '12px' }}>
                    <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>Owner: <strong>{item.agent}</strong></span>
                    
                    <div style={{ display: 'flex', gap: '8px' }}>
                      {item.status === 'pending' ? (
                        <>
                          <button
                            className="btn btn-secondary"
                            onClick={() => handleDecision(item.id, 'rejected')}
                            style={{ padding: '6px 14px', fontSize: '12px' }}
                          >
                            Dismiss
                          </button>
                          <button
                            className="btn btn-primary"
                            onClick={() => handleDecision(item.id, 'approved')}
                            style={{ padding: '6px 14px', fontSize: '12px' }}
                          >
                            Approve
                          </button>
                        </>
                      ) : (
                        <span
                          style={{
                            fontSize: '12px',
                            fontWeight: 600,
                            color: item.status === 'approved' ? 'var(--accent-success)' : 'var(--text-tertiary)',
                          }}
                        >
                          {item.status === 'approved' ? '✓ APPROVED' : 'DISMISSED'}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      </main>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--border-color)', padding: '32px 24px', backgroundColor: 'var(--bg-secondary)', marginTop: '80px', fontSize: '14px', color: 'var(--text-secondary)' }}>
        <div className="app-container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>© 2026 Financial Life Copilot. All rights reserved.</div>
          <div style={{ display: 'flex', gap: '20px' }}>
            <span>Google ADK</span>
            <span>Gemini Enterprise</span>
            <span>Next.js Frontend</span>
          </div>
        </div>
      </footer>
    </>
  );
}
