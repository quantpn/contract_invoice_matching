const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000/api/v1';

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `HTTP Error ${res.status}`);
  }
  return data;
}

export const apiClient = {
  getConfig: () => request('/config'),
  updateConfig: (payload) =>
    request('/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  getSampleFiles: () => request('/sample-files'),
  loadSampleFile: (filename, docType = 'auto', contractId = null) =>
    request('/sample-files/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename,
        doc_type: docType,
        contract_id: contractId,
      }),
    }),

  listContracts: () => request('/contracts'),
  uploadContract: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return request('/contracts/upload', {
      method: 'POST',
      body: formData,
    });
  },
  deleteContract: (id) => request(`/contracts/${id}`, { method: 'DELETE' }),

  listInvoices: () => request('/invoices'),
  uploadInvoice: (file, contractId = null) => {
    const formData = new FormData();
    formData.append('file', file);
    if (contractId !== null && contractId !== undefined) {
      formData.append('contract_id', String(contractId));
    }
    return request('/invoices/upload', {
      method: 'POST',
      body: formData,
    });
  },
  updateInvoiceFields: (invoiceId, fields, lineItems, contractId = null) =>
    request(`/invoices/${invoiceId}/fields`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fields,
        line_items: lineItems,
        contract_id: contractId,
      }),
    }),
  reExtractInvoice: (invoiceId) =>
    request(`/invoices/${invoiceId}/re-extract`, { method: 'POST' }),
  deleteInvoice: (invoiceId) =>
    request(`/invoices/${invoiceId}`, { method: 'DELETE' }),

  reconcileInvoice: (invoiceId, contractId = null) =>
    request('/audit/reconcile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        invoice_id: invoiceId,
        contract_id: contractId,
      }),
    }),

  chatWithAgent: (prompt, invoiceId = null, contractId = null) =>
    request('/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        invoice_id: invoiceId,
        contract_id: contractId,
      }),
    }),
};

