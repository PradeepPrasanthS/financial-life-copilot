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

  // Mock initial state using Indian sample data format
  const [uploadedFiles, setUploadedFiles] = useState<DocumentFile[]>([
    { id: 'doc-1', name: 'Form_16_Salary_FY_2025-26.pdf', size: '1.8 MB', type: 'PDF', uploadedAt: '2026-06-22 10:14', status: 'analyzed' },
    { id: 'doc-2', name: 'Nippon_India_SIP_Statement.csv', size: '124 KB', type: 'CSV', uploadedAt: '2026-06-22 11:32', status: 'analyzed' },
  ]);

  // Actions mapped to Indian Financial System, EPF, NPS, PPF, SIPs, Section 80C
  const [actionItems, setActionItems] = useState<ActionItem[]>([
    {
      id: 'act-1',
      title: 'Maximize Section 80C Deductions (ELSS/PPF)',
      agent: 'Retirement Agent',
      priority: 'high',
      timeframe: 'Immediate',
      description: 'Reallocate ₹1,50,000 to Equity Linked Savings Scheme (ELSS) or Public Provident Fund (PPF) to maximize tax savings under Section 80C for FY 2025-26.',
      status: 'pending',
    },
    {
      id: 'act-2',
      title: 'Setup NPS Tier-1 Contributions (Section 80CCD(1B))',
      agent: 'Retirement Agent',
      priority: 'high',
      timeframe: 'Immediate',
      description: 'Allocate an additional ₹50,000 to the National Pension System (NPS) Tier-1 account to secure exclusive tax benefits under Section 80CCD(1B).',
      status: 'pending',
    },
    {
      id: 'act-3',
      title: 'Review Term Insurance & Family Floater Health Cover',
      agent: 'Insurance Agent',
      priority: 'high',
      timeframe: '30-Day',
      description: 'Address the protection coverage gap by purchasing a ₹1,00,00,000 Term Life policy and upgrading your corporate health policy to a ₹10,00,000 Family Floater Plan.',
      status: 'pending',
    },
    {
      id: 'act-4',
      title: 'Automate Nifty 50 Index Mutual Fund SIPs',
      agent: 'Financial Health Agent',
      priority: 'medium',
      timeframe: '90-Day',
      description: 'Redirect ₹25,000 monthly from excess income to a Nifty 50 Index Fund and a Mid Cap Hybrid Fund SIP to achieve early retirement corpus target.',
      status: 'approved',
    },
    {
      id: 'act-5',
      title: 'Upgrade Section 80D Health Insurance Premium',
      agent: 'Compliance Agent',
      priority: 'low',
      timeframe: '1-Year',
      description: 'Maximize tax relief under Section 80D by structuring health checkup and premium payments for self and senior citizen parents.',
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
            🛡️ Indian <span>Life Copilot</span>
          </div>
          <nav style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              className={`nav-tab ${activeTab === 'dashboard' ? 'nav-tab-active' : ''}`}
              onClick={() => setActiveTab('dashboard')}
            >
              Wealth Dashboard
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
                <h1 style={{ fontSize: '32px', marginBottom: '8px' }}>Wealth Dashboard</h1>
                <p style={{ color: 'var(--text-secondary)' }}>Monitor Indian tax regimes (FY 2025-26), retirement corpuses, and trigger agent verification cycles.</p>
              </div>
              <button className="btn btn-primary" onClick={() => setActiveTab('upload')}>
                Upload Form 16 / SIP Statements 🚀
              </button>
            </section>

            {/* Metric Overview Grid - Indian Formatting */}
            <div className="grid-cols-4">
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px', fontWeight: 500 }}>Total Retirement Corpus</span>
                <span style={{ fontSize: '36px', fontWeight: 700, color: 'var(--primary-light)' }}>₹26,00,000</span>
                <span style={{ color: 'var(--accent-success)', fontSize: '12px' }}>↑ 4.2% from EPF updates</span>
              </div>
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px', fontWeight: 500 }}>Emergency Cash Index</span>
                <span style={{ fontSize: '36px', fontWeight: 700, color: 'var(--accent-warning)' }}>3.2 mo</span>
                <span style={{ color: 'var(--text-tertiary)', fontSize: '12px' }}>Target: 6.0 months (₹3,00,000)</span>
              </div>
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px', fontWeight: 500 }}>Savings Percentage</span>
                <span style={{ fontSize: '36px', fontWeight: 700, color: 'var(--text-primary)' }}>30.3%</span>
                <span style={{ color: 'var(--accent-success)', fontSize: '12px' }}>Within healthy boundaries</span>
              </div>
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px', fontWeight: 500 }}>Active Protection Risks</span>
                <span style={{ fontSize: '36px', fontWeight: 700, color: 'var(--accent-error)' }}>2 Gaps</span>
                <span style={{ color: 'var(--accent-error)', fontSize: '12px' }}>Term coverage gap identified</span>
              </div>
            </div>

            {/* Demo profile visualization */}
            <div className="card-premium" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <h3 style={{ fontSize: '20px' }}>Active Profile Context</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', fontSize: '14px' }}>
                <div><strong>Age:</strong> 28</div>
                <div><strong>Monthly Income:</strong> ₹1,65,000</div>
                <div><strong>Monthly Expenses:</strong> ₹50,000</div>
                <div><strong>Target Retirement Age:</strong> 45</div>
                <div><strong>EPF Balance:</strong> ₹8,00,000</div>
                <div><strong>NPS Balance:</strong> ₹3,00,000</div>
                <div><strong>Mutual Funds:</strong> ₹15,00,000</div>
                <div><strong>Life Cover:</strong> ₹1,00,00,000</div>
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
                    Start Indian Market Scan ⚡
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
              <p style={{ color: 'var(--text-secondary)' }}>Upload Form 16, payslips, PPF log books, and Mutual Fund CAS statements. PII data is automatically redacted client-side.</p>
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
                    <p><strong>PII Redaction:</strong> PAN Card, Aadhaar Card, Account Numbers, and addresses are masked immediately using localized session keys before files reach the analysis engine.</p>
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
              <h1 style={{ fontSize: '32px', marginBottom: '8px' }}>Multi-Agent Advisory Findings</h1>
              <p style={{ color: 'var(--text-secondary)' }}>Detailed reports and simulated gaps generated by specialist agents for the Indian market.</p>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '24px' }}>
              
              {/* Card 1: Insurance */}
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontSize: '18px' }}>🛡️ Protection Coverage</h3>
                  <span style={{ fontSize: '10px', background: 'rgba(239, 68, 68, 0.1)', color: 'var(--accent-error)', padding: '2px 8px', borderRadius: '4px' }}>Gap Alert</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
                  <p><strong>Term Insurance:</strong> Recommended ₹1,50,00,000. Existing ₹1,00,00,000. <strong>Gap: ₹50,00,000.</strong></p>
                  <p><strong>Health Floater & Critical Illness:</strong> Recommended ₹15,00,000. Existing ₹10,00,000. <strong>Gap: ₹5,00,000.</strong></p>
                </div>
                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
                  Audited by Insurance Agent
                </span>
              </div>

              {/* Card 2: Health */}
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontSize: '18px' }}>📊 Target Retirement Corpus</h3>
                  <span style={{ fontSize: '10px', background: 'rgba(16, 185, 129, 0.1)', color: 'var(--accent-success)', padding: '2px 8px', borderRadius: '4px' }}>Progressing</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
                  <p><strong>Inflation-Adjusted Target:</strong> ₹4,50,00,000 (Retirement Age 45).</p>
                  <p><strong>Required Monthly SIPs:</strong> ₹35,00/month (Current SIPs: ₹25,000/month).</p>
                </div>
                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
                  Audited by Financial Health Agent
                </span>
              </div>

              {/* Card 3: Compliance */}
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontSize: '18px' }}>⚖️ Indian Tax Regime & Fiduciary</h3>
                  <span style={{ fontSize: '10px', background: 'rgba(59, 130, 246, 0.1)', color: 'var(--accent-info)', padding: '2px 8px', borderRadius: '4px' }}>Secure</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
                  <p><strong>Deductions Audited:</strong> Sec 80C limit (₹1,50,000) and Sec 80D health policies check complete.</p>
                  <p><strong>Tax Recommendation:</strong> Comparing Old vs New Tax regimes for FY 2025-26. No direct commercial mutual fund brand pitches (compliance-passed).</p>
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
              <p style={{ color: 'var(--text-secondary)' }}>Prioritized tax and investment tasks generated by the Action Plan Agent. Secure approval gates for executing high-impact items.</p>
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
          <div>© 2026 Indian Life Copilot. All rights reserved.</div>
          <div style={{ display: 'flex', gap: '20px' }}>
            <span>Google ADK</span>
            <span>Gemini Enterprise</span>
            <span>Indian Localization</span>
          </div>
        </div>
      </footer>
    </>
  );
}
