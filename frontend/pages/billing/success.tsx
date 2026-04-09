import Head from "next/head";
import Link from "next/link";
import OwlLogo from "../../components/OwlLogo";

export default function BillingSuccessPage() {
  return (
    <>
      <Head>
        <title>You're on Pro! — Hootly</title>
      </Head>
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm text-center">
          <div className="mb-6">
            <Link href="/" className="inline-flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors">
              <OwlLogo size={64} />
            </Link>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl p-10 shadow-sm">
            <div className="text-5xl mb-5">🎉</div>
            <h1 className="text-2xl font-bold text-slate-900 mb-3">
              You&apos;re now on Pro!
            </h1>
            <p className="text-slate-500 text-sm leading-relaxed mb-8">
              Enjoy unlimited analyses, priority processing, and everything else
              Hootly Pro has to offer.
            </p>
            <Link
              href="/"
              className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold px-6 py-3 rounded-xl text-sm transition-colors"
            >
              Start analyzing →
            </Link>
          </div>

          <p className="mt-6 text-xs text-slate-400">
            Questions? Email us at support@hootlylabs.com
          </p>
        </div>
      </div>
    </>
  );
}
