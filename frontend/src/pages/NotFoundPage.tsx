import React from 'react';
import { Link } from 'react-router-dom';
import { Navbar, Footer } from '../components/layout/Navbar';

export const NotFoundPage: React.FC = () => {
  return (
    <div className="bg-surface font-body-md text-on-surface antialiased flex flex-col min-h-screen">
      <Navbar />

      <main className="w-full pt-32 pb-16 bg-surface max-w-4xl mx-auto px-4 text-center flex-1 flex flex-col items-center justify-center">
        <div className="w-16 h-16 rounded-full bg-surface-container-high flex items-center justify-center text-primary mb-4">
          <span className="material-symbols-outlined text-[36px]">find_in_page</span>
        </div>
        <h1 className="font-headline-lg text-headline-lg text-on-surface mb-2">Page or Document Not Found</h1>
        <p className="font-body-lg text-on-surface-variant max-w-md mb-6">
          The requested verification workspace or report could not be located on this server.
        </p>
        <Link
          to="/"
          className="px-6 py-2.5 rounded-lg bg-primary text-on-primary font-label-md text-label-md hover:bg-primary/90 transition-colors shadow-sm"
        >
          Return to CiteVerify Home
        </Link>
      </main>

      <Footer />
    </div>
  );
};

