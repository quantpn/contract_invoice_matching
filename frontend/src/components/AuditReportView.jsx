import React, { useState } from 'react';

export default function AuditReportView({
  report,
  invoice,
  contract,
  onAskAgent,
}) {
  const [question, setQuestion] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [asking, setAsking] = useState(false);

  if (!report) {
    return (
      <section className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">
              3. Kết quả Đối chiếu AI (Hóa đơn vs Hợp đồng gốc &amp; Luật Thuế)
            </h2>
            <p className="card-desc">
              Sau khi kiểm tra và chỉnh sửa bảng Hóa đơn ở mục 2, hãy bấm nút <strong>"✓ Xác nhận chốt bảng &amp; Đối chiếu Hợp đồng"</strong> để xem báo cáo kiểm toán chi tiết.
            </p>
          </div>
        </div>
        <div className="empty-hint">
          Chưa chạy đối chiếu cho hóa đơn này.
        </div>
      </section>
    );
  }

  const isGood = report.overall_status === 'GOOD';
  const violations = report.violations || [];
  const passedChecks = report.passed_checks || [];

  const handleChatSubmit = async (e) => {
    e.preventDefault();
    if (!question.trim()) return;
    const q = question.trim();
    setQuestion('');
    setAsking(true);
    setChatHistory((prev) => [...prev, { role: 'user', text: q }]);
    try {
      const res = await onAskAgent(q);
      setChatHistory((prev) => [
        ...prev,
        { role: 'agent', text: res.reply, model: res.llm_model },
      ]);
    } catch (err) {
      setChatHistory((prev) => [
        ...prev,
        { role: 'error', text: err.message },
      ]);
    } finally {
      setAsking(false);
    }
  };

  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">
            3. Kết quả Đối chiếu AI: Hóa đơn <code>{invoice?.filename}</code>
            {contract ? ` ↔ Hợp đồng #${contract.contract_number || contract.id} (${contract.filename})` : ' (Kiểm tra Độc lập theo Luật)'}
          </h2>
          <p className="card-desc">
            Chế độ kiểm toán: <code>{report.audit_mode}</code> • Thời gian: {report.created_at}
          </p>
        </div>

        <div>
          <span className={`status-banner-badge ${isGood ? 'good' : 'violation'}`}>
            {isGood ? '✓ HÓA ĐƠN HỢP LỆ (GOOD)' : `✕ PHÁT HIỆN ${violations.length} VI PHẠM (VIOLATION)`}
          </span>
        </div>
      </div>

      {/* Summary Banner */}
      <div className={`audit-alert ${isGood ? 'audit-alert-good' : 'audit-alert-violation'}`}>
        <div style={{ fontWeight: 600, fontSize: '15px', marginBottom: '4px' }}>
          {report.summary}
        </div>
        <div style={{ fontSize: '13px', opacity: 0.9 }}>
          Điểm rủi ro (Risk Score): <strong>{report.risk_score}/100</strong> • Số hạng mục đạt chuẩn:{' '}
          <strong>{passedChecks.length}</strong> • Số lỗi vi phạm: <strong>{violations.length}</strong>
        </div>
      </div>

      {/* Violations Table */}
      {violations.length > 0 && (
        <div style={{ marginTop: '16px' }}>
          <h3 className="section-subtitle" style={{ color: '#842029' }}>
            Chi tiết các lỗi vi phạm phát hiện trên Hóa đơn ({violations.length} lỗi):
          </h3>
          <div className="excel-table-wrapper">
            <table className="excel-table">
              <thead>
                <tr>
                  <th style={{ width: '42px' }}>#</th>
                  <th style={{ width: '110px' }}>Mức độ</th>
                  <th style={{ width: '190px' }}>Loại vi phạm</th>
                  <th style={{ width: '170px' }}>Trường vi phạm</th>
                  <th style={{ width: '155px' }}>Giá trị trên Hóa đơn</th>
                  <th style={{ width: '175px' }}>Giá trị chuẩn (HĐ / Luật)</th>
                  <th style={{ width: '210px' }}>Vị trí / Căn cứ điều khoản</th>
                  <th>Giải thích chi tiết &amp; Trích dẫn</th>
                </tr>
              </thead>
              <tbody>
                {violations.map((v, idx) => (
                  <tr key={idx} className="row-violation">
                    <td className="row-num">{idx + 1}</td>
                    <td>
                      <span
                        className={`badge ${
                          v.severity === 'CRITICAL' ? 'badge-danger' : 'badge-warning'
                        }`}
                      >
                        {v.severity}
                      </span>
                    </td>
                    <td>
                      <strong>{v.category}</strong>
                    </td>
                    <td>
                      <div>{v.field_label}</div>
                      <code style={{ fontSize: '11px', color: '#666' }}>{v.field_key}</code>
                    </td>
                    <td style={{ color: '#b02a37', fontWeight: 600 }}>
                      {v.invoice_value}
                    </td>
                    <td style={{ color: '#0f5132', fontWeight: 600 }}>
                      {v.expected_value}
                    </td>
                    <td>{v.location}</td>
                    <td>
                      {v.explanation_html ? (
                        <div
                          dangerouslySetInnerHTML={{ __html: v.explanation_html }}
                        />
                      ) : (
                        v.explanation
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Passed Checks */}
      {passedChecks.length > 0 && (
        <div style={{ marginTop: '16px' }}>
          <h3 className="section-subtitle" style={{ color: '#0f5132' }}>
            Các hạng mục kiểm tra Hợp lệ ({passedChecks.length} hạng mục đạt chuẩn):
          </h3>
          <div className="passed-grid">
            {passedChecks.map((pc, idx) => (
              <div key={idx} className="passed-item">
                <span className="passed-icon">✓</span>
                <div>
                  <strong>{pc.label}:</strong> <span>{pc.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* AI Agent Narrative with [SOURCE:id] Citations */}
      {report.rendered_narrative_html && (
        <div style={{ marginTop: '16px' }}>
          <h3 className="section-subtitle">
            Báo cáo tổng hợp từ AI Compliance Agent (kèm trích dẫn RAG <code>apply_numeric_citations</code>):
          </h3>
          <div
            className="narrative-box"
            dangerouslySetInnerHTML={{
              __html: report.rendered_narrative_html.replace(/\n/g, '<br/>'),
            }}
          />
        </div>
      )}

      {/* Interactive Chat with AI Compliance Agent */}
      <div className="agent-chat-box">
        <h3 className="section-subtitle">
          Hỏi đáp trực tiếp với AI Compliance Agent về Hóa đơn &amp; Hợp đồng này:
        </h3>
        {chatHistory.length > 0 && (
          <div className="chat-messages">
            {chatHistory.map((m, i) => (
              <div key={i} className={`chat-msg chat-msg-${m.role}`}>
                <strong>
                  {m.role === 'user'
                    ? 'Bạn: '
                    : m.role === 'agent'
                    ? `AI Agent (${m.model}): `
                    : 'Thông báo: '}
                </strong>
                <span
                  dangerouslySetInnerHTML={{
                    __html: (m.text || '').replace(/\n/g, '<br/>'),
                  }}
                />
              </div>
            ))}
          </div>
        )}
        <form onSubmit={handleChatSubmit} style={{ display: 'flex', gap: '8px' }}>
          <input
            type="text"
            placeholder="Nhập câu hỏi cho AI Agent (VD: Hóa đơn này có đủ điều kiện thanh toán đợt 2 theo Điều 3 Hợp đồng không?)..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            style={{ flex: 1 }}
            disabled={asking}
          />
          <button type="submit" className="btn btn-primary" disabled={asking}>
            {asking ? 'Đang hỏi AI...' : 'Gửi câu hỏi'}
          </button>
        </form>
      </div>
    </section>
  );
}

