import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Privacy Policy | FinanceOne",
  description: "FinanceOne Privacy Policy",
}

export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16 text-sm leading-7 text-zinc-800">
      <h1 className="text-2xl font-semibold">Privacy Policy</h1>
      <p className="mt-1 text-zinc-500">Last Updated: April 28, 2026</p>

      <p className="mt-6">
        <strong>Application:</strong> FinanceOne (Hanah One Group Internal Accounting BPO)
        <br />
        <strong>Operator:</strong> Hanah One Inc.
      </p>

      <h2 className="mt-8 text-lg font-semibold">1. Overview</h2>
      <p>
        FinanceOne (&quot;Application&quot;) is an internal accounting and financial reporting
        platform operated by Hanah One Inc. (&quot;Company&quot;). This Privacy Policy explains how
        the Application collects, uses, and protects information.
      </p>

      <h2 className="mt-6 text-lg font-semibold">2. Scope</h2>
      <p>
        The Application is used exclusively for internal accounting operations of the Hanah One
        group of companies (Hanah One Inc., 주식회사 한아원코리아, 주식회사 한아원리테일) and
        authorized accounting partners. The Application is not offered to or used by general
        consumers.
      </p>

      <h2 className="mt-6 text-lg font-semibold">3. Information We Collect</h2>
      <h3 className="mt-3 font-semibold">3.1 Financial Data</h3>
      <ul className="ml-6 list-disc space-y-1">
        <li>Bank transactions, account balances, and statements (via Mercury, Codef, QuickBooks Online).</li>
        <li>Card transactions and billing statements.</li>
        <li>Tax invoices and accounting ledger data.</li>
        <li>Vendor, customer, and counterparty information.</li>
      </ul>
      <h3 className="mt-3 font-semibold">3.2 Authentication Data</h3>
      <ul className="ml-6 list-disc space-y-1">
        <li>OAuth tokens (refresh and access tokens) for connected financial services.</li>
        <li>API keys provided by the Company for integration purposes.</li>
      </ul>
      <h3 className="mt-3 font-semibold">3.3 Usage Data</h3>
      <ul className="ml-6 list-disc space-y-1">
        <li>Application logs (timestamps, actions performed, errors).</li>
        <li>IP addresses of authorized users for audit purposes.</li>
      </ul>
      <h3 className="mt-3 font-semibold">3.4 Personal Data of Authorized Users</h3>
      <ul className="ml-6 list-disc space-y-1">
        <li>Names and email addresses of authorized employees and accounting partners.</li>
      </ul>

      <h2 className="mt-6 text-lg font-semibold">4. How We Use Information</h2>
      <ul className="ml-6 list-disc space-y-1">
        <li>Generate financial statements (Balance Sheet, Income Statement, Cash Flow).</li>
        <li>Reconcile transactions and detect duplicates or anomalies.</li>
        <li>Calculate exchange rates and currency translations for consolidated reporting.</li>
        <li>Maintain audit trails for compliance.</li>
        <li>Communicate with authorized users about system status.</li>
      </ul>

      <h2 className="mt-6 text-lg font-semibold">5. Third-Party Services</h2>
      <p>
        The Application integrates with the following services. Their respective privacy policies
        apply to data handled by them:
      </p>
      <ul className="ml-6 list-disc space-y-1">
        <li>Intuit QuickBooks Online — https://www.intuit.com/privacy/</li>
        <li>Mercury Bank — https://mercury.com/legal/privacy</li>
        <li>Codef (Korea Credit Data) — https://codef.io/privacy</li>
        <li>Anthropic Claude API — https://www.anthropic.com/legal/privacy</li>
        <li>Supabase (database hosting) — https://supabase.com/privacy</li>
      </ul>

      <h2 className="mt-6 text-lg font-semibold">6. Data Storage and Security</h2>
      <ul className="ml-6 list-disc space-y-1">
        <li>Financial data is stored in a private Supabase PostgreSQL database with encryption at rest.</li>
        <li>OAuth tokens are stored securely; access tokens are short-lived and refreshed automatically.</li>
        <li>Access to the Application is restricted to authorized employees and accounting partners.</li>
        <li>The Application does not sell, rent, or share data with unrelated third parties.</li>
      </ul>

      <h2 className="mt-6 text-lg font-semibold">7. Data Retention</h2>
      <p>
        Financial records are retained as required by Korean and U.S. tax law and accounting
        regulations (typically 5–10 years). Authentication tokens are deleted upon disconnection of
        the integration.
      </p>

      <h2 className="mt-6 text-lg font-semibold">8. User Rights</h2>
      <p>Authorized users may:</p>
      <ul className="ml-6 list-disc space-y-1">
        <li>Request access to data held about them.</li>
        <li>Request correction of inaccurate data.</li>
        <li>Disconnect any integrated third-party service at any time via the Application&apos;s settings.</li>
      </ul>

      <h2 className="mt-6 text-lg font-semibold">9. Children&apos;s Privacy</h2>
      <p>
        The Application is not intended for use by individuals under 18. We do not knowingly
        collect data from minors.
      </p>

      <h2 className="mt-6 text-lg font-semibold">10. International Data Transfers</h2>
      <p>
        Data may be processed in the United States, Republic of Korea, and other regions where the
        Company or its third-party providers operate. Appropriate safeguards are in place for
        cross-border transfers.
      </p>

      <h2 className="mt-6 text-lg font-semibold">11. Changes to This Policy</h2>
      <p>
        The Company may update this Privacy Policy from time to time. Material changes will be
        communicated via the Application or by email to authorized users.
      </p>

      <h2 className="mt-6 text-lg font-semibold">12. Contact</h2>
      <p>
        Hanah One Inc.
        <br />
        Email: shawn@hanah1.com
        <br />
        Address: Beverly Hills, California, USA
      </p>
    </main>
  )
}
