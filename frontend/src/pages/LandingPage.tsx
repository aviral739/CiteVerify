import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Navbar, Footer } from '../components/layout/Navbar';
import { createDocument, seedDemoDocument, ApiError } from '../lib/api';

const MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB
const ALLOWED_EXTENSIONS = ['.pdf', '.docx'];

export const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<'file' | 'text'>('file');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Single claim form state
  const [claimText, setClaimText] = useState('');
  const [refInput, setRefInput] = useState('');

  const validateFile = (file: File): string | null => {
    const extension = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(extension)) {
      return `Unsupported file format (${extension || 'unknown'}). Only PDF and DOCX files are supported.`;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
      return `File size (${sizeMB} MB) exceeds the 20 MB limit. Please select a smaller manuscript.`;
    }
    return null;
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const validationError = validateFile(file);
      if (validationError) {
        setErrorMessage(validationError);
        setSelectedFile(null);
      } else {
        setSelectedFile(file);
        setErrorMessage(null);
      }
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      const validationError = validateFile(file);
      if (validationError) {
        setErrorMessage(validationError);
        setSelectedFile(null);
      } else {
        setSelectedFile(file);
        setErrorMessage(null);
      }
    }
  };

  const handleClearFile = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedFile(null);
    setErrorMessage(null);
  };

  const handleSubmitFile = async () => {
    if (!selectedFile || isSubmitting) return;

    const validationError = validateFile(selectedFile);
    if (validationError) {
      setErrorMessage(validationError);
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      // Connect to real backend: POST /api/documents
      const doc = await createDocument({
        title: selectedFile.name,
      });

      // Real document mode: navigate directly to analysis with actual document ID
      navigate(`/documents/${doc.id}/analysis`);
    } catch (err: any) {
      console.error("Document upload/registration failed:", err);
      let userMsg = "Failed to upload document. Please ensure the CiteVerify backend server is running.";
      if (err instanceof ApiError) {
        userMsg = `Server error (${err.statusCode}): ${err.message}`;
      } else if (err.message) {
        userMsg = err.message;
      }
      setErrorMessage(userMsg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDemoClick = async () => {
    if (isSubmitting) return;
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      // Call real backend demo endpoint: POST /api/documents/demo
      const doc = await seedDemoDocument('attention_is_all_you_need');
      navigate(`/documents/${doc.id}/analysis?mode=demo`);
    } catch (err: any) {
      console.warn("Backend demo call failed, using client demo fallback:", err);
      // Demonstrator fallback only for explicit demo mode when backend is unavailable
      navigate(`/documents/sample-demo-4092/analysis?mode=demo&offline=true`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSingleClaimSubmit = async () => {
    if (!claimText.trim() || isSubmitting) return;
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const doc = await createDocument({
        title: `Single Claim Check: "${claimText.slice(0, 40)}${claimText.length > 40 ? '...' : ''}"`,
        doi: refInput.trim() || undefined,
      });
      navigate(`/documents/${doc.id}/analysis`);
    } catch (err: any) {
      console.error("Single claim creation failed:", err);
      let userMsg = "Failed to verify single claim. Backend is unavailable.";
      if (err instanceof ApiError) {
        userMsg = `Server error (${err.statusCode}): ${err.message}`;
      } else if (err.message) {
        userMsg = err.message;
      }
      setErrorMessage(userMsg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-surface font-body-md text-body-md text-on-surface flex flex-col min-h-screen">
      <Navbar />

      <main className="flex flex-col relative w-full pt-28 pb-16 bg-surface min-h-screen px-4 sm:px-8">
        <div className="flex flex-col w-full pb-6 space-y-space-lg">
          <div className="max-w-4xl mx-auto w-full flex flex-col space-y-10">
            {/* Hero Section */}
            <section className="flex flex-col items-center text-center space-y-4 pt-2">
              <h1 className="font-headline-lg text-[2.5rem] leading-tight text-on-surface tracking-tight max-w-3xl font-medium">
                Does the paper you cited actually say that?
              </h1>
              <p className="font-body-lg text-[16px] text-on-surface-variant max-w-2xl leading-relaxed">
                Upload a paper or report. CiteVerify finds claims that cite sources, retrieves the originals, and shows the exact passage that supports, or doesn’t support, each claim. You review every finding.
              </p>

              <div className="flex flex-wrap items-center justify-center gap-2.5 pt-2">
                <span className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-surface-container text-on-surface font-label-md text-[14px]">
                  <span className="material-symbols-outlined text-[18px] text-secondary">check_circle</span>
                  Checks DOIs and titles
                </span>
                <span className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-surface-container text-on-surface font-label-md text-[14px]">
                  <span className="material-symbols-outlined text-[18px] text-error">flag</span>
                  Flags retracted papers
                </span>
                <span className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-surface-container text-on-surface font-label-md text-[14px]">
                  <span className="material-symbols-outlined text-[18px] text-primary">compare_arrows</span>
                  Compares numbers
                </span>
              </div>
            </section>

            {/* Document Upload Interface Box */}
            <section className="w-full bg-surface-container-lowest rounded-xl shadow-sm border border-outline-variant/30 p-6 sm:p-8 flex flex-col space-y-6">
              {/* Tab Selector */}
              <div className="flex border-b border-outline-variant/30" role="tablist">
                <button
                  type="button"
                  onClick={() => setActiveTab('file')}
                  className={`py-3 px-6 font-label-md text-[14px] font-semibold flex items-center gap-2 -mb-px transition-colors ${activeTab === 'file'
                      ? 'text-primary border-b-2 border-primary'
                      : 'text-on-surface-variant hover:text-on-surface border-b-2 border-transparent'
                    }`}
                >
                  <span className="material-symbols-outlined text-[18px]">upload_file</span>
                  Upload paper
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('text')}
                  className={`py-3 px-6 font-label-md text-[14px] font-semibold flex items-center gap-2 -mb-px transition-colors ${activeTab === 'text'
                      ? 'text-primary border-b-2 border-primary'
                      : 'text-on-surface-variant hover:text-on-surface border-b-2 border-transparent'
                    }`}
                >
                  <span className="material-symbols-outlined text-[18px]">edit_note</span>
                  Check one claim
                </button>
              </div>

              {errorMessage && (
                <div className="p-4 bg-error-container text-on-error-container rounded-lg text-sm flex items-start justify-between gap-3 border border-error/30 animate-fadeIn">
                  <div className="flex items-start gap-2.5">
                    <span className="material-symbols-outlined text-[20px] text-error shrink-0 mt-0.5">error</span>
                    <div className="flex flex-col">
                      <span className="font-semibold text-error">Validation / Upload Error</span>
                      <span className="text-[13px] mt-0.5">{errorMessage}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setErrorMessage(null)}
                    className="text-on-error-container/70 hover:text-on-error-container shrink-0 p-1 rounded hover:bg-error-container/80 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[18px]">close</span>
                  </button>
                </div>
              )}

              {/* Upload Tab */}
              {activeTab === 'file' && (
                <div className="flex flex-col space-y-6">
                  <label
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={handleDrop}
                    className="border-2 border-dashed border-outline-variant/60 rounded-xl p-8 sm:p-10 flex flex-col items-center justify-center text-center bg-surface-container-low/40 cursor-pointer hover:bg-surface-container-low/70 transition-colors"
                  >
                    <input
                      type="file"
                      accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      onChange={handleFileChange}
                      className="hidden"
                    />
                    <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center text-primary mb-3">
                      <span className="material-symbols-outlined text-[32px]">cloud_upload</span>
                    </div>
                    <p className="font-label-md text-[16px] text-on-surface font-semibold mb-1">
                      Drop a PDF or DOCX here or <span className="text-primary underline underline-offset-2">browse</span>
                    </p>
                    <p className="font-body-sm text-[14px] text-on-surface-variant">PDF or DOCX up to 20 MB</p>

                    {selectedFile && (
                      <div className="inline-flex items-center gap-2 mt-4 px-3.5 py-1.5 bg-surface-container-high rounded-full text-[14px] font-label-md text-primary shadow-xs">
                        <span className="material-symbols-outlined text-[18px]">description</span>
                        <span className="font-medium">{selectedFile.name}</span>
                        <span className="text-on-surface-variant text-xs">({(selectedFile.size / 1024 / 1024).toFixed(1)} MB)</span>
                        <button
                          type="button"
                          onClick={handleClearFile}
                          className="ml-1 text-on-surface-variant hover:text-error transition-colors p-0.5 rounded-full"
                          title="Remove file"
                        >
                          <span className="material-symbols-outlined text-[16px]">cancel</span>
                        </button>
                      </div>
                    )}
                  </label>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                    <div>
                      <button
                        type="button"
                        onClick={handleSubmitFile}
                        disabled={!selectedFile || isSubmitting}
                        className={`w-full min-h-[48px] py-3 px-5 rounded-lg font-label-md text-[14px] font-semibold flex items-center justify-center gap-2 transition-all ${selectedFile && !isSubmitting
                            ? 'bg-primary-container text-on-primary hover:bg-primary shadow-sm cursor-pointer'
                            : 'bg-primary-container text-inverse-on-surface opacity-50 cursor-not-allowed'
                          }`}
                      >
                        <span className={`material-symbols-outlined text-[18px] ${isSubmitting ? 'animate-spin' : ''}`}>
                          {isSubmitting ? 'sync' : 'search_check'}
                        </span>
                        <span>{isSubmitting ? 'Registering document...' : 'Check my citations'}</span>
                      </button>
                      <p className="font-body-sm text-[13px] text-outline text-center mt-1.5">
                        {selectedFile ? 'Ready to analyze with backend' : 'Choose a PDF or DOCX to enable'}
                      </p>
                    </div>

                    <div>
                      <button
                        type="button"
                        onClick={handleDemoClick}
                        disabled={isSubmitting}
                        className="w-full min-h-[48px] py-3 px-5 rounded-lg bg-surface-container-lowest text-primary font-label-md text-[14px] font-semibold border-2 border-primary hover:bg-surface-container-low transition-colors flex items-center justify-center gap-2 shadow-xs cursor-pointer disabled:opacity-50"
                      >
                        <span className="material-symbols-outlined text-[18px] text-primary">science</span>
                        <span>Try a sample paper with planted errors</span>
                      </button>
                      <p className="font-body-sm text-[13px] text-outline text-center mt-1.5">
                        Demonstration audit. No local file needed.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Single Claim Tab */}
              {activeTab === 'text' && (
                <div className="flex flex-col space-y-4">
                  <div className="flex flex-col space-y-1.5">
                    <label htmlFor="claim-input" className="font-label-md text-[14px] font-semibold text-on-surface">
                      Claim text
                    </label>
                    <textarea
                      id="claim-input"
                      rows={3}
                      value={claimText}
                      onChange={(e) => setClaimText(e.target.value)}
                      placeholder="e.g., A study found that a learning app improved test scores by 30%..."
                      className="w-full p-3 rounded-lg border border-outline-variant/60 bg-surface-container-low/30 text-[14px] font-body-md text-on-surface focus:outline-none focus:border-primary"
                    />
                  </div>

                  <div className="flex flex-col space-y-1.5">
                    <label htmlFor="ref-input" className="font-label-md text-[14px] font-semibold text-on-surface">
                      Reference (DOI or title)
                    </label>
                    <input
                      id="ref-input"
                      type="text"
                      value={refInput}
                      onChange={(e) => setRefInput(e.target.value)}
                      placeholder="e.g., 10.5555/12345678 or Rivera & Chen (2022)..."
                      className="w-full p-3 rounded-lg border border-outline-variant/60 bg-surface-container-low/30 text-[14px] font-body-md text-on-surface focus:outline-none focus:border-primary"
                    />
                  </div>

                  <div className="pt-2">
                    <button
                      type="button"
                      onClick={handleSingleClaimSubmit}
                      disabled={!claimText.trim() || isSubmitting}
                      className="w-full sm:w-auto min-h-[48px] py-3 px-8 rounded-lg bg-primary text-on-primary font-label-md text-[14px] font-semibold hover:bg-primary/90 transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                    >
                      <span className={`material-symbols-outlined text-[18px] ${isSubmitting ? 'animate-spin' : ''}`}>
                        {isSubmitting ? 'sync' : 'verified'}
                      </span>
                      <span>{isSubmitting ? 'Submitting claim...' : 'Verify single claim'}</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Disclaimer footer inside box */}
              <div className="pt-2 border-t border-outline-variant/20">
                <p className="font-body-sm text-[13px] text-on-surface-variant leading-relaxed text-center">
                  Your text is sent to an AI model and public scholarly databases for checking. Results are saved on this server so you can review and export them. CiteVerify checks only text it can legally access: full text when open access, otherwise the abstract.
                </p>
              </div>
            </section>

            {/* How It Works 5-Step Process */}
            <section className="w-full bg-surface-container-lowest rounded-xl p-5 border border-outline-variant/30 shadow-xs" id="how-it-works">
              <div className="grid grid-cols-1 sm:grid-cols-5 gap-4 text-center items-start">
                <div className="flex flex-col items-center gap-1.5 p-2">
                  <div className="flex items-center gap-2 font-label-md text-[14px] font-semibold text-primary">
                    <span className="w-6 h-6 rounded-full bg-primary-fixed text-primary flex items-center justify-center text-[12px] font-semibold">1</span>
                    <span>Upload</span>
                  </div>
                  <p className="font-body-sm text-[14px] text-on-surface-variant leading-tight">Add your PDF or DOCX</p>
                </div>

                <div className="flex flex-col items-center gap-1.5 p-2">
                  <div className="flex items-center gap-2 font-label-md text-[14px] font-semibold text-on-surface">
                    <span className="w-6 h-6 rounded-full bg-surface-container-high text-on-surface flex items-center justify-center text-[12px] font-semibold">2</span>
                    <span>Extract</span>
                  </div>
                  <p className="font-body-sm text-[14px] text-on-surface-variant leading-tight">Find claims and citations</p>
                </div>

                <div className="flex flex-col items-center gap-1.5 p-2">
                  <div className="flex items-center gap-2 font-label-md text-[14px] font-semibold text-on-surface">
                    <span className="w-6 h-6 rounded-full bg-surface-container-high text-on-surface flex items-center justify-center text-[12px] font-semibold">3</span>
                    <span>Retrieve</span>
                  </div>
                  <p className="font-body-sm text-[14px] text-on-surface-variant leading-tight">Locate the original papers</p>
                </div>

                <div className="flex flex-col items-center gap-1.5 p-2">
                  <div className="flex items-center gap-2 font-label-md text-[14px] font-semibold text-on-surface">
                    <span className="w-6 h-6 rounded-full bg-surface-container-high text-on-surface flex items-center justify-center text-[12px] font-semibold">4</span>
                    <span>Compare</span>
                  </div>
                  <p className="font-body-sm text-[14px] text-on-surface-variant leading-tight">Check claims against source text</p>
                </div>

                <div className="flex flex-col items-center gap-1.5 p-2">
                  <div className="flex items-center gap-2 font-label-md text-[14px] font-semibold text-on-surface">
                    <span className="w-6 h-6 rounded-full bg-surface-container-high text-on-surface flex items-center justify-center text-[12px] font-semibold">5</span>
                    <span>Report</span>
                  </div>
                  <p className="font-body-sm text-[14px] text-on-surface-variant leading-tight">Verdicts, evidence and links</p>
                </div>
              </div>
            </section>

            {/* Example Illustrative Card */}
            <section className="flex flex-col space-y-4" id="demo">
              <div className="flex flex-col space-y-1">
                <h2 className="font-headline-md text-headline-md text-on-surface font-medium">
                  Example result (illustrative)
                </h2>
                <p className="font-body-md text-[14px] text-on-surface-variant">
                  This is what a checked claim looks like.
                </p>
              </div>

              <div className="w-full bg-surface-container-lowest rounded-xl border border-outline-variant/30 shadow-sm p-6 flex flex-col space-y-5">
                <div className="p-3.5 rounded-lg bg-surface-container-low border border-outline-variant/20 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-[18px] text-primary shrink-0">menu_book</span>
                    <span className="font-body-md text-[14px] text-on-surface font-medium">
                      [3] Rivera & Chen (2022). Pilot evaluation of a mobile learning app. <span className="italic">Journal of Example Studies.</span>
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="font-code-sm text-[14px] text-primary underline">doi:10.5555/12345678</span>
                    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-container text-secondary font-label-md text-[14px] font-semibold">
                      <span className="material-symbols-outlined text-[14px]">verified</span>
                      Exact DOI match
                    </span>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-tertiary-fixed text-tertiary font-label-md text-[14px] font-semibold">
                    <span className="material-symbols-outlined text-[16px]">warning</span>
                    Partly supported
                  </span>
                  <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-error-container text-on-error-container font-label-md text-[14px] font-semibold">
                    <span className="material-symbols-outlined text-[16px]">error</span>
                    Quantitative mismatch
                  </span>
                  <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-surface-container-high text-on-surface-variant font-label-md text-[14px] font-semibold">
                    <span className="material-symbols-outlined text-[16px]">article</span>
                    Abstract only
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="p-4 rounded-lg bg-surface-container-low flex flex-col space-y-2 border border-outline-variant/20">
                    <div className="flex items-center justify-between text-[14px] font-label-md text-on-surface-variant">
                      <span className="font-semibold text-on-surface">In your document · p. 4</span>
                    </div>
                    <blockquote className="font-body-md text-[15px] text-on-surface italic leading-relaxed">
                      “A study found that a learning app improved test scores by <mark className="bg-error-container/40 text-error font-semibold not-italic px-1.5 py-0.5 rounded">30%</mark>.”
                    </blockquote>
                  </div>

                  <div className="p-4 rounded-lg bg-surface-container-low flex flex-col space-y-2 border border-outline-variant/20">
                    <div className="flex items-center justify-between text-[14px] font-label-md text-on-surface-variant">
                      <span className="font-semibold text-on-surface">In the cited paper · Abstract only</span>
                    </div>
                    <blockquote className="font-body-md text-[15px] text-on-surface-variant italic leading-relaxed">
                      “…<mark className="bg-surface-container-high text-primary font-medium px-1.5 py-0.5 rounded not-italic">test scores improved in a small pilot group (n = 24) after eight weeks of app use</mark>…”
                    </blockquote>
                    <div className="pt-1 font-code-sm text-[14px] text-outline">doi:10.5555/12345678</div>
                  </div>
                </div>

                <div className="p-3.5 rounded-lg bg-surface-container-low border border-outline-variant/20 flex items-center gap-2">
                  <span className="material-symbols-outlined text-[18px] text-primary shrink-0">info</span>
                  <p className="font-body-md text-[14px] text-on-surface leading-normal">
                    <span className="font-semibold">Verdict:</span> The paper reports improvement in a small pilot group, but no 30% increase.
                  </p>
                </div>

                <div className="p-3 rounded-lg bg-error-container/20 border border-error-container flex items-center justify-between text-[14px] font-label-md">
                  <span className="flex items-center gap-2 text-on-error-container">
                    <span className="material-symbols-outlined text-[18px]">insights</span>
                    <span className="font-semibold">Number check breakdown:</span>
                  </span>
                  <span className="font-code-sm text-[14px] font-medium text-error">
                    30% → not found in the abstract (full text not checked)
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-low border border-outline-variant/20 text-[14px] font-label-md text-on-surface">
                    <span className="material-symbols-outlined text-[16px] text-secondary">check_circle</span>
                    <span className="font-semibold">Identity: High</span> · exact DOI match
                  </span>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-low border border-outline-variant/20 text-[14px] font-label-md text-on-surface">
                    <span className="material-symbols-outlined text-[16px] text-tertiary">description</span>
                    <span className="font-semibold">Access: Medium</span> · abstract only
                  </span>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-low border border-outline-variant/20 text-[14px] font-label-md text-on-surface">
                    <span className="material-symbols-outlined text-[16px] text-error">rule</span>
                    <span className="font-semibold">Support: Medium</span> · quote verified, number not found
                  </span>
                </div>

                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-3 border-t border-outline-variant/20">
                  <div className="flex items-center gap-2 text-on-surface-variant font-label-md text-[14px]">
                    <span className="material-symbols-outlined text-[18px] text-outline">pending</span>
                    <span>Not yet reviewed</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      className="px-5 py-2 rounded-lg bg-surface-container-lowest text-on-surface border border-outline-variant/60 font-label-md text-[14px] font-semibold hover:bg-surface-container-low transition-colors shadow-xs"
                    >
                      Override
                    </button>
                    <button
                      type="button"
                      className="px-5 py-2 rounded-lg bg-primary text-on-primary font-label-md text-[14px] font-semibold hover:bg-primary/90 transition-colors shadow-xs"
                    >
                      Approve
                    </button>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
};
