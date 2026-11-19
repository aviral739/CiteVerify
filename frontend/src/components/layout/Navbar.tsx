import React from 'react';
import { Link, useLocation } from 'react-router-dom';

interface NavbarProps {
  documentTitle?: string;
  isAnalyzing?: boolean;
  isComplete?: boolean;
  onRerun?: () => void;
  onExport?: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  documentTitle,
  isAnalyzing,
  isComplete,
  onRerun,
  onExport,
}) => {
  const location = useLocation();
  const isLanding = location.pathname === '/';

  return (
    <>
      <header className="fixed top-0 left-0 w-full z-50 bg-surface/90 backdrop-blur-xl shadow-[0_1px_8px_rgba(0,0,0,0.04)] pt-safe border-b border-outline-variant/30">
        <div className="max-w-[1440px] mx-auto h-16 px-4 sm:px-8 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link to="/" className="flex items-center gap-2.5 text-primary hover:opacity-90 transition-opacity">
              <div className="w-9 h-9 rounded-lg bg-surface-container-high flex items-center justify-center text-primary">
                <span className="material-symbols-outlined text-[22px]">verified_user</span>
              </div>
              <span className="font-headline-sm text-headline-sm text-on-surface tracking-tight font-semibold">
                CiteVerify
              </span>
            </Link>

            {documentTitle && (
              <>
                <div className="h-5 w-px bg-outline-variant/60 hidden sm:block mx-1"></div>
                <div className="hidden sm:flex items-center gap-2">
                  <span className="px-1.5 py-0.5 rounded bg-surface-container-high text-primary font-label-sm text-label-sm uppercase font-semibold">
                    PDF
                  </span>
                  <span className="font-code-sm text-code-sm text-on-surface font-medium truncate max-w-[200px]">
                    {documentTitle}
                  </span>
                  {isAnalyzing && (
                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-container-highest text-on-surface-variant font-label-sm text-label-sm">
                      <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse"></span>
                      ANALYZING
                    </span>
                  )}
                  {isComplete && (
                    <span className="flex items-center gap-1 text-secondary font-label-sm text-label-sm">
                      <span className="material-symbols-outlined text-[14px]">check_circle</span>
                      Audit completed
                    </span>
                  )}
                </div>
              </>
            )}
          </div>

          <div className="flex items-center gap-4 sm:gap-6 font-label-md text-label-md">
            {isLanding ? (
              <>
                <a href="#how-it-works" className="text-on-surface-variant hover:text-on-surface transition-colors text-[14px]">
                  How it works
                </a>
                <a
                  href="https://github.com/aviral739/CiteVerify"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-on-surface-variant hover:text-on-surface transition-colors text-[14px]"
                >
                  GitHub
                </a>
              </>
            ) : (
              <>
                {onRerun && (
                  <button
                    onClick={onRerun}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-outline-variant bg-surface-container-lowest text-on-surface hover:bg-surface-container-low transition-colors font-label-md text-label-md text-[13px]"
                  >
                    <span className="material-symbols-outlined text-[16px]">refresh</span>
                    <span className="hidden sm:inline">Re-run</span>
                  </button>
                )}
                {onExport && (
                  <button
                    onClick={onExport}
                    className="flex items-center gap-1 px-3.5 py-1.5 rounded-lg bg-primary-container text-on-primary hover:bg-primary transition-colors font-label-md text-label-md text-[13px] shadow-sm"
                  >
                    <span className="material-symbols-outlined text-[16px]">ios_share</span>
                    <span>Export</span>
                  </button>
                )}
                <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-on-primary">
                  <span className="material-symbols-outlined text-[18px]">person</span>
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Persistent Academic Disclaimer Banner */}
      <div className="fixed top-16 w-full z-40 bg-surface-container-low/95 backdrop-blur border-b border-outline-variant/30 py-2 px-4 text-center">
        <div className="max-w-6xl mx-auto flex items-center justify-center gap-2 text-on-surface-variant font-body-md text-[13px]">
          <span className="material-symbols-outlined text-[16px] text-primary shrink-0">info</span>
          <span>Automated screening to support human review. Not a final academic judgment.</span>
        </div>
      </div>
    </>
  );
};

export const Footer: React.FC = () => {
  return (
    <footer className="w-full border-t border-outline-variant/30 py-6 px-4 bg-surface text-center mt-auto">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3 text-on-surface-variant font-body-md text-[13px]">
        <p className="flex items-center gap-2 flex-wrap justify-center">
          <span className="font-medium text-on-surface">CiteVerify</span>
          <span>·</span>
          <span>Evidence-Linked Scientific Claim Verification</span>
          <span>·</span>
          <a
            href="https://github.com/aviral739/CiteVerify"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline underline-offset-2"
          >
            GitHub
          </a>
        </p>
        <p className="text-outline text-xs">
          Academic Editorial Standard · v0.1.0
        </p>
      </div>
    </footer>
  );
};

