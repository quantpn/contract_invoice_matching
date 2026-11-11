import React, { useEffect, useState } from 'react';

export default function InvoiceExcelEditor({
  invoices,
  selectedInvoice,
  onSelectInvoice,
  onUploadInvoice,
  onSaveFields,
  onReExtract,
  onReconcile,
  onDeleteInvoice,
  sampleFiles,
  onLoadSample,
  loading,
}) {
  const [fields, setFields] = useState([]);
  const [lineItems, setLineItems] = useState([]);
  const [activeTab, setActiveTab] = useState('kv'); // 'kv' | 'items' | 'raw'
  const [dirty, setDirty] = useState(false);

  const sampleInvoices = (sampleFiles || []).filter((f) => f.suggested_type === 'invoice');

  useEffect(() => {
    if (selectedInvoice) {
      setFields(selectedInvoice.fields || []);
      setLineItems(selectedInvoice.line_items || []);
      setDirty(false);
    } else {
      setFields([]);
      setLineItems([]);
      setDirty(false);
    }
  }, [selectedInvoice]);

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await onUploadInvoice(file);
    e.target.value = '';
  };

  const handleFieldChange = (idx, prop, val) => {
    const next = [...fields];
    const updatedRow = { ...next[idx], [prop]: val };
    if (prop === 'value') {
      updatedRow.could_not_resolve = !String(val || '').trim();
      if (!updatedRow.could_not_resolve) {
        updatedRow.unresolved_cause = null;
      }
    }
    next[idx] = updatedRow;
    setFields(next);
    setDirty(true);
  };

  const handleAddFieldRow = () => {
    setFields([
      ...fields,
      {
        key: `custom_field_${fields.length + 1}`,
        label: 'Trường bổ sung mới',
        group: 'VI. Trường tùy chỉnh',
        field_type: 'char',
        value: '',
        could_not_resolve: false,
        unresolved_cause: null,
      },
    ]);
    setDirty(true);
  };

  const handleDeleteFieldRow = (idx) => {
    setFields(fields.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const handleItemChange = (idx, prop, val) => {
    const next = [...lineItems];
    next[idx] = { ...next[idx], [prop]: val };
    setLineItems(next);
    setDirty(true);
  };

  const handleAddItemRow = () => {
    setLineItems([
      ...lineItems,
      {
        stt: lineItems.length + 1,
        name: '',
        model: '',
        unit: 'Bộ',
        quantity: 1,
        unit_price: 0,
        amount: 0,
        currency: 'VND',
        note: '',
      },
    ]);
    setDirty(true);
  };

  const handleDeleteItemRow = (idx) => {
    setLineItems(lineItems.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const handleSaveOnly = async () => {
    if (!selectedInvoice) return;
    await onSaveFields(selectedInvoice.id, fields, lineItems);
    setDirty(false);
  };

  const handleConfirmAndReconcile = async () => {
    if (!selectedInvoice) return;
    await onReconcile(selectedInvoice.id, fields, lineItems);
    setDirty(false);
  };

  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">
            2. Tải Hóa đơn &amp; Bảng Bóc tách Key-Value kiểu Excel (Human-in-the-loop)
          </h2>
          <p className="card-desc">
            AI trích xuất Hóa đơn thành bảng Key-Value và bảng Hàng hóa. Bạn có thể sửa trực tiếp bất kỳ tên trường hoặc giá trị nào trên bảng trước khi ấn <strong>Xác nhận &amp; Đối chiếu</strong>.
          </p>
        </div>

        <div className="action-row">
          <label className="btn btn-primary" style={{ cursor: 'pointer' }}>
            + Tải Hóa đơn lên (.pdf, .docx, ảnh)
            <input
              type="file"
              accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
              onChange={handleFileChange}
              style={{ display: 'none' }}
              disabled={loading}
            />
          </label>
        </div>
      </div>

      {/* Quick sample loader bar for /home/quan/Documents/Data */}
      {sampleInvoices.length > 0 && (
        <div className="sample-bar">
          <span className="meta-label" style={{ marginRight: '6px' }}>
            Nạp nhanh Hóa đơn test (<code>/home/quan/Documents/Data</code>):
          </span>
          {sampleInvoices.map((si) => (
            <button
              key={si.filename}
              type="button"
              className="btn btn-xs btn-outline"
              onClick={() => onLoadSample(si.filename, 'invoice')}
              disabled={loading}
            >
              {si.filename}
            </button>
          ))}
        </div>
      )}

      {/* Invoice selector */}
      <div className="contract-selector-bar">
        <label>
          <strong>Hóa đơn đang làm việc:</strong>
        </label>
        <div style={{ display: 'flex', gap: '8px', flex: 1 }}>
          <select
            value={selectedInvoice?.id || ''}
            onChange={(e) => {
              const id = Number(e.target.value);
              const inv = invoices.find((x) => x.id === id) || null;
              onSelectInvoice(inv);
            }}
            style={{ flex: 1 }}
          >
            <option value="">-- Chọn Hóa đơn đã tải lên --</option>
            {invoices.map((inv) => (
              <option key={inv.id} value={inv.id}>
                [Hóa đơn #{inv.id}] {inv.filename} — Trạng thái: {inv.status}
                {inv.latest_report ? ` (${inv.latest_report.overall_status})` : ''}
              </option>
            ))}
          </select>

          {selectedInvoice && (
            <>
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => onReExtract(selectedInvoice.id)}
                disabled={loading}
                title="Gọi lại LLMApiService với INVOICE_EXTRACTION_SCHEMA"
              >
                ↻ Bóc tách lại bằng AI
              </button>
              <button
                type="button"
                className="btn btn-danger-outline"
                onClick={() => onDeleteInvoice(selectedInvoice.id)}
                disabled={loading}
              >
                Xóa HĐơn
              </button>
            </>
          )}
        </div>
      </div>

      {selectedInvoice ? (
        <div>
          <div className="excel-toolbar">
            <div className="tab-group">
              <button
                type="button"
                className={`tab-btn ${activeTab === 'kv' ? 'active' : ''}`}
                onClick={() => setActiveTab('kv')}
              >
                Sheet 1: Bảng Trường Key-Value ({fields.length} dòng)
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'items' ? 'active' : ''}`}
                onClick={() => setActiveTab('items')}
              >
                Sheet 2: Chi tiết Hàng hóa / Dịch vụ ({lineItems.length} dòng)
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'raw' ? 'active' : ''}`}
                onClick={() => setActiveTab('raw')}
              >
                Sheet 3: Văn bản thô bóc tách (Raw Text)
              </button>
            </div>

            <div className="excel-actions">
              {dirty && (
                <span className="badge badge-warning">Đã chỉnh sửa (Chưa lưu)</span>
              )}
              <button
                type="button"
                className="btn btn-outline"
                onClick={handleSaveOnly}
                disabled={loading}
              >
                💾 Lưu chỉnh sửa bảng
              </button>
              <button
                type="button"
                className="btn btn-success"
                onClick={handleConfirmAndReconcile}
                disabled={loading}
              >
                {loading
                  ? '⏳ Đang đối chiếu AI...'
                  : '✓ Xác nhận chốt bảng & Đối chiếu Hợp đồng'}
              </button>
            </div>
          </div>

          {activeTab === 'kv' && (
            <div className="excel-table-wrapper">
              <table className="excel-table">
                <thead>
                  <tr>
                    <th style={{ width: '44px' }}>#</th>
                    <th style={{ width: '170px' }}>Nhóm thông tin</th>
                    <th style={{ width: '220px' }}>Tên trường (Label - Có thể sửa)</th>
                    <th style={{ width: '175px' }}>Mã trường (Key)</th>
                    <th>Giá trị bóc tách từ Hóa đơn (Value - Click để sửa)</th>
                    <th style={{ width: '185px' }}>Trạng thái bóc tách</th>
                    <th style={{ width: '44px' }}>Xóa</th>
                  </tr>
                </thead>
                <tbody>
                  {fields.map((row, idx) => {
                    const isEmpty = !String(row.value || '').trim();
                    return (
                      <tr
                        key={idx}
                        className={row.could_not_resolve || isEmpty ? 'row-warning' : ''}
                      >
                        <td className="row-num">{idx + 1}</td>
                        <td>
                          <input
                            type="text"
                            className="cell-input muted"
                            value={row.group || ''}
                            onChange={(e) => handleFieldChange(idx, 'group', e.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className="cell-input bold"
                            value={row.label || ''}
                            onChange={(e) => handleFieldChange(idx, 'label', e.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className="cell-input code"
                            value={row.key || ''}
                            onChange={(e) => handleFieldChange(idx, 'key', e.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className="cell-input value-cell"
                            placeholder="(Đang bỏ trống trên hóa đơn - nhập để bổ sung/sửa)"
                            value={row.value ?? ''}
                            onChange={(e) => handleFieldChange(idx, 'value', e.target.value)}
                          />
                        </td>
                        <td>
                          {row.could_not_resolve ? (
                            <span
                              className="badge badge-danger"
                              title={row.unresolved_cause || 'Bỏ trống trên hóa đơn'}
                            >
                              ⚠ Bỏ trống / Thiếu
                            </span>
                          ) : isEmpty ? (
                            <span className="badge badge-warning">Trống</span>
                          ) : (
                            <span className="badge badge-success">✓ Đã bóc tách</span>
                          )}
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <button
                            type="button"
                            className="btn-icon"
                            onClick={() => handleDeleteFieldRow(idx)}
                            title="Xóa dòng này"
                          >
                            ×
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              <div className="table-bottom-bar">
                <button type="button" className="btn btn-outline btn-sm" onClick={handleAddFieldRow}>
                  + Thêm trường Key-Value mới
                </button>
                <span className="text-muted">
                  Mẹo: Bạn có thể sửa trực tiếp các ô <strong>Giá trị bóc tách (Value)</strong> hoặc <strong>Tên trường (Label)</strong> giống như trên Excel trước khi ấn Xác nhận.
                </span>
              </div>
            </div>
          )}

          {activeTab === 'items' && (
            <div className="excel-table-wrapper">
              <table className="excel-table">
                <thead>
                  <tr>
                    <th style={{ width: '50px' }}>STT</th>
                    <th>Tên hàng hóa, dịch vụ</th>
                    <th style={{ width: '120px' }}>Model / Ký hiệu</th>
                    <th style={{ width: '90px' }}>ĐVT</th>
                    <th style={{ width: '100px' }}>Số lượng</th>
                    <th style={{ width: '140px' }}>Đơn giá</th>
                    <th style={{ width: '150px' }}>Thành tiền</th>
                    <th style={{ width: '80px' }}>Tiền tệ</th>
                    <th style={{ width: '44px' }}>Xóa</th>
                  </tr>
                </thead>
                <tbody>
                  {lineItems.map((item, idx) => (
                    <tr key={idx}>
                      <td className="row-num">{idx + 1}</td>
                      <td>
                        <input
                          type="text"
                          className="cell-input"
                          value={item.name || ''}
                          onChange={(e) => handleItemChange(idx, 'name', e.target.value)}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className="cell-input"
                          value={item.model || ''}
                          onChange={(e) => handleItemChange(idx, 'model', e.target.value)}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className="cell-input"
                          value={item.unit || ''}
                          onChange={(e) => handleItemChange(idx, 'unit', e.target.value)}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          className="cell-input"
                          value={item.quantity ?? 0}
                          onChange={(e) => handleItemChange(idx, 'quantity', Number(e.target.value))}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          className="cell-input"
                          value={item.unit_price ?? 0}
                          onChange={(e) => handleItemChange(idx, 'unit_price', Number(e.target.value))}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          className="cell-input bold"
                          value={item.amount ?? 0}
                          onChange={(e) => handleItemChange(idx, 'amount', Number(e.target.value))}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className="cell-input"
                          value={item.currency || 'VND'}
                          onChange={(e) => handleItemChange(idx, 'currency', e.target.value)}
                        />
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <button
                          type="button"
                          className="btn-icon"
                          onClick={() => handleDeleteItemRow(idx)}
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="table-bottom-bar">
                <button type="button" className="btn btn-outline btn-sm" onClick={handleAddItemRow}>
                  + Thêm dòng hàng hóa
                </button>
              </div>
            </div>
          )}

          {activeTab === 'raw' && (
            <pre className="raw-text-box">{selectedInvoice.raw_text}</pre>
          )}
        </div>
      ) : (
        <div className="empty-hint">
          Chưa có Hóa đơn nào được chọn. Hãy bấm vào một trong các nút <strong>Nạp nhanh Hóa đơn test</strong> ở trên (ví dụ: <code>Hóa đơn 1.pdf</code>, <code>Hóa đơn 2.pdf</code>, <code>Vi phạm 1.pdf</code>) hoặc tải file hóa đơn của bạn lên.
        </div>
      )}
    </section>
  );
}

