import React, { useState } from 'react';

export default function Navbar({ config, onSaveConfig }) {
  const [showConfig, setShowConfig] = useState(false);
  const [llmModel, setLlmModel] = useState(config?.llm_model || 'gpt-4.1');
  const [responseStyle, setResponseStyle] = useState(config?.response_style || 'analytical');
  const [openaiKey, setOpenaiKey] = useState('');
  const [googleKey, setGoogleKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  const handleOpen = () => {
    setLlmModel(config?.llm_model || 'gpt-4.1');
    setResponseStyle(config?.response_style || 'analytical');
    setMsg('');
    setShowConfig(!showConfig);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setMsg('');
    try {
      const payload = {
        llm_model: llmModel,
        response_style: responseStyle,
      };
      if (openaiKey.trim()) payload.openai_key = openaiKey.trim();
      if (googleKey.trim()) payload.google_key = googleKey.trim();
      await onSaveConfig(payload);
      setOpenaiKey('');
      setGoogleKey('');
      setMsg('Đã lưu cấu hình LLM & API Key thành công!');
    } catch (err) {
      setMsg(`Lỗi: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <header className="navbar">
      <div className="navbar-inner">
        <div>
          <h1 className="navbar-title">
            AI Agent Đối soát Hóa đơn &amp; Hợp đồng
          </h1>
          <p className="navbar-subtitle">
            Kiến trúc Clean Architecture (Refactored từ module <code>ai</code> &amp; <code>ai_fields</code> của Odoo Enterprise 19)
          </p>
        </div>

        <div className="navbar-actions">
          <span className={`badge ${config?.active_key_ready ? 'badge-success' : 'badge-warning'}`}>
            Model: <strong>{config?.llm_model || 'gpt-4.1'}</strong> ({config?.provider || 'openai'})
            {' • '}
            {config?.active_key_ready ? 'Đã có API Key' : 'Chế độ Local / Chưa nhập API Key'}
          </span>
          <button type="button" className="btn btn-outline" onClick={handleOpen}>
            ⚙ Cấu hình API Key &amp; Model
          </button>
        </div>
      </div>

      {showConfig && (
        <form className="config-panel" onSubmit={handleSubmit}>
          <div className="config-grid">
            <div className="form-group">
              <label>Chọn Mô hình AI (PROVIDERS từ Odoo-ET):</label>
              <select value={llmModel} onChange={(e) => setLlmModel(e.target.value)}>
                {(config?.providers || []).map((prov) => (
                  <optgroup key={prov.name} label={`${prov.display_name} (Embedding: ${prov.embedding_model})`}>
                    {prov.models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label} ({m.id})
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Phong cách phản hồi (TEMPERATURE_MAP):</label>
              <select value={responseStyle} onChange={(e) => setResponseStyle(e.target.value)}>
                <option value="analytical">Analytical (Temperature 0.2 - Chuẩn kiểm toán)</option>
                <option value="balanced">Balanced (Temperature 0.5 - Cân bằng)</option>
                <option value="creative">Creative (Temperature 0.8 - Linh hoạt)</option>
              </select>
            </div>

            <div className="form-group">
              <label>
                OpenAI API Key {config?.has_openai_key ? `(Hiện tại: ${config.openai_key_masked})` : '(Chưa cấu hình)'}:
              </label>
              <input
                type="password"
                placeholder="sk-... (Để trống nếu giữ nguyên)"
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>
                Google Gemini API Key {config?.has_google_key ? `(Hiện tại: ${config.google_key_masked})` : '(Chưa cấu hình)'}:
              </label>
              <input
                type="password"
                placeholder="AIza... (Để trống nếu giữ nguyên)"
                value={googleKey}
                onChange={(e) => setGoogleKey(e.target.value)}
              />
            </div>
          </div>

          <div className="config-footer">
            <span className="text-muted">
              * Khi cấu hình API Key, hệ thống sẽ gọi trực tiếp <code>LLMApiService._request_llm</code> với Strict JSON Schema (<code>ai_fields</code>) và Vector RAG (<code>AIEmbedding</code>).
            </span>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              {msg && <span className="status-msg">{msg}</span>}
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? 'Đang lưu...' : 'Lưu cấu hình'}
              </button>
              <button type="button" className="btn btn-secondary" onClick={() => setShowConfig(false)}>
                Đóng
              </button>
            </div>
          </div>
        </form>
      )}
    </header>
  );
}

