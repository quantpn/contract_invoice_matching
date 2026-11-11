import React, { useState } from 'react';

export default function ContractPanel({
  contracts,
  selectedContractId,
  onSelectContract,
  onUploadContract,
  onDeleteContract,
  sampleFiles,
  onLoadSample,
  loading,
}) {
  const [showRawText, setShowRawText] = useState(false);
  const selectedContract = contracts.find((c) => c.id === selectedContractId) || null;
  const sampleContracts = (sampleFiles || []).filter((f) => f.suggested_type === 'contract');

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await onUploadContract(file);
    e.target.value = '';
  };

  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">1. Hợp đồng gốc (Source of Truth - RAG Context)</h2>
          <p className="card-desc">
            Tải lên các loại Hợp đồng để AI bóc tách điều khoản và lập chỉ mục Vector RAG (<code>AIAgentSource</code> &amp; <code>AIEmbedding</code>).
          </p>
        </div>

        <div className="action-row">
          <label className="btn btn-primary" style={{ cursor: 'pointer' }}>
            + Tải file Hợp đồng lên (.pdf, .docx, ảnh)
            <input
              type="file"
              accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
              onChange={handleFileChange}
              style={{ display: 'none' }}
              disabled={loading}
            />
          </label>

          {sampleContracts.map((sc) => (
            <button
              key={sc.filename}
              type="button"
              className="btn btn-outline"
              onClick={() => onLoadSample(sc.filename, 'contract')}
              disabled={loading}
              title="Nạp nhanh từ /home/quan/Documents/Data"
            >
              Nạp mẫu: {sc.filename}
            </button>
          ))}
        </div>
      </div>

      <div className="contract-selector-bar">
        <label>
          <strong>Chế độ chọn Hợp đồng đối chiếu (RAG Sources):</strong>
        </label>
        <div style={{ display: 'flex', gap: '8px', flex: 1 }}>
          <select
            value={selectedContractId || ''}
            onChange={(e) => onSelectContract(e.target.value ? Number(e.target.value) : null)}
            style={{ flex: 1 }}
          >
            <option value="">
              🤖 Tự động tìm Hợp đồng liên quan trong Kho bằng Vector RAG (Chuẩn Odoo-ET _build_rag_context)
            </option>
            {contracts.map((c) => (
              <option key={c.id} value={c.id}>
                📌 [Ghim cố định HĐ #{c.id} | Source ID: {c.source_id}] {c.filename} — Số HĐ: {c.contract_number || 'N/A'} — Tổng: {Number(c.total_amount || 0).toLocaleString('vi-VN')} đ
              </option>
            ))}
          </select>

          {selectedContract && (
            <button
              type="button"
              className="btn btn-danger-outline"
              onClick={() => onDeleteContract(selectedContract.id)}
            >
              Xóa HĐ
            </button>
          )}
        </div>
      </div>

      {selectedContract ? (
        <div className="contract-summary-box" id={`contract-source-${selectedContract.source_id}`}>
          <div className="summary-grid">
            <div>
              <span className="meta-label">Số Hợp đồng &amp; Loại:</span>
              <div>
                <strong>{selectedContract.contract_number || 'N/A'}</strong> ({selectedContract.contract_type})
              </div>
            </div>
            <div>
              <span className="meta-label">Ngày ký:</span>
              <div>{selectedContract.signing_date || 'N/A'}</div>
            </div>
            <div>
              <span className="meta-label">Bên Mua (Bên A):</span>
              <div>
                <strong>{selectedContract.buyer_name}</strong> — MST: <code>{selectedContract.buyer_tax_code || 'N/A'}</code>
              </div>
            </div>
            <div>
              <span className="meta-label">Bên Bán (Bên B):</span>
              <div>
                <strong>{selectedContract.seller_name}</strong> — MST: <code>{selectedContract.seller_tax_code || 'N/A'}</code>
              </div>
            </div>
            <div>
              <span className="meta-label">Thuế suất VAT chuẩn:</span>
              <div>
                <span className="badge badge-info">{selectedContract.vat_rate}%</span>
              </div>
            </div>
            <div>
              <span className="meta-label">Tổng giá trị Hợp đồng:</span>
              <div>
                <strong style={{ color: '#0f5132' }}>
                  {Number(selectedContract.total_amount || 0).toLocaleString('vi-VN')} VND
                </strong>
              </div>
            </div>
          </div>

          {selectedContract.summary?.items?.length > 0 && (
            <div style={{ marginTop: '10px' }}>
              <div className="meta-label" style={{ marginBottom: '4px' }}>
                Danh mục Hàng hóa / Dịch vụ trong Hợp đồng gốc:
              </div>
              <table className="mini-table">
                <thead>
                  <tr>
                    <th>STT</th>
                    <th>Tên hàng hóa / Quy cách</th>
                    <th>Model</th>
                    <th>ĐVT</th>
                    <th>SL</th>
                    <th>Đơn giá</th>
                    <th>Thành tiền</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedContract.summary.items.map((it, idx) => (
                    <tr key={idx}>
                      <td>{it.stt || idx + 1}</td>
                      <td>{it.name}</td>
                      <td>{it.model}</td>
                      <td>{it.unit}</td>
                      <td>{it.quantity}</td>
                      <td>{Number(it.unit_price || 0).toLocaleString('vi-VN')}</td>
                      <td>{Number(it.amount || 0).toLocaleString('vi-VN')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="contract-footer-meta">
            <span>
              RAG Source ID: <code>[SOURCE:{selectedContract.source_id}]</code> • Số phân đoạn (<code>AIEmbedding</code> chunks):{' '}
              <strong>{selectedContract.chunks?.length || 0}</strong> • Chế độ bóc tách:{' '}
              <code>{selectedContract.extraction_mode}</code>
            </span>
            <button
              type="button"
              className="btn-link"
              onClick={() => setShowRawText(!showRawText)}
            >
              {showRawText ? 'Ẩn văn bản gốc Hợp đồng' : 'Xem toàn văn Hợp đồng & RAG Chunks'}
            </button>
          </div>

          {showRawText && (
            <pre className="raw-text-box">{selectedContract.raw_text}</pre>
          )}
        </div>
      ) : contracts.length > 0 ? (
        <div className="contract-summary-box">
          <div className="meta-label" style={{ marginBottom: '6px' }}>
            Kho Hợp đồng gốc đang hoạt động trong <code>agent.sources</code> ({contracts.length} hợp đồng — AI sẽ tự động tìm kiếm Vector RAG trên toàn bộ các hợp đồng này):
          </div>
          <table className="mini-table">
            <thead>
              <tr>
                <th>Source ID</th>
                <th>Tên file Hợp đồng</th>
                <th>Loại Hợp đồng</th>
                <th>Số HĐ</th>
                <th>Bên Mua (MST)</th>
                <th>Bên Bán (MST)</th>
                <th>Tổng giá trị</th>
                <th>Số Chunks</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {contracts.map((c) => (
                <tr key={c.id} id={`contract-source-${c.source_id}`}>
                  <td>
                    <code>[SOURCE:{c.source_id}]</code>
                  </td>
                  <td>
                    <strong>{c.filename}</strong>
                  </td>
                  <td>{c.contract_type}</td>
                  <td>{c.contract_number || 'N/A'}</td>
                  <td>
                    {c.buyer_name} ({c.buyer_tax_code || 'N/A'})
                  </td>
                  <td>
                    {c.seller_name} ({c.seller_tax_code || 'N/A'})
                  </td>
                  <td>{Number(c.total_amount || 0).toLocaleString('vi-VN')} đ</td>
                  <td>{c.chunks?.length || 0}</td>
                  <td>
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() => onSelectContract(c.id)}
                    >
                      Xem chi tiết
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-hint">
          Kho Hợp đồng (<code>agent.sources</code>) đang trống. Hãy nhập API Key ở góc phải phía trên rồi bấm <strong>"Nạp mẫu: Hop dong mua ban hang hoa 1.pdf"</strong> hoặc tải file hợp đồng của bạn lên.
        </div>
      )}
    </section>
  );
}

