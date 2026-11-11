import React, { useEffect, useState } from 'react';
import { apiClient } from './api/client';
import Navbar from './components/Navbar';
import ContractPanel from './components/ContractPanel';
import InvoiceExcelEditor from './components/InvoiceExcelEditor';
import AuditReportView from './components/AuditReportView';

export default function App() {
  const [config, setConfig] = useState(null);
  const [sampleFiles, setSampleFiles] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [selectedContractId, setSelectedContractId] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [selectedInvoice, setSelectedInvoice] = useState(null);
  const [currentReport, setCurrentReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [bannerMsg, setBannerMsg] = useState(null);

  const notify = (text, type = 'info') => {
    setBannerMsg({ text, type });
    setTimeout(() => {
      setBannerMsg((prev) => (prev?.text === text ? null : prev));
    }, 6000);
  };

  const fetchInitialData = async () => {
    try {
      const [cfg, samplesRes, contractsRes, invoicesRes] = await Promise.all([
        apiClient.getConfig(),
        apiClient.getSampleFiles(),
        apiClient.listContracts(),
        apiClient.listInvoices(),
      ]);
      setConfig(cfg);
      setSampleFiles(samplesRes.files || []);
      const cList = contractsRes.contracts || [];
      setContracts(cList);
      const invList = invoicesRes.invoices || [];
      setInvoices(invList);
      if (invList.length > 0 && !selectedInvoice) {
        setSelectedInvoice(invList[0]);
        setCurrentReport(invList[0].latest_report || null);
      }
    } catch (err) {
      notify(`Không thể kết nối Backend API: ${err.message}`, 'error');
    }
  };

  useEffect(() => {
    fetchInitialData();
  }, []);

  const handleSaveConfig = async (payload) => {
    const updated = await apiClient.updateConfig(payload);
    setConfig(updated);
    notify(`Đã cập nhật model AI: ${updated.llm_model} (${updated.provider})`, 'success');
  };

  const handleUploadContract = async (file) => {
    setLoading(true);
    try {
      const c = await apiClient.uploadContract(file);
      const res = await apiClient.listContracts();
      setContracts(res.contracts || []);
      notify(`Đã tải lên & lập chỉ mục Hợp đồng "${c.filename}" vào kho agent.sources (Source ID: ${c.source_id})`, 'success');
    } catch (err) {
      notify(`Lỗi tải hợp đồng: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteContract = async (id) => {
    setLoading(true);
    try {
      await apiClient.deleteContract(id);
      const res = await apiClient.listContracts();
      const list = res.contracts || [];
      setContracts(list);
      if (selectedContractId === id) {
        setSelectedContractId(null);
      }
      notify('Đã xóa hợp đồng.', 'info');
    } catch (err) {
      notify(`Lỗi xóa hợp đồng: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleUploadInvoice = async (file) => {
    setLoading(true);
    try {
      const inv = await apiClient.uploadInvoice(file, selectedContractId);
      const res = await apiClient.listInvoices();
      setInvoices(res.invoices || []);
      setSelectedInvoice(inv);
      setCurrentReport(inv.latest_report || null);
      notify(`Đã bóc tách Hóa đơn "${inv.filename}" thành bảng Key-Value (${inv.fields?.length || 0} trường). Hãy kiểm tra/chỉnh sửa trước khi Xác nhận!`, 'success');
    } catch (err) {
      notify(`Lỗi tải hóa đơn: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleLoadSample = async (filename, docType) => {
    setLoading(true);
    try {
      const res = await apiClient.loadSampleFile(filename, docType, selectedContractId);
      if (res.type === 'contract') {
        const cList = await apiClient.listContracts();
        setContracts(cList.contracts || []);
        notify(`Đã nạp Hợp đồng mẫu "${filename}" vào kho agent.sources!`, 'success');
      } else {
        const invList = await apiClient.listInvoices();
        setInvoices(invList.invoices || []);
        setSelectedInvoice(res.invoice);
        setCurrentReport(res.invoice.latest_report || null);
        notify(`Đã nạp & bóc tách Hóa đơn mẫu "${filename}". Bạn có thể sửa bảng dưới đây rồi bấm Xác nhận & Đối chiếu!`, 'success');
      }
    } catch (err) {
      notify(`Lỗi nạp file mẫu: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleSelectInvoice = (inv) => {
    setSelectedInvoice(inv);
    setCurrentReport(inv?.latest_report || null);
  };

  const handleSaveFields = async (invoiceId, fields, lineItems) => {
    setLoading(true);
    try {
      const updated = await apiClient.updateInvoiceFields(
        invoiceId,
        fields,
        lineItems,
        selectedContractId
      );
      setSelectedInvoice(updated);
      const invList = await apiClient.listInvoices();
      setInvoices(invList.invoices || []);
      notify('Đã lưu các chỉnh sửa trên bảng Hóa đơn!', 'success');
      return updated;
    } catch (err) {
      notify(`Lỗi lưu bảng: ${err.message}`, 'error');
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const handleReExtract = async (invoiceId) => {
    setLoading(true);
    try {
      const updated = await apiClient.reExtractInvoice(invoiceId);
      setSelectedInvoice(updated);
      const invList = await apiClient.listInvoices();
      setInvoices(invList.invoices || []);
      notify('Đã bóc tách lại Hóa đơn bằng mô hình AI!', 'success');
    } catch (err) {
      notify(`Lỗi bóc tách AI: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteInvoice = async (invoiceId) => {
    setLoading(true);
    try {
      await apiClient.deleteInvoice(invoiceId);
      const invList = await apiClient.listInvoices();
      const list = invList.invoices || [];
      setInvoices(list);
      const next = list.length > 0 ? list[0] : null;
      setSelectedInvoice(next);
      setCurrentReport(next?.latest_report || null);
      notify('Đã xóa hóa đơn.', 'info');
    } catch (err) {
      notify(`Lỗi xóa hóa đơn: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleReconcile = async (invoiceId, fields, lineItems) => {
    setLoading(true);
    try {
      // 1. Save any edits user made in the Excel table first
      await apiClient.updateInvoiceFields(
        invoiceId,
        fields,
        lineItems,
        selectedContractId
      );
      // 2. Run AI compliance reconciliation (if selectedContractId is null, Backend automatically searches across all agent.sources via Vector RAG)
      const res = await apiClient.reconcileInvoice(
        invoiceId,
        selectedContractId
      );
      setCurrentReport(res.report);
      if (res.invoice) {
        setSelectedInvoice(res.invoice);
      }
      const invList = await apiClient.listInvoices();
      setInvoices(invList.invoices || []);
      if (res.report.overall_status === 'GOOD') {
        notify('Đối chiếu hoàn tất: HÓA ĐƠN HỢP LỆ (GOOD)!', 'success');
      } else {
        notify(
          `Đối chiếu hoàn tất: Phát hiện ${res.report.violations?.length || 0} lỗi VI PHẠM trên hóa đơn!`,
          'error'
        );
      }
    } catch (err) {
      notify(`Lỗi khi đối chiếu: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleAskAgent = async (prompt) => {
    return await apiClient.chatWithAgent(
      prompt,
      selectedInvoice?.id || null,
      selectedContractId || null
    );
  };

  const matchedContractId =
    selectedContractId || currentReport?.contract_id || selectedInvoice?.contract_id || null;
  const activeContract = contracts.find((c) => c.id === matchedContractId) || null;

  return (
    <div className="app-layout">
      <Navbar config={config} onSaveConfig={handleSaveConfig} />

      <main className="main-container">
        {bannerMsg && (
          <div className={`toast-banner toast-${bannerMsg.type}`}>
            <span>{bannerMsg.text}</span>
            <button
              type="button"
              className="btn-icon"
              onClick={() => setBannerMsg(null)}
            >
              ×
            </button>
          </div>
        )}

        <ContractPanel
          contracts={contracts}
          selectedContractId={selectedContractId}
          onSelectContract={setSelectedContractId}
          onUploadContract={handleUploadContract}
          onDeleteContract={handleDeleteContract}
          sampleFiles={sampleFiles}
          onLoadSample={handleLoadSample}
          loading={loading}
        />

        <InvoiceExcelEditor
          invoices={invoices}
          selectedInvoice={selectedInvoice}
          onSelectInvoice={handleSelectInvoice}
          onUploadInvoice={handleUploadInvoice}
          onSaveFields={handleSaveFields}
          onReExtract={handleReExtract}
          onReconcile={handleReconcile}
          onDeleteInvoice={handleDeleteInvoice}
          sampleFiles={sampleFiles}
          onLoadSample={handleLoadSample}
          loading={loading}
        />

        <AuditReportView
          report={currentReport}
          invoice={selectedInvoice}
          contract={activeContract}
          onAskAgent={handleAskAgent}
        />
      </main>
    </div>
  );
}

